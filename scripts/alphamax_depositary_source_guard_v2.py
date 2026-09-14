"""Source-bound USD depositary runner. Binding is not economic qualification."""
import json
from pathlib import Path
from decimal import Decimal
from alphamax_payment_source_guard_v3 import guarded_payable_factory, sha, validate_source
from alphaforge.backtest.depositary_dividend_ledger import DepositaryCashTerms
from continuous_depositary_runner import continuous_depositary_factory


def guarded_depositary_factory(directory, *, terms_file, terms_sha256,
                               required_fee_event_ids, **source):
    source = dict(source)
    for key in ['payments', 'retrospective_actions', 'instrument_ids']:
        source[key] = tuple(source[key])
    root = Path(source['root'])
    gate_path = Path(source['review_dir'])/'gate.json'
    gate_sha256 = sha(gate_path)
    required = tuple(required_fee_event_ids)
    if len(set(required)) != len(required):
        raise ValueError('Unique independently frozen fee-event coverage required')
    events = {e.event_id:e for e in source['payments']}
    def check():
        if sha(gate_path) != gate_sha256:
            raise ValueError("Changed source review gate")
        # Reuse full three-way source partition and exact gross action/payment
        # checks; this factory builds no engine and creates no output directory.
        guarded_payable_factory(directory, **source)
        path = Path(terms_file)
        if sha(path) != terms_sha256:
            raise ValueError('Changed depositary terms manifest')
        manifest = json.loads(path.read_text())
        links = manifest.get('sha256', {})
        if not isinstance(links, dict) or not links:
            raise ValueError('Retained fee-policy evidence required')
        seen = set()
        def verify(p, h):
            p=p.resolve()
            if sha(p)!=h: raise ValueError('Changed depositary policy evidence')
            if p in seen:return
            seen.add(p)
            if p.suffix=='.json':
                value=json.loads(p.read_text())
                children=value.get('sha256',{}) if isinstance(value,dict) else {}
                if isinstance(children,dict):
                    for name,digest in children.items():verify(root/name,digest)
        for name,h in links.items():verify(root/name,h)
        terms=[]
        for row in manifest['terms']:
            row=dict(row)
            for key in ['long_fee_per_share','long_tax_per_share','short_payment_per_share','short_fee_per_share']:
                row[key]=Decimal(row[key])
            t=DepositaryCashTerms(**row)
            e=events.get(t.event_id)
            values=[t.long_fee_per_share,t.long_tax_per_share,t.short_payment_per_share,t.short_fee_per_share]
            if (e is None or not isinstance(t.policy_id,str) or not t.policy_id.strip()
                    or type(t.observed_ms) is not int or not 0<=t.observed_ms<=e.ex_ms
                    or any(not x.is_finite() or x<0 for x in values)
                    or e.cash_per_share-t.long_fee_per_share-t.long_tax_per_share<=0
                    or t.short_payment_per_share+t.short_fee_per_share<=0):
                raise ValueError('Invalid or late depositary cash terms')
            terms.append(t)
        ids=[t.event_id for t in terms]
        if len(set(ids))!=len(ids) or set(ids)!=set(required):
            raise ValueError('Depositary terms differ from frozen fee-event coverage')
        return tuple(terms)
    terms=check()
    base=continuous_depositary_factory(directory,payments=source['payments'],depositary_terms=terms,
        retrospective_vintage_ms=source['retrospective_vintage_ms'],retrospective_actions=source['retrospective_actions'])
    class GuardedDepositary(base):
        def __init__(self,*args,**kwargs):
            if check()!=terms:raise ValueError('Depositary binding changed')
            super().__init__(*args,**kwargs)
        def run(self,strategy,run_ids,*,start,end,initial_cash=100000.):
            run_ids=tuple(run_ids)
            if (len(run_ids)!=len(source['instrument_ids']) or set(run_ids)!=set(source['instrument_ids'])
                    or start!=source['start'] or end!=source['end']):
                raise ValueError('Run differs from bound source scope')
            if check()!=terms:raise ValueError('Depositary binding changed')
            _,proof=validate_source(source['review_dir'],**{k:source[k] for k in ['root','frozen_audit','frozen_sha256','start','end']})
            self._config_echo.update(payment_source_review=proof,depositary_terms_sha256=terms_sha256,
                required_fee_event_ids=required,depositary_qualification=False)
            return super().run(strategy,run_ids,start=start,end=end,initial_cash=initial_cash)
    return GuardedDepositary
