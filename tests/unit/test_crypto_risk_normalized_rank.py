import numpy as np
import pytest
from types import SimpleNamespace
from crypto_risk_normalized_rank import RiskNormalizedRankAllocator,install_risk_normalized_rank
from alphaforge.portfolio.optimizer import RankEqualVolFallback,PortfolioConstraints
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.risk.monitors import DrawdownLadder


def inputs():
    return [np.array([.8,.7,.6,.1,-.1,-.6,-.7,-.8]),np.diag([100.,1.,1.,1.,1.,1.,1.,100.]),np.zeros(8),np.full(8,.001),np.ones(8)]


def test_rank_changes_but_sizing_and_objective_use_original_inputs():
    x=inputs();a=RiskNormalizedRankAllocator().solve(*x)
    assert set(np.flatnonzero(a.weights>0))=={1,2}
    assert set(np.flatnonzero(a.weights<0))=={5,6}
    b=RankEqualVolFallback().solve(x[0]/np.sqrt(np.diag(x[1])),*x[1:])
    np.testing.assert_array_equal(a.weights,b.weights)
    assert a.objective==float(x[0]@a.weights)
    assert not np.array_equal(a.weights,RankEqualVolFallback().solve(*x).weights)


def test_equal_vol_exact_legacy_parity_and_ties():
    x=inputs();x[1]=np.eye(8)
    for mu in [x[0],np.ones(8)*.1]:
        x[0]=mu
        np.testing.assert_array_equal(RiskNormalizedRankAllocator().solve(*x).weights,RankEqualVolFallback().solve(*x).weights)


def test_caps_forbidden_short_and_no_input_mutation():
    x=inputs();x[4][6]=0;original=[a.copy() for a in x]
    c=PortfolioConstraints(w_max=.1)
    a=RiskNormalizedRankAllocator(c).solve(*x)
    assert a.weights[6]==0 and abs(a.weights).max()<=.1 and abs(a.weights).sum()<=.5+1e-14
    for a,b in zip(x,original):np.testing.assert_array_equal(a,b)


def test_invalid_variance_is_not_silently_scored():
    x=inputs();x[1][0,0]=0
    with pytest.raises(ValueError,match='Positive covariance'):RiskNormalizedRankAllocator().solve(*x)


def test_per_instance_install_and_immediate_risk_exits():
    for equity,expected in [(89.,{'A':.1,'B':-.1}),(84.,{'A':0.,'B':0.}),(100.,{})]:
        ladder=DrawdownLadder();ladder.update(100.)
        s=SimpleNamespace(_allocator=RankEqualVolFallback(),_ladder=ladder,_equity_hist=[],_scale_hist=[],_last_scale=1.,_n_bars_halted_flat=0,_n_bars_half_gross=0,_n_hold_between_rebalance=0,_rebalance_anchor='run',_next_rebalance_ts=1000,_last_targets={'A':.2,'B':-.2})
        other=SimpleNamespace(_allocator=RankEqualVolFallback());constraints=s._allocator.constraints
        install_risk_normalized_rank(s);installed=s._allocator;install_risk_normalized_rank(s)
        assert s._allocator is installed and installed.constraints is constraints and type(other._allocator) is RankEqualVolFallback
        assert BlendStrategy.on_bar_close(s,SimpleNamespace(equity=equity,ts=1,instruments={'A':object(),'B':object()}))==expected
