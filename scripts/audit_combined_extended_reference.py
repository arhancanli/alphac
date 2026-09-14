"""Rebuild combined daily paths directly from saved engine curves and DFF source."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/combined_extended_reference_20260913'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('arm');arm=parser.parse_args().arm;d=OUT/arm
    days=pd.date_range('2023-01-01','2026-06-01');cal=XNYSCalendar();opens=cal.expected_bar_opens(1672272000000,1780358400000,Timeframe.D1)
    marks=[cal.next_bar_open(t,Timeframe.D1) for t in opens];frame=pd.DataFrame(index=days);refs={}
    for key,name in [('max','alphamax_extended_reference_20260913'),('trend','trend_extended_reference_20260913')]:
        p=ROOT/'artifacts/analysis'/name/arm/'run/equity.parquet';refs[str(p.relative_to(ROOT))]=sha(p)
        raw=pd.read_parquet(p).set_index('ts').equity;np.testing.assert_array_equal(raw.index,marks)
        source=pd.Series(raw.to_numpy(),index=pd.to_datetime(opens,unit='ms'))
        returns=source.pct_change(fill_method=None).dropna();expected=cal.expected_bar_opens(1672531200000,1780358400000,Timeframe.D1)
        selected=returns.reindex(pd.to_datetime(expected,unit='ms'));assert selected.notna().all()
        frame[key]=0.;frame.loc[selected.index,key]=selected.to_numpy()
    p=ROOT/'artifacts/analysis/crypto_extended_reference_20260913'/arm/'run/equity.parquet';refs[str(p.relative_to(ROOT))]=sha(p)
    raw=pd.read_parquet(p).set_index('ts').equity;endpoints=pd.date_range('2023-01-01','2026-06-02');ts=endpoints.astype('datetime64[ms]').astype('int64')
    curve=raw.reindex(ts);assert curve.notna().all();frame['crypto']=curve.pct_change(fill_method=None).dropna().to_numpy()
    p=ROOT/'evidence/alphac-capital-budget-20260913/DFF.parquet';refs[str(p.relative_to(ROOT))]=sha(p)
    rates=pd.read_parquet(p).sort_values(['publication_date','obs_date']).drop_duplicates('publication_date',keep='last');rates.publication_date=rates.publication_date.astype('datetime64[ms]')
    aligned=pd.merge_asof(pd.DataFrame({'day':days.astype('datetime64[ms]')}),rates,left_on='day',right_on='publication_date',direction='backward',allow_exact_matches=False)
    assert aligned.value.notna().all() and (aligned.publication_date<aligned.day).all() and (aligned.day-aligned.obs_date).dt.days.between(0,7).all()
    frame['benchmark']=aligned.value.to_numpy()/36000
    frame['total']=frame['max']*.225+frame.crypto*.225+frame.trend*.225
    frame['excess']=frame.total-frame.benchmark
    saved=pd.read_csv(d/'daily.csv',index_col='day',parse_dates=True);assert saved.index.equals(frame.index)
    errors={key:float(np.abs(saved[key]-frame[key]).max()) for key in frame.columns};assert max(errors.values())<1e-12,errors
    assert saved.cash_contribution.eq(0).all()
    result=json.loads((d/'result.json').read_text());wealth=np.r_[1.,(1+frame.total).cumprod().to_numpy()]
    computed={'return':float(wealth[-1]-1),'excess_sharpe_proxy':float(frame.excess.mean()/frame.excess.std(ddof=1)*np.sqrt(365)),'max_drawdown':float((1-wealth/np.maximum.accumulate(wealth)).max())}
    for key,value in computed.items():assert abs(value-result[key])<1e-11
    manifest=json.loads((OUT/'input_manifest.json').read_text())['sha256']
    for p,h in manifest.items():assert sha(ROOT/p)==h,p
    c=json.loads((d/'closure.json').read_text());assert sha(ROOT/c['packet'])==c['packet_sha256']
    packet=json.loads((ROOT/c['packet']).read_text());digest=packet.pop('content_hash');assert digest=='sha256:'+hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for section in packet['required_sections'].values():
        for b in section['evidence']:assert sha(ROOT/b['path'])==b['sha256']
    refs[str(Path(__file__).relative_to(ROOT))]=sha(Path(__file__))
    with (d/'independent_audit.json').open('x') as f:json.dump({'status':'COMBINED_PATH_REBUILT_FROM_ENGINE_CURVES','observations':len(frame),'max_errors':errors,'metrics':computed,'input_bindings_verified':len(manifest),'sha256':refs,'qualification':False},f,indent=2);f.write('\n')
    print(json.dumps(computed,indent=2))
if __name__=='__main__':main()
