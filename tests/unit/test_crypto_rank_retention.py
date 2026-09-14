import numpy as np
import pytest
from crypto_rank_retention import RankRetentionAllocator
from alphaforge.portfolio.optimizer import PortfolioConstraints, RankEqualVolFallback

def inputs(n=8):
    return [np.arange(n,0,-1,dtype=float)*.01,np.diag(np.arange(1,n+1,dtype=float)),np.zeros(n),np.full(n,.001),np.ones(n)]

def test_flat_and_disabled_exact_parity():
    x=inputs();old=RankEqualVolFallback()
    for prev in [np.zeros(8),np.linspace(-.1,.1,8)]:
        x[2]=prev
        for width in ([0,1] if not np.any(prev) else [0]):
            a=RankRetentionAllocator(buffer_ranks=width).solve(*x);b=old.solve(*x)
            np.testing.assert_array_equal(a.weights,b.weights);assert a.objective==b.objective

def test_one_rank_retention_and_forced_outside_exit():
    x=inputs();x[2][2]=.1;x[2][5]=-.1
    a=RankRetentionAllocator().solve(*x)
    assert set(np.flatnonzero(a.weights>0))=={0,2}
    assert set(np.flatnonzero(a.weights<0))=={5,7}
    x[2][:]=0;x[2][3]=.1;x[2][4]=-.1
    b=RankRetentionAllocator().solve(*x)
    assert b.weights[3]==b.weights[4]==0

def test_forbidden_short_caps_objective_and_no_mutation():
    x=inputs();x[2][5]=-.1;x[4][5]=0;copies=[v.copy() for v in x]
    a=RankRetentionAllocator().solve(*x)
    assert a.weights[5]>=0 and np.max(np.abs(a.weights))<=.15+1e-14
    assert a.objective==float(x[0]@a.weights)
    assert np.abs(a.weights).sum()<=.5+1e-14
    for left,right in zip(x,copies):np.testing.assert_array_equal(left,right)

def test_retained_inverse_vol_sizing():
    x=inputs();x[2][2]=.1;x[2][5]=-.1;a=RankRetentionAllocator().solve(*x)
    proxy=np.array([2.,0.,1.,0.,0.,-2.,0.,-1.])
    b=RankEqualVolFallback().solve(proxy,*x[1:]);np.testing.assert_array_equal(a.weights,b.weights)

def test_small_cross_section_and_ties():
    for n in [2,3]:
        x=inputs(n);x[2][0]=.1
        np.testing.assert_array_equal(RankRetentionAllocator().solve(*x).weights,RankEqualVolFallback().solve(*x).weights)
    x=inputs();x[0][:]=1;x[2][2]=.1
    a=RankRetentionAllocator().solve(*x);b=RankRetentionAllocator().solve(*x)
    np.testing.assert_array_equal(a.weights,b.weights)
    assert not set(np.flatnonzero(a.weights>0))&set(np.flatnonzero(a.weights<0))

def test_reject_unregistered_width_and_long_only():
    with pytest.raises(ValueError):RankRetentionAllocator(buffer_ranks=2)
    with pytest.raises(ValueError):RankRetentionAllocator(PortfolioConstraints(long_only=True))
