#!/bin/zsh
# Canli Capital - daily AlphaTrend (managed-futures trend) refresh.
#
# AlphaTrend is the managed-futures trend sleeve: time-series momentum across a 17-market ETF basket
# (equity-index, rates, commodities, FX). ETFs are daily bars, so this runs once per day (after the
# US session's data publishes) to:
#   1. refresh the ETF lake from Yahoo total-return adjusted (mf_etf_load.py — dedupe-safe), and
#   2. regenerate AlphaTrend's realized FORWARD curve via the tested directional-trend gauntlet
#      (mf_gauntlet.py, ~1-2 min) into artifacts/walkforward/mf_live_fwd.
#
# It does NOT publish or deploy: the hourly live tick (com.accapital.livetick) re-runs
# paper_trading_state.py every hour (which reads this fresh forward curve and re-emits the
# 4-algorithm state), and the daily publish deploys. So AlphaTrend stays current within the hour.

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/alphaforge" || exit 1
mkdir -p var/log var/locks
# Single-runner lock (atomic mkdir; no flock on macOS). Prevents an overlapping AlphaTrend run from
# double-submitting to its Alpaca account — required now that live_cycle uses per-cycle order ids.
LOCK="var/locks/mf_tick.lock"
[ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +30 2>/dev/null)" ] && rmdir "$LOCK" 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "=== mf_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ'): another run holds $LOCK; exiting ===" >> var/log/mf_tick.log
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
WF_WATCHDOG_S=900   # 15 min hard cap (a healthy MF gauntlet is ~1-2 min)

{
  echo "=== mf_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="

  TOMORROW="$(date -u -v+1d +%F)"   # extend the WF through today so the forward record accrues

  echo "--- refresh the managed-futures ETF lake (Yahoo total-return) ---"
  # WATCHDOGGED 2026-08-03: this call reaches an external venue/vendor and had no bound.
  # An unbounded external call on the trading path is what let a hung deploy block ALL
  # trading for 28h. Hard-cap it; the tick must always reach its state refresh.
  ( sleep 900; pkill -TERM -f "mf_etf_load.py" 2>/dev/null; \
    sleep 15; pkill -KILL -f "mf_etf_load.py" 2>/dev/null ) &
  _ETFLDWD=$!
  /usr/bin/caffeinate -s .venv/bin/python3 scripts/mf_etf_load.py
  kill "$_ETFLDWD" 2>/dev/null; wait "$_ETFLDWD" 2>/dev/null

  echo "--- regenerate AlphaTrend forward curve through ${TOMORROW} (directional-trend gauntlet) ---"
  ( sleep "${WF_WATCHDOG_S}"; pkill -TERM -f "mf_gauntlet" 2>/dev/null; \
    sleep 10; pkill -KILL -f "mf_gauntlet" 2>/dev/null ) &
  WD=$!
  /usr/bin/caffeinate -s .venv/bin/python3 scripts/mf_gauntlet.py \
    --alphas mf_trend_63,mf_trend_126,mf_trend_252 --rebalance 10 --cash 100000 \
    --start 2003-01-01 --end "${TOMORROW}" --out artifacts/walkforward/mf_live_fwd
  kill "${WD}" 2>/dev/null; wait "${WD}" 2>/dev/null

  echo "--- submit AlphaTrend deltas to Alpaca paper (GENUINE broker execution) ---"
  # Reads the freshly-regenerated target book, sizes it to the live Alpaca paper account, and
  # submits the deltas (cancel-stale first so repeat runs never stack a duplicate book). Market
  # orders submitted while the US session is closed queue and fill at the next open -> a clean
  # signal-on-close / execute-next-open record. A broker/market hiccup must NOT break the tick,
  # so failure is logged and the state still refreshes below.
  # WATCHDOGGED 2026-08-03: this call reaches an external venue/vendor and had no bound.
  # An unbounded external call on the trading path is what let a hung deploy block ALL
  # trading for 28h. Hard-cap it; the tick must always reach its state refresh.
  ( sleep 1200; pkill -TERM -f "live_cycle.py --profile managed_futures" 2>/dev/null; \
    sleep 15; pkill -KILL -f "live_cycle.py --profile managed_futures" 2>/dev/null ) &
  _MFCYCWD=$!
  /usr/bin/caffeinate -s .venv/bin/python3 scripts/live_cycle.py --profile managed_futures \
    || echo "WARN: live_cycle returned non-zero (broker/market issue) — state still refreshes"
  kill "$_MFCYCWD" 2>/dev/null; wait "$_MFCYCWD" 2>/dev/null

  echo "--- refresh published state now (the hourly tick also does this) ---"
  .venv/bin/python3 scripts/paper_trading_state.py
  echo "=== mf_tick done $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
} >> var/log/mf_tick.log 2>&1
