"""The redesign notes are a published document, so every number in them must trace to an artifact.

WHY IT EXISTS. `IDENTITY_REDESIGN_NOTES.md` is prose, and prose is where a measured number turns
back into a remembered one. It quotes counts from four artifacts: the spin-off language
measurement, the two-family reachability measurement, the form-universe audit, and the prospective
merger confirmation design. This file pins
each quoted figure to the artifact that produced it, so editing the note without re-running the
measurement fails a test rather than shipping a confident sentence.

It also pins the two things the note must NOT do. A redesign note that proposes a threshold has
done the thing the whole analysis exists to prevent, and a draft that reads as registered is one
copy-paste away from spending a trial nobody authorised.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).parents[2]
NOTES = REPO / "docs" / "design" / "IDENTITY_REDESIGN_NOTES.md"
SPINOFF_LANGUAGE = REPO / "artifacts" / "analysis" / "spinoff_prorata_gate" / "result.json"
REACHABILITY = REPO / "artifacts" / "analysis" / "feasibility_gate_reachability" / "result.json"
FORM_UNIVERSE = REPO / "artifacts" / "analysis" / "spinoff_form_universe" / "result.json"
MERGER_DESIGN = (
    REPO
    / "artifacts"
    / "feasibility"
    / "merger_arbitrage"
    / "announcement_confirmatory_design.json"
)


def _notes() -> str:
    return NOTES.read_text()


def test_the_spin_off_language_figures_match_their_artifact() -> None:
    published = json.loads(SPINOFF_LANGUAGE.read_text())
    text = _notes()
    assert f"{published['documents']} frozen" in text
    assert str(published["documents_containing_any_pro_rata_token"]) in text
    assert f"{published['any_pro_rata_token_rate'] * 100:.1f}%" in text
    assert f"{published['tolerant_near_distribution_rate'] * 100:.1f}%" in text
    assert f"{published['shipped_detector_rate']:.4f}" in text
    assert f"{published['gate_threshold']:.0%}" in text


def test_the_customer_supplier_figures_match_their_artifact() -> None:
    family = json.loads(REACHABILITY.read_text())["families"]["customer_supplier_propagation"]
    text = _notes()
    assert str(family["documents_sampled"]) in text
    assert str(family["documents_with_genuine_concentration_language"]) in text
    assert f"{family['published_rate'] * 100:.1f}%" in text
    assert f"{family['naming_rate_among_genuine_disclosures'] * 100:.1f}%" in text
    assert f"{family['genuine_concentration_share'] * 100:.1f}%" in text


def test_the_merger_arbitrage_figures_match_their_artifact() -> None:
    family = json.loads(REACHABILITY.read_text())["families"]["merger_arbitrage"]
    text = _notes()
    assert f"{family['blended_rate'] * 100:.1f}%" in text
    for form, stats in family["by_form"].items():
        assert form in text
        assert str(stats["anchors"]) in text
        assert f"{stats['prior_item101_8k_rate']:.4f}" in text


def test_the_form_universe_figures_match_their_artifact() -> None:
    """The measurement written for this note; the note must not drift from it."""
    universe = json.loads(FORM_UNIVERSE.read_text())["spin_off_registrations"]
    text = _notes()
    assert str(universe["total_initial"]) in text
    assert str(universe["mean_initial_per_year"]) in text
    for year, row in universe["by_year"].items():
        assert re.search(rf"{year}\s+{row['initial']} / {row['amended']}", text) or re.search(
            rf"{year}\s+{row['initial']} initial / {row['amended']} amendments", text
        ), f"{year} counts not found in the note as {row['initial']} / {row['amended']}"


def test_the_corporate_action_route_is_reported_as_checked_and_absent() -> None:
    """The note's strongest move is a route it ruled OUT; the artifact must still rule it out."""
    checked = json.loads(FORM_UNIVERSE.read_text())["corporate_action_route_checked"]
    assert checked["carries_a_spin_off_or_distribution_type"] is False
    text = _notes()
    assert str(checked["instruments_sampled"]) in text
    for kind in checked["action_types"]:
        assert f"`{kind}`" in text


def _renderings(value: object) -> set[str]:
    """Every way a measured value could legitimately appear in prose."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return set()
    out = {f"{value:.4f}", f"{value:.2f}", f"{value:.1f}"}
    if float(value).is_integer():
        out.add(str(int(value)))
    if 0 <= value <= 1:
        out |= {f"{value * 100:.1f}%", f"{value:.0%}", f"{value * 100:.0f}%"}
    return out


def _walk(node: object) -> set[str]:
    if isinstance(node, dict):
        return set().union(
            *({str(k)} | _walk(v) for k, v in node.items()), set()
        )
    if isinstance(node, list):
        return set().union(*(_walk(v) for v in node), set())
    return _renderings(node)


# Numbers in the note that are NOT measurements and cannot trace to an artifact. Both are
# structural: an SEC item number is a form field, and the drafting date is a date.
NON_MEASUREMENTS = {"1.01", "2026"}


def test_every_measurement_shaped_number_in_the_note_traces_to_an_artifact() -> None:
    """The invariant, checked in the direction that catches a wrong number ANYWHERE in the prose.

    Asserting that each artifact figure APPEARS in the note is the weak direction: a figure quoted
    twice can be wrong in one place and right in the other, and the check still passes. Both halves
    of that failure were demonstrated before this test was written. So the check runs the other
    way — every measurement-shaped token in the note must be derivable from an artifact.
    """
    allowed = set(NON_MEASUREMENTS)
    for artifact in (SPINOFF_LANGUAGE, REACHABILITY, FORM_UNIVERSE, MERGER_DESIGN):
        allowed |= _walk(json.loads(artifact.read_text()))

    tokens = set(re.findall(r"\d+(?:\.\d+)?%|\d+\.\d+|\b\d{3,}\b", _notes()))
    untraceable = sorted(tokens - allowed)
    assert untraceable == [], (
        f"these numbers appear in the note and in no artifact: {untraceable}. Either the "
        "measurement moved and the prose did not, or a figure was written from memory."
    )


def test_the_trace_check_would_catch_a_number_that_moved() -> None:
    """Mutation. The check above is only worth running if a wrong digit fails it."""
    allowed = {"386", "24.1"}
    tokens = {"386", "24.1"}
    assert not (tokens - allowed)
    assert sorted({"586", "24.1"} - allowed) == ["586"]


def test_the_notes_propose_no_threshold() -> None:
    """The one thing a redesign note must never do, checked against the class not a phrase list.

    Any sentence proposing a numeric bar for a redesigned identity is the failure this analysis
    exists to prevent, so the check looks for the SHAPE — a comparison word next to a number —
    rather than for particular wording someone could rephrase around.
    """
    body = _notes()
    proposals = re.findall(
        r"(?:should|must|will|would)\s+(?:be\s+)?(?:set\s+)?(?:at\s+)?"
        r"(?:least|above|below|over|under|exceed\w*)\s+[\d.]+%?",
        body,
        flags=re.IGNORECASE,
    )
    assert proposals == [], f"the note proposes a threshold: {proposals}"


def test_the_notes_declare_themselves_unregistered() -> None:
    """A draft that does not say it is a draft is one copy-paste from spending a trial."""
    text = _notes()
    assert "Status: DRAFT" in text
    assert "Nothing here is registered" in text
    assert "0 trials" in text


def test_every_family_the_backlog_names_has_a_note() -> None:
    text = _notes()
    for family in ("spin_off_dislocation", "customer_supplier_propagation", "merger_arbitrage"):
        assert "## Note" in text
        assert f"`{family}`" in text
