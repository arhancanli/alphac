"""Every guard over a published claim must have a mutation registered against it.

WHY THIS IS A SEPARATE, CHEAP TEST. Running the mutation ledger takes twenty pytest invocations,
which is right for a deliberate run and wrong for every commit. But the property that rots between
runs is not the RESULT — it is the COVERAGE: somebody adds a guard, it joins the unmutated
majority, and nothing says so until the next deliberate run months later. That check costs
milliseconds, so it belongs in the suite.

The rule is applied to the tests directory rather than to a list, so the answer to "is every guard
covered" is computed, not maintained.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "mutation_ledger", REPO / "scripts" / "mutation_ledger.py"
)
assert _spec is not None and _spec.loader is not None
ledger = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ledger
_spec.loader.exec_module(ledger)


def test_every_guard_over_a_published_claim_has_a_mutation() -> None:
    guards = set(ledger.discover_guards())
    mutated = {m.guard for m in ledger.MUTATIONS}
    missing = sorted(guards - mutated)
    assert missing == [], (
        f"these guards have never been proven able to fail: {missing}. Register a mutation in "
        "scripts/mutation_ledger.py — a check that cannot fail is worse than no check, and this "
        "repository has shipped that failure repeatedly."
    )


def test_no_mutation_targets_a_test_that_does_not_exist() -> None:
    guards = set(ledger.discover_guards())
    stale = sorted({m.guard for m in ledger.MUTATIONS} - guards)
    assert stale == [], f"mutations registered against tests that are gone: {stale}"


def test_the_discovery_rule_finds_something() -> None:
    """A rule that matched nothing would make the coverage check pass with zero guards covered."""
    assert len(ledger.discover_guards()) >= 15


def test_the_harness_declares_a_negative_control() -> None:
    """Without one, a runner that failed for unrelated reasons would report a perfect score.

    A mutation harness reporting CAUGHT for everything looks strongest exactly when it is broken,
    so at least one registered mutation must change no behaviour and be expected to survive.
    """
    controls = [m for m in ledger.MUTATIONS if m.expect == "SURVIVED"]
    assert controls, "the mutation ledger has no negative control"


def test_every_mutation_names_a_target_that_exists() -> None:
    missing = sorted(str(m.target) for m in ledger.MUTATIONS if not m.target.exists())
    assert missing == [], f"mutations aimed at files that are not there: {missing}"
