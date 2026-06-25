#!/bin/bash
# Autonomous overnight strategy campaign: full IC screen (208 zoo factors) -> deflated
# walk-forward gauntlet on the survivors -> synthesis report. Designed to run unattended.
# RUNS ONLY WHILE THE MAC IS AWAKE — closing the lid (without `pmset -c disablesleep 1`)
# sleeps the machine and pauses this; it resumes on wake. Launch via:
#   nohup caffeinate -dimsu bash scripts/overnight_campaign.sh > artifacts/overnight.out 2>&1 &
set -uo pipefail
cd "$HOME/alphaforge" || exit 1
export PATH="$HOME/.local/bin:$PATH"
LOG="artifacts/overnight_campaign.log"
mkdir -p artifacts/sweep
echo "=== overnight campaign START $(date) ===" | tee -a "$LOG"

run_guarded() {  # $1 = timeout seconds, rest = command (kills a hung step so it can't eat the night)
  local secs="$1"; shift
  "$@" & local p=$!
  ( sleep "$secs"; kill -9 "$p" 2>/dev/null ) & local k=$!
  wait "$p" 2>/dev/null; local rc=$?
  kill "$k" 2>/dev/null
  return $rc
}

# 1) FULL equity IC screen over all 208 zoo factors (the cheap first cut)
echo "--- [1] full IC screen (208 factors) $(date) ---" | tee -a "$LOG"
run_guarded 5400 uv run python scripts/zoo_screen.py --profile sharadar \
  --start 2008-01-01 --end 2026-06-01 --horizons 63 --top 50 >> "$LOG" 2>&1

# 2) pick the survivors: top by |Rank-IC NW t|, keep |t| >= 2.5, cap at 6 (the deflation-aware cut)
SURV=$(uv run python - <<'PY'
import json
try:
    rep = json.load(open("data/research/zoo/ic_report.json"))
    rows = [r for r in rep.get("rows", []) if int(r.get("horizon", 63)) == 63]
    rows.sort(key=lambda r: abs(float(r.get("t_nw") or 0.0)), reverse=True)
    surv = [r["factor"] for r in rows if abs(float(r.get("t_nw") or 0.0)) >= 2.5][:6]
    print(",".join(surv))
except Exception as e:
    print("")
PY
)
echo "--- [2] IC survivors (|t|>=2.5, top6): ${SURV:-<none>} ---" | tee -a "$LOG"

# 3) full deflated walk-forward gauntlet on each survivor (net of cost, DSR, skew), 1h cap each
if [ -n "$SURV" ]; then
  IFS=',' read -ra FACTORS <<< "$SURV"
  ARGS=()
  for f in "${FACTORS[@]}"; do
    echo "--- [3] gauntlet $f $(date) ---" | tee -a "$LOG"
    run_guarded 3600 uv run af research walkforward --profile sharadar \
      --start 2010-01-01 --end 2026-06-01 --train-days 252 --test-days 63 \
      --rebalance-bars 63 --allocator rank --alphas "$f" \
      --out "artifacts/sweep/gauntlet_$f" >> "$LOG" 2>&1
    [ -f "artifacts/sweep/gauntlet_$f/walkforward.json" ] && ARGS+=("$f=artifacts/sweep/gauntlet_$f")
  done
  # 4) synthesis: deflated Sharpe + skew + decorrelation across the survivors
  echo "--- [4] synthesis report $(date) ---" | tee -a "$LOG"
  if [ ${#ARGS[@]} -gt 0 ]; then
    uv run python scripts/eq_factor_family_report.py "${ARGS[@]}" > artifacts/overnight_report.txt 2>&1
  fi
else
  echo "no IC survivors cleared |t|>=2.5 — the honest first-cut result (most factors are noise)" | tee -a "$LOG"
fi

echo "=== overnight campaign DONE $(date) ===" | tee -a "$LOG"
echo "results: artifacts/overnight_report.txt + data/research/zoo/ic_report.json + $LOG"
