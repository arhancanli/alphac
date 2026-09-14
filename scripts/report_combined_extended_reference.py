"""Fixed annual reporting and saved-path attribution for the combined reference."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/combined_extended_reference_20260913'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    rows=[];attribution={};results={};refs={}
    for arm in ['baseline','baseline_stress']:
        d=OUT/arm;f=pd.read_csv(d/'daily.csv');f['year']=pd.to_datetime(f.day).dt.year;r=json.loads((d/'result.json').read_text());results[arm]=r
        audit=json.loads((d/'independent_audit.json').read_text());assert audit['observations']==1248
        for p,h in audit['sha256'].items():assert sha(ROOT/p)==h
        for year,g in f.groupby('year'):
            wealth=np.r_[1.,(1+g.total).cumprod().to_numpy()];sr=float(g.excess.mean()/g.excess.std(ddof=1)*np.sqrt(365));dd=float((1-wealth/np.maximum.accumulate(wealth)).max())
            rows.append({'arm':arm,'year':int(year),'days':len(g),'return':float(wealth[-1]-1),'excess_sharpe':sr,'max_drawdown':dd,'sharpe_gt2':sr>2,'drawdown_le11pct':dd<=.11,'partial_year':bool(year==2026)})
        prior=np.r_[1.,(1+f.total).cumprod().to_numpy()[:-1]]
        parts={key:float((prior*.225*f[key]).sum()) for key in ['max','crypto','trend']};parts['idle_cash']=0.
        assert abs(sum(parts.values())-r['return'])<1e-12
        attribution[arm]={'wealth_return_contributions':parts,'benchmark_compound_return':float((1+f.benchmark).prod()-1),'interpretation':'Exact attribution of the saved portfolio wealth path, not sleeve removal or reweighting counterfactual.'}
        for p in [d/'daily.csv',d/'result.json',d/'independent_audit.json',d/'closure.json']:refs[str(p.relative_to(ROOT))]=sha(p)
    pd.DataFrame(rows).to_csv(OUT/'yearly.csv',index=False);(OUT/'component_attribution.json').write_text(json.dumps(attribution,indent=2)+'\n')
    report='# Combined AlphaC extended reference\n\nFrozen evaluation: January1 2023–June1 2026 inclusive, 1,248 daily returns. Allocation:22.5% AlphaMax,22.5% crypto carry,22.5% confirmedTrend,32.5% idlecash at zero yield. EntireNAV benchmark uses the retained prior-publication DFF proxy.\n\n| Metric | Normal costs | Doubled costs |\n|---|---:|---:|\n'
    for label,key,fmt in [('Total return','return','.4%'),('Excess Sharpe','excess_sharpe_proxy','.4f'),('Raw Sharpe','raw_sharpe','.4f'),('Daily maximum drawdown','max_drawdown','.4%')]:report+=f"| {label} | {results['baseline'][key]:{fmt}} | {results['baseline_stress'][key]:{fmt}} |\n"
    report+='\nThe full-period daily drawdown threshold passes both scenarios, but the >2 excess-Sharpe target fails both. Neither proves the15-qualified-sleeve goal or full intraday/stress-horizon requirement. The2022 result of1.23 excessSharpe is a retrospective historical slice, not representative of this broader result. No averaging of standalone Sharpes was used.\n\nBoth paths were independently rebuilt from raw saved equity curves: invert XNYS next-session marks, require actual source-session predecessors, and insert zero equity return only on exchange-closed dates after complete session checks. Crypto uses actual next-midnight endpoints. All2,496 daily rows and fresh DFF source alignment reconcile; both reservations/packets verified. Fixed annual slices are in yearly.csv, including partial2026.\n\n'
    report+='The saved-path component attribution identifies the contribution of each sleeve without calculating a new allocation. Crypto provides the strongest standalone excess result but loses substantial performance at doubled costs. AlphaMax has weak broader returns and an inherited336-session drawdown cooldown; confirmedTrend also falls below the cash benchmark. Changing idlecash assumptions cannot establish new alpha or qualified sleeves.\n\nNext algorithm phase: use these preserved normal/stress baselines to preregister a bounded investigation of equity risk recovery and crypto turnover costs. First verify the intended cooldown time units and recorded halt behavior; keep every computed variant and require combined full/annual stress reporting. No weight or cash-yield sweep, no target relabeling, and no qualification based on this inspected history. Economically distinct sleeves remain a separate required research lane.\n\nThis is a retrospective fixed-subbook-weight research proxy. Daily capital rebalancing execution, collateral/financing, intraday synchronization, historical source availability, older equity price artifacts, funding schedule completeness and true terminal proceeds remain unverified or modeled. Daily threshold passes are not a live maximum-loss guarantee. No admission, deployment or additional qualified sleeve is claimed.\n'
    (OUT/'REPORT.md').write_text(report)
    for p in [Path(__file__),OUT/'yearly.csv',OUT/'component_attribution.json',OUT/'REPORT.md',OUT/'protocol.json',OUT/'input_manifest.json']:refs[str(p.relative_to(ROOT))]=sha(p)
    (OUT/'phase_closure.json').write_text(json.dumps({'status':'COMBINED_REFERENCE_AUDITED_SHARPE_TARGET_FAILED','qualified':False,'sha256':refs},indent=2)+'\n')
    print(json.dumps({'annual':rows,'attribution':attribution},indent=2))
if __name__=='__main__':main()
