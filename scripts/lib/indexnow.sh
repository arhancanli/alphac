# =============================================================================
# CANLI CAPITAL / scripts/lib/indexnow.sh
# -----------------------------------------------------------------------------
# Push every canonical URL to IndexNow after a successful landing deploy.
#
# WHY THIS IS A SHARED FILE AND NOT TWO COPIES. There are two deploy paths — the
# hourly change-gated one and the nightly ceremony — and this repo has already
# been bitten twice by the same logic living in two hand-mirrored places: the
# retracted-claim gate that one job ran and the other did not, and the glassbox
# copy list where one host got a paper the other did not. Two copies is one copy
# too many. Both callers source this.
#
# WHY IT IS LOUD BUT NOT FATAL. IndexNow is a notification to third-party search
# engines, not a correctness gate on what we published. A network blip must not
# mark a good publication as failed. But "non-fatal" has been an excuse for
# "silent" here before, so this writes a MARKER on every attempt, and
# indexnow_warn_if_stale reports when the last SUCCESS is older than a day. A
# failure that nothing ever reports is the same as no submission at all.
# =============================================================================

INDEXNOW_MARKER="${INDEXNOW_MARKER:-$HOME/alphaforge/var/log/indexnow_last.json}"
INDEXNOW_STALE_SECONDS="${INDEXNOW_STALE_SECONDS:-93600}"   # 26h: one missed hourly run is fine

# Submit, bounded, and record the outcome either way. Never returns non-zero.
indexnow_submit() {
  local site="${1:-$HOME/meridian}"
  local now out status count
  now=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  mkdir -p "$(dirname "$INDEXNOW_MARKER")"

  if ! out=$( cd "$site" && run_bounded 120 npm run --silent indexnow 2>&1 ); then
    status="FAILED"
    echo "  [indexnow] SUBMISSION FAILED — search engines were NOT told about this deploy"
    printf '%s\n' "$out" | tail -8 | sed 's/^/    [indexnow:err] /'
  else
    status="OK"
    echo "  [indexnow] $out"
  fi
  count=$(printf '%s\n' "$out" | grep -oE 'accepted [0-9]+' | grep -oE '[0-9]+' | tail -1)
  [ -n "$count" ] || count=0

  # The marker is written on FAILURE too, with the status, so "when did this last work" is a
  # question the file can answer rather than one that needs the log.
  printf '{\n  "attempted_at": "%s",\n  "status": "%s",\n  "urls_submitted": %s\n}\n' \
    "$now" "$status" "$count" > "$INDEXNOW_MARKER"
  [ "$status" = "OK" ] && printf '%s\n' "$now" > "${INDEXNOW_MARKER%.json}.ok"
  return 0
}

# Report if the last SUCCESSFUL submission is older than the staleness window. This is the half
# that makes a non-fatal failure loud: one failed run is a line in a log, and a run of failed runs
# is a line at the top of every subsequent publish.
indexnow_warn_if_stale() {
  local ok_file="${INDEXNOW_MARKER%.json}.ok"
  local last age
  if [ ! -f "$ok_file" ]; then
    echo "  [indexnow] WARNING: no successful submission has EVER been recorded"
    return 0
  fi
  last=$(cat "$ok_file" 2>/dev/null)
  # BSD date on macOS; GNU date as the fallback so this is not silently a no-op on Linux.
  age=$(( $(date -u '+%s') - $(date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$last" '+%s' 2>/dev/null \
        || date -u -d "$last" '+%s' 2>/dev/null || echo 0) ))
  if [ "$age" -gt "$INDEXNOW_STALE_SECONDS" ]; then
    echo "  [indexnow] WARNING: last successful submission was $((age / 3600))h ago ($last)."
    echo "             New and changed pages are not being pushed to search engines."
  fi
}
