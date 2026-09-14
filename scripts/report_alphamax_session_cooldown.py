"""Describe measured cooldown candidate against immutable matched references."""
import hashlib
import json
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/alphamax_session_cooldown_20260913'
OLD=ROOT/'artifacts/analysis/alphamax_extended_reference_20260913'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    rows=[];refs={}
    manifest=json.loads((OUT/'input_manifest.json').read_text())['sha256']
    for p,h in manifest.items():assert sha(ROOT/p)==h,p
    for candidate,control in [('candidate','baseline'),('candidate_stress','baseline_stress')]:
        for source,arm,policy in [(OLD,control,336),(OUT,candidate,10)]:
            d=source/arm;c=json.loads((d/'closure.json').read_text());assert sha(ROOT/c['packet'])==c['packet_sha256']
            a=json.loads((d/'benchmark_audit.json').read_text());wf=json.loads((d/'run/walkforward.json').read_text())
            row={'arm':arm,'cooldown_sessions':policy,**{k:a[k] for k in ['total_return','net_excess_sharpe_DFF_proxy','max_drawdown']},'flat_halted_sessions':sum(x['risk_counters']['bars_halted_flat'] for x in wf['legs']),'auto_rearms':sum(x['risk_counters']['n_auto_rearms'] for x in wf['legs'])};rows.append(row)
            for p in [d/'closure.json',d/'benchmark_audit.json',d/'run/walkforward.json',d/'independent_audit.json']:refs[str(p.relative_to(ROOT))]=sha(p)
    pd.DataFrame(rows).to_csv(OUT/'comparison.csv',index=False)
    report='# AlphaMax10-session cooldown candidate\n\nOne preregistered equity research change:336-session cooldown becomes10sessions, approximately two trading weeks. The documented default336 was based on hourly bars. This experiment does not establish original equity intent or change production. Drawdown thresholds, rearm high-water-mark reset, algorithm and cost assumptions remain fixed.\n\n| Arm | Return | Excess Sharpe | Max drawdown | Halted sessions |\n|---|---:|---:|---:|---:|\n'
    for r in rows:report+=f"| {r['arm']} | {r['total_return']:.4%} | {r['net_excess_sharpe_DFF_proxy']:.4f} | {r['max_drawdown']:.4%} | {r['flat_halted_sessions']} |\n"
    report+='\nBoth candidate runs have857 independently reconciled engine marks and855 source-session evaluation returns overJan2023–June1 2026. Maxdrawdown is computed from the complete observed wealth path including prior losses across all rearms, not the reset risk-monitor HWM. Matched original results and all packets remain retained. Existing21 drawdown monitor tests passed; one-field settings difference verified before computation.\n\nCombined performance gates are still pending. Recombine only these candidate AlphaMax curves with unchanged crypto/Trend paths and cash weights, retaining whole/annual normal/stress comparisons. If preregistered combined gates fail, stop this cooldown family without a duration sweep. If they pass, separately preregister2022 validation before promotion. This is inspected retrospective development, not untouched OOS, a new sleeve, or qualified live performance. Existing source/borrow/label/corporate-action limitations remain.\n'
    (OUT/'REPORT.md').write_text(report)
    for p in [Path(__file__),OUT/'comparison.csv',OUT/'REPORT.md',OUT/'input_manifest.json']:refs[str(p.relative_to(ROOT))]=sha(p)
    (OUT/'phase_closure.json').write_text(json.dumps({'status':'COOLDOWN_SUBBOOK_ARMS_AUDITED_COMBINED_GATES_PENDING','sha256':refs,'qualified':False},indent=2)+'\n')
    print(json.dumps(rows,indent=2))
if __name__=='__main__':main()
