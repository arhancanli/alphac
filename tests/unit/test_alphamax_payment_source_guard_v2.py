import json
import pytest
from alphamax_payment_source_guard_v2 import guarded_payable_factory,validate_source,sha
from test_alphamax_payment_source_guard import fixture


def excluded_fixture(tmp_path):
    args,kwargs,c,_=fixture(tmp_path)
    review=c['review_dir'];original=json.loads(c['frozen_audit'].read_text())['matches'][0]
    evidence=tmp_path/'issuer.txt';evidence.write_text('Synthetic issuer evidence for rejection-path testing only')
    decision=tmp_path/'decision.json'
    decision.write_text(json.dumps({'status':'EXCLUDE_INVALID_CASH_EVENT','original_event':original,
        'rationale':'Synthetic invalid duplicate','sha256':{'issuer.txt':sha(evidence)}}))
    (review/'reviewed_schedule.json').write_text('[]')
    (review/'excluded.json').write_text(json.dumps([{'instrument_id':original['instrument_id'],
        'ex_date':original['ex_date'],'original_event':original,'decision_file':'decision.json'}]))
    def bind():
        gate=json.loads((review/'gate.json').read_text());gate.update(reviewed=0,excluded=1)
        gate['sha256'].update({str(p.relative_to(tmp_path)):sha(p) for p in [review/'reviewed_schedule.json',review/'excluded.json',decision]})
        (review/'gate.json').write_text(json.dumps(gate))
    bind()
    return args,kwargs,c,bind,decision,evidence


def test_explicit_exclusion_accepts_empty_inputs_and_reports_count(tmp_path):
    _,_,c,_,_,_=excluded_fixture(tmp_path)
    params={k:c[k] for k in ['root','frozen_audit','frozen_sha256','start','end']}
    rows,proof=validate_source(c['review_dir'],**params)
    assert rows==[] and proof['excluded_events']==1
    c.update(payments=[],retrospective_actions=[])
    guarded_payable_factory(tmp_path/'out',**c)
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('keep',['payment','action'])
def test_excluded_event_cannot_reenter_either_input(tmp_path,keep):
    _,_,c,_,_,_=excluded_fixture(tmp_path)
    if keep=='payment':c['retrospective_actions']=[]
    else:c['payments']=[]
    with pytest.raises(ValueError,match='differ from reviewed source'):
        guarded_payable_factory(tmp_path/'out',**c)
    assert not (tmp_path/'out').exists()


def test_exclusion_must_preserve_full_original_row(tmp_path):
    _,_,c,bind,_,_=excluded_fixture(tmp_path)
    p=c['review_dir']/'excluded.json';rows=json.loads(p.read_text());rows[0]['original_event']['cash_amount']=3
    p.write_text(json.dumps(rows));bind()
    with pytest.raises(ValueError,match='exact original'):guarded_payable_factory(tmp_path/'out',**c)


def test_source_change_rejected_before_engine_construction(tmp_path):
    args,kwargs,c,_,_,source=excluded_fixture(tmp_path)
    c.update(payments=[],retrospective_actions=[])
    factory=guarded_payable_factory(tmp_path/'out',**c);source.write_text('changed')
    with pytest.raises(ValueError,match='Changed evidence'):factory(*args,**kwargs)
    assert not (tmp_path/'out').exists()


def test_exclusion_cannot_overlap_unresolved_partition(tmp_path):
    _,_,c,bind,_,_=excluded_fixture(tmp_path)
    p=c['review_dir']/'unresolved.json';p.write_text(json.dumps(json.loads(c['frozen_audit'].read_text())['matches']))
    bind();g=c['review_dir']/'gate.json';v=json.loads(g.read_text());v['unresolved']=1;v['sha256'][str(p.relative_to(tmp_path))]=sha(p);g.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='partition'):guarded_payable_factory(tmp_path/'out',**c)
