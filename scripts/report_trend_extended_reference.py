"""Report audited confirmedTrend extended reference and frozen annual slices."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/trend_extended_reference_20260913'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    reports={};rows=[];refs={}
    for arm in ['baseline','baseline_stress']:
        d=OUT/arm;a=json.loads((d/'independent_audit.json').read_text());c=json.loads((d/'audit_closure.json').read_text())
        assert sha(d/'independent_audit.json')==c['audit_sha256'];assert sha(ROOT/c['packet'])==c['packet_sha256']
        for p,h in a['sha256'].items():assert sha(ROOT/p)==h
        reports[arm]={k:v for k,v in a.items() if k!='sha256'}
        f=pd.read_csv(d/'calendar2023_2026_excess.csv');f['year']=pd.to_datetime(f.session,utc=True).dt.year
        for year,g in f.groupby('year'):
            w=np.r_[1.,(1+g['return']).cumprod().to_numpy()]
            rows.append({'arm':arm,'year':int(year),'sessions':len(g),'total_return':float(w[-1]-1),'excess_sharpe':float(g.excess.mean()/g.excess.std(ddof=1)*np.sqrt(252)),'max_drawdown':float((1-w/np.maximum.accumulate(w)).max()),'partial_year':bool(year==2026)})
        for p in [d/'independent_audit.json',d/'audit_closure.json',d/'calendar2023_2026_excess.csv']:refs[str(p.relative_to(ROOT))]=sha(p)
    (OUT/'comparison.json').write_text(json.dumps(reports,indent=2)+'\n');pd.DataFrame(rows).to_csv(OUT/'yearly.csv',index=False)
    report='# ConfirmedTrend extended reference\n\nFrozen Jan2023–June1 2026, fresh cash/risk state from Dec29 2022, established forecasts anchored2012 with future rows removed, unchanged confirmation/normalization and10-session rebalance.\n\n| Metric | Normal costs | Doubled costs |\n|---|---:|---:|\n'
    for label,key,fmt in [('Total return','total_return','.4%'),('Excess DFF Sharpe proxy','net_excess_sharpe_DFF_proxy','.4f'),('Maximum drawdown','max_drawdown','.4%')]:report+=f"| {label} | {reports['baseline'][key]:{fmt}} | {reports['baseline_stress'][key]:{fmt}} |\n"
    report+='\nBoth runs have857 observed engine marks/855 evaluation returns. Independent reconstruction covers fills, post-fill short borrow at raw session opens, ex-date dividend accruals, settlements and pending receivables. Saved engine labels are inverted to source sessions; observedDec30 predecessor retained. Annual slices saved separately. Initial auditor borrowed legacy conventions incorrectly and failed; its source/error are preserved, corrected audit passes without strategy recomputation.\n\nThese are standalone retrospective results, not combined AlphaC or sleeve qualification. Current-vintage forecasts, source timing, static borrow, payment dates and USD DFF remain subject to retained modeling limitations. Packet closure accounts for the trial; independent audit is linked in audit_closure.json. All three core components are now measured for normal/stress. Next: reserve synchronized combined identities using fixed22.5% each plus32.5% zero-yield idle cash, retain full and annual outcomes, then choose a preregistered algorithm improvement from the evidence.\n'
    (OUT/'REPORT.md').write_text(report)
    for p in [Path(__file__),OUT/'comparison.json',OUT/'yearly.csv',OUT/'REPORT.md']:refs[str(p.relative_to(ROOT))]=sha(p)
    (OUT/'phase_closure.json').write_text(json.dumps({'status':'BOTH_CONFIRMED_TREND_ARMS_AUDITED_NOT_QUALIFIED','sha256':refs},indent=2)+'\n')
    print(json.dumps(reports,indent=2))
if __name__=='__main__':main()
