"""A bar is not a day, and it is a different amount of time on each sleeve.

``ewma_cov`` takes a covariance halflife in BARS. A bar is one hour on the crypto H1 sleeve and
one session on equity D1, so a single bar-valued setting means two different durations. The old
default of 720 bars meant 30 days to crypto and roughly 2.9 YEARS to equities -- nobody chose
that, it was just what one number does when it is read in two calendars.

It mattered when the drawdown study set policy. That study measured a DAILY book, so its sweep
values (21, 63, 126, 252, 720) are day counts, and the admission contract states the gate as
``covariance_halflife_days_max``. Writing the study's 21 into the bar parameter would have given
the crypto sleeve a 21-HOUR covariance halflife: not the change that was measured, and a live
sizing defect rather than a configuration choice.

The full unit suite passed both before and after the parameter changed, which is the point of
this file: nothing pinned the conversion, so nothing could have caught it.
"""

from __future__ import annotations

import inspect

import pytest

from alphaforge.core.calendar import Always24x7Calendar, XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.portfolio.strategy import BlendStrategy


class _Ctx:
    """Only what the conversion reads. The CALENDARS are the real ones, not fakes."""

    def __init__(self, calendar: object) -> None:
        self.calendar = calendar


def _bars_for(days: float, calendar: object, tf: Timeframe) -> int:
    strategy = BlendStrategy.__new__(BlendStrategy)
    strategy._cov_halflife_days = days
    return BlendStrategy._cov_halflife_bars_for(strategy, _Ctx(calendar), tf)


def test_default_is_stated_in_days_and_matches_the_measured_study() -> None:
    default = inspect.signature(BlendStrategy.__init__).parameters["cov_halflife_days"].default
    assert default == 21.0, (
        "the drawdown objective is only met at a 21-day covariance halflife; see "
        "artifacts/analysis/overlay_halflife_decision/result.json"
    )


def test_no_bar_valued_covariance_halflife_parameter_remains() -> None:
    """The mutation that reintroduces the defect is renaming the parameter back."""
    parameters = inspect.signature(BlendStrategy.__init__).parameters
    assert "cov_halflife_bars" not in parameters, (
        "a bar-valued covariance halflife means different durations on different sleeves; "
        "express it in days and convert against the calendar"
    )


@pytest.mark.parametrize(
    ("calendar", "tf", "days", "expected_bars", "why"),
    [
        (Always24x7Calendar(), Timeframe.H1, 21.0, 504, "24 hourly bars a day, 365-day year"),
        (Always24x7Calendar(), Timeframe.H1, 30.0, 720, "the old 720-bar default WAS 30 days here"),
        (XNYSCalendar(), Timeframe.D1, 21.0, 21, "one session a day, 252-session year"),
        (XNYSCalendar(), Timeframe.D1, 720.0, 720, "the old 720-bar default WAS 720 sessions here"),
    ],
)
def test_days_convert_to_bars_on_the_sleeves_own_calendar(
    calendar: object, tf: Timeframe, days: float, expected_bars: int, why: str
) -> None:
    assert _bars_for(days, calendar, tf) == expected_bars, why


def test_the_two_sleeves_disagree_by_the_factor_that_caused_the_defect() -> None:
    """Stated as a relationship rather than two constants, so it survives a calendar change."""
    crypto = _bars_for(21.0, Always24x7Calendar(), Timeframe.H1)
    equity = _bars_for(21.0, XNYSCalendar(), Timeframe.D1)
    assert crypto == 24 * equity, (
        "the same day count must produce 24x more bars on an hourly sleeve than a daily one; if "
        "these are equal, the conversion has been dropped and one sleeve is silently mis-sized"
    )


def test_a_sub_bar_halflife_floors_to_one_rather_than_zero() -> None:
    """Rounding to zero would set lambda to zero and discard the estimator entirely."""
    assert _bars_for(0.01, XNYSCalendar(), Timeframe.D1) == 1


def test_a_non_positive_halflife_is_rejected_at_construction() -> None:
    strategy = BlendStrategy.__new__(BlendStrategy)
    strategy._cov_halflife_days = 21.0
    assert _bars_for(21.0, XNYSCalendar(), Timeframe.D1) > 0
    with pytest.raises(ValueError, match="cov_halflife_days"):
        BlendStrategy(
            settings=None,  # type: ignore[arg-type]
            signal_frame=None,
            mu_provider=lambda _ts: {},
            cov_halflife_days=0.0,
        )
