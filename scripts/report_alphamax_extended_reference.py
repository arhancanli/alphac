"""Report fixed annual slices and risk counters from independently audited runs."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/alphamax_extended_reference_20260913'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    rows=[];risk={};reports={};refs={}
    manifest=json.loads((OUT/'input_manifest.json').read_text())['sha256']
    for path,digest in manifest.items():assert sha(ROOT/path)==digest,path
    for arm in ['baseline','baseline_stress']:
        d=OUT/arm
        closure=json.loads((d/'closure.json').read_text());assert sha(ROOT/closure['packet'])==closure['packet_sha256']
        report=json.loads((d/'benchmark_audit.json').read_text());reports[arm]=report
        f=pd.read_csv(d/'calendar2023_2026_excess.csv');f['year']=pd.to_datetime(f.session,utc=True).dt.year
        for year,g in f.groupby('year'):
            wealth=np.r_[1.,(1+g['return']).cumprod().to_numpy()]
            vol=g.excess.std(ddof=1)
            rows.append({'arm':arm,'year':int(year),'sessions':len(g),'total_return':float(wealth[-1]-1),'excess_sharpe':float(g.excess.mean()/vol*np.sqrt(252)) if vol>0 else None,'max_drawdown':float((1-wealth/np.maximum.accumulate(wealth)).max()),'partial_year':bool(year==2026)})
        wf=json.loads((d/'run/walkforward.json').read_text());legs=[];terminals=[]
        for leg in wf['legs']:
            folder=d/f"run/legs/leg_{leg['leg']:02d}"
            fills=pd.read_parquet(folder/'fills.parquet');pos=pd.read_parquet(folder/'positions.parquet')
            forced=fills[fills.reason.eq('forced_flat')]
            for item in forced.to_dict('records'):
                terminals.append({'leg':leg['leg'],**item})
            legs.append({'leg':leg['leg'],'start':str(pd.to_datetime(leg['test_start'],unit='ms',utc=True)),'end_exclusive':str(pd.to_datetime(leg['test_end'],unit='ms',utc=True)),'position_rows':len(pos),'fill_rows':len(fills),'risk_counters':leg['risk_counters']})
        risk[arm]={'legs':legs,'flat_halted_sessions':sum(l['risk_counters']['bars_halted_flat'] for l in legs),'auto_rearms':sum(l['risk_counters']['n_auto_rearms'] for l in legs),'forced_terminal_fills':terminals}
        for p in [d/'closure.json',d/'benchmark_audit.json',d/'independent_audit.json',d/'calendar2023_2026_excess.csv',d/'run/walkforward.json']:
            refs[str(p.relative_to(ROOT))]=sha(p)
    pd.DataFrame(rows).to_csv(OUT/'yearly.csv',index=False)
    (OUT/'risk_and_terminal_diagnostics.json').write_text(json.dumps(risk,indent=2,default=str)+'\n')
    normal=reports['baseline'];stress=reports['baseline_stress']
    text='# AlphaMax extended corrected reference\n\n'
    text+='Frozen evaluation: January 1, 2023–June 1, 2026, with an observed December 30, 2022 predecessor. Fresh walk-forward cash/risk state; corrected momentum/sigma and session-complete split-corrected covariance. Original algorithm knobs retained.\n\n'
    text+='| Metric | Normal costs | Doubled costs |\n|---|---:|---:|\n'
    for label,key,fmt in [('Total return','total_return','.4%'),('Excess Sharpe (DFF proxy)','net_excess_sharpe_DFF_proxy','.4f'),('Maximum drawdown','max_drawdown','.4%')]:
        text+=f'| {label} | {normal[key]:{fmt}} | {stress[key]:{fmt}} |\n'
    text+='\nThese are standalone sleeve results, not combined AlphaC performance. Both runs have 855 evaluation returns and 857 independently reconciled engine marks in fourteen legs. Annual slices include their actual predecessor and are saved separately. The modeled current-vintage DFF benchmark compounds over 1,249 calendar days; it is not certified cash yield.\n\n'
    text+=f"The normal-cost run spends {risk['baseline']['flat_halted_sessions']} sessions flat under its existing drawdown ladder, with {risk['baseline']['auto_rearms']} automatic rearm. Its configured cooldown is 336 equity session bars. This accounts for the five consecutive empty-position legs; no missing-feed/cold-start hold is needed to explain those recorded flat legs. Do not shorten the cooldown retrospectively or attribute a counterfactual benefit without a new preregistered experiment.\n\n"
    text+='The broad result exposes a weak reference and provides an algorithm-research target. Retain the original losses and complete crypto and confirmedTrend normal/stress replays before judging the combined rule. No sleeve is qualified. Historical HLT/RIOT EWMA boundaries, raw forward labels, modeled membership/metadata, static borrow and final-close terminal proceeds remain limitations. No untouched OOS or live performance claim.\n'
    (OUT/'REPORT.md').write_text(text)
    for p in [Path(__file__),OUT/'yearly.csv',OUT/'risk_and_terminal_diagnostics.json',OUT/'REPORT.md',OUT/'input_manifest.json']:refs[str(p.relative_to(ROOT))]=sha(p)
    (OUT/'phase_closure.json').write_text(json.dumps({'status':'BOTH_EXTENDED_REFERENCE_ARMS_ACCOUNTED_NOT_QUALIFIED','verified_input_bindings':len(manifest),'sha256':refs},indent=2)+'\n')
    print(json.dumps({'normal':{k:normal[k] for k in ['total_return','net_excess_sharpe_DFF_proxy','max_drawdown']},'stress':{k:stress[k] for k in ['total_return','net_excess_sharpe_DFF_proxy','max_drawdown']},'risk_normal_flat_sessions':risk['baseline']['flat_halted_sessions']},indent=2))

if __name__=='__main__':main()
