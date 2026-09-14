from types import SimpleNamespace
import numpy as np
import pandas as pd
from alphaforge.core.time import Timeframe
from alphaforge.portfolio.optimizer import PortfolioConstraints
from alphaforge.portfolio.trend_direction_confirmation import DirectionState
from trend_group_risk_allocator import GroupRiskAllocator
from trend_group_risk_strategy import GroupRiskConfirmedStrategy


def iid(x):return f'XUSE:CASH:{x}USD'

def strategy_fixture():
    s=object.__new__(GroupRiskConfirmedStrategy)
    names=[iid(x) for x in ['GLD','SPY','SHY','QQQ']]
    t=np.arange(80.)
    # SHY is constant and must be removed before ordered IDs reach allocator.
    panel=pd.DataFrame({names[0]:100*np.exp(.001*t+.003*np.sin(t)),names[1]:100*np.exp(.0003*t+.005*np.sin(t*.7)),names[2]:np.ones(80)*100,names[3]:100*np.exp(.0008*t+.004*np.sin(t*.4))})
    s._signal_close_panel=lambda ctx,ids:panel.loc[:,ids]
    s._close_panel=lambda ctx,ids:panel.loc[:,ids]
    s._cov_min_periods=10;s._cov_halflife_bars_for=lambda ctx,tf:20
    s._cost_frac=.0006;s._realized_vol_ann=lambda x:0.
    s._vol_target_ann=.1;s._vol_scale_max=1.;s._gross_max=1.;s._w_max=.5
    s._retain_cash=lambda weights,ids,ctx:weights
    s._ladder=SimpleNamespace(gross_multiplier=lambda:1.)
    s._group_allocator=GroupRiskAllocator(PortfolioConstraints(gross_max=1.,w_max=.5))
    s._direction_states={};s.direction_audit=[]
    for x in ['_n_hold_cov_cold_start','_n_hold_degenerate_xsection','_n_realized_leg_bound','_n_rebalances','_n_fallback_used']:setattr(s,x,0)
    ctx=SimpleNamespace(tf=Timeframe.D1,ts=100,equity=100000.,positions={names[2]:10.},instruments={x:SimpleNamespace(can_short=True) for x in names},calendar=SimpleNamespace(periods_per_year=lambda tf:252.))
    return s,ctx,names


def test_final_filtered_order_and_orphan_exit_reach_group_route():
    s,ctx,names=strategy_fixture()
    out=s._rebalance(ctx,{x:1. for x in names})
    expected=tuple(sorted(x for x in names if x!=iid('SHY')))
    assert s._group_allocator.last_diagnostics['ids']==expected
    assert out[iid('SHY')]==0 # carried constant-price instrument must explicitly exit
    assert all(out[x]>0 for x in expected)
    assert sum(abs(x) for x in out.values())<=1+1e-12
    assert max(abs(x) for x in out.values())<=.5+1e-12
    assert s._n_rebalances==1 and len(s.direction_audit)==1


def test_confirmation_survives_actual_group_sizing_route():
    s,ctx,names=strategy_fixture();positive={x:1. for x in names}
    s._rebalance(ctx,positive)
    negative={x:-1. for x in names}
    ctx.ts+=1;first=s._rebalance(ctx,negative)
    ctx.ts+=1;second=s._rebalance(ctx,negative)
    assert first[iid('SPY')]>0 and second[iid('SPY')]<0
    assert s._direction_states[iid('SPY')]==DirectionState(-1)


def test_cold_start_does_not_commit_confirmation_state():
    s,ctx,names=strategy_fixture();s._direction_states={names[0]:DirectionState(1)}
    s._cov_min_periods=200
    assert s._rebalance(ctx,{names[0]:-1.}) is None
    assert s._direction_states=={names[0]:DirectionState(1)}
    assert s.direction_audit==[] and s._n_hold_cov_cold_start==1
