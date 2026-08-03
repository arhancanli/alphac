#!/bin/zsh
# Canli Capital - hourly live PAPER cycle (the running track record).
#
# Runs one idempotent paper cycle for the just-closed bar (scheduled a few minutes
# past the hour by launchd so the bar has closed), then regenerates the published-state
# JSONs from the REALIZED marks in trading.sqlite. Only ACCRUES + regenerates locally;
# publishing to the live sites is the separate daily live_publish.sh step.
#
# HARD WATCHDOG: a hung network fetch must never block forever. If the cycle overruns
# WATCHDOG_S, it is killed and the next hour retries (every cycle is idempotent +
# crash-safe by the Phase-8 gates, so an abandoned cycle costs nothing but a gap).

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/alphaforge" || exit 1
mkdir -p var/log var/locks
# Single-runner lock (mkdir is atomic on macOS; no flock here). Prevents an overlapping run from
# double-submitting — required now that live_cycle uses per-cycle order ids. A SIGKILL'd run can't
# clear its lock, so steal one older than the watchdog window.
LOCK="var/locks/live_tick.lock"
[ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +60 2>/dev/null)" ] && rmdir "$LOCK" 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "=== live_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ'): another run holds $LOCK; exiting ===" >> var/log/live_tick.log
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
WATCHDOG_S=2400   # 40 min cap: hourly cache-hit cycles are ~3 min; the once-daily
                  # blend-weight refresh (cache miss) is ~25 min -- 40 min bounds a
                  # hang while clearing the daily refresh with comfortable margin.

{
  echo "=== live_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  # watchdog: after WATCHDOG_S, terminate any lingering cycle, then hard-kill.
  ( sleep "$WATCHDOG_S"; pkill -TERM -f "af paper run --once" 2>/dev/null; \
    sleep 15; pkill -KILL -f "af paper run --once" 2>/dev/null; \
    pkill -KILL -f "caffeinate -s uv run af paper" 2>/dev/null ) &
  WD=$!
  /usr/bin/caffeinate -s uv run af paper run --once
  kill "$WD" 2>/dev/null; wait "$WD" 2>/dev/null
  echo "--- regenerate published state from realized NAV ---"
  uv run python scripts/glassbox_export.py
  uv run python scripts/paper_trading_state.py
  # anchor the day's track record into the signed append-only transparency chain (no-op if
  # nothing changed since the last entry) — the tamper-evident proof the record isn't rewritten
  uv run python scripts/transparency_log.py
  # HOURLY web refresh: redeploy the public sites when the served data changed (change-gated,
  # freshness-guarded; see live_deploy_hourly.sh). The web app now tracks the live book hourly.
  # WATCHDOGGED (added 2026-08-03 after a real incident): `vercel deploy` has no timeout of its
  # own, so a hung deploy held this tick's single-runner lock for 28 HOURS and blocked ALL trading
  # — a purely cosmetic web publish stopping the critical path, the same failure class as the
  # corp-actions ingest that once buried the equity tick for 10.8 days. The web can always catch up
  # next hour; trading cannot. Hard-bound it and treat any failure as non-fatal.
  # (This no longer broad-kills `vercel deploy`: that would also kill the nightly publish,
  #  which overlaps this job by schedule. The deploy is now bounded by PID inside the
  #  script itself and the two jobs share a lock — see scripts/lib/bounded.sh.)
  ( sleep 600; pkill -TERM -f "live_deploy_hourly" 2>/dev/null; \
    sleep 15; pkill -KILL -f "live_deploy_hourly" 2>/dev/null ) &
  _DWD=$!
  /bin/zsh scripts/live_deploy_hourly.sh || echo "WARN: hourly web deploy failed (next hour retries)"
  kill "$_DWD" 2>/dev/null; wait "$_DWD" 2>/dev/null
  # MAKER SHADOW (measure-only, places NO orders): samples top-of-book on the names the crypto
  # sleeve actually holds and later checks the trade tape to see whether a passive quote WOULD
  # have filled and at what markout. This is how the modelled +0.04-0.09 Sharpe maker/post-only
  # edge gets an HONEST forward measurement instead of being booked on assumption — the fund's
  # discipline forbids crediting a fill we have not proven we can get. Strictly non-fatal: a
  # measurement must never be able to break the trading tick.
  # WATCHDOGGED: both calls hit the Binance REST API, so an unresponsive venue would otherwise
  # hang the hourly tick exactly the way the unbounded `vercel deploy` did (28h, all trading
  # blocked). A measurement must never be able to stop trading.
  ( sleep 300; pkill -TERM -f "maker_shadow.py" 2>/dev/null; \
    sleep 10; pkill -KILL -f "maker_shadow.py" 2>/dev/null ) &
  _MWD=$!
  uv run python scripts/maker_shadow.py record   || echo "WARN: maker_shadow record failed (non-fatal)"
  uv run python scripts/maker_shadow.py evaluate || echo "WARN: maker_shadow evaluate failed (non-fatal)"
  kill "$_MWD" 2>/dev/null; wait "$_MWD" 2>/dev/null
  echo "=== tick done $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
} >> var/log/live_tick.log 2>&1
