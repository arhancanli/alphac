"""Independent saved-ledger reconstruction; no candidate replay."""
from pathlib import Path
import json,hashlib
import pandas as pd,numpy as np
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
ROOT=Path(__file__).resolve().parents[1];D=ROOT/'artifacts/analysis/earnings_change_20260913_v2/normal'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 r=json.loads((D/'reservation.json').read_text());cfg=r['trial_config'];cal=XNYSCalendar()
 frames={n:pd.read_parquet(D/'run'/f'{n}.parquet') for n in ['equity','fills','positions','corporate_actions','funding','financing']}
 eq=frames['equity'].set_index('ts').equity;fills=frames['fills'];pos=frames['positions'];actions=frames['corporate_actions']
 opens=cal.expected_bar_opens(cfg['start'],cfg['end'],Timeframe.D1);marks=[cal.next_bar_open(t,Timeframe.D1) for t in opens]
 np.testing.assert_array_equal(eq.index,marks)
 assert frames['funding'].empty and frames['financing'].empty
 fm=fills.ts.map(lambda t:cal.next_bar_open(int(t),Timeframe.D1));fm.loc[fills.reason.eq('forced_flat')]=fills.loc[fills.reason.eq('forced_flat'),'ts']
 am=actions.action_ts.map(lambda t:cal.next_bar_open(int(t),Timeframe.D1))
 dividends=actions[actions.action_type.eq('dividend')]
 np.testing.assert_allclose(dividends.cashflow_quote,dividends.position_qty_before*dividends.cash_amount,atol=1e-10)
 accrual=actions.cashflow_quote.groupby(am).sum().reindex(marks,fill_value=0)
 held=pos[pos.qty<0][['ts','instrument_id','qty']].copy()
 terminal=fills[fills.reason.eq('forced_flat')&fills.side.eq('buy')][['ts','instrument_id','qty']].copy();terminal['qty']*=-1
 held=pd.concat([held,terminal],ignore_index=True);held['session_ms']=held.ts.map(dict(zip(marks,opens)))
 table=PITDataReader(LakePaths(ROOT/'evidence/core-2023-2026-frozen-inputs-20260913/lake')).ohlcv(cfg['instrument_ids'],start=cfg['start'],end=cfg['end'],as_of=cfg['end'],tf=Timeframe.D1)
 raw=table.select(['instrument_id','ts_open','open']).to_pandas();raw['session_ms']=raw.ts_open.astype('datetime64[ms, UTC]').astype('int64');raw=raw.rename(columns={'open':'raw_open'})
 held=held.merge(raw[['instrument_id','session_ms','raw_open']],on=['instrument_id','session_ms'],how='left',validate='many_to_one');assert held.raw_open.notna().all()
 held['days']=(held.ts-held.session_ms)/86400000
 rate=cfg['resolved_costs']['equity_borrow_bps_annual']*1e-4/365
 borrow=(held.qty*held.raw_open*held.days*rate).groupby(held.ts).sum().reindex(marks,fill_value=0)
 realized=(fills.realized_pnl_quote-fills.fee).groupby(fm).sum().reindex(marks,fill_value=0)
 unreal=pos.groupby('ts').unreal_pnl.sum().reindex(marks,fill_value=0)
 reconstructed=100000+(realized+accrual+borrow).cumsum()+unreal
 residual=float((eq-reconstructed).abs().max());assert residual<1e-6,residual
 meta=json.loads((D/'run/run_meta.json').read_text())['config'];assert abs(borrow.sum()-meta['borrow_total'])<1e-6
 payments=pd.DataFrame(meta['dividend_settlements']);pm=payments.ts.map(lambda t:marks[int(np.searchsorted(marks,t))])
 paid=payments.cashflow_quote.groupby(pm).sum().reindex(marks,fill_value=0);pending=(accrual-paid).cumsum()
 net_trades=(fills.notional.where(fills.side.eq('sell'),-fills.notional)-fills.fee).groupby(fm).sum().reindex(marks,fill_value=0)
 settled=100000+(net_trades+paid+borrow).cumsum();value=pos.assign(v=lambda x:x.qty*x.mark).groupby('ts').v.sum().reindex(marks,fill_value=0)
 cashres=float((eq-settled-value-pending).abs().max());assert cashres<1e-6,cashres
 assert abs(pending.iloc[-1]-meta['terminal_pending_dividends'])<1e-6
 assert abs(settled.iloc[-1]-meta['terminal_settled_cash'])<1e-6
 mapped=pd.Series(eq.to_numpy(),index=opens);expected=cal.expected_bar_opens(1672531200000,1780358400000,Timeframe.D1)
 window=mapped.loc[[1672358400000,*expected]];rets=window.pct_change().dropna()
 bp=ROOT/'artifacts/analysis/alphamax_extended_reference_20260913/baseline/calendar2023_2026_excess.csv';b=pd.read_csv(bp)
 np.testing.assert_array_equal(pd.to_datetime(b.session,utc=True).astype('datetime64[ms, UTC]').astype('int64'),expected)
 f=pd.DataFrame({'session':b.session,'equity':window.iloc[1:].to_numpy(),'return':rets.to_numpy(),'benchmark':b.benchmark.to_numpy()});f['excess']=f['return']-f.benchmark
 f.to_csv(D/'calendar2023_2026_excess.csv',index=False)
 report={'pass':True,'status':'SAVED_ACCOUNTING_RECONCILED_NOT_FULL_ADMISSION','engine_marks':len(marks),'evaluated_session_returns':len(rets),'extra_source_sessions_after_cutoff':[str(pd.Timestamp(t,unit='ms',tz='UTC')) for t in opens if t>=1780358400000],'nav_residual':residual,'cash_pending_residual':cashres,'borrow_total':float(borrow.sum()),'total_return':float(window.iloc[-1]/window.iloc[0]-1),'raw_sharpe':float(rets.mean()/rets.std(ddof=1)*np.sqrt(252)),'excess_sharpe_DFF_proxy':float(f.excess.mean()/f.excess.std(ddof=1)*np.sqrt(252)),'max_drawdown':float((1-window/window.cummax()).max()),'qualified':False,'limitations':'Saved-fill realized/unrealized fields used; positions and execution-price source checks still needed. Extra June2 source session excluded from evaluation, not replayed.'}
 report['bindings']=[{'path':str(p),'sha256':sha(p)} for p in [Path(__file__),bp,*sorted((D/'run').glob('*.parquet')),D/'run/run_meta.json']]
 (D/'accounting_audit.json').write_text(json.dumps(report,indent=2)+'\n');print({k:v for k,v in report.items() if k!='bindings'})
if __name__=='__main__':main()
