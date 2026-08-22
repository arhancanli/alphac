#!/bin/zsh
# Shared safety helpers for every scheduled job. Source with:  . "$HOME/alphaforge/scripts/lib/bounded.sh"
#
# WHY THIS FILE EXISTS (a real incident, 2026-08-03)
# --------------------------------------------------
# `vercel deploy` has no timeout of its own. One hung deploy held the hourly tick's single-runner
# lock for 28 HOURS and blocked ALL trading — a purely cosmetic web publish stopping the critical
# path. The first fix pattern-killed `vercel deploy` from live_tick's watchdog, which fixed the
# hang but introduced a SECOND bug: livetick runs hourly at :05 and publish daily at 02:10, so the
# two overlap by design, and a broad `pkill -f "vercel deploy"` would kill the *other* job's
# deploy mid-upload. Pattern-killing is a blunt instrument that cannot tell whose process it hit.
#
# So the honest fix is two rules, applied everywhere:
#   1. Every external call is bounded — but by PID, so a job can only ever kill its OWN child.
#   2. Jobs that touch the same external resource take a shared lock instead of racing.

# run_bounded <seconds> <cmd> [args...]
# Runs cmd under a hard wall-clock cap. Kills ONLY this invocation's own child (by PID), never
# another job's identically-named process. Returns the child's exit code (143/137 if it was
# killed), so callers keep their existing `|| echo ...` soft-fail handling unchanged.
# stdout/stderr pass through untouched, so `url=$(run_bounded 600 vercel deploy ...)` still works
# (the watchdog's own output is discarded so it never holds the capture pipe open).
run_bounded() {
  local _secs="$1"; shift
  # The child is started as its own PROCESS GROUP LEADER (setpgrp, then exec) so the watchdog can
  # kill the whole tree. Killing just the direct child is NOT enough and this was proven by test,
  # not assumed: `vercel` spawns grandchildren, and a surviving grandchild keeps the stdout pipe
  # open — so `url=$(run_bounded ... vercel deploy ...)` would block on the capture even after the
  # child died. That would have reproduced the exact 28h hang this file exists to prevent.
  # zsh's MONITOR option does not enable job control in a script (verified), hence the perl hop.
  perl -e 'setpgrp(0,0); exec {$ARGV[0]} @ARGV
           or print STDERR "run_bounded: cannot exec $ARGV[0]: $!\n" and exit 127' -- "$@" &
  local _pid=$!
  # Kill the GROUP (-pid). If setpgrp somehow failed, -pid matches no group and the kill is a
  # no-op, so we fall back to the pid — never to our own group, since our pgid != _pid.
  ( sleep "$_secs"
    kill -TERM -"$_pid" 2>/dev/null || kill -TERM "$_pid" 2>/dev/null
    sleep 15
    kill -KILL -"$_pid" 2>/dev/null || kill -KILL "$_pid" 2>/dev/null ) >/dev/null 2>&1 &
  local _wd=$!
  wait "$_pid"; local _rc=$?
  kill "$_wd" 2>/dev/null; wait "$_wd" 2>/dev/null
  return $_rc
}

# Shared Vercel deploy lock: the hourly light deploy and the nightly full publish must never run
# concurrently (they deploy the same two projects from the same box).
DEPLOY_LOCK="$HOME/alphaforge/var/locks/vercel_deploy.lock"

# deploy_lock_acquire -> 0 if we hold it, 1 if another job does (caller should skip, not wait:
# the hourly deploy retries next hour and the nightly publish's data is already on disk).
deploy_lock_acquire() {
  mkdir -p "$(dirname "$DEPLOY_LOCK")" 2>/dev/null
  # steal a stale lock — a SIGKILL'd deploy cannot clean up after itself, and a permanently
  # stuck lock would silently freeze the public site (the failure mode we are removing).
  if [ -d "$DEPLOY_LOCK" ] && [ -n "$(find "$DEPLOY_LOCK" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
    echo "  (stealing deploy lock older than 30m — previous holder died)"
    rmdir "$DEPLOY_LOCK" 2>/dev/null
  fi
  mkdir "$DEPLOY_LOCK" 2>/dev/null
}

deploy_lock_release() { rmdir "$DEPLOY_LOCK" 2>/dev/null; }

# deploy_lock_wait <max_seconds> -> 0 if acquired within the window, 1 if it timed out.
# For the nightly publish, which would rather wait out a short hourly deploy than skip.
deploy_lock_wait() {
  local _max="$1" _waited=0
  while ! deploy_lock_acquire; do
    [ "$_waited" -ge "$_max" ] && return 1
    sleep 15; _waited=$((_waited + 15))
  done
  return 0
}
