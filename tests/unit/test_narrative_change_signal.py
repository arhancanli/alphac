"""Task 4 of the narrative-change plan: the signal's clauses, each pinned on synthetic data.
No return is loaded; a cohort's sides are the only thing these tests read."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from alphaforge.research.narrative_change.inputs import DailyPanel, SessionCalendar
from alphaforge.research.narrative_change.signal import (
    eligible_pairs,
    entry_eligibility,
    filing_reaction,
    momentum_12_1,
    rank_cohort,
    residual_signal,
)


def _cohort(n: int, *, seed: int = 3, sics: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "cik": np.arange(1000, 1000 + n),
            "instrument_id": [f"XUSE:CASH:T{k}USD" for k in range(n)],
            "sic": [str(10 + (k % sics)) for k in range(n)],
            "stability": rng.uniform(0.2, 0.9, size=n),
            "reaction": rng.normal(0.0, 0.03, size=n),
            "momentum": rng.normal(0.05, 0.2, size=n),
        }
    )


def test_a_cohort_below_twenty_issuers_is_flat() -> None:
    ranked, status = rank_cohort(_cohort(19))
    assert status == "fewer_than_20_eligible" and set(ranked["side"]) == {"FLAT"}


def test_a_ranked_cohort_longs_the_top_quintile_and_shorts_the_bottom() -> None:
    cohort = _cohort(30)
    ranked, status = rank_cohort(cohort)
    assert status == "RANKED"
    assert (ranked["side"] == "LONG").sum() == 6 and (ranked["side"] == "SHORT").sum() == 6
    top = ranked[ranked["side"] == "LONG"]["residual"]
    bottom = ranked[ranked["side"] == "SHORT"]["residual"]
    assert top.min() >= ranked[ranked["side"] == "NONE"]["residual"].max()
    assert bottom.max() <= ranked[ranked["side"] == "NONE"]["residual"].min()


def test_the_residual_is_orthogonal_to_the_controls_and_the_industry_dummies() -> None:
    cohort = _cohort(60, sics=4)
    residual, status = residual_signal(cohort)
    assert status == "RANKED" and residual is not None
    ranked_reaction = cohort["reaction"].rank(pct=True)
    ranked_momentum = cohort["momentum"].rank(pct=True)
    assert abs(float(np.dot(residual, ranked_reaction))) < 1e-9
    assert abs(float(np.dot(residual, ranked_momentum))) < 1e-9
    for sic in cohort["sic"].unique():
        assert abs(float(residual[cohort["sic"] == sic].sum())) < 1e-9


def test_a_saturated_industry_design_leaves_the_cohort_flat() -> None:
    """Twenty issuers, twenty industries: the one-hot design absorbs everything."""
    cohort = _cohort(20, sics=20)
    ranked, status = rank_cohort(cohort)
    assert status == "residual_dof_below_10" and set(ranked["side"]) == {"FLAT"}


def test_ties_break_by_cik_and_never_by_order_of_arrival() -> None:
    cohort = _cohort(25)
    cohort["stability"] = 0.5  # every name identical: all residuals tie at zero
    cohort["reaction"] = 0.0
    cohort["momentum"] = 0.0
    _ranked, status = rank_cohort(cohort)
    # ten distinct residuals are required; identical inputs cannot rank
    assert status == "fewer_than_10_distinct_residuals"
    cohort2 = _cohort(25, seed=9)
    shuffled = cohort2.sample(frac=1.0, random_state=1)
    a, _ = rank_cohort(cohort2)
    b, _ = rank_cohort(shuffled)
    assert a["cik"].to_list() == b["cik"].to_list()


def test_eligible_pairs_require_500_words_and_parse_acceptance() -> None:
    pairs = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "current_accession": ["a", "b", "c"],
            "previous_acceptance": ["2024-03-01T10:00:00.000Z"] * 3,
            "current_acceptance": ["2025-03-01T21:00:00.000Z"] * 3,
            "previous_section_words": [600, 499, 800],
            "current_section_words": [700, 700, 700],
            "sic": ["36", "36", "49"],
            "fivegram_jaccard": [0.7, 0.8, 0.9],
        }
    )
    frame = eligible_pairs(pairs)
    assert frame["cik"].to_list() == [1, 3]
    assert frame["cohort_year"].to_list() == [2025, 2025] and frame["cohort_month"].iloc[0] == 3
    assert int(frame["acceptance_ms"].iloc[0]) == int(
        dt.datetime(2025, 3, 1, 21, tzinfo=dt.UTC).timestamp() * 1000
    )


def _ms(day: dt.date, hour: int = 0) -> int:
    return int(dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.UTC).timestamp() * 1000)


def _world(n_sessions: int = 300) -> tuple[SessionCalendar, DailyPanel, pd.Series]:
    start = dt.date(2024, 1, 2)
    days: list[dt.date] = []
    day = start
    while len(days) < n_sessions:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    cal = SessionCalendar([_ms(d) for d in days])
    index = pd.Index(cal.opens, name="ts_open")
    iid = "XUSE:CASH:AAAUSD"
    close = pd.DataFrame({iid: np.linspace(10.0, 40.0, n_sessions)}, index=index)
    volume = pd.DataFrame({iid: np.full(n_sessions, 1_000_000.0)}, index=index)
    spy = pd.Series(np.linspace(400.0, 500.0, n_sessions), index=index)
    panel = DailyPanel(close * 0.99, close, volume, close.copy(), pd.DataFrame())
    return cal, panel, spy


def test_reaction_momentum_and_eligibility_follow_the_clauses() -> None:
    cal, panel, spy = _world()
    iid = "XUSE:CASH:AAAUSD"
    accepted = _ms(cal.dates[100], 21)  # after that session's open: window is 100 -> 101
    reaction = filing_reaction(panel, spy, cal, iid, accepted)
    p = panel.adjusted_close[iid]
    expected = p.iloc[101] / p.iloc[100] - spy.iloc[101] / spy.iloc[100]
    assert reaction == pytest.approx(expected)
    month_end = cal.dates[270]
    assert momentum_12_1(panel, cal, iid, month_end) == pytest.approx(
        p.iloc[249] / p.iloc[18] - 1.0
    )
    assert np.isnan(momentum_12_1(panel, cal, iid, cal.dates[100]))  # 252 sessions unavailable
    ok, reason = entry_eligibility(panel, cal, iid, cal.dates[50])
    assert ok and reason == "eligible"
    cheap = DailyPanel(
        panel.open, panel.close * 0.1, panel.volume, panel.adjusted_close, panel.actions
    )
    assert entry_eligibility(cheap, cal, iid, cal.dates[50]) == (False, "close_below_5")
    thin = DailyPanel(
        panel.open, panel.close, panel.volume * 0.001, panel.adjusted_close, panel.actions
    )
    assert entry_eligibility(thin, cal, iid, cal.dates[50]) == (
        False,
        "median_dollar_volume_below_5m",
    )
    assert entry_eligibility(panel, cal, iid, cal.dates[5]) == (False, "dollar_volume_window_short")
