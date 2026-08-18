"""Deflation must penalise SEARCH, not operations.

`cross_config_dsr` called `log.n_trials()` — the raw ROW count — while its own docstring called the
result the "HONEST distinct-trial count". It is not. The live tick re-runs the SAME hypothesis every
day on one more day of data; the window keys shift, the config hash changes, and a row is appended.
Measured 2026-08-08: 50 of 135 rows in var/experiments.jsonl are `eq_mom_252_21` re-measuring
AlphaMax, and across the union it is 185 rows for 133 distinct hypotheses.

Multiple-testing correction exists to penalise how many distinct ideas were tried before one was
picked. Re-measuring today's book on today's data is not a new idea. Counting it pushed SR* from
1.1776 to 1.2272 — a bar ~4% too high, applied to every candidate, for no research reason.

`n_hypotheses()` already excluded window-only variation. It simply was not the function being
called. These tests pin that it is.
"""

from __future__ import annotations

from pathlib import Path

from alphaforge.analytics.grand_matrix import cross_config_dsr
from alphaforge.validation.experiments import ExperimentLog

_BASE = {"allocator": "rank", "alpha_names": ["eq_mom_252_21"], "rebalance_bars": 63}
NOW = 1_780_000_000_000


def _daily_reruns(path: Path, days: int) -> ExperimentLog:
    """The live tick's behaviour: one hypothesis, a window that slides by a day each run."""
    log = ExperimentLog(path)
    for i in range(days):
        log.record(
            {**_BASE, "start": 946684800000, "end": 1780272000000 + i * 86_400_000},
            sharpe_ann=0.1 + 0.01 * i, sharpe_per_period=0.006, n_obs=175 + i,
            skew=0.0, kurtosis=3.0, now_ms=NOW + i * 86_400_000,
        )
    return log


def test_daily_reruns_append_rows_but_are_one_hypothesis(tmp_path: Path) -> None:
    """The premise. If this fails, the ledger stopped recording per-tick and the rest is moot."""
    log = _daily_reruns(tmp_path / "e.jsonl", 30)
    assert log.n_trials() == 30, "each daily re-run should append a row"
    assert log.n_hypotheses() == 1, "…but they are all the SAME idea, re-measured"


def test_deflation_counts_hypotheses_not_rows(tmp_path: Path) -> None:
    """THE TEST THIS FILE EXISTS FOR."""
    log = _daily_reruns(tmp_path / "e.jsonl", 30)
    ctx = cross_config_dsr(log)
    assert ctx.n_trials == log.n_hypotheses() == 1, (
        f"deflation used {ctx.n_trials} — it is counting rows, so a sleeve that merely keeps "
        "running raises the bar for every other sleeve in the book"
    )
    assert ctx.n_trials != 30


def test_genuinely_distinct_ideas_still_count(tmp_path: Path) -> None:
    """The guard must not become an excuse. Different ideas are different trials."""
    log = ExperimentLog(tmp_path / "e.jsonl")
    for i, alpha in enumerate(["eq_mom_252_21", "eq_accruals", "eq_net_issuance"]):
        log.record(
            {**_BASE, "alpha_names": [alpha], "start": 946684800000, "end": 1780272000000},
            sharpe_ann=0.2, sharpe_per_period=0.01, n_obs=175, skew=0.0, kurtosis=3.0,
            now_ms=NOW + i,
        )
    assert log.n_hypotheses() == 3
    assert cross_config_dsr(log).n_trials == 3


def test_a_changed_parameter_is_a_new_hypothesis(tmp_path: Path) -> None:
    """Sliding a window is operations; changing a knob is a search step."""
    log = ExperimentLog(tmp_path / "e.jsonl")
    for i, rb in enumerate((63, 21)):
        log.record(
            {**_BASE, "rebalance_bars": rb, "start": 946684800000, "end": 1780272000000},
            sharpe_ann=0.2, sharpe_per_period=0.01, n_obs=175, skew=0.0, kurtosis=3.0,
            now_ms=NOW + i,
        )
    assert log.n_hypotheses() == 2, "re-tuning the rebalance cadence IS a new trial"
