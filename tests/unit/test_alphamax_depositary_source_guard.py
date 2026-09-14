import json
from dataclasses import asdict
import pytest
from test_alphamax_payment_source_guard import fixture
from test_depositary_engine import terms
from test_payable_engine import IID,ms
from alphamax_depositary_source_guard import guarded_depositary_factory
from alphamax_payment_source_guard_v2 import sha
from alphaforge.backtest.engine import ScriptedStrategy
from continuous_crypto_runner import ScheduledSignalStrategy


def bound(tmp_path):
    args,kwargs,c,_=fixture(tmp_path)
    policy=tmp_path/'policy.txt';policy.write_text('Synthetic independent short contract; not historical evidence')
    p=tmp_path/'terms.json';p.write_text(json.dumps({'terms':[asdict(terms())],'sha256':{'policy.txt':sha(policy)}},default=str))
    c.update(terms_file=p,terms_sha256=sha(p),required_fee_event_ids=['div1'])
    return args,kwargs,c,policy


def test_guarded_model_transition_persists_fee_and_source_evidence(tmp_path):
    args,kwargs,c,_=bound(tmp_path)
    class Persistent(ScriptedStrategy):
        def load_leg(self,frame):pass
    strategy=ScheduledSignalStrategy(Persistent({ms('2026-01-13'):{IID:.1},ms('2026-01-16'):{IID:0.}}),[
        {'decision_start':ms('2026-01-13'),'frame':None},{'decision_start':ms('2026-01-16'),'frame':None}])
    factory=guarded_depositary_factory(tmp_path/'out',**c)
    result=factory(*args,**kwargs).run(strategy,[IID],start=c['start'],end=c['end'],initial_cash=22500.)
    saved=json.loads((tmp_path/'out/000/run_meta.json').read_text())['config']
    assert saved['depositary_terms_sha256']==c['terms_sha256']
    assert saved['payment_source_review']['reviewed_events']==1
    assert saved['model_boundary_transitions']==result.config['model_boundary_transitions']
    assert len(saved['model_boundary_transitions'])==1
    assert saved['model_boundary_transitions'][0]['positions_before_model_swap'][IID]>0
    assert saved['depositary_cash_records'][0]['applied_per_share']=='1.98'
    assert len(saved['dividend_settlements'])==1
    assert (tmp_path/'out/000/SAVE_COMPLETE').exists()


@pytest.mark.parametrize('target',['policy','manifest','coverage','source_gate'])
def test_binding_changes_or_omitted_coverage_reject_before_output(tmp_path,target):
    args,kwargs,c,policy=bound(tmp_path)
    if target=='coverage':
        c['required_fee_event_ids']=[]
        with pytest.raises(ValueError,match='coverage'):guarded_depositary_factory(tmp_path/'out',**c)
    else:
        factory=guarded_depositary_factory(tmp_path/'out',**c)
        target_path = policy if target=='policy' else c['review_dir']/'gate.json' if target=='source_gate' else c['terms_file']
        target_path.write_text('changed')
        with pytest.raises(ValueError,match='Changed'):factory(*args,**kwargs)
    assert not (tmp_path/'out').exists()


def test_policy_change_after_construction_rejects_before_run(tmp_path):
    args,kwargs,c,policy=bound(tmp_path)
    engine=guarded_depositary_factory(tmp_path/'out',**c)(*args,**kwargs)
    policy.write_text('changed')
    with pytest.raises(ValueError,match='Changed'):engine.run(None,[IID],start=c['start'],end=c['end'])
    assert not (tmp_path/'out/000/SAVE_COMPLETE').exists()
