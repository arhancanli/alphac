from dataclasses import replace

import pytest

from alphaforge.validation.trend_observation import ObservationError, session_window
from alphaforge.validation.trend_ohlc_bridge import advance_bar
from alphaforge.validation.trend_price_bridge import Action, ActionSnapshot, PriceState

PREV = 1788998400000
NEXT = 1789084800000
DECISION = session_window(NEXT)[0] + 1
STATE = PriceState("SPY", PREV, 100, 200)
SNAP = ActionSnapshot("SPY", PREV, NEXT + 86400000, DECISION - 1, "a" * 64, True, ())


def run(snapshot=SNAP, **changes):
    params = {"raw_open": 99, "raw_high": 103, "raw_low": 98, "raw_close": 102}
    params.update(changes)
    return advance_bar(STATE, session_ms=NEXT, snapshot=snapshot, decision_ms=DECISION, **params)


def test_open_never_uses_current_close():
    snap = replace(SNAP, actions=(Action("cash", "SPY", NEXT, "dividend", 1),))
    a, b = run(snap, raw_close=100), run(snap, raw_close=102)
    assert (a.open, a.high, a.low) == (b.open, b.high, b.low) == (200, 208, 198)
    assert a.close != b.close


def test_split_adjusts_every_print():
    snap = replace(SNAP, actions=(Action("split", "SPY", NEXT, "split", 2),))
    b = run(snap, raw_open=50, raw_high=51, raw_low=49, raw_close=50)
    assert (b.open, b.high, b.low, b.close) == (200, 204, 196, 200)


def test_no_action_scaling():
    b = run()
    assert (b.open, b.high, b.low, b.close) == (198, 206, 196, 204)


@pytest.mark.parametrize(
    "changes",
    [{"raw_low": 101}, {"raw_high": 100}, {"raw_open": float("nan")}, {"raw_close": True}],
)
def test_invalid_bar(changes):
    with pytest.raises(ObservationError):
        run(**changes)


def test_late_snapshot_rejected():
    with pytest.raises(ObservationError):
        run(replace(SNAP, observed_ms=DECISION + 1))
