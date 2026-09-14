"""Apply preregistered whole/annual combined cooldown gates without retuning."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/combined_session_cooldown_20260913'
CONTROL=ROOT/'artifacts/analysis/combined_extended_reference_20260913'
SPEC=ROOT/'evidence/alphamax-session-cooldown-20260913/EXPERIMENT_SPEC.json'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    gates=json.loads(SPEC.read_text())['combined_gate'];rows=[];checks={};results={};refs={str(SPEC.relative_to(ROOT)):sha(SPEC)}
    for arm,base in [('candidate','baseline'),('candidate_stress','baseline_stress')]:
        d=OUT/arm;c=CONTROL/base
        current=json.loads((d/'result.json').read_text());prior=json.loads((c/'result.json').read_text());results[arm]={'candidate':current,'baseline':prior}
        x=pd.read_csv(d/'daily.csv');y=pd.read_csv(c/'daily.csv');assert x.day.equals(y.day)
        for col in ['crypto','trend','benchmark','cash_contribution']:np.testing.assert_array_equal(x[col],y[col])
        np.testing.assert_allclose(x.total-y.total,.225*(x['max']-y['max']),atol=1e-15,rtol=0)
        stress=arm.endswith('stress');gain=current['excess_sharpe_proxy']-prior['excess_sharpe_proxy']
        checks[arm+'_excess_gain']=gain>=gates['stress_excess_gain_min' if stress else 'normal_excess_gain_min']
        checks[arm+'_return_not_lower']=current['return']>=prior['return']
        checks[arm+'_whole_drawdown']=current['max_drawdown']<=gates['normal_and_stress_full_daily_drawdown_le']
        for year in [2023,2024,2025,2026]:
            yr=pd.to_datetime(x.day).dt.year;cur=x[yr==year];old=y[yr==year]
            sr=float(cur.excess.mean()/cur.excess.std(ddof=1)*np.sqrt(365));oldsr=float(old.excess.mean()/old.excess.std(ddof=1)*np.sqrt(365));w=np.r_[1.,(1+cur.total).cumprod().to_numpy()];dd=float((1-w/np.maximum.accumulate(w)).max())
            checks[f'{arm}_{year}_drawdown']=dd<=gates['all_annual_daily_drawdown_le']
            checks[f'{arm}_{year}_excess_floor']=sr-oldsr>=gates['annual_excess_degradation_floor_vs_matched_baseline']
            rows.append({'arm':arm,'year':year,'days':len(cur),'return':float(w[-1]-1),'excess_sharpe':sr,'baseline_excess_sharpe':oldsr,'excess_change':sr-oldsr,'max_drawdown':dd})
        audit=json.loads((d/'independent_audit.json').read_text());assert audit['observations']==1248
        for p,h in audit['sha256'].items():assert sha(ROOT/p)==h
        for folder in [d,c]:
            for name in ['result.json','daily.csv','closure.json','independent_audit.json']:
                p=folder/name;refs[str(p.relative_to(ROOT))]=sha(p)
    passed=all(checks.values());decision='PASS_BROADER_GATES_REQUIRE_SEPARATE_2022_CHECK' if passed else 'FAIL_STOP_COOLDOWN_FAMILY_NO_DURATION_SWEEP'
    pd.DataFrame(rows).to_csv(OUT/'yearly_comparison.csv',index=False)
    (OUT/'gate_result.json').write_text(json.dumps({'decision':decision,'checks':checks,'results':results,'qualification':False},indent=2)+'\n')
    report='# Combined10-session cooldown comparison\n\nFrozenJan2023–June1 2026; only AlphaMax cooldown path changes. Crypto,confirmedTrend,benchmark and cash contributions exactly unchanged on every date.\n\n| Metric | Baseline | Candidate | Baseline stress | Candidate stress |\n|---|---:|---:|---:|---:|\n'
    for label,key,fmt in [('Return','return','.4%'),('Excess Sharpe','excess_sharpe_proxy','.4f'),('Daily max drawdown','max_drawdown','.4%')]:
        vals=[results['candidate']['baseline'][key],results['candidate']['candidate'][key],results['candidate_stress']['baseline'][key],results['candidate_stress']['candidate'][key]];report+='| '+label+' | '+' | '.join(format(v,fmt) for v in vals)+' |\n'
    report+=f'\nDecision: **{decision}**. All gates were frozen in the subbook preregistration before candidate returns. Full-period improvements do not override annual guardrails. Failed checks: '+(', '.join(k for k,v in checks.items() if not v) or 'none')+'.\n\n'
    report+='Both combined paths independently reconstructed from saved engine curves and DFF; all2,496daily observations reconcile. Daily weights22.5% each+32.5%zero-yieldcash, source-session equity/fullUTCcrypto conventions unchanged. Saved-path difference equals.225 times the AlphaMax difference, confirming no hidden component substitution.\n\n'
    report+=('Next: separately preregister2022 normal/stress validation of the same10-session rule; no promotion yet. ' if passed else 'Stop this cooldown family as preregistered. Preserve candidate and baseline; do not sweep nearby durations or relax annual gates. Pivot to crypto turnover costs or independent alpha research. ')
    report+='Retrospective inspected-history research; no qualified sleeve or live deployment. Combined excessSharpe remains below2. Intraday synchronization, integrated rebalancing/collateral, source timing, equity artifacts and modeled funding/borrow remain limitations.\n'
    (OUT/'REPORT.md').write_text(report)
    for p in [Path(__file__),OUT/'REPORT.md',OUT/'gate_result.json',OUT/'yearly_comparison.csv']:refs[str(p.relative_to(ROOT))]=sha(p)
    (OUT/'phase_closure.json').write_text(json.dumps({'status':decision,'sha256':refs,'qualified':False},indent=2)+'\n')
    print(json.dumps({'decision':decision,'checks':checks,'yearly':rows},indent=2))
if __name__=='__main__':main()
