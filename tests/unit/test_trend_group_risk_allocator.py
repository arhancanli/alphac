import numpy as np
import pytest
from alphaforge.portfolio.optimizer import PortfolioConstraints, TrendVolTarget
from trend_group_risk_allocator import GroupRiskAllocator

def iid(x): return f'XUSE:CASH:{x}USD'
def solve(symbols, cov, mu=None, short=None, cap=1.):
    n=len(symbols);obj=GroupRiskAllocator(PortfolioConstraints(gross_max=1.,w_max=cap))
    result=obj.solve_for_ids([iid(x) for x in symbols],np.ones(n) if mu is None else np.array(mu),np.array(cov),np.zeros(n),np.zeros(n),np.ones(n) if short is None else np.array(short))
    return result,obj.last_diagnostics

def test_equal_group_risk_with_unequal_asset_counts():
    r,d=solve(['SPY','QQQ','SHY'],np.eye(3))
    assert r.weights[2] == pytest.approx(np.sqrt(2)*r.weights[0])
    assert d['group_vol_before_limits']['equity']==pytest.approx(1)
    assert d['group_vol_before_limits']['rates']==pytest.approx(1)
    assert d['group_vol_after_limits']['equity']==pytest.approx(d['group_vol_after_limits']['rates'])

def test_within_group_correlation_changes_sizing():
    a,_=solve(['SPY','QQQ','SHY'],np.eye(3))
    b,_=solve(['SPY','QQQ','SHY'],[[1,.8,0],[.8,1,0],[0,0,1]])
    assert b.weights[2]>a.weights[2]

def test_cross_group_correlation_only_changes_total_risk():
    a,_=solve(['SPY','SHY'],np.eye(2))
    b,_=solve(['SPY','SHY'],[[1,.8],[.8,1]])
    np.testing.assert_allclose(a.weights,b.weights)
    assert b.ex_ante_vol_ann>a.ex_ante_vol_ann

def test_permutation_and_covariance_scale_invariance():
    ids=['SPY','QQQ','SHY','GLD'];cov=np.diag([1,2,3,4]);mu=[1,-1,1,-1]
    a,_=solve(ids,cov,mu)
    order=[3,1,0,2]
    b,_=solve([ids[i] for i in order],cov[np.ix_(order,order)]*17,[mu[i] for i in order])
    np.testing.assert_allclose(b.weights,a.weights[order])

def test_shortability_zero_and_absent_groups():
    r,d=solve(['SPY','QQQ','SHY'],np.eye(3),[-1,0,1],[0,1,1])
    np.testing.assert_array_equal(r.weights,[0,0,1])
    assert d['group_vol_before_limits']['equity']==0 and d['group_vol_before_limits']['currency']==0

def test_all_zero_is_flat():
    r,_=solve(['SPY','SHY'],np.zeros((2,2)),[0,0])
    np.testing.assert_array_equal(r.weights,[0,0])

def test_single_group_matches_existing_allocator_including_caps():
    cov=np.diag([.01,.04,.09]);mu=np.array([1,-1,1.]);c=PortfolioConstraints(gross_max=1.,w_max=.4)
    expected=TrendVolTarget(c).solve(mu,cov,np.zeros(3),np.zeros(3),np.ones(3))
    actual,_=solve(['SPY','QQQ','IWM'],cov,mu,cap=.4)
    np.testing.assert_allclose(actual.weights,expected.weights,rtol=1e-14,atol=1e-14)

def test_limits_may_break_group_risk_equality():
    r,d=solve(['SPY','QQQ','SHY'],np.diag([1,1,.0001]),cap=.4)
    assert abs(r.weights).sum()<=1+1e-14 and max(abs(r.weights))<=.4+1e-14
    assert d['group_vol_after_limits']['rates']!=pytest.approx(d['group_vol_after_limits']['equity'])

@pytest.mark.parametrize('symbols,cov', [(['SPY','SPY'],np.eye(2)), (['SPY','UNKNOWN'],np.eye(2)), (['SPY','SHY'],[[1,.3],[.1,1]]), (['SPY','SHY'],[[0,0],[0,1]])])
def test_bad_input_fails(symbols,cov):
    with pytest.raises(ValueError):solve(symbols,cov)

def test_zero_variance_hedged_group_fails():
    with pytest.raises(ValueError,match='group variance'):
        solve(['SPY','QQQ'],np.ones((2,2)),[1,-1])
