"""Exactly two jobs may regenerate the published state, and both regenerate ALL of it.

``paper_trading_state.py`` writes ``data/paper/state.json``; a dozen artifacts downstream bind
that file's hash (``forward_evidence_maturity.json`` above all) and ``research_export.py``
refuses to build when a binding is stale. ``live_tick.sh`` and ``live_publish.sh`` run the whole
chain in its load-bearing order (pinned by ``test_publish_pipeline_order.py``).

2026-09-06: ``alphamax_tick.sh`` and ``mf_tick.sh`` each ALSO ran ``paper_trading_state.py`` on
its own, once a day, right after their broker cycle: "refresh published state now (the hourly
tick also does this)". Their own headers say the opposite ("It does NOT regenerate the published
state"), and ``alphavintage_tick.sh`` spells out why: "Doing either here would duplicate a job
that already has an owner." Each standalone run rewrote the state after the maturity artifact
had bound its hash, so every downstream freshness test was red until the next :25 tick, and the
nightly suite could not be green by construction. This test makes the header true.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"

PUBLISHERS = {"live_tick.sh", "live_publish.sh"}
PUBLISH_STEPS = (
    "paper_trading_state.py",
    "glassbox_export.py",
    "transparency_log.py",
    "evaluate_forward_evidence_maturity.py",
    "research_export.py",
)


def _body(script: Path) -> str:
    return "\n".join(
        ln for ln in script.read_text().splitlines() if not ln.lstrip().startswith("#")
    )


def test_only_the_two_publishers_run_a_publish_step() -> None:
    scripts = sorted(SCRIPTS.glob("*.sh"))
    assert len(scripts) >= 10, f"glob matched {len(scripts)} scripts; the loop below is vacuous"
    offenders = {
        script.name: [step for step in PUBLISH_STEPS if step in _body(script)]
        for script in scripts
        if script.name not in PUBLISHERS
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}, (
        f"these scripts regenerate published state outside the two publishers: {offenders}. "
        "The hourly tick already re-runs the whole chain in order; a standalone step leaves "
        "every downstream hash binding stale until the next :25."
    )


def test_both_publishers_really_are_publishers() -> None:
    """If the allowlist ever names a script that no longer publishes, the test above would be
    exempting nothing and proving nothing."""
    for name in sorted(PUBLISHERS):
        body = _body(SCRIPTS / name)
        assert all(step in body for step in PUBLISH_STEPS), (name, PUBLISH_STEPS)
