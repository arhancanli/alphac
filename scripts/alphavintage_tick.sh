#!/bin/zsh
# Canli Capital — daily AlphaVintage (CPI-surprise size spread) refresh.
#
# AlphaVintage trades the IWM/SPY size spread off the point-in-time CPI surprise. Its signal only
# CHANGES monthly (one CPI vintage per month), but this tick runs DAILY, deliberately:
#   * live_cycle re-diffs the target against ACTUAL broker positions, so an order that did not
#     fill (the 0.75% limit collar rejects gap fills by design) is retried the next session
#     instead of silently leaving the sleeve half-on;
#   * position drift from price moves is corrected back toward the target;
#   * the staleness guard in alphavintage_target.py gets a daily chance to shout if the macro
#     vintage feed has died. A monthly cadence would let a dead feed hide for weeks.
#
# ORDERING. This runs at 10:00, AFTER com.accapital.macrovintage (08:20) refreshes the CPI vintage
# lake and AFTER com.accapital.alphatrend (09:30), whose mf_tick refreshes the data/lake_mf bars
# that supply IWM/SPY prices and the trading-day calendar this sleeve's entry rule reads.
#
# WHAT THIS TICK DOES NOT DO. It does not ingest data (two other ticks own that) and it does not
# refresh the published state — com.accapital.livetick already re-runs paper_trading_state.py
# hourly. Doing either here would duplicate a job that already has an owner.

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/alphaforge" || exit 1
mkdir -p var/log var/locks

# Single-runner lock (atomic mkdir; macOS has no flock). Prevents an overlapping run from
# double-submitting to the AlphaVintage Alpaca account.
LOCK="var/locks/alphavintage_tick.lock"
[ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +30 2>/dev/null)" ] && rmdir "$LOCK" 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "=== alphavintage_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ'): another run holds $LOCK; exiting ===" \
    >> var/log/alphavintage_tick.log
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

{
  echo "=== alphavintage_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="

  echo "--- write the target book from the pre-registered rule ---"
  # Exits NON-ZERO and writes nothing if the vintage feed is stale (>45d) or if the resulting
  # gross would exceed live_cycle's _GROSS_HARD_CAP. Both are fail-closed: on either, the tick
  # STOPS here rather than submitting, because the previous target is still the correct one and
  # re-submitting against a bad book is worse than doing nothing.
  if ! /usr/bin/caffeinate -s .venv/bin/python3 scripts/alphavintage_target.py; then
    echo "STOP: alphavintage_target.py refused to write (stale feed or gross over cap)."
    echo "STOP: NOT submitting. The existing position stands; a human should read the reason above."
    echo "=== alphavintage_tick done (refused) $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
    exit 0
  fi

  echo "--- submit AlphaVintage deltas to its own Alpaca paper account (PA39G6N49JRY) ---"
  # WATCHDOGGED for the same reason every other sleeve's broker call is: an unbounded external
  # call on the trading path once blocked ALL trading for 28h on this system. 20 min hard cap.
  ( sleep 1200; pkill -TERM -f "live_cycle.py --profile alphavintage" 2>/dev/null; \
    sleep 15; pkill -KILL -f "live_cycle.py --profile alphavintage" 2>/dev/null ) &
  _WD=$!
  /usr/bin/caffeinate -s .venv/bin/python3 scripts/live_cycle.py --profile alphavintage \
    || echo "WARN: live_cycle (alphavintage) returned non-zero (broker/market issue)"
  kill "$_WD" 2>/dev/null; wait "$_WD" 2>/dev/null

  echo "=== alphavintage_tick done $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
} >> var/log/alphavintage_tick.log 2>&1
