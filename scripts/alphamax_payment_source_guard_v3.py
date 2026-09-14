"""Validate a bound reviewed schedule before constructing a funded account.

This does not certify PIT data or qualify a strategy. The original frozen audit
must be pinned by the experiment, independently of the evolving review gate.
Version 3 adds explicit original-key-preserving ex-date amendments.
"""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def date_ms(value):
    return int(datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()*1000)


def validate_source(review_dir, *, root, frozen_audit, frozen_sha256, start, end):
    root=Path(root); review_dir=Path(review_dir); frozen_audit=Path(frozen_audit)
    if start >= end:
        raise ValueError('Invalid source horizon')
    if sha(frozen_audit) != frozen_sha256:
        raise ValueError('Frozen audit binding changed')
    gate=json.loads((review_dir/'gate.json').read_text())
    bindings=gate.get('sha256', {})
    excluded_path=review_dir/'excluded.json'
    required_files=[review_dir/'reviewed_schedule.json', review_dir/'unresolved.json', frozen_audit]
    if excluded_path.exists():required_files.append(excluded_path)
    elif gate.get('excluded',0):raise ValueError('Missing exclusion partition')
    for required in required_files:
        name=str(required.resolve().relative_to(root.resolve()))
        if bindings.get(name) != sha(required):
            raise ValueError('Missing or changed schedule binding: '+name)
    # Recursively verify upstream adjudication/source bindings, not just the gate.
    seen=set()
    def verify(path, expected):
        path=path.resolve()
        if sha(path)!=expected:raise ValueError('Changed evidence: '+str(path))
        if path in seen:return
        seen.add(path)
        if path.suffix=='.json':
            value=json.loads(path.read_text())
            links=value.get('sha256',{}) if isinstance(value,dict) else {}
            # Capture receipts also use sha256 as a scalar payload digest.
            if not isinstance(links,dict):return
            for name,h in links.items():
                child=Path(name);verify(child if child.is_absolute() else root/child,h)
    for name,h in bindings.items():
        p=Path(name);verify(p if p.is_absolute() else root/p,h)
    original=json.loads(frozen_audit.read_text())['matches']
    reviewed=json.loads((review_dir/'reviewed_schedule.json').read_text())
    unresolved=json.loads((review_dir/'unresolved.json').read_text())
    excluded=json.loads(excluded_path.read_text()) if excluded_path.exists() else []
    key=lambda x:(x['instrument_id'],x['ex_date'])
    def index(rows, key_fn=key):
        result={key_fn(x):x for x in rows}
        if len(result)!=len(rows):raise ValueError('Duplicate source event')
        return result
    baseline=index(original);pending=index(unresolved);removed=index(excluded)
    original_key=lambda x:(x['instrument_id'],x.get('frozen_ex_date',x['ex_date']))
    accepted=index(reviewed,original_key)
    index(reviewed)  # corrected entitlement keys must also be unique
    for k,x in accepted.items():
        if k not in baseline:raise ValueError('Date correction references unknown original')
        if key(x)==k:
            if 'frozen_ex_date' in x:raise ValueError('Redundant date correction')
            continue
        if key(x) in baseline:raise ValueError('Corrected date collides with another frozen event')
        name=x.get('date_decision_file')
        if not isinstance(name,str) or name not in bindings:
            raise ValueError('Date decision missing direct binding')
        p=Path(name);decision=json.loads((p if p.is_absolute() else root/p).read_text())
        if (decision.get('status')!='AMEND_EX_DATE' or decision.get('original_event')!=baseline[k]
                or decision.get('corrected_ex_date')!=x['ex_date']
                or not isinstance(decision.get('rationale'),str) or not decision['rationale'].strip()
                or not isinstance(decision.get('sha256'),dict) or not decision['sha256']):
            raise ValueError('Invalid original-bound date correction')
        date_ms(x['frozen_ex_date']);date_ms(x['ex_date'])
    if (set(accepted)&set(pending) or set(accepted)&set(removed) or set(pending)&set(removed)
            or set(accepted)|set(pending)|set(removed)!=set(baseline)):
        raise ValueError('Source partition drops or adds frozen events')
    if gate['total']!=len(baseline) or gate['reviewed']!=len(accepted) or gate['unresolved']!=len(pending) or gate.get('excluded',0)!=len(removed):
        raise ValueError('Inconsistent gate counts')
    for k,x in removed.items():
        if x.get('original_event')!=baseline[k]:
            raise ValueError('Exclusion differs from exact original event')
        name=x.get('decision_file')
        if not isinstance(name,str) or name not in bindings:
            raise ValueError('Exclusion decision missing direct binding')
        decision_path=Path(name);decision_path=decision_path if decision_path.is_absolute() else root/decision_path
        decision=json.loads(decision_path.read_text())
        if (decision.get('status')!='EXCLUDE_INVALID_CASH_EVENT'
                or decision.get('original_event')!=baseline[k]
                or not isinstance(decision.get('rationale'),str) or not decision['rationale'].strip()):
            raise ValueError('Invalid exclusion decision')
        sources=decision.get('sha256',{})
        if not isinstance(sources,dict) or not sources:
            raise ValueError('Exclusion requires retained evidence bindings')
    for k,x in accepted.items():
        value=Decimal(x['amount']); original_value=Decimal(str(baseline[k]['cash_amount']))
        if not value.is_finite() or value<=0 or date_ms(x['pay_date'])<date_ms(x['ex_date']):
            raise ValueError('Invalid reviewed cash terms')
        changed=value!=original_value
        if x['amount_changed'] is not changed:
            raise ValueError('Incorrect amendment flag')
        if changed and Decimal(str(x['frozen_amount']))!=original_value:
            raise ValueError('Correction does not preserve frozen amount')
    scoped=lambda x:start<=date_ms(x['ex_date'])<end
    missing=[x for x in unresolved if scoped(x)]
    if missing:raise ValueError(f'Unresolved dividend source events in requested horizon: {len(missing)}')
    rows=[x for x in reviewed if scoped(x)]
    return rows, {'gate_sha256':sha(review_dir/'gate.json'),'frozen_audit_sha256':frozen_sha256,
                  'start':start,'end':end,'reviewed_events':len(rows),'excluded_events':sum(scoped(x) for x in excluded),'point_in_time_proven':False}


def guarded_payable_factory(directory, *, review_dir, root, frozen_audit,
                            frozen_sha256, instrument_ids, start, end,
                            payments, retrospective_vintage_ms, retrospective_actions):
    """Reject incomplete/mismatched inputs before output directory or engine exists."""
    from continuous_equity_runner import continuous_payable_factory
    from alphaforge.execution.corporate_actions import CorporateActionType
    payments=tuple(payments);actions=tuple(retrospective_actions)
    ids=tuple(instrument_ids)
    if not ids or len(set(ids))!=len(ids):raise ValueError('Unique frozen universe required')
    def check():
        rows,evidence=validate_source(review_dir,root=root,frozen_audit=frozen_audit,
            frozen_sha256=frozen_sha256,start=start,end=end)
        expected={(x['instrument_id'],date_ms(x['ex_date'])):(Decimal(x['amount']),date_ms(x['pay_date'])) for x in rows}
        if any(iid not in ids for iid,_ in expected):raise ValueError('Frozen dividend names omitted from universe')
        actual={(e.symbol,e.ex_ms):(e.cash_per_share,e.pay_ms) for e in payments}
        if len(actual)!=len(payments) or actual!=expected:raise ValueError('Payments differ from reviewed source')
        dividends=[a for a in actions if a.action_type is CorporateActionType.CASH_DIVIDEND]
        amounts={(a.instrument_id,a.ex_date):Decimal(str(a.cash_amount)) for a in dividends}
        if len(amounts)!=len(dividends) or amounts!={k:v[0] for k,v in expected.items()}:
            raise ValueError('Actions differ from reviewed source')
        return evidence
    evidence=check()
    base=continuous_payable_factory(directory,payments=payments,
        retrospective_vintage_ms=retrospective_vintage_ms,retrospective_actions=actions)
    class GuardedPayable(base):
        def __init__(self,*args,**kwargs):
            if check()!=evidence:raise ValueError('Review changed since factory binding')
            super().__init__(*args,**kwargs)
        def run(self,strategy,run_ids,*,start:int,end:int,initial_cash=100000.):
            if set(run_ids)!=set(ids) or start!=evidence['start'] or end!=evidence['end']:
                raise ValueError('Run differs from bound source scope')
            if check()!=evidence:raise ValueError('Review changed before replay')
            self._config_echo['payment_source_review']=evidence
            return super().run(strategy,run_ids,start=start,end=end,initial_cash=initial_cash)
    return GuardedPayable
