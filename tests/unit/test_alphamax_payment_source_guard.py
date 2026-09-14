import json
from dataclasses import replace
from decimal import Decimal
import pytest
from alphamax_payment_source_guard import validate_source,guarded_payable_factory,sha
from test_payable_engine import setup,ms,IID
from alphaforge.execution.corporate_actions import CorporateAction,CorporateActionType
from alphaforge.backtest.engine import ScriptedStrategy
from continuous_crypto_runner import ScheduledSignalStrategy


def fixture(tmp_path):
 args,kwargs,payments,start,end=setup(tmp_path)
 row={'instrument_id':IID,'symbol':'TEST','ex_date':'2026-01-15','cash_amount':2.}
 frozen=tmp_path/'frozen.json';frozen.write_text(json.dumps({'matches':[row]}))
 review=tmp_path/'review';review.mkdir()
 accepted={k:v for k,v in row.items() if k!='cash_amount'}
 accepted.update(amount='2',pay_date='2026-01-17',amount_changed=False)
 (review/'reviewed_schedule.json').write_text(json.dumps([accepted]));(review/'unresolved.json').write_text('[]')
 def bind():
  a=json.loads((review/'reviewed_schedule.json').read_text());u=json.loads((review/'unresolved.json').read_text())
  (review/'gate.json').write_text(json.dumps({'total':1,'reviewed':len(a),'unresolved':len(u),'sha256':{str(p.relative_to(tmp_path)):sha(p) for p in [frozen,review/'reviewed_schedule.json',review/'unresolved.json']}}))
 bind()
 actions=[CorporateAction(instrument_id=IID,action_type=CorporateActionType.CASH_DIVIDEND,ex_date=ms('2026-01-15'),available_at=start,ratio=1.,cash_amount=2.)]
 config=dict(review_dir=review,root=tmp_path,frozen_audit=frozen,frozen_sha256=sha(frozen),start=start,end=end,instrument_ids=[IID],payments=payments,retrospective_vintage_ms=end,retrospective_actions=actions)
 return args,kwargs,config,bind


def test_real_engine_saves_source_evidence(tmp_path):
 args,kwargs,c,_=fixture(tmp_path)
 class Persistent(ScriptedStrategy):
  def load_leg(self,frame):pass
 strategy=ScheduledSignalStrategy(Persistent({ms('2026-01-13'):{IID:.1}}),[{'decision_start':ms('2026-01-13'),'frame':None}])
 factory=guarded_payable_factory(tmp_path/'out',**c)
 result=factory(*args,**kwargs).run(strategy,[IID],start=c['start'],end=c['end'],initial_cash=22500.)
 saved=json.loads((tmp_path/'out/000/run_meta.json').read_text())
 assert saved['config']['payment_source_review']['reviewed_events']==1
 assert result.config['dividend_settlements']


def test_omission_from_both_review_and_payment_rejected(tmp_path):
 _,_,c,bind=fixture(tmp_path)
 (c['review_dir']/'reviewed_schedule.json').write_text('[]');bind()
 c.update(payments=[],retrospective_actions=[])
 with pytest.raises(ValueError,match='partition'):guarded_payable_factory(tmp_path/'out',**c)
 assert not (tmp_path/'out').exists()


def test_unresolved_event_blocks_even_without_position(tmp_path):
 _,_,c,bind=fixture(tmp_path)
 rows=json.loads(c['frozen_audit'].read_text())['matches']
 (c['review_dir']/'reviewed_schedule.json').write_text('[]');(c['review_dir']/'unresolved.json').write_text(json.dumps(rows));bind()
 with pytest.raises(ValueError,match='Unresolved'):guarded_payable_factory(tmp_path/'out',**c)
 assert not (tmp_path/'out').exists()


def test_changed_pay_date_rejected(tmp_path):
 _,_,c,_=fixture(tmp_path)
 c['payments']=[replace(c['payments'][0],pay_ms=ms('2026-01-20'))]
 with pytest.raises(ValueError,match='Payments differ'):guarded_payable_factory(tmp_path/'out',**c)


def test_source_mutation_after_binding_rejected_before_engine(tmp_path):
 args,kwargs,c,_=fixture(tmp_path);factory=guarded_payable_factory(tmp_path/'out',**c)
 with (c['review_dir']/'reviewed_schedule.json').open('a') as f:f.write(' ')
 with pytest.raises(ValueError,match='binding'):factory(*args,**kwargs)
 assert not (tmp_path/'out').exists()
