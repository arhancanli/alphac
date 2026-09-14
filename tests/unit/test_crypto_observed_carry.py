import numpy as np
import pytest
from crypto_observed_carry import observed_carry

H=3600000

@pytest.mark.parametrize('interval',[1,4,8])
def test_fixed_cadence_matches_correct_interval(interval):
    ts=np.arange(22)*interval*H;rates=np.linspace(-.0002,.0004,22)
    assert observed_carry(ts,ts+300000,rates,decision_ms=int(ts[-1]+300000))==pytest.approx(-rates[1:].mean()*8760/interval)


def test_mixed_cadence_uses_elapsed_time():
    ts=np.array([0,8,12])*H
    assert observed_carry(ts,ts+300000,[0,.008,.004],decision_ms=13*H,k=2)==pytest.approx(-.012*8760/12)


def test_unpublished_future_payment_cannot_change_result():
    ts=np.arange(23)*8*H;pub=ts+300000;rates=np.ones(23)*.0001
    baseline=observed_carry(ts,pub,rates,decision_ms=int(ts[-2]+300000))
    rates[-1]=999
    assert observed_carry(ts,pub,rates,decision_ms=int(ts[-2]+300000))==baseline


@pytest.mark.parametrize('hours',[[0,8],[0,0,8],[0,8,24]])
def test_insufficient_duplicate_or_large_gap_is_unresolved(hours):
    ts=np.array(hours)*H
    assert np.isnan(observed_carry(ts,ts,np.ones(len(ts)),decision_ms=25*H,k=2))
