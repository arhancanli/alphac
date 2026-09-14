import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

from alphaforge.validation.treasury_settlement_calendar import regular_settlement_date

spec = importlib.util.spec_from_file_location(
    "calendar_audit", Path(__file__).resolve().parents[2] / "scripts/audit_treasury_calendar.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_wrapped_date_is_retained():
    assert module.parse_cell("Monday, November\n 11", 2013) == ["2013-11-11"]
    assert module.parse_cell("Frida y, M a y 24", 2013) == ["2013-05-24"]


@pytest.mark.parametrize("cell", ["Monday, February 21, 2021", "Thursday, November 24, 2021"])
def test_wrong_source_year_refused(cell):
    with pytest.raises(ValueError):
        module.parse_cell(cell, 2022)


def test_adjacent_year_and_missing_day():
    assert module.parse_cell("Monday, December 31, 2012", 2013) == ["2012-12-31"]
    with pytest.raises(ValueError):
        module.parse_cell("Monday, November", 2013)


def calendars():
    start = date(2023, 4, 7)
    dates = [start + timedelta(days=i) for i in range(5)]
    fed = {d: d.weekday() < 5 for d in dates}
    market = dict(fed)
    market[start] = False
    return fed, market


def test_fedwire_open_does_not_make_good_friday_good_settlement():
    fed, market = calendars()
    assert regular_settlement_date(date(2023, 4, 6), fed, market) == date(2023, 4, 10)


def test_explicit_good_friday_two_day_rule():
    fed, market = calendars()
    assert regular_settlement_date(date(2023, 4, 7), fed, market, lag=2) == date(2023, 4, 11)


def test_missing_market_calendar_cannot_default_open():
    fed, market = calendars()
    del market[date(2023, 4, 7)]
    with pytest.raises(ValueError, match="unverified"):
        regular_settlement_date(date(2023, 4, 6), fed, market)


@pytest.mark.parametrize("lag", [True, 0, -1, 1.5])
def test_invalid_lag(lag):
    with pytest.raises(ValueError):
        regular_settlement_date(date(2023, 4, 6), {}, {}, lag=lag)
