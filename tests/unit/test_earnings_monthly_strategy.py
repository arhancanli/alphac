from dataclasses import replace
from types import SimpleNamespace
import pandas as pd
import exchange_calendars as xc
import pytest
from test_backtest_engine import bar_row,make_instrument,ohlcv_table
from alphaforge.backtest.engine import EventDrivenBacktester,StaticCostInputs
from alphaforge.core.instruments import InstrumentStore
from alphaforge.core.types import AssetClass,MarketType
from alphaforge.core.time import Timeframe
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.store.reader import PITDataReader
from earnings_monthly_strategy import EarningsMonthlyStrategy,callback_routes


def setup_strategy():
 cal=xc.get_calendar('XNYS',start='2024-11-27',end='2024-12-09')
 sessions=[(s.date(),cal.session_open(s).to_pydatetime(),cal.session_close(s).to_pydatetime()) for s in cal.sessions]
 routes=callback_routes(sessions)
 ids=[f'XUSE:CASH:T{i:02d}USD' for i in range(40)]
 calls=[]
 def scores(t):calls.append(t);return {iid:float(i) for i,iid in enumerate(ids)}
 strategy=EarningsMonthlyStrategy(routes=routes,score_provider=scores,stable_ids={i:i for i in ids},eligible_provider=lambda t:ids)
 return strategy,ids,sessions,calls


def test_risk_reduces_between_monthly_rebalances():
 s,ids,sessions,calls=setup_strategy()
 inst={i:SimpleNamespace(can_short=True) for i in ids}
 keys=sorted(s.routes)
 # Nov29 callback is not monthly; Dec2 is the first monthly route.
 ctx=lambda t,e:SimpleNamespace(ts=t,equity=e,positions={i:1 for i in ids},instruments=inst)
 assert s.on_bar_close(ctx(keys[0],100000))=={}
 w=s.on_bar_close(ctx(keys[1],100000));assert sum(abs(x) for x in w.values())==pytest.approx(1)
 half=s.on_bar_close(ctx(keys[2],89000));assert sum(abs(x) for x in half.values())==pytest.approx(.5)
 flat=s.on_bar_close(ctx(keys[3],84000));assert not any(flat.values()) and len(flat)==40
 assert len(calls)==1


@pytest.mark.parametrize("revoke",[False,True])
def test_actual_engine_fills_first_month_source_open(tmp_path,revoke):
 s,ids,sessions,calls=setup_strategy()
 if revoke:
  s.eligible_provider=lambda t:ids[1:] if t>=pd.Timestamp('2024-12-02T21:00:00Z').to_pydatetime() else ids
 paths=LakePaths(tmp_path/'lake');writer=LakeWriter(paths)
 bars=[]
 for day,op,cl in sessions:
  t=int(pd.Timestamp(day,tz='UTC').timestamp()*1000)
  # Distinct preceding close/current open makes source-date mistakes visible.
  price=100 if day.month==11 else 120
  for iid in ids:bars.append(bar_row(iid,t,open_=price,close=price+5,quote_volume=1e9))
 writer.write(Dataset.OHLCV_1D,ohlcv_table(bars))
 with InstrumentStore(tmp_path/'ops.sqlite') as store:
  for iid in ids:
   store.upsert(replace(make_instrument('BINANCE:PERP:BTCUSDT'),instrument_id=iid,asset_class=AssetClass.EQUITY,market_type=MarketType.CASH,base=iid.split(":")[-1][:-3],quote='USD',funding_interval_hours=None),as_of=1)
  engine=EventDrivenBacktester(PITDataReader(paths),store,TransactionCostModel(),tf=Timeframe.D1,asset_class=AssetClass.EQUITY,cost_inputs=StaticCostInputs(adv_quote=1e9,sigma_daily=.02))
  result=engine.run(s,ids,start=int(pd.Timestamp('2024-11-27',tz='UTC').timestamp()*1000),end=int(pd.Timestamp('2024-12-09',tz='UTC').timestamp()*1000),initial_cash=100000.)
 assert len(calls)==1
 assert calls[0]==pd.Timestamp('2024-11-29T18:00:00Z').to_pydatetime()
 assert len(result.fills)==(41 if revoke else 40)
 first=int(pd.Timestamp('2024-12-02',tz='UTC').timestamp()*1000)
 assert len(result.fills[result.fills.ts==first])==40
 if revoke:
  exit_fill=result.fills[result.fills.ts!=first]
  assert len(exit_fill)==1
  assert exit_fill.iloc[0].instrument_id==ids[0]
  assert exit_fill.iloc[0].ts==int(pd.Timestamp('2024-12-03',tz='UTC').timestamp()*1000)
 else:
  assert set(result.fills.ts)=={first}
 # Costs shift buys up and sells down, but all execute near Dec2's120, not Nov29's100/105.
 assert result.fills.price.between(119,121).all()
