import json
from dataclasses import asdict,replace
from decimal import Decimal
import pytest
from test_alphamax_payment_source_guard_v3 import amended
from test_depositary_engine import terms
from test_payable_engine import IID,ms
from alphamax_depositary_source_guard_v2 import guarded_depositary_factory
from alphamax_payment_source_guard_v3 import sha
from alphaforge.backtest.engine import ScriptedStrategy
from continuous_crypto_runner import ScheduledSignalStrategy


def bound(tmp_path):
    args,kwargs,c,d,bind=amended(tmp_path)
    policy=tmp_path/'fee.txt';policy.write_text('Synthetic fee contract, not historical qualification')
    p=tmp_path/'terms.json';p.write_text(json.dumps({'terms':[asdict(terms())],'sha256':{'fee.txt':sha(policy)}},default=str))
    c.update(terms_file=p,terms_sha256=sha(p),required_fee_event_ids=['div1'])
    return args,kwargs,c,d,bind


def test_effective_date_fee_and_durable_model_swap_together(tmp_path):
    args,kwargs,c,_,_=bound(tmp_path)
    class Persistent(ScriptedStrategy):
        def load_leg(self,frame):pass
    wrapped=ScheduledSignalStrategy(Persistent({ms('2026-01-13'):{IID:.1},ms('2026-01-16'):{IID:0.}}),[
        {'decision_start':ms('2026-01-13'),'frame':None},{'decision_start':ms('2026-01-16'),'frame':None}])
    result=guarded_depositary_factory(tmp_path/'out',**c)(*args,**kwargs).run(wrapped,[IID],start=c['start'],end=c['end'],initial_cash=22500.)
    action,=result.corporate_actions.to_dict('records')
    assert action['action_ts']==ms('2026-01-14')  # corrected, not frozenJan15
    meta=json.loads((tmp_path/'out/000/run_meta.json').read_text())['config']
    rec,=meta['depositary_cash_records']
    assert rec['ts']==ms('2026-01-14') and rec['gross_per_share']=='2'
    assert Decimal(rec['applied_per_share'])==Decimal('1.98')
    assert len(meta['dividend_settlements'])==1
    assert meta['dividend_settlements'][0]['cashflow_quote']==pytest.approx(float(Decimal(rec['net_signed_entitlement'])))
    assert len(meta['model_boundary_transitions'])==1
    assert meta['payment_source_review']['gate_sha256']==sha(c['review_dir']/'gate.json')
    assert (tmp_path/'out/000/SAVE_COMPLETE').exists()


@pytest.mark.parametrize('bad',['old_action','old_payment','date_evidence','fee_after_corrected_ex'])
def test_combined_guard_rejects_bad_inputs_before_output(tmp_path,bad):
    args,kwargs,c,d,bind=bound(tmp_path)
    if bad=='old_action':c['retrospective_actions']=[replace(c['retrospective_actions'][0],ex_date=ms('2026-01-15'))]
    elif bad=='old_payment':c['payments']=[replace(c['payments'][0],ex_ms=ms('2026-01-15'))]
    elif bad=='date_evidence':
        (tmp_path/'issuer.txt').write_text('changed original evidence')
    else:
        p=c['terms_file'];v=json.loads(p.read_text());v['terms'][0]['observed_ms']=ms('2026-01-15');p.write_text(json.dumps(v));c['terms_sha256']=sha(p)
    with pytest.raises(ValueError):guarded_depositary_factory(tmp_path/'out',**c)
    assert not (tmp_path/'out').exists()
