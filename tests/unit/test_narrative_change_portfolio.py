"""Task 5 of the narrative-change plan: a synthetic three-stock world with a halt, a delisting and
a month-end on a holiday reproduces the pre-registration's execution semantics exactly."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from alphaforge.research.narrative_change.inputs import DailyPanel, SessionCalendar
from alphaforge.research.narrative_change.portfolio import (
    BASELINE_COSTS,
    HOLD_SESSIONS,
    STRESS_COSTS,
    ActiveCohort,
    capacity_report,
    schedule_cohorts,
    simulate_book,
    target_book,
)
from alphaforge.research.narrative_change.signal import CohortResult

AAA, BBB, CCC, SPY = "XUSE:CASH:AAAUSD", "XUSE:CASH:BBBUSD", "XUSE:CASH:CCCUSD", "XUSE:CASH:SPYUSD"


def _ms(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp() * 1000)


def _sessions(n: int) -> list[dt.date]:
    days: list[dt.date] = []
    day = dt.date(2024, 1, 2)
    while len(days) < n:
        if day.weekday() < 5 and day != dt.date(2024, 9, 2):  # Labor Day is not a session
            days.append(day)
        day += dt.timedelta(days=1)
    return days


def _world(n: int = 420) -> tuple[SessionCalendar, DailyPanel, DailyPanel]:
    days = _sessions(n)
    cal = SessionCalendar([_ms(d) for d in days])
    index = pd.Index(cal.opens, name="ts_open")
    k = np.arange(n, dtype="float64")
    close = pd.DataFrame(
        {AAA: 50.0 + 0.10 * k, BBB: 30.0 - 0.02 * k, CCC: 20.0 + 0.05 * k}, index=index
    )
    open_ = close.shift(1).fillna(close.iloc[0]) * 1.001  # opens near the prior close
    volume = pd.DataFrame(
        {AAA: np.full(n, 2e6), BBB: np.full(n, 1e6), CCC: np.full(n, 5e5)}, index=index
    )
    # BBB halts for three sessions starting one session after the entry (which is session 260)
    for pos in (261, 262, 263):
        for frame in (close, open_, volume):
            frame.iloc[pos, frame.columns.get_loc(BBB)] = np.nan
    # CCC delists: no bars after session 290
    for frame in (close, open_, volume):
        frame.iloc[291:, frame.columns.get_loc(CCC)] = np.nan
    spy_close = pd.DataFrame({SPY: 400.0 + 0.2 * k}, index=index)
    spy = DailyPanel(
        spy_close * 0.999, spy_close, spy_close * 0 + 1e7, spy_close.copy(), pd.DataFrame()
    )
    panel = DailyPanel(open_, close, volume, close.copy(), pd.DataFrame())
    return cal, panel, spy


def _cohort(cal: SessionCalendar, entry_pos: int) -> CohortResult:
    rows = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "instrument_id": [AAA, BBB, CCC],
            "residual": [0.3, -0.2, -0.1],
            "side": ["LONG", "SHORT", "SHORT"],
        }
    )
    return CohortResult(2024, 12, cal.dates[entry_pos], "RANKED", rows, {"eligible": 3})


def test_entry_is_the_second_open_after_a_month_end_on_a_holiday_weekend() -> None:
    cal, _panel, _spy = _world()
    # August 2024 ends on Saturday the 31st; Monday 09-02 is Labor Day: sessions 09-03, 09-04
    assert cal.second_session_open_after_month_end(2024, 8) == dt.date(2024, 9, 4)


def test_scheduling_excludes_a_cohort_whose_exit_falls_after_the_window() -> None:
    cal, panel, spy = _world()
    late = _cohort(cal, len(cal) - 10)
    active, excluded = schedule_cohorts([late], panel, spy, cal, last_admissible_exit=cal.dates[-1])
    assert active == [] and excluded == ["2024-12"]
    early = _cohort(cal, 260)
    active, excluded = schedule_cohorts(
        [early], panel, spy, cal, last_admissible_exit=cal.dates[-1]
    )
    assert excluded == [] and active[0].exit_pos == 260 + HOLD_SESSIONS
    assert active[0].weights == {AAA: 0.5, BBB: -0.25, CCC: -0.25}
    assert all(-1.0 <= b <= 1.0 for b in active[0].betas.values())


def test_the_target_book_averages_cohorts_hedges_beta_and_normalizes_total_gross() -> None:
    a = ActiveCohort(2024, 1, 0, 63, {AAA: 0.5, BBB: -0.5}, {AAA: 1.0, BBB: 0.5})
    b = ActiveCohort(2024, 2, 20, 83, {AAA: 0.5, CCC: -0.5}, {AAA: 1.0, CCC: 1.0})
    weights, hedge = target_book([a, b], 30)
    # averaged: AAA 0.5, BBB -0.25, CCC -0.25 (stock gross 1.0); beta 0.5 - 0.125 - 0.25 = 0.125
    total = sum(abs(w) for w in weights.values()) + abs(hedge)
    assert total == pytest.approx(1.0)
    assert hedge == pytest.approx(-0.125 / 1.125)
    assert weights[AAA] == pytest.approx(0.5 / 1.125) and weights[BBB] == pytest.approx(
        -0.25 / 1.125
    )
    assert target_book([a, b], 100) == ({}, 0.0)


def test_the_book_realizes_open_to_open_defers_through_a_halt_and_force_flats_a_delisting() -> None:
    cal, panel, spy = _world()
    cohort = _cohort(cal, 260)
    active, _ = schedule_cohorts([cohort], panel, spy, cal, last_admissible_exit=cal.dates[-1])
    book = simulate_book(active, panel, spy, cal, start_pos=255, end_pos=340)
    frame = book.frame()
    entry = cal.dates[260]
    # nothing before entry; at entry the stock gross is 1 minus the hedge's share of total gross
    assert frame.loc[cal.dates[259], "positions"] == 0
    assert frame.loc[entry, "positions"] == 3
    assert frame.loc[entry, "stock_gross"] + abs(frame.loc[entry, "hedge_weight"]) == pytest.approx(
        1.0
    )
    assert frame.loc[entry, "turnover"] == pytest.approx(1.0)  # every weight bought or sold once
    # the first day's gross return is the weighted open-to-open move plus the hedge
    w = {AAA: frame.loc[entry, "stock_gross"] * 0.5, BBB: -frame.loc[entry, "stock_gross"] * 0.25}
    aopen = panel.open * (panel.adjusted_close / panel.close)
    expected = sum(
        w_i * (aopen[iid].iloc[261] / aopen[iid].iloc[260] - 1.0)
        for iid, w_i in w.items()
        if iid != BBB
    )
    # BBB is halted on 261: its move is realized when it reopens (session 264), not today
    expected += -frame.loc[entry, "stock_gross"] * 0.25 * 0.0
    ccc_w = -frame.loc[entry, "stock_gross"] * 0.25
    expected += ccc_w * (aopen[CCC].iloc[261] / aopen[CCC].iloc[260] - 1.0)
    spy_open = spy.open[SPY] * (spy.adjusted_close[SPY] / spy.close[SPY])
    expected += frame.loc[entry, "hedge_weight"] * (spy_open.iloc[261] / spy_open.iloc[260] - 1.0)
    assert frame.loc[entry, "gross_return"] == pytest.approx(expected)
    # the halt: BBB's reopening interval lands on the reopening session
    reopen = cal.dates[264]
    bbb_gap = aopen[BBB].iloc[264] / aopen[BBB].iloc[260] - 1.0
    assert book.deferred_changes == 0  # no target changed during the halt (hold is constant)
    assert frame.loc[reopen, "gross_return"] != frame.loc[cal.dates[265], "gross_return"]
    assert abs(bbb_gap) > 0
    # the delisting: CCC has no open after session 290 -> force-flat at its final open, reported
    flats = [e for e in book.events if e.kind == "FORCE_FLAT"]
    assert len(flats) == 1 and flats[0].instrument_id == CCC and flats[0].session == cal.dates[290]
    assert frame.loc[cal.dates[291], "positions"] == 2
    # costs: net is gross less 15 bps on turnover and 3 percent annual borrow on the shorts
    short_gross = -sum(v for v in (w[BBB], ccc_w) if v < 0)
    cost = (
        1.0 * BASELINE_COSTS.stock_rate
        + abs(frame.loc[entry, "hedge_weight"]) * BASELINE_COSTS.spy_rate
    )
    cost += short_gross * BASELINE_COSTS.borrow_per_session
    assert frame.loc[entry, "net_return"] == pytest.approx(frame.loc[entry, "gross_return"] - cost)
    assert frame.loc[entry, "stressed_net_return"] < frame.loc[entry, "net_return"]
    assert STRESS_COSTS.stock_bps == 2 * BASELINE_COSTS.stock_bps
    # exit: 63 sessions after entry the book is flat again and turnover paid once more
    exit_session = cal.dates[260 + HOLD_SESSIONS]
    assert frame.loc[exit_session, "positions"] == 0
    assert frame.loc[exit_session, "turnover"] > 0


def test_capacity_reports_the_capital_at_which_the_largest_position_hits_each_adv_fraction() -> (
    None
):
    cal, panel, spy = _world()
    active, _ = schedule_cohorts(
        [_cohort(cal, 260)], panel, spy, cal, last_admissible_exit=cal.dates[-1]
    )
    report = capacity_report(active, panel, cal)
    assert report["status"] == "REPORTED"
    # CCC: weight 0.25 on the thinnest ADV binds (5e5 shares * ~$33 open... median dollar volume)
    dollar = (panel.close * panel.volume)[CCC].iloc[260 - 21 : 260].median()
    assert report["binding_position"]["instrument_id"] == CCC
    assert report["capital_at"]["1pct_adv"] == pytest.approx(0.01 * dollar / 0.25)
    assert report["capital_at"]["1bp_adv"] == pytest.approx(1e-4 * dollar / 0.25)
