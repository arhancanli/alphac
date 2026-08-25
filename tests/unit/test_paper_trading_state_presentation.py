"""Regression: the published paper-state must LEAD WITH THE FLAGSHIP and carry the owed
evidence-base disclosure.

Why this test exists (2026-08-01). Two defects in the public record, both presentation-layer
but both misleading:

  1. ``scripts/paper_trading_state.py`` emitted ``algorithms[]`` in build order, so AlphaForge
     (the crypto carry sleeve — our SMALLEST-capacity sleeve at a ~$10M measured cliff, and
     venue-halted for 11 days in July) rendered FIRST and ALPHAC — the combined cross-asset
     book that is the product, and the book the published forward Sharpe actually describes —
     rendered LAST. The site renders that array top to bottom.
  2. The published evidence figures for the equity sleeve (net Sharpe 0.907 / DSR 0.341)
     describe a construction that re-measures LOWER on today's lake (0.818, DSR ~0.15 at the
     N=111 ledger) and is NOT the construction the live tick trades — and a matched-window
     head-to-head found the two statistically INDISTINGUISHABLE. That had to reach the record.

These tests pin the RUNNING path: the exact module objects ``main()`` emits — ``ALGOS`` becomes
``state["algorithms"]`` one-for-one (order preserved), ``transparency_entries()`` IS
``state["transparency"]``, and ``ALGO_BY_KEY`` is what the back-compat ``book.sleeves`` block
resolves descriptors through. No network, no DB, no disk writes. The last test additionally
validates the real emitted artifact when it is present on the box.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PTS_PATH = REPO / "scripts" / "paper_trading_state.py"
STATE_JSON = REPO / "data" / "paper" / "state.json"
ALPHATREND_SELECTED_ARTIFACT = (
    REPO / "artifacts" / "walkforward" / "managed_futures" / "walkforward.json"
)

# The sleeves that COMPOSE the flagship, addressed by key (never by list position).
# The sleeves that COMPOSE the flagship. AlphaVintage joined 2026-08-10 (WEIGHT_SCHEDULE entry
# at its own go-live, so the days before it existed still compound at thirds). Updating this
# tuple is how a composition change is meant to be noticed — the test failing on the day the
# book changed is the guard working, not a nuisance.
COMPOSITION_KEYS = ("alphaforge", "alphamax", "managed_futures", "alphavintage")


@pytest.fixture(scope="module")
def pts():
    spec = importlib.util.spec_from_file_location("paper_trading_state_under_test", PTS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------- ordering (fix A)


def test_flagship_alphac_is_first_and_is_the_only_flagship(pts):
    """ALPHAC leads. This is the whole point: the record is ABOUT the combined book."""
    assert pts.ALGOS[0]["key"] == "alphac"
    assert pts.ALGOS[0].get("flagship") is True
    flagged = [a["key"] for a in pts.ALGOS if a.get("flagship")]
    assert flagged == ["alphac"], f"exactly one flagship, and it must lead: {flagged}"


def test_alphaforge_no_longer_leads(pts):
    """The specific regression: the smallest-capacity, venue-fragile sleeve must not head the
    page just because it was built first."""
    assert pts.ALGOS[0]["key"] != "alphaforge"
    assert pts.ALGOS[-1]["key"] == "alphaforge"


def test_rank_matches_presentation_order(pts):
    """``rank`` and array order must agree, or a renderer that sorts by rank and a renderer that
    just iterates the array will disagree about what leads."""
    assert [a["rank"] for a in pts.ALGOS] == list(range(1, len(pts.ALGOS) + 1))
    assert len({a["rank"] for a in pts.ALGOS}) == len(pts.ALGOS), "ranks must be unique"


def test_every_algorithm_is_present_exactly_once(pts):
    keys = [a["key"] for a in pts.ALGOS]
    assert sorted(keys) == sorted(["alphac", *COMPOSITION_KEYS])
    assert len(keys) == len(set(keys))


def test_execution_provenance_is_structured_and_never_claims_real_money(pts):
    by_key = {algo["key"]: algo["execution"] for algo in pts.ALGOS}

    assert all(item["capital_kind"] == "PAPER_ONLY" for item in by_key.values())
    assert by_key["alphac"]["record_kind"] == "DERIVED_PAPER_BOOK"
    assert by_key["alphac"]["account_scope"] == "NO_DIRECT_BROKER_ACCOUNT"
    for key in ("alphamax", "managed_futures", "alphavintage"):
        assert by_key[key]["record_kind"] == "BROKER_EXECUTED_PAPER"
        assert by_key[key]["broker"] == "ALPACA"
        assert by_key[key]["external_attestation"] is False
    assert by_key["alphaforge"]["broker"] == "ALPHAFORGE_PAPERBROKER"
    assert by_key["alphaforge"]["record_kind"] == "LOCALLY_SIMULATED_PAPER_FILLS"


# ------------------------------------- descriptors resolve by key, never by position


def test_descriptors_are_addressed_by_key(pts):
    """``ALGO_BY_KEY`` is how the back-compat ``book.sleeves`` block reads descriptors. If a
    sleeve were addressed by list POSITION, this reorder would have silently re-labelled it
    (AlphaForge's crypto description printed under AlphaMax, etc.)."""
    for key in COMPOSITION_KEYS:
        assert pts.ALGO_BY_KEY[key]["key"] == key
    assert pts.ALGO_BY_KEY["alphaforge"]["desc"] != pts.ALGO_BY_KEY["alphamax"]["desc"]


def test_alphatrend_headline_and_family_rederivation_are_not_conflated(pts):
    """The card's selected artifact and the broader family re-derivation are different curves."""
    trend = pts.ALGO_BY_KEY["managed_futures"]
    selected = json.loads(ALPHATREND_SELECTED_ARTIFACT.read_text())["summary"]
    assert trend["standalone_sharpe"] == pytest.approx(selected["sharpe"], abs=0.005)
    assert "selected 5,133-day walk-forward artifact" in trend["desc"]
    assert f"Sharpe {selected['sharpe']:.4f}" in trend["desc"]
    assert "family-wide re-derivation has net Sharpe 0.25" in trend["desc"]
    assert "Both are historical simulations" in trend["desc"]
    assert "The 0.33 headline is the selected walk-forward artifact" in trend["caveat"]


def test_source_contains_no_positional_algos_indexing():
    """A hard guard on the bug class: ``ALGOS[0]`` style indexing is order-fragile and is what
    made the previous ordering load-bearing. Address the descriptors by key."""
    src = PTS_PATH.read_text()
    positional = re.findall(r"ALGOS\[\s*\d+\s*\]", src)
    assert positional == [], f"positional ALGOS indexing is order-fragile: {positional}"


# ------------------------------------------------- the owed disclosure (fix B)


def test_transparency_entries_are_non_empty_strings(pts):
    entries = pts.transparency_entries()
    assert entries and all(isinstance(e, str) and e.strip() for e in entries)


def test_evidence_base_disclosure_is_published(pts):
    """The dated entry must state ALL THREE facts, or it is a half-disclosure."""
    entry = next(
        (e for e in pts.transparency_entries() if e.startswith("DISCLOSURE 2026-08-01")), None
    )
    assert entry is not None, "the owed 2026-08-01 evidence-base disclosure is missing"

    # (1) the published figures re-measure lower on today's data
    for token in ("0.907", "0.341", "0.818", "N=111", "N=27"):
        assert token in entry, f"missing evidence figure {token!r}"

    # (2) the evidenced construction is NOT what trades
    assert "not what the live sleeve trades" in entry.lower() or "is NOT" in entry
    assert "2026-07-19" in entry, "must point at the dated recipe-drift disclosure"

    # (3) the head-to-head is a NULL, stated as a null in both directions
    assert "INDISTINGUISHABLE" in entry
    assert "never shown to be a downgrade" in entry
    assert "never shown to be an upgrade" in entry

    # the in-sample figure moved
    assert "1.46" in entry and "1.85" in entry


def test_disclosure_does_not_claim_the_live_construction_is_better(pts):
    """The honest line is 'indistinguishable'. A null must never be spun into a win — that is
    exactly how the stale 0.907 got published in the first place."""
    entry = next(e for e in pts.transparency_entries() if e.startswith("DISCLOSURE 2026-08-01"))
    lowered = entry.lower()
    for spin in ("the live construction is better", "an upgrade", "outperforms"):
        if spin in lowered:
            # the only permitted mentions are explicit NEGATIONS of the claim
            idx = lowered.index(spin)
            context = lowered[max(0, idx - 60) : idx + len(spin)]
            assert "never shown" in context or "not claiming" in context, (
                f"unqualified claim of superiority near: ...{context}"
            )


def test_presentation_change_is_itself_disclosed(pts):
    """The signed transparency chain hashes ``algorithms[]``; a verifier diffing seq N vs N+1
    sees the reorder. It gets a documented reason, not an unexplained reshuffle."""
    entry = next(
        (e for e in pts.transparency_entries() if e.startswith("PRESENTATION 2026-08-01")), None
    )
    assert entry is not None
    assert "ALPHAC now leads" in entry
    assert "No number, weight, cadence or metric changed" in entry


def test_older_disclosures_survive_append_only(pts):
    """Corrections are ADDED to the record, never swapped in over an older claim."""
    blob = "\n".join(pts.transparency_entries())
    for marker in (
        "CORRECTION 2026-07-05",
        "CORRECTION 2026-07-19",
        "OPEN INCIDENT 2026-07-20",
        "DISCLOSURE 2026-07-11",
        "GATE AUDIT 2026-07-12",
        "2026-06-29 RE-BASELINE",
    ):
        assert marker in blob, f"an existing disclosure was dropped: {marker}"


# ---------------------------------------------------- the real emitted artifact


@pytest.mark.skipif(
    not STATE_JSON.exists(),
    reason="data/paper/state.json is generated (gitignored); nothing to check",
)
def test_emitted_state_json_leads_with_the_flagship_and_carries_the_disclosure(pts):
    """End of the running path: the file the sites actually serve."""
    state = json.loads(STATE_JSON.read_text())
    algos = state["algorithms"]
    assert [a["key"] for a in algos] == [a["key"] for a in pts.ALGOS]
    assert algos[0]["key"] == "alphac" and algos[0]["flagship"] is True
    assert [a["rank"] for a in algos] == list(range(1, len(algos) + 1))

    # book.sleeves is the COMPOSITION list; its descriptors must match by key, not by position
    for sleeve in state["book"]["sleeves"]:
        assert sleeve["desc"] == pts.ALGO_BY_KEY[sleeve["key"]]["desc"]

    assert any(e.startswith("DISCLOSURE 2026-08-01") for e in state["transparency"])
    assert any(e.startswith("PRESENTATION 2026-08-01") for e in state["transparency"])
