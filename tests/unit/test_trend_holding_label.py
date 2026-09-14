from dataclasses import replace

import pytest

from alphaforge.validation.trend_holding_label import holding_label, label_sessions
from alphaforge.validation.trend_observation import ObservationError, session_window
from alphaforge.validation.trend_price_bridge import Action, ActionSnapshot

ENTRY = 1788998400000
EXIT = 1789084800000
RELEASE = session_window(EXIT)[0]
SNAP = ActionSnapshot("SPY", ENTRY, EXIT + 86400000, RELEASE, "a" * 64, True, ())


def label(snap=SNAP, **changes):
    args = {
        "symbol": "SPY",
        "entry_ms": ENTRY,
        "exit_ms": EXIT,
        "entry_open": 100,
        "exit_open": 110,
        "snapshot": snap,
        "as_of_ms": RELEASE,
    }
    args.update(changes)
    return holding_label(**args)


def test_no_action():
    assert label().gross_return == pytest.approx(0.1)


def test_entry_dividend_not_entitled():
    snap = replace(SNAP, actions=(Action("entry", "SPY", ENTRY, "dividend", 1),))
    assert label(snap) == label()


def test_exit_dividend_entitled():
    snap = replace(SNAP, actions=(Action("exit", "SPY", EXIT, "dividend", 1),))
    result = label(snap, exit_open=99)
    assert result.gross_return == 0
    assert result.dividend_receivables == 1


def test_entry_split_excluded_exit_split_included():
    entry = replace(SNAP, actions=(Action("split", "SPY", ENTRY, "split", 2),))
    assert label(entry) == label()
    ex = replace(SNAP, actions=(Action("split", "SPY", EXIT, "split", 2),))
    assert label(ex, exit_open=50).gross_return == 0


def test_cash_is_not_reinvested():
    end = 1789344000000
    snap = replace(
        SNAP, end_ms=end + 86400000, actions=(Action("cash", "SPY", EXIT, "dividend", 10),)
    )
    result = label(snap, exit_ms=end, exit_open=120, as_of_ms=session_window(end)[0])
    assert result.terminal_shares == 1
    assert result.dividend_receivables == 10
    assert result.gross_return == pytest.approx(0.3)


def test_split_then_cash_uses_new_share_count():
    end = 1789344000000
    snap = replace(
        SNAP,
        end_ms=end + 86400000,
        actions=(
            Action("split", "SPY", EXIT, "split", 2),
            Action("cash", "SPY", end, "dividend", 1),
        ),
    )
    result = label(snap, exit_ms=end, exit_open=49, as_of_ms=session_window(end)[0])
    assert result.gross_return == 0
    assert result.dividend_receivables == 2


def test_exit_close_release():
    with pytest.raises(ObservationError):
        label(as_of_ms=RELEASE - 1)
    assert label().release_ms == RELEASE


def test_late_snapshot():
    late = replace(SNAP, observed_ms=RELEASE + 1)
    with pytest.raises(ObservationError):
        label(late)
    assert label(late, mode="DIAGNOSTIC_CURRENT_VINTAGE").mode == "DIAGNOSTIC_CURRENT_VINTAGE"


@pytest.mark.parametrize(
    "snap",
    [
        replace(SNAP, complete=False),
        replace(SNAP, end_ms=EXIT),
        replace(SNAP, symbol="QQQ"),
        replace(SNAP, actions=(Action("a", "SPY", EXIT, "dividend", 1),) * 2),
    ],
)
def test_invalid_coverage(snap):
    with pytest.raises(ObservationError):
        label(snap)


def test_horizon_weekend_and_holiday():
    # Thursday September 3 -> Friday September 4 entry, Tuesday September 8 exit.
    import pandas as pd

    def ms(d):
        return int(pd.Timestamp(d, tz="UTC").value // 1_000_000)
    assert label_sessions(ms("2026-09-03"), 1) == (ms("2026-09-04"), ms("2026-09-08"))
