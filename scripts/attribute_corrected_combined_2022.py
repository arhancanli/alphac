"""Exact component wealth attribution of an already registered portfolio path."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/combined_2022_corrected_max_20260913'
WEIGHTS={'max':.225,'crypto':.225,'trend':.225,'vintage':.225,'btc_overlay':.05,'spy_overlay':.05}


def main():
    results={}
    for arm in ['baseline','baseline_stress']:
        f=pd.read_csv(OUT/arm/'daily.csv')
        curve=np.r_[1.,np.cumprod(1+f.total.to_numpy())]
        peak=np.maximum.accumulate(curve);trough=int(np.argmax(1-curve/peak));top=int(np.argmax(curve[:trough+1]))
        rows=[]
        for name,weight in WEIGHTS.items():
            wealth_change=curve[:-1]*weight*f[name].to_numpy()
            rows.append({'component':name,'weight':weight,'total_wealth_contribution':float(wealth_change.sum()),'worst_drawdown_wealth_contribution':float(wealth_change[top:trough].sum()),'annual_arithmetic_contribution':float((weight*f[name]).sum())})
        assert abs(sum(x['total_wealth_contribution'] for x in rows)-(curve[-1]-1))<1e-12
        assert abs(sum(x['worst_drawdown_wealth_contribution'] for x in rows)-(curve[trough]-curve[top]))<1e-12
        results[arm]={'components':rows,'peak_index':top,'trough_index':trough,'peak_date':'2021-12-31' if top==0 else str(f.day.iloc[top-1]),'trough_date':str(f.day.iloc[trough-1]),'claim':'Attribution of existing registered path, not a portfolio with any component removed.'}
    with (OUT/'component_attribution.json').open('x') as stream:json.dump(results,stream,indent=2);stream.write('\n')
    print(json.dumps(results))


if __name__=='__main__': main()
