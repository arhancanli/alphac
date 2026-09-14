"""Fixed aggregate earnings-change research candidate; no historical I/O.

Scores are accounting ratios, not annualized expected returns. Do not feed them
through the mu_ann contract. Targets require engine risk/execution integration.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from math import isfinite
from typing import Iterable, Mapping
from earnings_filing_inputs import Filing, seasonal_pair


def score_at(filings: Iterable[Filing], security_id: str, decision: datetime,
             *, usd_metadata: bool, fx_by_filing: Mapping[Filing, Decimal]):
    pair=seasonal_pair(filings,security_id,decision)
    if pair is None or not usd_metadata:
        return None
    current,prior=pair
    if decision-current.available_at > timedelta(days=180):
        return None
    if any(fx_by_filing.get(f)!=Decimal(1) for f in pair):
        return None
    value=(current.common_income-prior.common_income)/prior.assets
    result=float(value)
    return result if isfinite(result) else None


def target_weights(scores: Mapping[str,float], *, stable_ids: Mapping[str,str],
                   shortable: Mapping[str,bool], held_ids: Iterable[str]=()):
    """40-name target or flat on insufficient eligibility; explicit exits included.

    Longs are best20 finite scores; shorts worst20 shortable names excluding longs.
    All ties use stable security ID ascending on both sides. No score-unit guard
    from the separate expected-return allocator is weakened or bypassed.
    """
    if any(i not in stable_ids or not stable_ids[i] for i in scores):
        raise ValueError('Missing stable security ID')
    if len({stable_ids[i] for i in scores})!=len(scores):
        raise ValueError('Multiple instruments for same stable security')
    clean={i:float(s) for i,s in scores.items() if isfinite(float(s))}
    targets={i:0.0 for i in set(held_ids)|set(scores)}
    if len(clean)<40:
        return targets
    longs=sorted(clean,key=lambda i:(-clean[i],stable_ids[i]))[:20]
    shorts=sorted((i for i in clean if i not in longs and shortable.get(i,False)),
                  key=lambda i:(clean[i],stable_ids[i]))[:20]
    if len(shorts)<20:
        return targets
    targets.update({i:0.025 for i in longs})
    targets.update({i:-0.025 for i in shorts})
    return targets


def month_routes(schedule):
    """Map preceding-session physical close to first-month physical open.

    schedule is a complete, ordered sequence of (session date, UTC-aware open,
    UTC-aware close), including a preceding-month session. No engine-label
    conversion is inferred here; caller must prove that mapping separately.
    """
    rows=list(schedule)
    for i,(day,op,cl) in enumerate(rows):
        if any(t.tzinfo is None or t.utcoffset() is None for t in (op,cl)) or op>=cl:
            raise ValueError('Invalid session timestamps')
        if i and (rows[i-1][0]>=day or rows[i-1][2]>=op):
            raise ValueError('Unordered/overlapping schedule')
    routes={}
    for previous,current in zip(rows,rows[1:]):
        if (previous[0].year,previous[0].month)!=(current[0].year,current[0].month):
            routes[previous[2]]=current[1]
    return routes
