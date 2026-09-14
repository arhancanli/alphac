import numpy as np
import pandas as pd
import pytest
from continuous_equity_schedule import equity_schedule
from continuous_crypto_runner import ScheduledSignalStrategy
from test_payable_engine import setup,ms,IID
from alphaforge.backtest.payable_engine import PayableEquityBacktester
from alphaforge.backtest.engine import ScriptedStrategy

class Splitter:
 def __init__(self,legs):self.legs=legs
 def split(self,grid):
  for leg in self.legs:yield np.array([],dtype=np.int64),np.array([ms(x) for x in leg])

def schedule(legs):
 return equity_schedule(Splitter(legs),[],pd.DataFrame({'x':[]}),np.array([],dtype=np.int64),252)

def test_friday_decision_hops_holiday_weekend():
 s=schedule([['2026-01-14','2026-01-15'],['2026-01-16','2026-01-20']])
 assert s[1]['decision_start']==ms('2026-01-20')
 assert s[1]['test_start']==ms('2026-01-16')

def test_missing_session_and_interleg_gap_rejected():
 for legs in [[['2026-01-14','2026-01-16']],[['2026-01-12','2026-01-13'],['2026-01-15','2026-01-16']]]:
  with pytest.raises(ValueError):schedule(legs)

def test_actual_payable_engine_preserves_pending_exit_and_weekend_dividend(tmp_path):
 args,kwargs,payments,start,end=setup(tmp_path,financing=True)
 script={ms('2026-01-13'):{IID:.1},ms('2026-01-16'):{IID:0.}}
 class Persistent(ScriptedStrategy):
  def __init__(self):super().__init__(script);self.loads=[]
  def load_leg(self,frame):self.loads.append(frame)
 strategy=Persistent()
 wrapped=ScheduledSignalStrategy(strategy,[{'decision_start':ms('2026-01-13'),'frame':'first'},{'decision_start':ms('2026-01-16'),'frame':'next'}])
 actual=PayableEquityBacktester(*args,payments=payments,**kwargs).run(wrapped,[IID],start=start,end=end,initial_cash=22500.)
 expected=PayableEquityBacktester(*args,payments=payments,**kwargs).run(ScriptedStrategy(script),[IID],start=start,end=end,initial_cash=22500.)
 pd.testing.assert_frame_equal(actual.fills,expected.fills,check_exact=True)
 pd.testing.assert_series_equal(actual.equity,expected.equity,check_exact=True)
 assert actual.config['dividend_settlements']==expected.config['dividend_settlements']
 assert len(actual.config['dividend_settlements'])==1
 assert wrapped.transitions[0]['positions_before_model_swap'][IID]>0
 assert strategy.loads==['next']
 assert actual.fills.side.tolist()==['buy','sell']

def test_durable_factory_saves_transition_evidence_with_equity(tmp_path):
 import json
 from continuous_equity_runner import continuous_payable_factory
 args,kwargs,payments,start,end=setup(tmp_path)
 class Persistent(ScriptedStrategy):
  def load_leg(self,frame):pass
 wrapped=ScheduledSignalStrategy(Persistent({ms('2026-01-13'):{IID:.1}}),[
  {'decision_start':ms('2026-01-13'),'frame':None},{'decision_start':ms('2026-01-16'),'frame':None}])
 factory=continuous_payable_factory(tmp_path/'durable',payments=payments,retrospective_vintage_ms=None,retrospective_actions=None)
 result=factory(*args,**kwargs).run(wrapped,[IID],start=start,end=end,initial_cash=22500.)
 meta=json.loads((tmp_path/'durable/000/run_meta.json').read_text())
 assert meta['config']['model_boundary_transitions']==result.config['model_boundary_transitions']
 assert len(meta['config']['model_boundary_transitions'])==1
 assert (tmp_path/'durable/000/SAVE_COMPLETE').exists()
 with pytest.raises(FileExistsError):factory(*args,**kwargs)
