from dataclasses import replace

import pytest

from alphaforge.validation.trend_observation import ObservationError, session_window
from alphaforge.validation.trend_price_bridge import (
    Action,
    ActionSnapshot,
    PriceState,
    advance_close,
)

PREV = 1788998400000
NEXT = 1789084800000
DECISION = session_window(NEXT)[0] + 1000
STATE = PriceState("SPY", PREV, 100, 200)
SNAP = ActionSnapshot("SPY", PREV, NEXT + 86400000, DECISION - 1, "a" * 64, True, ())


def advance(snapshot=SNAP, price=101, **kwargs):
    return advance_close(
        STATE, session_ms=NEXT, raw_close=price, snapshot=snapshot, decision_ms=DECISION, **kwargs
    )


def test_no_action():
    assert advance().signal_close == 202


def test_cash_distribution_preserves_wealth():
    event = Action("d1", "SPY", NEXT, "dividend", 1)
    assert advance(replace(SNAP, actions=(event,)), price=99).signal_close == 200


def test_split_preserves_wealth():
    event = Action("s1", "SPY", NEXT, "split", 2)
    assert advance(replace(SNAP, actions=(event,)), price=50).signal_close == 200


def test_reverse_split():
    event = Action("s1", "SPY", NEXT, "split", 0.1)
    assert advance(replace(SNAP, actions=(event,)), price=1000).signal_close == 200


def test_late_receipt_only_diagnostic():
    snap = replace(SNAP, observed_ms=DECISION + 1)
    with pytest.raises(ObservationError):
        advance(snap)
    assert advance(snap, mode="DIAGNOSTIC_CURRENT_VINTAGE").signal_close == 202


@pytest.mark.parametrize(
    "snap",
    [
        replace(SNAP, complete=False),
        replace(SNAP, end_ms=NEXT),
        replace(SNAP, symbol="QQQ"),
        replace(SNAP, digest="bad"),
        replace(SNAP, actions=(Action("d1", "SPY", NEXT, "dividend", 1),) * 2),
        replace(SNAP, actions=(Action("d1", "SPY", NEXT, "dividend", -1),)),
        replace(
            SNAP,
            actions=(
                Action("s1", "SPY", NEXT, "split", 2),
                Action("d1", "SPY", NEXT, "dividend", 1),
            ),
        ),
    ],
)
def test_reject_bad_snapshots(snap):
    with pytest.raises(ObservationError):
        advance(snap)


def test_repeat_session_rejected():
    with pytest.raises(ObservationError):
        advance_close(
            advance(), session_ms=NEXT, raw_close=101, snapshot=SNAP, decision_ms=DECISION
        )


def test_future_action_does_not_change_current_price():
    future = 1789344000000  # next Monday
    snapshot = replace(
        SNAP, end_ms=future + 86400000, actions=(Action("future", "SPY", future, "dividend", 1),)
    )
    assert advance(snapshot) == advance()


def test_preclose_rejected():
    with pytest.raises(ObservationError):
        advance_close(
            STATE,
            session_ms=NEXT,
            raw_close=101,
            snapshot=SNAP,
            decision_ms=session_window(NEXT)[0] - 1,
        )
