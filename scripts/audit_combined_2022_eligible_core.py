"""Verify the declared capital policy without recomputing any sleeve strategy."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/combined_2022_eligible_core_20260913'
CONTROL=ROOT/'artifacts/analysis/combined_2022_corrected_max_20260913'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('arm');arm=parser.parse_args().arm
    d=OUT/arm;f=pd.read_csv(d/'daily.csv');old=pd.read_csv(CONTROL/arm/'daily.csv')
    assert f.day.tolist()==old.day.tolist() and len(f)==365
    for col in ['max','crypto','trend','vintage','btc_overlay','spy_overlay','benchmark']:
        np.testing.assert_array_equal(f[col],old[col])
    total=np.array([.225*row.max+.225*row.crypto+.225*row.trend for row in f.itertuples()])
    assert np.max(np.abs(total-f.total))<1e-14
    assert (f.cash_contribution==0).all()
    removed=.225*old.vintage+.05*old.btc_overlay+.05*old.spy_overlay
    assert np.max(np.abs((f.total-old.total)+removed))<1e-14
    value=peak=1.;dd=0.
    for r in total:
        value*=1+r;peak=max(peak,value);dd=max(dd,1-value/peak)
    excess=total-f.benchmark.to_numpy()
    result=json.loads((d/'result.json').read_text())
    for k,v in {'return':value-1,'max_drawdown':dd,'excess_sharpe_proxy':np.mean(excess)/np.std(excess,ddof=1)*np.sqrt(365)}.items():assert abs(v-result[k])<1e-12
    c=json.loads((d/'closure.json').read_text());p=ROOT/c['packet'];assert sha(p)==c['packet_sha256']
    packet=json.loads(p.read_text());digest=packet.pop('content_hash');assert digest=='sha256:'+hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for ref in next(iter(packet['required_sections'].values()))['evidence']:assert sha(ROOT/ref['path'])==ref['sha256']
    audit={'status':'CAPITAL_RETIREMENT_EXACTLY_RECONSTRUCTED','core_weights':[.225,.225,.225],'idle_cash_weight':.325,'cash_yield':0,'benchmark_applies_to_total_nav':True,'sleeve_paths_unchanged':True,'packet_verified':True,'daily_sha256':sha(d/'daily.csv'),'qualified':False}
    with (d/'independent_audit.json').open('x') as stream:json.dump(audit,stream,indent=2);stream.write('\n')
    print(json.dumps({'arm':arm,**audit}))


if __name__=='__main__':main()
