"""Reconstruct confirmedTrend session NAV, settled cash and dividend receivables."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/analysis/trend_group_risk_20260913'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('arm',choices=['baseline','baseline_stress']);arm=parser.parse_args().arm;d=OUT/arm
    r=json.loads((d/'reservation.json').read_text());config=r['trial_config'];cal=XNYSCalendar()
    frames={n:pd.read_parquet(d/'run'/f'{n}.parquet') for n in ['equity','fills','positions','corporate_actions','funding','financing']}
    eq=frames['equity'].set_index('ts').equity;fills=frames['fills'];pos=frames['positions'];actions=frames['corporate_actions']
    opens=cal.expected_bar_opens(config['start'],config['end'],Timeframe.D1);marks=[cal.next_bar_open(t,Timeframe.D1) for t in opens]
    np.testing.assert_array_equal(eq.index,marks);assert len(marks)==857
    assert frames['funding'].empty and frames['financing'].empty
    fm=fills.ts.map(lambda t:cal.next_bar_open(int(t),Timeframe.D1));assert set(fm)<=set(marks)
    am=actions.action_ts.map(lambda t:cal.next_bar_open(int(t),Timeframe.D1));assert set(am)<=set(marks)
    dividends=actions[actions.action_type.eq('dividend')]
    np.testing.assert_allclose(dividends.cashflow_quote,dividends.position_qty_before*dividends.cash_amount,atol=1e-10)
    accrual=actions.cashflow_quote.groupby(am).sum().reindex(marks,fill_value=0)
    raw_path=ROOT/'evidence/alphatrend-retrospective-execution-20260912/paired_prices.parquet'
    raw=pd.read_parquet(raw_path,columns=['symbol','session_ms','raw_open'])
    mapping=json.loads((raw_path.parent/'schedule.json').read_text())['instrument_symbols']
    held=pos[pos.qty<0].copy();held['symbol']=held.instrument_id.map(mapping)
    held['session_ms']=held.ts.map(dict(zip(marks,opens)))
    held=held.merge(raw,on=['symbol','session_ms'],how='left',validate='many_to_one');assert held.raw_open.notna().all()
    held['days']=(held.ts-held.session_ms)/86400000
    rate=config['resolved_settings']['costs']['equity_borrow_bps_annual']*1e-4/365
    borrow=(held.qty*held.raw_open*held.days*rate).groupby(held.ts).sum().reindex(marks,fill_value=0)
    realized=(fills.realized_pnl_quote-fills.fee).groupby(fm).sum().reindex(marks,fill_value=0)
    unreal=pos.groupby('ts').unreal_pnl.sum().reindex(marks,fill_value=0)
    reconstructed=100000+(realized+accrual+borrow).cumsum()+unreal
    residual=float((eq-reconstructed).abs().max());assert residual<1e-6,residual
    meta=json.loads((d/'run/run_meta.json').read_text())['config']
    assert abs(borrow.sum()-meta['borrow_total'])<1e-6
    payments=pd.DataFrame(meta['dividend_settlements']);pm=payments.ts.map(lambda t:marks[int(np.searchsorted(marks,t))])
    assert set(pm)<=set(marks)
    paid=payments.cashflow_quote.groupby(pm).sum().reindex(marks,fill_value=0)
    pending=(accrual-paid).cumsum()
    net_trades=(fills.notional.where(fills.side.eq('sell'),-fills.notional)-fills.fee).groupby(fm).sum().reindex(marks,fill_value=0)
    settled=100000+(net_trades+paid+borrow).cumsum()
    value=pos.assign(v=lambda x:x.qty*x.mark).groupby('ts').v.sum().reindex(marks,fill_value=0)
    cash_residual=float((eq-settled-value-pending).abs().max());assert cash_residual<1e-6,cash_residual
    assert abs(pending.iloc[-1]-meta['terminal_pending_dividends'])<1e-6
    assert abs(settled.iloc[-1]-meta['terminal_settled_cash'])<1e-6
    mapped=pd.Series(eq.to_numpy(),index=opens);expected=cal.expected_bar_opens(1672531200000,1780358400000,Timeframe.D1)
    window=mapped.loc[[1672358400000,*expected]];rets=window.pct_change().dropna();assert len(rets)==855
    benchmark_path=ROOT/'artifacts/analysis/alphamax_extended_reference_20260913/baseline/calendar2023_2026_excess.csv'
    benchmark_audit=json.loads((benchmark_path.parent/'benchmark_audit.json').read_text())
    assert sha(benchmark_path)==benchmark_audit['source_sha256'][str(benchmark_path.relative_to(ROOT))]
    benchmark=pd.read_csv(benchmark_path);np.testing.assert_array_equal(pd.to_datetime(benchmark.session,utc=True).astype('datetime64[ms, UTC]').astype('int64'),expected)
    f=pd.DataFrame({'session':benchmark.session,'equity':window.iloc[1:].to_numpy(),'return':rets.to_numpy(),'benchmark':benchmark.benchmark.to_numpy()});f['excess']=f['return']-f.benchmark
    f.to_csv(d/'calendar2023_2026_excess.csv',index=False)
    report={'status':'ALL_SESSION_NAV_CASH_RECEIVABLES_RECONCILED','engine_marks':len(marks),'session_returns':855,'nav_max_abs_residual':residual,'cash_receivable_max_abs_residual':cash_residual,'terminal_pending_dividends':float(pending.iloc[-1]),'total_return':float(window.iloc[-1]/window.iloc[0]-1),'raw_sharpe':float(rets.mean()/rets.std(ddof=1)*np.sqrt(252)),'net_excess_sharpe_DFF_proxy':float(f.excess.mean()/f.excess.std(ddof=1)*np.sqrt(252)),'max_drawdown':float((1-window/window.cummax()).max()),'qualification':False,'limitations':'Retrospective saved forecasts/current-vintage sources; modeled costs/borrow/metadata and DFF publication. Ledger reconciliation is not independent payment-date source certification.'}
    refs={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),raw_path,benchmark_path,d/'calendar2023_2026_excess.csv',*sorted((d/'run').glob('*.parquet')),d/'run/run_meta.json']}
    manifest=json.loads((OUT/'input_manifest.json').read_text())
    for p,h in manifest['bindings'].items():assert sha(ROOT/p)==h,p
    for p,h in manifest['source_seal']['files'].items():assert sha(ROOT/p)==h,p
    group=json.loads((d/'group_risk_audit.json').read_text())
    direction=json.loads((d/'direction_audit.json').read_text())
    assert len(group)==len(direction) and len(group)>0
    for g,q in zip(group,direction):
        assert g['ts']==q['ts'] and g['final_targets']==q['targets']
        assert len(g['ids'])==len(set(g['ids']))
        assert all(abs(v-1)<1e-9 or v==0 for v in g['group_vol_before_limits'].values())
        assert np.isfinite(list(g['group_vol_after_limits'].values())).all()
    report['group_rebalances_verified']=len(group)
    refs.update({str(p.relative_to(ROOT)):sha(p) for p in [d/'group_risk_audit.json',d/'direction_audit.json']})
    with (d/'independent_audit.json').open('x') as stream:json.dump({**report,'sha256':refs},stream,indent=2);stream.write('\n')
    with (d/'audit_closure.json').open('x') as stream:json.dump({'status':'ACCOUNTING_AUDITED_CANONICAL_PACKET_PENDING','audit_sha256':sha(d/'independent_audit.json'),'qualified':False},stream,indent=2);stream.write('\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
