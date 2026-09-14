"""Summarize fixed annual windows and hourly drawdown from audited crypto curves."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/crypto_extended_reference_20260913'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    refs={};summaries={};annual=[]
    bindings=json.loads((OUT/'input_manifest.json').read_text())['sha256']
    for p,h in bindings.items():assert sha(ROOT/p)==h,p
    for arm in ['baseline','baseline_stress']:
        d=OUT/arm;c=json.loads((d/'closure.json').read_text());assert sha(ROOT/c['packet'])==c['packet_sha256']
        report=json.loads((d/'calendar2023_2026_audit.json').read_text())
        f=pd.read_csv(d/'calendar2023_2026.csv');f['year']=pd.to_datetime(f.day).dt.year
        curve=pd.read_parquet(d/'run/equity.parquet').set_index('ts').equity
        hours=curve.loc[1672531200000:1780358400000]
        expected=np.arange(1672531200000,1780358400000+1,3600000)
        np.testing.assert_array_equal(hours.index.to_numpy(),expected)
        report['hourly_max_drawdown']=float((1-hours/hours.cummax()).max())
        report['hourly_observations_including_predecessor']=len(hours)
        summaries[arm]=report
        for year,g in f.groupby('year'):
            wealth=np.r_[1.,(1+g['return']).cumprod().to_numpy()]
            annual.append({'arm':arm,'year':int(year),'days':len(g),'total_return':float(wealth[-1]-1),'excess_sharpe':float(g.excess.mean()/g.excess.std(ddof=1)*np.sqrt(365)),'max_drawdown':float((1-wealth/np.maximum.accumulate(wealth)).max()),'partial_year':bool(year==2026)})
        for name in ['closure.json','calendar2023_2026_audit.json','calendar2023_2026.csv','boundary_audit.json','independent_audit.json','terminal_invariants.json']:
            p=d/name;refs[str(p.relative_to(ROOT))]=sha(p)
    pd.DataFrame(annual).to_csv(OUT/'yearly.csv',index=False)
    (OUT/'comparison.json').write_text(json.dumps(summaries,indent=2)+'\n')
    report='# Extended crypto carry reference\n\nFrozen evaluation: Jan1 2023–June1 2026, 1,248 full UTC days using next-midnight endpoints and an observed Jan1 predecessor.\n\n| Metric | Normal costs | Doubled costs |\n|---|---:|---:|\n'
    for label,key,fmt in [('Total return','total_return','.4%'),('Excess DFF Sharpe proxy','net_excess_sharpe_DFF_proxy','.4f'),('Daily maximum drawdown','max_drawdown','.4%'),('Hourly maximum drawdown','hourly_max_drawdown','.4%')]:
        report+=f"| {label} | {summaries['baseline'][key]:{fmt}} | {summaries['baseline_stress'][key]:{fmt}} |\n"
    report+='\nTwenty walk-forward legs per run; all29,976 engine marks per arm independently reconstructed, durable/final parquet parity verified. No LUNA exposure, fills, funding or settlement: its terminal event predates the tests and only eligibility applies. Source boundary screens pass but do not certify complete exchange funding schedules. Annual slices are retained.\n\nStandalone retrospective crypto, not combined AlphaC performance or a qualified sleeve. Current-vintage benchmark, modeled publication/metadata, funding marks and terminal prices remain limitations. Normal closure encountered an argument error before writes, then a final-print error after successful packet/closure creation; both preserved in evidence and did not rerun strategy returns. v2 closure fixes the print for stress. The inherited scope.initial_diagnostic prose describes old2022 and is obsolete; numeric scope and explicit evaluation govern.\n\nNext: fresh confirmedTrend normal/stress, then synchronized combined22.5% each plus32.5% zero-yield cash; report whole horizon and frozen annual slices before choosing algorithm changes.\n'
    (OUT/'REPORT.md').write_text(report)
    for p in [Path(__file__),OUT/'comparison.json',OUT/'yearly.csv',OUT/'REPORT.md',OUT/'input_manifest.json']:refs[str(p.relative_to(ROOT))]=sha(p)
    (OUT/'phase_closure.json').write_text(json.dumps({'status':'BOTH_CRYPTO_ARMS_ACCOUNTED_NOT_QUALIFIED','verified_input_bindings':len(bindings),'sha256':refs},indent=2)+'\n')
    print(json.dumps({arm:{k:x[k] for k in ['total_return','net_excess_sharpe_DFF_proxy','max_drawdown','hourly_max_drawdown']} for arm,x in summaries.items()},indent=2))
if __name__=='__main__':main()
