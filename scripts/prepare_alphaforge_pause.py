"""Prepare a prospective schedule proposal; does not activate or publish it."""
from datetime import date
import hashlib
import json
from pathlib import Path

from paper_trading_state import WEIGHT_SCHEDULE, combined_live


def proposal(curves, effective_date, allocation):
    if allocation not in ('cash','redistribute'):
        raise ValueError('Choose cash or redistribute')
    date.fromisoformat(effective_date)
    last=max(p['date'] for curve in curves.values() for p in curve)
    if effective_date<=last or effective_date<=WEIGHT_SCHEDULE[-1][0]:
        raise ValueError('Cutover must follow every existing mark and schedule entry')
    weights=({'crypto':0.,'equity':.25,'mf':.25,'vintage':.25,'cash':.25}
             if allocation=='cash' else {'crypto':0.,'equity':1/3,'mf':1/3,'vintage':1/3})
    schedule=[*WEIGHT_SCHEDULE,(effective_date,weights)]
    old=combined_live(curves,schedule=WEIGHT_SCHEDULE)
    new=combined_live(curves,schedule=schedule)
    if old!=new:
        raise ValueError('Historical curve changed')
    return dict(state='PREPARED_NOT_ACTIVE',effective_date=effective_date,
        allocation=allocation,weights=weights,schedule=schedule,
        historical_marks_unchanged=True,history_sha256=hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest(),
        overlay='Existing separately disclosed strategic overlay remains unchanged; crypto removal is not a zero-crypto-exposure mandate.',
        cash_return_assumption='Zero; no invented interest' if allocation=='cash' else None,
        runtime_orders_authorized=False,standalone_alphaforge_history_retained=True)


if __name__=='__main__':
    source=Path('/Users/arhancanli/alphac-sleeve-review-20260911/published-curves.json')
    raw=json.loads(source.read_text())
    curves={k:raw[v] for k,v in [('crypto','AlphaForge'),('equity','AlphaMax'),('mf','AlphaTrend'),('vintage','AlphaVintage')]}
    output=Path(__file__).resolve().parents[1]/'evidence/pause-options.json'
    with output.open('x') as f:
        json.dump({option:proposal(curves,'2026-09-12',option) for option in ('cash','redistribute')},f,indent=2);f.write('\n')
    print('Prepared both next-day allocation options; existing history unchanged.')
