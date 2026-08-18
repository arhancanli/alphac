from __future__ import annotations

from pathlib import Path
from runpy import run_path

MODULE = run_path(str(Path(__file__).parents[2] / "scripts/build_sleeve_atlas.py"))
FAMILY_SPECS = MODULE["FAMILY_SPECS"]
build_atlas = MODULE["build_atlas"]


def test_atlas_is_broad_unique_and_family_accounted() -> None:
    atlas = build_atlas()
    cells = atlas["cells"]
    ids = [cell["id"] for cell in cells]

    assert len(FAMILY_SPECS) == 40
    assert len(cells) == 240
    assert len(ids) == len(set(ids))
    assert atlas["summary"]["asset_groups"] >= 12
    assert {cell["family_trial_account"] for cell in cells} == {
        family.id for family in FAMILY_SPECS
    }
    assert all(cell["family_trial_account"] == cell["family_id"] for cell in cells)


def test_atlas_is_fail_closed_before_returns() -> None:
    atlas = build_atlas()

    assert atlas["objective"]["target_total_sleeves"] == 14
    assert atlas["objective"]["minimum_new_sleeves"] == 10
    assert atlas["objective"]["targets_are_promises"] is False
    assert atlas["governance"]["family_wise_accounting"] is True
    assert atlas["governance"]["cell_is_independent_trial"] is False
    assert atlas["summary"]["return_data_opened"] == 0
    assert atlas["summary"]["return_hypotheses_spent"] == 0
    assert atlas["summary"]["family_return_data_opened"] == 1
    assert atlas["summary"]["family_return_hypotheses_spent"] == 1
    assert atlas["summary"]["lineage_classifications"] == {
        "ACTIVE_FEASIBILITY": 9,
        "DUPLICATE_OVERLAP": 7,
        "IDENTITY_REDESIGN_REQUIRED": 2,
        "NOVEL_ATLAS": 17,
        "RETIRED_KILLED": 5,
    }
    narrative = [
        cell for cell in atlas["cells"] if cell["family_id"] == "earnings_narrative_change"
    ]
    assert len(narrative) == 6
    assert all(cell["screen_state"] == "FAMILY_KILLED_EXACT_CELL_UNTESTED" for cell in narrative)
    assert not any(cell["return_data_opened"] for cell in atlas["cells"])
    assert not any(cell["return_hypotheses_spent"] for cell in atlas["cells"])


def test_historical_aliases_cannot_be_presented_as_novel() -> None:
    atlas = build_atlas()
    families = {family["id"]: family for family in atlas["families"]}

    assert families["closed_end_fund_discount"]["lineage_classification"] == "RETIRED_KILLED"
    assert families["closed_end_fund_discount"]["lineage_aliases"] == ["cef_discount"]
    assert families["closed_end_fund_discount"]["forward_experiment"]["status"] == "FORWARD_ONLY"
    assert families["short_interest_revision"]["lineage_aliases"] == ["equity_short_interest_dtc"]
    assert families["natural_gas_storage_weather"]["lineage_aliases"] == [
        "commodity_inventory_seasonal"
    ]
    assert (
        families["customer_supplier_propagation"]["lineage_classification"]
        == "ACTIVE_FEASIBILITY"
    )
    assert (
        families["bond_etf_nav_dislocation"]["lineage_classification"]
        == "ACTIVE_FEASIBILITY"
    )
    assert families["merger_arbitrage"]["lineage_classification"] == "ACTIVE_FEASIBILITY"
    assert families["tender_offer_spread"]["lineage_classification"] == "ACTIVE_FEASIBILITY"
    assert (
        families["active_ownership_escalation"]["lineage_classification"]
        == "ACTIVE_FEASIBILITY"
    )
    assert families["cftc_hedging_pressure"]["lineage_aliases"] == ["cot_positioning"]
    assert families["crypto_cross_venue_basis"]["lineage_classification"] == "RETIRED_KILLED"
    assert (
        families["treasury_auction_concession"]["lineage_classification"]
        == "IDENTITY_REDESIGN_REQUIRED"
    )
    assert (
        families["spin_off_dislocation"]["lineage_classification"]
        == "IDENTITY_REDESIGN_REQUIRED"
    )
    assert families["earnings_narrative_change"]["return_outcome"]["verdict"] == "KILL"


def test_registry_classifies_every_family_exactly_once() -> None:
    atlas = build_atlas()

    assert len(atlas["families"]) == 40
    assert all(family["lineage_classification"] for family in atlas["families"])
    assert len({family["id"] for family in atlas["families"]}) == 40


def test_every_family_declares_real_world_failure_surfaces() -> None:
    for family in FAMILY_SPECS:
        assert family.mechanism
        assert len(family.universes) == 2
        assert len(family.horizons) == 3
        assert family.point_in_time_data
        assert family.execution_model
        assert family.primary_friction
        assert family.overlap_guard
