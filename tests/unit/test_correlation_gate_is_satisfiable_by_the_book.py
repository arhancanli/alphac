"""The correlation-observation gate must be satisfiable by the book that has to satisfy it.

A candidate's own sample length is the candidate's to supply. The correlation window is not: it is
the INTERSECTION of the candidate and the book, so a threshold on it is really a threshold on the
BOOK's common history. v6 briefly applied minimum_oos_observations (756) to both, which made
admission impossible for a reason no candidate could do anything about -- this book supplies 728
days on its blessed basis and 177 on its live-forward one, and neither can be extended by
re-running anything, because the blessed curves are frozen by disclosure protocol.

That is the fourth instance of one defect in a single day: a gate nobody can pass. This pins the
class shut for this gate by checking it against the measured book rather than against an opinion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
CONTRACT = REPO / "config" / "sleeve_admission_contract.json"
DRY_RUN = REPO / "artifacts" / "analysis" / "admission_dry_run" / "result.json"


def _thresholds() -> dict:
    return json.loads(CONTRACT.read_text())["thresholds"]


def test_the_two_observation_gates_are_separate() -> None:
    thresholds = _thresholds()
    assert "minimum_correlation_observations" in thresholds, (
        "the correlation window and the candidate's own sample must be separately gateable; "
        "one number for both makes the book's history a candidate's problem"
    )
    assert thresholds["minimum_correlation_observations"] <= thresholds[
        "minimum_oos_observations"
    ], "a correlation window cannot exceed the candidate's own sample, so neither may its floor"


def test_the_correlation_gate_is_satisfiable_by_the_measured_book() -> None:
    """Measured, not asserted: read the real common window the dry run found."""
    if not DRY_RUN.exists():
        pytest.skip("no admission dry run on disk; run scripts/analyze_admission_dry_run.py")
    measured = json.loads(DRY_RUN.read_text())
    window = measured["book_common_window_days"]
    floor = _thresholds()["minimum_correlation_observations"]

    assert floor <= window, (
        f"minimum_correlation_observations is {floor} but the book's measured common window is "
        f"{window} days, so no candidate can clear it however long its own record. The blessed "
        "curves are frozen and cannot be extended by re-running anything: lower the floor, or "
        "re-bless the evidence base on a longer window, but do not leave a gate standing that "
        "nothing can pass."
    )


def test_the_precision_gate_is_what_actually_protects_the_correlation() -> None:
    """Lowering the raw count is only defensible while the BOUND is still gated.

    At 504 observations a correlation carries a standard error near 0.045, larger than the 0.03
    effect the objective turns on. The count alone therefore cannot protect precision, and it is
    not asked to: average_pairwise_correlation_upper_95_max gates the bootstrap bound, which
    accounts for sample length directly.
    """
    thresholds = _thresholds()
    assert "average_pairwise_correlation_upper_95_max" in thresholds
    assert thresholds["average_pairwise_correlation_upper_95_max"] > thresholds[
        "candidate_average_correlation_to_existing_book_max"
    ], "an upper bound below the point-estimate gate would be unsatisfiable by construction"
