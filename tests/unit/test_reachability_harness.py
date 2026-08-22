"""The reachability harness must give the right verdict, and must be able to give a wrong one.

WHY IT EXISTS. Three families sat one gate from clearing feasibility, and all three turned out to
be unreachable by extraction. The tempting move in that situation is always the same — widen the
detector until the number clears — and it is tuning a measurement to agree with a target. The
harness asks the opposite question first, and it must be trustworthy enough to act on.

THE FAILURE MODE THIS FILE GUARDS. A verdict function that returns UNREACHABLE for everything
would reproduce all three published answers for two of them and look correct. So the tests below
exercise every branch with constructed cases, not just the registered families.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "reachability_harness", REPO / "scripts" / "reachability_harness.py"
)
assert _spec is not None and _spec.loader is not None
harness = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = harness
_spec.loader.exec_module(harness)


def _r(**kwargs):
    base = {
        "family": "test",
        "gate": "some_rate_gte_0_50",
        "threshold": 0.50,
        "measured_rate": 0.30,
        "ceiling_rate": 0.35,
        "ceiling_basis": "constructed",
    }
    base.update(kwargs)
    return harness.Reachability(**base)


def test_unreachable_when_a_perfect_detector_still_misses() -> None:
    assert _r(measured_rate=0.30, ceiling_rate=0.35).verdict == harness.UNREACHABLE


def test_reachable_when_a_perfect_detector_would_clear() -> None:
    """The ONLY verdict that justifies parser effort, so it must be reachable in the harness."""
    assert _r(measured_rate=0.30, ceiling_rate=0.60).verdict == harness.REACHABLE


def test_already_clears_is_not_reported_as_a_problem() -> None:
    assert _r(measured_rate=0.55, ceiling_rate=0.60).verdict == harness.CLEARS


def test_blended_when_a_stratum_clears_alone() -> None:
    answer = _r(
        measured_rate=0.30,
        ceiling_rate=0.30,
        strata={"a": (0.70, 100), "b": (0.20, 400)},
    )
    assert answer.verdict == harness.BLENDED


def test_a_single_stratum_is_not_a_blend() -> None:
    """One population cannot be a mixture of populations, however it is labelled."""
    answer = _r(measured_rate=0.30, ceiling_rate=0.35, strata={"only": (0.70, 100)})
    assert answer.verdict == harness.UNREACHABLE


def test_blended_carries_the_selection_warning() -> None:
    """A clearing subgroup is not permission to narrow the universe, and the artifact must say so.

    Selecting it after observing that it passes makes its rate in-sample for that decision, so it
    cannot be that decision's evidence. This is the single most likely way for the harness to be
    misused.
    """
    answer = _r(measured_rate=0.30, ceiling_rate=0.30, strata={"a": (0.70, 10), "b": (0.20, 90)})
    payload = answer.to_dict()
    assert payload["⚠️_if_blended"] is not None
    assert "in-sample" in payload["⚠️_if_blended"]
    assert payload["strata_clearing_alone"] == ["a"]


def test_every_verdict_has_a_meaning() -> None:
    for verdict in (harness.UNREACHABLE, harness.BLENDED, harness.REACHABLE, harness.CLEARS):
        assert verdict in harness._MEANING
        assert len(harness._MEANING[verdict]) > 40


def test_the_registered_families_reproduce_their_published_answers() -> None:
    """The harness generalises three hand-worked results; it must still agree with all three."""
    for name, probe in harness.REGISTRY.items():
        assert probe().verdict == harness.PUBLISHED_VERDICTS[name], (
            f"{name} no longer reproduces its published answer — the harness has drifted from "
            "the results it claims to generalise"
        )


def test_the_harness_refuses_to_run_on_a_drifted_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A check that cannot fail is worse than no check, so prove the drift guard bites."""
    monkeypatch.setitem(
        harness.PUBLISHED_VERDICTS, "merger_arbitrage", harness.REACHABLE
    )
    with pytest.raises(AssertionError, match="does not reproduce the published answers"):
        harness.main()


def test_headroom_is_signed_from_the_ceiling_not_the_measurement() -> None:
    """Headroom must say what a PERFECT detector could add, not what this one did.

    Measuring it from the observed rate would make every failing gate look closeable by parser
    work, which is the exact error the harness exists to prevent.
    """
    answer = _r(measured_rate=0.10, ceiling_rate=0.35, threshold=0.50)
    assert answer.headroom == pytest.approx(0.35 - 0.50)
