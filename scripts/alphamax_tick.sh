#!/bin/zsh
# Canli Capital - daily AlphaMax (equity) refresh.
#
# AlphaMax is the US-equity 12-1 momentum sleeve. Equity bars are daily (Polygon S3 flat
# files), so this runs once per day (after the prior US session's flat file publishes) to:
#   1. ingest the latest equity sessions (catch-up, dedupe-safe), and
#   2. regenerate AlphaMax's realized FORWARD curve via the tested walk-forward (momentum-only,
#      ~72s) into artifacts/walkforward/equity_live_fwd.
#
# It does NOT regenerate the published state or deploy: the hourly crypto tick
# (com.accapital.livetick) already re-runs paper_trading_state.py every hour (which reads this
# fresh forward curve + the live crypto NAV and re-combines the 3-algorithm state), and the daily
# publish deploys. So AlphaMax's forward + ALPHAC's combination stay current within the hour.

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/alphaforge" || exit 1
mkdir -p var/log
WF_WATCHDOG_S=1200   # 20 min hard cap (a healthy momentum WF is ~1-2 min)

{
  echo "=== alphamax_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  set -a; . "$HOME/.config/alphaforge/polygon.env" 2>/dev/null; set +a

  TOMORROW="$(date -u -v+1d +%F)"
  INGEST_START="$(date -u -v-12d +%F)"   # catch up the last ~2 weeks of sessions (dedupe-safe)
  WF_START="$(date -u -v-2y -v-2m +%F)"  # ~2.2yr: 365-session train + test legs through today

  echo "--- ingest equities ${INGEST_START} .. ${TOMORROW} ---"
  /usr/bin/caffeinate -s uv run af data ingest-equities \
    --start "${INGEST_START}" --until "${TOMORROW}" --profile equity

  echo "--- regenerate AlphaMax forward curve (momentum-only WF) ---"
  ( sleep "${WF_WATCHDOG_S}"; pkill -TERM -f "research walkforward" 2>/dev/null; \
    sleep 10; pkill -KILL -f "research walkforward" 2>/dev/null ) &
  WD=$!
  /usr/bin/caffeinate -s uv run af research walkforward --profile equity \
    --start "${WF_START}" --end "${TOMORROW}" \
    --train-days 365 --test-days 91 --alphas eq_mom_252_21 \
    --out artifacts/walkforward/equity_live_fwd
  kill "${WD}" 2>/dev/null; wait "${WD}" 2>/dev/null

  echo "--- refresh published state now (the hourly tick also does this) ---"
  uv run python scripts/paper_trading_state.py
  echo "=== alphamax_tick done $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
} >> var/log/alphamax_tick.log 2>&1
