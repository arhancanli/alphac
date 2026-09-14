"""Isolate the effect of corrected AlphaMax in saved combined2022 results."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/combined_2022_corrected_max_20260913'
CONTROL=ROOT/'artifacts/analysis/combined_2022_diagnostic_20260913'


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    comparisons={};checks={}
    for arm in ['baseline','baseline_stress']:
        current=pd.read_csv(OUT/arm/'daily.csv')
        old=pd.read_csv(CONTROL/arm/'daily.csv')
        assert current.day.tolist()==old.day.tolist()
        for column in ['crypto','trend','vintage','btc_overlay','spy_overlay','benchmark']:
            np.testing.assert_array_equal(current[column],old[column])
        error=float(np.max(np.abs((current.total-old.total)-.225*(current['max']-old['max']))))
        assert error<1e-14
        audit=json.loads((OUT/arm/'independent_audit.json').read_text());assert audit['daily_sha256']==sha(OUT/arm/'daily.csv')
        before=json.loads((CONTROL/arm/'result.json').read_text())
        after=json.loads((OUT/arm/'result.json').read_text())
        comparisons[arm]={'control':{k:before[k] for k in ['return','excess_sharpe_proxy','max_drawdown']},'corrected':{k:after[k] for k in ['return','excess_sharpe_proxy','max_drawdown']}}
        checks[arm]={'unchanged_other_components':True,'max_contribution_residual':error}
    b,c=comparisons['baseline']['control'],comparisons['baseline']['corrected']
    bs,cs=comparisons['baseline_stress']['control'],comparisons['baseline_stress']['corrected']
    gates={'excess_gain_at_least_0_1':c['excess_sharpe_proxy']-b['excess_sharpe_proxy']>=.1,'drawdown_not_worse':c['max_drawdown']<=b['max_drawdown'],'return_not_worse':c['return']>=b['return'],'cost_stress_excess_gain_positive':cs['excess_sharpe_proxy']>bs['excess_sharpe_proxy']}
    result={'comparisons':comparisons,'gates':gates,'checks':checks,'qualified':False}
    with (OUT/'comparison.json').open('x') as f: json.dump(result,f,indent=2);f.write('\n')
    lines=['# Corrected AlphaMax in combined2022: fixed substitution\n','| Scenario | Return | Excess Sharpe proxy | Drawdown |','|---|---:|---:|---:|']
    for arm,pair in comparisons.items():
        for kind,r in pair.items(): lines.append(f"| {arm} {kind} | {r['return']:.3%} | {r['excess_sharpe_proxy']:.6f} | {r['max_drawdown']:.3%} |")
    lines.extend(['\nOthercomponents,benchmark,dates andweights match the saved288/290controls exactly. Eachdaily portfolio difference is22.5% of the AlphaMax return difference. Newarms302/303 are registered and preserved;730dailyrows independently reconstructed. All result claims remain retrospective.\n','The more complete AlphaMax corrections improve price semantics; they do not fix a portfolio composed partly of a killed CPI probe and a price-only BTCperpetual/SPY overlay. No change to Vintage or overlay allocation was hidden in this test. Equity closes grouped with full UTCcrypto days are an economic-date diagnostic, not a simultaneous executable NAV. Historical data timing, financing, overnight accrual attribution and inter-sleeve rebalancing costs remain unresolved. Onlythree core components receive doubledcosts.\n','The earlier2023–2026 legacycombined1.1065excessSharpe remains affected by timing mismatch; this2022 comparison cannot validate it. No sleeve admission or launch. Next inspect saved component contribution and downside concentration to identify portfolio-design changes with an economic rationale; register any revised allocation before returns and preserve this fixed control.\n'])
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    refs=[OUT/'comparison.json',OUT/'REPORT.md',Path(__file__),ROOT/'scripts/audit_combined_2022_corrected_max.py']
    refs.extend(OUT/arm/'independent_audit.json' for arm in ['baseline','baseline_stress'])
    with (OUT/'phase_closure.json').open('x') as f: json.dump({'status':'TWO_ARM_COMPONENT_SUBSTITUTION_COMPLETE','qualified':False,'goal_complete':False,'sha256':{str(p.relative_to(ROOT)):sha(p) for p in refs}},f,indent=2);f.write('\n')
    print(json.dumps(result))


if __name__=='__main__': main()
