"""Validate retained model boundaries under cash inception, without signals/returns."""
import json,hashlib
from pathlib import Path
import pandas as pd,numpy as np
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from continuous_equity_schedule import equity_schedule
R=Path(__file__).resolve().parents[1];O=R/'evidence/alphamax-continuous-runner-20260913'
p=R/'artifacts/analysis/alphamax_session_cooldown_20260913/candidate/run/walkforward.json';prior=json.loads(p.read_text())['legs'];cal=XNYSCalendar()
class Retained:
 def split(self,grid):
  for x in prior:yield [],np.array(cal.expected_bar_opens(x['test_start'],x['test_end'],Timeframe.D1))
s=equity_schedule(Retained(),[],pd.DataFrame({'empty':[]}),np.array([],dtype=np.int64),252)
allbars=[t for x in s for t in cal.expected_bar_opens(x['test_start'],x['test_end'],Timeframe.D1)]
expected=cal.expected_bar_opens(1672531200000,1780358400000,Timeframe.D1)
assert allbars==expected and len(allbars)==855 and len(s)==14
assert [x['test_start'] for x in s[1:]]==[x['test_start'] for x in prior[1:]]
report={'status':'RETAINED_MODEL_GRID_FUNDED_INCEPTION_VALID','source_sessions':len(allbars),'model_intervals':len(s),'model_switches':len(s)-1,'first_source_session':allbars[0],'first_decision':s[0]['decision_start'],'later_model_boundaries_unchanged':True,'signal_frames_computed':False,'returns_computed':False,'notes':'Retains existing252calendar-day warmup formula applied to clipped first test start; no claim of252XNYS training observations. Fourteen signal intervals feed one account, not fourteen flat-reset ledgers.','schedules':[{k:v for k,v in x.items() if k!='frame'} for x in s],'sha256':{str(x.relative_to(R)):hashlib.sha256(x.read_bytes()).hexdigest() for x in [p,Path(__file__),R/'scripts/continuous_equity_schedule.py']}}
with (O/'frozen_grid_audit.json').open('x') as f:json.dump(report,f,indent=2)
print({k:v for k,v in report.items() if k not in ['schedules','sha256']})
