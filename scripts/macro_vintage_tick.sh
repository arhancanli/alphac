#!/bin/zsh
# Daily PIT macro-vintage refresh — the job that starts AlphaVintage's arrival-lag clock.
#
# WHY DAILY, when RTDSM only publishes monthly. The point is not the refresh, it is the
# TIMESTAMP. AlphaVintage's backtest enters on the first trading day after a vintage's stamped
# date (always the 15th), and whether that is achievable LIVE depends on when the Philly Fed
# workbook actually becomes downloadable. That gap cannot be measured backwards: the lake stores
# no acquisition field and every cached workbook carries the date WE fetched it. Checking daily is
# what turns "we assume the data arrives in time" into a measured fact, and each day not checking
# is a day added before this sleeve can be funded honestly.
#
# The first observation (2026-08-07) recorded +23d for five series, but that measured OUR neglect:
# the lake had gone 27 days without a refresh. Clean observations only start accruing now.
#
# The refresh script forces a real download (the underlying builder caches xlsx forever and would
# otherwise rebuild from stale copies while stamping meta.json with today's date).
set -uo pipefail
cd "$HOME/alphaforge" || exit 1
echo "=== macro vintage tick $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
.venv/bin/python scripts/refresh_macro_vintage.py
rc=$?
if [ $rc -ne 0 ]; then
  # A refresh failure is not cosmetic: a sleeve trading a signal off a lake that stopped updating
  # keeps trading yesterday's information and reports it as today's. Exit loudly so the health
  # check can see it rather than letting a silent no-op look like success.
  echo "!! macro vintage refresh FAILED rc=$rc"
fi
echo "=== macro vintage tick done rc=$rc ==="
exit $rc
