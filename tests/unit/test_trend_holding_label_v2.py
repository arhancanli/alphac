from dataclasses import replace

import pytest

from alphaforge.validation.trend_holding_label_v2 import holding_label
from alphaforge.validation.trend_observation import ObservationError, session_window
from alphaforge.validation.trend_price_bridge import ActionSnapshot

ENTRY, EXIT = 1788998400000, 1789084800000
RELEASE = session_window(EXIT)[0]
SNAP = ActionSnapshot("SPY", ENTRY, EXIT + 86400000, RELEASE, "a" * 64, True, ())


def test_late_record_rejected_even_when_computed_later():
    with pytest.raises(ObservationError, match="fixed exit-close"):
        holding_label(
            symbol="SPY",
            entry_ms=ENTRY,
            exit_ms=EXIT,
            entry_open=100,
            exit_open=110,
            snapshot=replace(SNAP, observed_ms=RELEASE + 1),
            as_of_ms=RELEASE + 100,
        )


def test_timely_record_can_be_replayed_later():
    result = holding_label(
        symbol="SPY",
        entry_ms=ENTRY,
        exit_ms=EXIT,
        entry_open=100,
        exit_open=110,
        snapshot=SNAP,
        as_of_ms=RELEASE + 100,
    )
    assert result.release_ms == RELEASE
    assert result.gross_return == pytest.approx(0.1)


def test_current_vintage_explicitly_diagnostic():
    result = holding_label(
        symbol="SPY",
        entry_ms=ENTRY,
        exit_ms=EXIT,
        entry_open=100,
        exit_open=110,
        snapshot=replace(SNAP, observed_ms=RELEASE + 1),
        as_of_ms=RELEASE,
        mode="DIAGNOSTIC_CURRENT_VINTAGE",
    )
    assert result.mode == "DIAGNOSTIC_CURRENT_VINTAGE"
