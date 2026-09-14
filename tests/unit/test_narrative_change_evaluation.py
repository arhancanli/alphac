"""Task 6 (evaluation half): each reported number is pinned on synthetic series, and the whole
report is exercised on the Task 5 world's book."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from alphaforge.research.narrative_change.evaluation import (
    annual_results,
    beta_to_spy,
    diversification_evidence,
    evaluate_book,
    leave_one_year_out,
    mean_zero_control,
    newey_west_lags,
    series_stats,
)


def _dates(n: int, start: dt.date = dt.date(2016, 1, 4)) -> list[dt.date]:
    out: list[dt.date] = []
    day = start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += dt.timedelta(days=1)
    return out


def test_the_newey_west_lag_rule_is_the_v2_template_rule() -> None:
    assert newey_west_lags(100) == 7
    assert newey_west_lags(1000) == max(7, int(4 * (10.0) ** (2 / 9)))
    assert newey_west_lags(5000) == 9


def test_series_stats_reproduce_sharpe_drawdown_and_cumulative_return() -> None:
    returns = pd.Series([0.01, -0.02, 0.015, 0.0, 0.005], index=_dates(5))
    stats = series_stats(returns)
    values = returns.to_numpy()
    assert stats.observations == 5
    assert stats.annualized_sharpe == pytest.approx(
        values.mean() / values.std(ddof=1) * np.sqrt(252)
    )
    assert stats.cumulative_return == pytest.approx(np.prod(1 + values) - 1)
    equity = np.cumprod(1 + values)
    assert stats.max_drawdown == pytest.approx(np.max(1 - equity / np.maximum.accumulate(equity)))
    assert stats.newey_west_t is not None
    empty = series_stats(pd.Series([], dtype="float64"))
    assert empty.observations == 0 and empty.annualized_sharpe is None


def test_annual_and_leave_one_year_out_partition_the_record() -> None:
    dates = _dates(600)
    rng = np.random.default_rng(1)
    returns = pd.Series(rng.normal(0.0005, 0.01, size=600), index=dates)
    annual = annual_results(returns)
    assert sum(v["observations"] for v in annual.values()) == 600
    loyo = leave_one_year_out(returns)
    for year, row in loyo.items():
        assert row["observations"] == 600 - annual[year]["observations"]


def test_beta_and_the_mean_zero_control_behave() -> None:
    dates = _dates(400)
    rng = np.random.default_rng(2)
    spy = pd.Series(rng.normal(0.0004, 0.01, size=400), index=dates)
    book = 0.5 * spy + pd.Series(rng.normal(0.0, 0.002, size=400), index=dates)
    assert beta_to_spy(book, spy) == pytest.approx(0.5, abs=0.05)
    assert beta_to_spy(book.iloc[:10], spy.iloc[:10]) is None
    control = mean_zero_control(book)
    assert control["status"] == "REPORTED" and control["draws"] == 1000
    assert (
        control["control_sharpe_p95"] > 0
        and 0.0 <= control["fraction_of_controls_at_or_above_candidate"] <= 1.0
    )
    assert mean_zero_control(book.iloc[:10])["status"] == "TOO_SHORT"


def test_evaluate_book_reports_every_preregistered_section_on_the_task5_world() -> None:
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "narrative_change_portfolio_world",
        Path(__file__).with_name("test_narrative_change_portfolio.py"),
    )
    assert spec and spec.loader
    world_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(world_module)
    _cohort, _world = world_module._cohort, world_module._world

    from alphaforge.research.narrative_change.portfolio import schedule_cohorts, simulate_book

    cal, panel, spy = _world()
    active, _ = schedule_cohorts(
        [_cohort(cal, 260)], panel, spy, cal, last_admissible_exit=cal.dates[-1]
    )
    book = simulate_book(active, panel, spy, cal, start_pos=255, end_pos=400)
    spy_id = spy.instrument_ids[0]
    spy_returns = spy.adjusted_close[spy_id].pct_change()
    spy_returns.index = pd.Index(cal.dates)
    report = evaluate_book(
        book,
        spy_returns=spy_returns,
        union_identities=347,
        union_sharpe_variance=0.0004,
        window_label="synthetic",
    )
    for key in (
        "gross",
        "net",
        "stressed_net",
        "beta_to_spy",
        "execution",
        "events",
        "annual",
        "leave_one_year_out",
        "mean_zero_control",
        "pbo",
        "deflated_sharpe",
    ):
        assert key in report, key
    assert report["pbo"]["status"] == "NOT_DEFINED"
    assert report["events"]["force_flat"] == 1
    assert report["net"]["observations"] == 145
    assert report["deflated_sharpe"]["union_identities"] == 347
    assert 0.0 <= report["deflated_sharpe"]["dsr"] <= 1.0
    assert report["stressed_net"]["cumulative_return"] <= report["net"]["cumulative_return"]


def test_diversification_evidence_runs_the_shared_engine_on_the_common_window() -> None:
    dates = _dates(800)
    rng = np.random.default_rng(5)
    candidate = pd.Series(rng.normal(0.0003, 0.008, size=800), index=dates)
    sleeves = {
        "equity": pd.Series(rng.normal(0.0002, 0.01, size=800), index=dates),
        "crypto": pd.Series(
            rng.normal(0.0004, 0.02, size=800),
            index=dates[100:] + _dates(100, dates[-1] + dt.timedelta(days=1)),
        ),
    }
    book = 0.5 * sleeves["equity"] + 0.5 * sleeves["crypto"].reindex(dates).fillna(0.0)
    evidence = diversification_evidence(candidate, sleeves, book=book)
    assert evidence["status"] == "REPORTED"
    assert evidence["observations"] == 700  # the common window, latest first to earliest last
    assert set(evidence["report"]["pairwise_correlations"]) == {"equity", "crypto"}
    short = diversification_evidence(candidate.iloc[:30], sleeves, book=book)
    assert short["status"] == "COMMON_WINDOW_TOO_SHORT"
