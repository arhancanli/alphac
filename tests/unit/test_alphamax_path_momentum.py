import numpy as np
import pandas as pd
import pytest
from alphamax_path_momentum import path_momentum


def paths():
    smooth=np.full(231,.001)
    jump=np.r_[np.full(230,-.001),.461]
    def prices(r):return np.r_[100.,100*np.exp(np.cumsum(r)),np.full(21,200.)]
    return pd.DataFrame({'smooth':prices(smooth),'jump':prices(jump)})


def test_identical_endpoints_different_paths():
    p=paths();r=path_momentum(p,p.index)
    assert r['control'].iloc[-1].smooth==pytest.approx(r['control'].iloc[-1]['jump'])
    assert r['discreteness'].iloc[-1].smooth==-1
    assert r['discreteness'].iloc[-1]['jump']==pytest.approx(229/231)
    assert r['candidate'].iloc[-1].smooth>r['candidate'].iloc[-1]['jump']>0
    assert r['candidate'].iloc[:252].isna().all().all()


def test_loser_sign_zero_days_and_flat_series():
    p=paths();p=10000/p;p['flat']=100.
    r=path_momentum(p,p.index)
    assert r['candidate'].iloc[-1].smooth<r['candidate'].iloc[-1]['jump']<0
    assert r['candidate'].iloc[-1]['flat']==0
    zero=p.copy();zero['flat']=np.r_[np.full(231,100.),110.,np.full(21,110.)]
    q=path_momentum(zero,zero.index)
    assert q['discreteness'].iloc[-1]['flat']==pytest.approx(-1/231)


def test_skip_recent_prices_and_future_prefix_invariance():
    p=paths();a=path_momentum(p,p.index)
    changed=p.copy();changed.iloc[-21:]=np.nan
    b=path_momentum(changed,changed.index)
    for k in a:pd.testing.assert_series_equal(a[k].iloc[-1],b[k].iloc[-1])
    extra=pd.concat([p,pd.DataFrame(999.,index=range(253,280),columns=p.columns)])
    c=path_momentum(extra,extra.index)
    for k in a:pd.testing.assert_frame_equal(a[k],c[k].iloc[:len(p)])


def test_missing_session_and_nonpositive_price_invalidate_window():
    p=paths();q=p.drop(index=100)
    assert path_momentum(q,p.index)['candidate'].iloc[-1].isna().all()
    p.loc[100,'smooth']=0
    assert np.isnan(path_momentum(p,p.index)['candidate'].iloc[-1].smooth)


def test_scale_invariance_and_scalar_reference():
    p=paths();r=path_momentum(p,p.index);scaled=path_momentum(p*3,p.index)
    for k in r:np.testing.assert_allclose(r[k],scaled[k],atol=1e-12,equal_nan=True)
    for c in p:
        values=p[c].iloc[:232].to_numpy();changes=np.diff(np.log(values))
        m=np.log(values[-1]/values[0]);id_=np.sign(m)*(sum(changes<0)-sum(changes>0))/231
        assert r['candidate'].iloc[-1][c]==pytest.approx(m*(1-id_)/2)


def test_duplicate_calendar_rejected():
    p=paths()
    with pytest.raises(ValueError):path_momentum(p,list(p.index)+[252])
