"""Verify retained overlay/benchmark inputs and close the fixed comparison."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/combined_2022_diagnostic_20260913'
ARMS=['baseline','candidate','baseline_stress','candidate_stress']


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    frames={arm:pd.read_csv(OUT/arm/'daily.csv',parse_dates=['day']) for arm in ARMS}
    baseline=frames['baseline']
    overlay=ROOT/'evidence/alphac-algorithm-contributions-20260913/overlay_sources'
    errors={}
    for column,iid,lake in [('btc_overlay','BINANCE:PERP:BTCUSDT','data/lake'),('spy_overlay','XUSE:CASH:SPYUSD','data/lake_mf')]:
        data=pd.concat([pd.read_parquet(overlay/lake/'ohlcv_1d'/f'instrument_id={iid}'/f'year={y}'/'data.parquet',columns=['ts_open','close']) for y in [2021,2022]])
        data['day']=pd.to_datetime(data.ts_open,utc=True).dt.tz_localize(None)
        prices=data.set_index('day').close.sort_index()
        assert prices.index.is_unique
        previous=prices.loc[pd.Timestamp('2021-12-31')]
        rebuilt=[]
        for day in baseline.day:
            if day in prices:
                rebuilt.append(prices.loc[day]/previous-1)
                previous=prices.loc[day]
            else:
                assert column=='spy_overlay'
                rebuilt.append(0.)
        errors[column]=float(np.max(np.abs(baseline[column]-rebuilt)))
        assert errors[column]<1e-14
    rates=pd.read_parquet(ROOT/'evidence/alphac-capital-budget-20260913/DFF.parquet').sort_values(['publication_date','obs_date'])
    expected=[]
    for day in baseline.day:
        known=rates[rates.publication_date<day]
        row=known.iloc[-1]
        assert 0<=(day-row.obs_date).days<=7
        expected.append(float(row.value)/100/360)
    assert np.max(np.abs(baseline.benchmark-expected))<1e-14
    errors['benchmark']=float(np.max(np.abs(baseline.benchmark-expected)))
    for arm,f in frames.items():
        for col in ['btc_overlay','spy_overlay','vintage','benchmark']:
            np.testing.assert_array_equal(f[col],baseline[col])
        audit=json.loads((OUT/arm/'independent_audit.json').read_text())
        assert audit['daily_sha256']==sha(OUT/arm/'daily.csv')
    for stress in [False,True]:
        suffix='_stress' if stress else ''
        a,b=frames['baseline'+suffix],frames['candidate'+suffix]
        np.testing.assert_allclose(b.total-a.total,.225*(b.trend-a.trend),atol=1e-14,rtol=0)
    results={arm:json.loads((OUT/arm/'result.json').read_text()) for arm in ARMS}
    b,c,bs,cs=(results[a] for a in ARMS)
    gates={'excess_gain_at_least_0_1':c['excess_sharpe_proxy']-b['excess_sharpe_proxy']>=.1,'drawdown_not_worse':c['max_drawdown']<=b['max_drawdown'],'return_not_worse':c['return']>=b['return'],'cost_stress_excess_gain_positive':cs['excess_sharpe_proxy']>bs['excess_sharpe_proxy']}
    with (OUT/'comparison.json').open('x') as f: json.dump({'results':results,'gates':gates,'passed':all(gates.values()),'source_arithmetic_errors':errors,'qualified':False},f,indent=2);f.write('\n')
    lines=['# Combined2022 source-day diagnostic: positive-only Trend rejected\n', '| Metric | Confirmed | Positive-only | Confirmed cost stress | Positive-only cost stress |','|---|---:|---:|---:|---:|']
    for label,key,fmt in [('Return','return','.3%'),('Excess Sharpe proxy','excess_sharpe_proxy','.6f'),('Maximum drawdown','max_drawdown','.3%')]:
        lines.append('| '+label+' | '+' | '.join(format(results[a][key],fmt) for a in ARMS)+' |')
    lines.extend(['\nAll four frozen development gates fail. Stop promoting this sign-only change as a general portfolio improvement; retain both paths and the crisis tradeoff. The earlier2023–2026 result remains an uncorrected legacy timing proxy. This2022 test does not repair that different horizon.\n',
        'Trials288–291 are preserved with closed packets. Four365-day paths independently reconstruct from saved Max,crypto,Trend,Vintage components; overlay price and DFF calculations separately reproduce. Candidate/control daily differences equal22.5% of the Trend difference. Three synthetic alignment tests pass. Missing equity sessions cannot become holiday zeros.\n',
        'This diagnostic groups equity source sessions with full UTC crypto days; it is not a simultaneous executable NAV. Vintage remains a killed log-spread probe and the BTCperpetual/SPY overlay remains a price-only proxy. Only Max,crypto,Trend costs are doubled. Daily capital resets lack inter-sleeve rebalancing fees; funding, financing and PIT limitations prevent qualification. Low modeled drawdown alone does not satisfy the combined goal.\n',
        'Next algorithm phase: investigate AlphaMax volatility estimates built from raw prices around corporate actions, using the now-reconciled baseline. Freeze any corrected-volatility challenger before returns and preserve original signals/labels as a control. Avoid another Trend sign-mask variant. Separately, a launchable portfolio still needs an explicit disposition for killed Vintage and a funded overlay; neither is silently removed here.\n'])
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    refs=[OUT/'comparison.json',OUT/'REPORT.md',Path(__file__),ROOT/'scripts/audit_combined_2022_diagnostic.py']
    refs.extend(OUT/arm/'independent_audit.json' for arm in ARMS)
    with (OUT/'phase_closure.json').open('x') as f: json.dump({'status':'FOUR_ARM_DIAGNOSTIC_COMPLETE_CANDIDATE_REJECTED','goal_complete':False,'qualified':False,'sha256':{str(p.relative_to(ROOT)):sha(p) for p in refs}},f,indent=2);f.write('\n')
    print(json.dumps({'results':{a:{k:results[a][k] for k in ['return','excess_sharpe_proxy','max_drawdown']} for a in ARMS},'gates':gates,'arithmetic_errors':errors}))


if __name__=='__main__': main()
