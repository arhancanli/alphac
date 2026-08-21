"""The screen must cover the atlas by derivation, and must rule on arithmetic before opinion.

WHY IT EXISTS. Two things make this screen worth acting on and both can rot silently. The first is
that its family list is DERIVED from the atlas rather than typed: a family added to the atlas has
to appear here and fail, or the screen would quietly stop covering the thing it claims to cover.
The second is that the contract's history minimum is read from the contract in force, so a
threshold change reaches the verdicts by the same path it reaches admission.

The tests below break each of those and watch the screen fail.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "atlas_reachability_screen", REPO / "scripts" / "atlas_reachability_screen.py"
)
assert _spec is not None and _spec.loader is not None
screen = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = screen
_spec.loader.exec_module(screen)


def test_the_screen_covers_exactly_the_untouched_atlas_families() -> None:
    atlas = json.loads(screen.ATLAS.read_text())
    assert sorted(s.family for s in screen.SCREENS) == screen._untouched_families(atlas)


def test_a_family_added_to_the_atlas_fails_the_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of deriving the list: new work cannot slip past unscreened."""
    atlas = json.loads(screen.ATLAS.read_text())
    atlas["families"].append(
        {
            "id": "a_family_nobody_screened",
            "lineage_classification": "NOVEL_ATLAS",
            "return_outcome": None,
        }
    )
    path = tmp_path / "atlas.json"
    path.write_text(json.dumps(atlas))
    monkeypatch.setattr(screen, "ATLAS", path)
    with pytest.raises(AssertionError, match="a_family_nobody_screened"):
        screen.main()


def test_a_family_that_opens_return_data_leaves_the_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The derivation must react in BOTH directions, or it is a list with extra steps."""
    atlas = json.loads(screen.ATLAS.read_text())
    for family in atlas["families"]:
        if family["id"] == "municipal_taxable_basis":
            family["return_outcome"] = {"return_data_opened": True}
    path = tmp_path / "atlas.json"
    path.write_text(json.dumps(atlas))
    monkeypatch.setattr(screen, "ATLAS", path)
    with pytest.raises(AssertionError, match="screened but not untouched"):
        screen.main()


def test_the_history_minimum_comes_from_the_contract_in_force() -> None:
    contract = json.loads(screen.CONTRACT.read_text())
    expected = contract["thresholds"]["minimum_oos_observations"] / screen.TRADING_DAYS_PER_YEAR
    result = json.loads(screen.OUTPUT.read_text())
    assert result["contract"]["minimum_history_years"] == pytest.approx(round(expected, 2))


def test_a_short_history_outranks_the_obtainability_class() -> None:
    """A source we hold with two years of history is held and useless, and must not read as held.

    This is the ordering the screen turns on. Reporting `OBTAINABLE_FROM_DATA_THIS_REPO_ALREADY
    _HOLDS` for a source that cannot supply an admissible sleeve would be true and would send the
    next iteration to work on it.
    """
    held_but_short = screen.Screen(
        family="x",
        required_record="r",
        source="s",
        status=screen.HELD,
        reason="r",
        documented_history_years=2.0,
        documented_history_basis="constructed",
    )
    verdict, arithmetic = screen._verdict(held_but_short, {}, 3.0)
    assert verdict == screen.SHORT
    assert arithmetic["meets_contract_history"] is False

    held_and_long = screen.Screen(
        family="x",
        required_record="r",
        source="s",
        status=screen.HELD,
        reason="r",
        documented_history_years=4.0,
        documented_history_basis="constructed",
    )
    assert screen._verdict(held_and_long, {}, 3.0)[0] == screen.HELD


def test_a_short_history_does_not_rescue_a_vendor_or_marks_verdict() -> None:
    """Arithmetic sharpens an obtainable family; it must not relabel an unobtainable one.

    A vendor-blocked family with a short free proxy is still vendor-blocked. Letting the length
    test overwrite it would report the cheaper blocker and hide the real one.
    """
    for status in (screen.VENDOR, screen.MARKS, screen.NO_PIT):
        s = screen.Screen(
            family="x",
            required_record="r",
            source="s",
            status=status,
            reason="r",
            documented_history_years=0.5,
            documented_history_basis="constructed",
        )
        assert screen._verdict(s, {}, 3.0)[0] == status


def test_every_unverified_row_names_the_check_that_would_settle_it() -> None:
    """A judgement with no route to verification is an opinion wearing a schema."""
    result = json.loads(screen.OUTPUT.read_text())
    unverified = [
        r
        for r in result["families"]
        if r["obtainability_evidence_status"] == "JUDGEMENT_NOT_VERIFIED_THIS_RUN"
        and not r["how_to_verify"]
        and not r["related_artifact"]
    ]
    assert unverified == [], f"unverified with no check named: {[r['family'] for r in unverified]}"


def test_no_row_claims_measurement_it_did_not_make() -> None:
    """A MEASURED stamp must correspond to a source this run actually re-derived from the lake."""
    result = json.loads(screen.OUTPUT.read_text())
    held = set(result["sources_held"])
    for row in result["families"]:
        if row["obtainability_evidence_status"] == "MEASURED_FROM_THIS_REPO":
            assert row["history_basis"] is not None, row["family"]
            assert row["history_basis"].startswith("MEASURED from ") or any(
                name in str(row["history_basis"]) for name in held
            ), row["family"]


def test_a_source_that_is_not_there_measures_as_absent_rather_than_as_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty lake must drop the source, not report a span of nothing as a span."""
    monkeypatch.setattr(screen, "REPO", tmp_path)
    assert screen._measure_funding() is None
    assert screen._measure_short_interest() is None
    assert screen._measure_deribit() is None
    assert screen._measure_edgar() is None
    assert screen.SOURCES["fred_breakeven_10y"]() is None


def test_every_verdict_is_ranked_and_explained() -> None:
    for verdict in screen.RANK:
        assert verdict in screen.MEANING
        assert len(screen.MEANING[verdict]) > 60
    assert set(screen.RANK) == set(screen.MEANING)
    assert len(screen.RANK) == len(set(screen.RANK))


def test_the_published_headline_counts_what_it_says_it_counts() -> None:
    """The headline splits engineering-blocked from the rest; the split must match the rows."""
    result = json.loads(screen.OUTPUT.read_text())
    engineering = {screen.HELD, screen.PUBLIC, screen.EXTRACTION}
    n = sum(1 for r in result["families"] if r["verdict"] in engineering)
    assert result["headline"].startswith(f"{n} of {len(result['families'])} ")
