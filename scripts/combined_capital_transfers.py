"""Accounting diagnostic for implicit fixed-weight subbook capital transfers.

Transfers are changes in subbook NAV allocations, not measured security trading
notional, cash withdrawals or executable orders. No transaction cost is inferred.
"""
from decimal import Decimal
D=Decimal
WEIGHTS={'max':D('.225'),'trend':D('.225'),'crypto':D('.225'),'bil':D('.325')}


def implied_transfers(returns, previous_nav):
    if set(returns)!=set(WEIGHTS):raise ValueError('Exact four subbooks required')
    previous_nav=D(str(previous_nav));r={k:D(str(v)) for k,v in returns.items()}
    if not previous_nav.is_finite() or previous_nav<=0:raise ValueError('Positive finite NAV required')
    if any(not x.is_finite() or x<=-1 for x in r.values()):raise ValueError('Invalid subbook return')
    total=sum(WEIGHTS[k]*r[k] for k in WEIGHTS)
    next_nav=previous_nav*(1+total)
    before={k:previous_nav*WEIGHTS[k]*(1+r[k]) for k in WEIGHTS}
    after={k:next_nav*WEIGHTS[k] for k in WEIGHTS}
    transfers={k:after[k]-before[k] for k in WEIGHTS}
    assert abs(sum(before.values())-next_nav)<D('1e-18')
    assert abs(sum(transfers.values()))<D('1e-18')
    return {'next_nav':next_nav,'return':total,'before':before,'after':after,'transfers':transfers,
            'one_way_redistribution':sum(abs(v) for v in transfers.values())/2}
