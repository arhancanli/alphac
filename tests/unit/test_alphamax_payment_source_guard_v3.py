import json
from dataclasses import replace
import pytest
from test_alphamax_payment_source_guard import fixture
from alphamax_payment_source_guard_v3 import guarded_payable_factory, validate_source, sha, date_ms


def amended(tmp_path):
    args,kwargs,c,_=fixture(tmp_path)
    original=json.loads(c['frozen_audit'].read_text())['matches'][0]
    evidence=tmp_path/'issuer.txt';evidence.write_text('Synthetic exact date evidence only')
    d=tmp_path/'date_decision.json';d.write_text(json.dumps({'status':'AMEND_EX_DATE','original_event':original,'corrected_ex_date':'2026-01-14','rationale':'Synthetic correction','sha256':{'issuer.txt':sha(evidence)}}))
    p=c['review_dir']/'reviewed_schedule.json';rows=json.loads(p.read_text());rows[0].update(ex_date='2026-01-14',frozen_ex_date='2026-01-15',date_decision_file='date_decision.json');p.write_text(json.dumps(rows))
    def bind():
        g=c['review_dir']/'gate.json';v=json.loads(g.read_text());v['sha256'].update({str(x.relative_to(tmp_path)):sha(x) for x in [p,d]});g.write_text(json.dumps(v))
    bind()
    c['payments']=[replace(c['payments'][0],ex_ms=date_ms('2026-01-14'))]
    c['retrospective_actions']=[replace(c['retrospective_actions'][0],ex_date=date_ms('2026-01-14'))]
    return args,kwargs,c,d,bind


def test_effective_date_controls_horizon_original_key_preserved(tmp_path):
    _,_,c,_,_=amended(tmp_path)
    rows,_=validate_source(c['review_dir'],**{k:c[k] for k in ['root','frozen_audit','frozen_sha256']},start=date_ms('2026-01-14'),end=date_ms('2026-01-15'))
    assert len(rows)==1 and rows[0]['frozen_ex_date']=='2026-01-15'
    guarded_payable_factory(tmp_path/'out',**c)
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('which',['payment','action','both_dates'])
def test_old_date_or_duplicate_entitlement_rejected(tmp_path,which):
    _,_,c,_,_=amended(tmp_path)
    if which in ['payment','both_dates']:
        old=replace(c['payments'][0],ex_ms=date_ms('2026-01-15'))
        c['payments']=[old] if which=='payment' else c['payments']+[old]
    else:c['retrospective_actions']=[replace(c['retrospective_actions'][0],ex_date=date_ms('2026-01-15'))]
    with pytest.raises(ValueError,match='differ'):guarded_payable_factory(tmp_path/'out',**c)


def test_changed_original_decision_rejected_even_if_rehashed(tmp_path):
    _,_,c,d,bind=amended(tmp_path);v=json.loads(d.read_text());v['original_event']['cash_amount']=3;d.write_text(json.dumps(v));bind()
    with pytest.raises(ValueError,match='original-bound'):guarded_payable_factory(tmp_path/'out',**c)
