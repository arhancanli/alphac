"""Synthetic full run with real allocator, covariance reader and payable engine."""
import dataclasses
import numpy as np
import pandas as pd
import pyarrow as pa
from alphaforge.config.settings import load_settings
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass,MarketType
from alphaforge.core.instruments import InstrumentStore
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.backtest.engine import StaticCostInputs
from continuous_equity_runner import ContinuousEquityRunner,continuous_payable_factory
from test_backtest_engine import bar_row,ohlcv_table,make_instrument
from test_payable_engine import ms

def test_full_runner_uses_one_account_and_observes_every_model_switch(tmp_path):
 start,end=ms('2022-01-03'),ms('2025-06-03');cal=XNYSCalendar();grid=cal.expected_bar_opens(start,end,Timeframe.D1)
 ids=['XUSE:CASH:AAAUSD','XUSE:CASH:BBBUSD','XUSE:CASH:CCCUSD','XUSE:CASH:DDDUSD']
 paths=LakePaths(tmp_path/'lake');writer=LakeWriter(paths);rows=[]
 for k,iid in enumerate(ids):
  rng=np.random.default_rng(100+k);prices=100*np.exp(np.cumsum(rng.normal(.0001,.008,len(grid))))
  rows += [bar_row(iid,t,open_=float(v),close=float(v),quote_volume=1e8) for t,v in zip(grid,prices)]
 writer.write(Dataset.OHLCV_1D,ohlcv_table(rows))
 universe=UniverseStore(paths)
 universe.write_intervals(pa.table({'instrument_id':pa.array(ids),'effective_from':pa.array([start]*4,type=pa.timestamp('ms',tz='UTC')),'effective_to':pa.array([None]*4,type=pa.timestamp('ms',tz='UTC')),'rank':pa.array([1,2,3,4],type=pa.int32()),'reason':pa.array(['synthetic']*4)}))
 store=InstrumentStore(tmp_path/'ops.sqlite')
 for k,iid in enumerate(ids):
  store.upsert(dataclasses.replace(make_instrument('BINANCE:PERP:BTCUSDT'),instrument_id=iid,base=['AAA','BBB','CCC','DDD'][k],quote='USD',asset_class=AssetClass.EQUITY,market_type=MarketType.CASH,funding_interval_hours=None),as_of=1)
 class Signals:
  def compute_research(self,start,end):
   return pd.DataFrame([{'ts_open':t,'instrument_id':iid,'alpha_blend':k-1.5,'mu_ann':.04*(k-1.5)} for t in grid for k,iid in enumerate(ids)]).set_index(['ts_open','instrument_id']).sort_index()
 settings=load_settings('equity')
 factory=continuous_payable_factory(tmp_path/'durable',payments=[],retrospective_vintage_ms=None,retrospective_actions=None)
 runner=ContinuousEquityRunner(PITDataReader(paths),store,universe,TransactionCostModel.from_settings(settings),Signals(),settings,cost_inputs=StaticCostInputs(adv_quote=1e8,sigma_daily=.02),engine_factory=factory,engine_research_config={"synthetic_continuous_payable":True})
 result=runner.run(start,end,train_bars=252,test_bars=63,embargo_bars=274,initial_cash=22500.,instrument_ids=ids,rebalance_bars=10,cov_window_bars=120,cov_min_periods=30)
 assert len(result.legs)==1
 account=result.legs[0].result;meta=account.config
 assert len(meta['model_boundary_transitions'])==len(meta['model_schedule'])-1>2
 assert len(account.fills)>0
 assert any(x['positions_before_model_swap'] for x in meta['model_boundary_transitions'])
 assert all(x['scheduled_decision_start']==x['actual_decision_ts'] for x in meta['model_boundary_transitions'])
 assert len(list((tmp_path/'durable').iterdir()))==1
 store.close()
