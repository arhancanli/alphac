#!/bin/bash
# Gauntlet the IC survivors from the equity + crypto screens through the full deflated
# walk-forward (net of cost, DSR, skew) — the decisive tradability test. Per-factor timeouts
# so a hang can't eat the run. Equity is fast (D1); crypto is slow (H1) so it runs second.
#   nohup caffeinate -dimsu bash scripts/gauntlet_survivors.sh > artifacts/gauntlet.out 2>&1 &
set -uo pipefail
cd "$HOME/alphaforge" || exit 1
export PATH="$HOME/.local/bin:$PATH"
LOG="artifacts/gauntlet_survivors.log"
mkdir -p artifacts/sweep
echo "=== gauntlet survivors START $(date) ===" | tee -a "$LOG"

run_guarded() { local secs="$1"; shift; "$@" & local p=$!; ( sleep "$secs"; kill -9 "$p" 2>/dev/null ) & local k=$!; wait "$p" 2>/dev/null; kill "$k" 2>/dev/null; }

gauntlet() {  # $1=profile $2=factor $3=start $4=cap_seconds
  echo "--- gauntlet $2 ($1) $(date) ---" | tee -a "$LOG"
  run_guarded "$4" uv run af research walkforward --profile "$1" \
    --start "$3" --end 2026-06-01 --train-days 365 --test-days 91 \
    --rebalance-bars 63 --allocator rank --alphas "$2" \
    --out "artifacts/sweep/g_$2" >> "$LOG" 2>&1
}

# --- EQUITY survivors (fast, D1): the momentum surface + lottery + the IC-leading quality ratio
for f in eq_mom_63_42 eq_mom_189_42 eq_maxret_21 eq_qual_gpe; do
  gauntlet sharadar "$f" 2012-01-01 2400
done
EQ_ARGS=()
for f in eq_mom_63_42 eq_mom_189_42 eq_maxret_21 eq_qual_gpe; do
  [ -f "artifacts/sweep/g_$f/walkforward.json" ] && EQ_ARGS+=("$f=artifacts/sweep/g_$f")
done
[ ${#EQ_ARGS[@]} -gt 0 ] && uv run python scripts/eq_factor_family_report.py "${EQ_ARGS[@]}" > artifacts/gauntlet_equity.txt 2>&1
echo "--- equity gauntlet report -> artifacts/gauntlet_equity.txt ---" | tee -a "$LOG"

# --- CRYPTO survivors (slow, H1): the strong low-vol / low-beta + fast carry. 2.5h cap each.
for f in lowvol_720 beta_lowbeta_720 carry_fund_7; do
  gauntlet base "$f" 2022-01-01 9000
done
CR_ARGS=()
for f in lowvol_720 beta_lowbeta_720 carry_fund_7; do
  [ -f "artifacts/sweep/g_$f/walkforward.json" ] && CR_ARGS+=("$f=artifacts/sweep/g_$f")
done
[ ${#CR_ARGS[@]} -gt 0 ] && uv run python scripts/eq_factor_family_report.py "${CR_ARGS[@]}" > artifacts/gauntlet_crypto.txt 2>&1
echo "--- crypto gauntlet report -> artifacts/gauntlet_crypto.txt ---" | tee -a "$LOG"

echo "=== gauntlet survivors DONE $(date) ===" | tee -a "$LOG"
