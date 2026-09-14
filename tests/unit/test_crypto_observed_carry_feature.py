from types import SimpleNamespace
import numpy as np
import pandas as pd
from crypto_observed_carry import observed_carry
from crypto_observed_carry_feature import carry_observed_21,feature_fn,payment_values

H=3600000

def context(f,grid):
    return SimpleNamespace(instrument_ids=['A'],panel=lambda _:pd.DataFrame(index=grid),funding=lambda:f.copy(),instrument=lambda _:SimpleNamespace(funding_interval_hours=4))

def frame():
    ts=np.arange(70)*8*H
    return pd.DataFrame({'instrument_id':'A','ts_funding':ts,'available_at':ts+300000,'rate':np.linspace(-.001,.002,70)})

def test_vector_matches_scalar_and_minimum_history():
    f=frame();actual=payment_values(f,21)
    expected=[observed_carry(f.ts_funding,f.available_at,f.rate,decision_ms=int(t)) for t in f.available_at]
    np.testing.assert_allclose(actual,expected,rtol=0,atol=0,equal_nan=True)
    assert np.isnan(actual[:21]).all()

def test_grid_publication_boundary_and_stale_metadata():
    f=frame();ts=int(f.ts_funding.iloc[21]);spec=carry_observed_21()
    out=feature_fn(context(f,[ts-H,ts]),spec)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1]==observed_carry(f.ts_funding,f.available_at,f.rate,decision_ms=ts+H)

def test_declared_history_and_future_independence():
    f=frame();spec=carry_observed_21();decision=500*H
    grid=[decision-H]
    full=feature_fn(context(f,grid),spec)
    short=f[(f.ts_funding>=decision-spec.lookback_bars*H)&(f.available_at<=decision)]
    minimal=feature_fn(context(short,grid),spec)
    pd.testing.assert_series_equal(full,minimal)
    changed=f.copy();changed.loc[changed.available_at>decision,'rate']=999
    pd.testing.assert_series_equal(full,feature_fn(context(changed,grid),spec))

def test_late_publication_uses_only_known_settlements():
    f=frame();f.loc[25,'available_at']=f.loc[28,'available_at']+1
    f=f.sort_values('available_at',kind='stable')
    actual=payment_values(f,21)
    expected=[observed_carry(f.ts_funding,f.available_at,f.rate,decision_ms=int(t)) for t in f.available_at]
    np.testing.assert_allclose(actual,expected,rtol=0,atol=0,equal_nan=True)
