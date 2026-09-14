"""Independent saved-component reconstruction and packet verification."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/combined_2022_corrected_max_20260913'


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('arm');arm=parser.parse_args().arm
    directory=OUT/arm
    frame=pd.read_csv(directory/'daily.csv',parse_dates=['day'])
    expected=pd.date_range('2022-01-01','2022-12-31')
    assert frame.day.tolist()==expected.tolist()
    closure=json.loads((directory/'closure.json').read_text());packet_path=ROOT/closure['packet'];assert sha(packet_path)==closure['packet_sha256']
    packet=json.loads(packet_path.read_text());h=packet.pop('content_hash');assert h=='sha256:'+hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for ref in next(iter(packet['required_sections'].values()))['evidence']: assert sha(ROOT/ref['path'])==ref['sha256']
    cal=XNYSCalendar();sessions=cal.expected_bar_opens(1640908800000,1672531200000,Timeframe.D1)
    stress=arm.endswith('_stress')
    paths={'trend':ROOT/'artifacts/analysis/alphatrend_positive_targets_20260913'/arm/'run/equity.parquet',
           'max':ROOT/'artifacts/analysis/alphamax_covariance_basis_20260913'/('sessions_splits_stress' if stress else 'sessions_splits')/'run/equity.parquet',
           'vintage':ROOT/'evidence/combined-baseline-audit-20260912/sources/artifacts/probe/cpi_surprise_size/equity.parquet'}
    errors={}
    for name,p in paths.items():
        saved=pd.read_parquet(p).set_index('ts').equity
        r=np.zeros(365)
        for previous,current in zip(sessions[:-1],sessions[1:],strict=True):
            left,right=(previous,current) if name=='vintage' else (cal.next_bar_open(previous,Timeframe.D1),cal.next_bar_open(current,Timeframe.D1))
            i=int((current-1640995200000)//86400000)
            r[i]=float(saved.loc[right]/saved.loc[left]-1)
        errors[name]=float(np.max(np.abs(frame[name]-r)))
        assert errors[name]<1e-14
    p=ROOT/'artifacts/analysis/crypto_full2022_terminal_20260913'/('terminal_lower_cost_stress' if stress else 'terminal_lower')/'run/equity.parquet'
    saved=pd.read_parquet(p).set_index('ts').equity
    r=[]
    for day in expected:
        left=int(day.timestamp()*1000);right=left+86400000
        r.append(saved.loc[right]/saved.loc[left]-1)
    errors['crypto']=float(np.max(np.abs(frame.crypto-r)));assert errors['crypto']<1e-14
    # Reconstruct every weighted daily return without dataframe sum or the runner helper.
    total=np.array([sum([.225*row.max,.225*row.crypto,.225*row.trend,.225*row.vintage,.05*row.btc_overlay,.05*row.spy_overlay]) for row in frame.itertuples()])
    assert np.max(np.abs(total-frame.total))<1e-14
    value=1.;peak=1.;dd=0.
    for r in total:
        value*=1+r;peak=max(peak,value);dd=max(dd,1-value/peak)
    excess=total-frame.benchmark.to_numpy()
    result=json.loads((directory/'result.json').read_text())
    for k,v in {'return':value-1,'max_drawdown':dd,'excess_sharpe_proxy':np.mean(excess)/np.std(excess,ddof=1)*np.sqrt(365)}.items(): assert abs(v-result[k])<1e-12
    audit={'status':'SAVED_CORE_COMPONENTS_AND_WEIGHTED_METRICS_VERIFIED','component_errors':errors,'packet_verified':True,'daily_sha256':sha(directory/'daily.csv'),'qualified':False,'limitations':'Overlay and benchmark source arithmetic separately inspected; no execution, financing or PIT certification.'}
    with (directory/'independent_audit.json').open('x') as f: json.dump(audit,f,indent=2);f.write('\n')
    print(json.dumps(audit))


if __name__=='__main__': main()
