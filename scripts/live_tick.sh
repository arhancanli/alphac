#!/bin/zsh
# AC Capital - hourly live PAPER cycle (the running track record).
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
mkdir -p var/log
WATCHDOG_S=1800   # 30 min hard cap (a healthy cycle is ~15-20 min)

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
  echo "=== tick done $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
} >> var/log/live_tick.log 2>&1
