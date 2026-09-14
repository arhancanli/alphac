#!/bin/zsh
# Daily macro-vintage candidate acquisition — STAGING ONLY.
#
# Fresh downloads, logs, hashes and observation times stay in an isolated candidate.
# Success means ready for review, NOT active-lake freshness or production arrival.
# No production data, arrival_log, receipt, signal or trading setting is changed.
# Promotion requires a separately approved phase. See docs/MACRO_REFRESH_STAGING.md.
set -uo pipefail
cd "$HOME/alphaforge" || exit 1
echo "=== macro vintage STAGING ONLY $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
.venv/bin/python -B scripts/stage_macro_vintage_refresh.py \
  --source-lake "$PWD/data/lake_macro_vintage" \
  --output-parent "$PWD/artifacts/macro_refresh_candidates"
rc=$?
if [ $rc -ne 0 ]; then
  echo "!! macro vintage candidate FAILED / NOT PROMOTED rc=$rc"
else
  echo "!! candidate ready for review / NOT PROMOTED / active freshness unchanged"
fi
echo "=== macro vintage staging done rc=$rc ==="
exit $rc
