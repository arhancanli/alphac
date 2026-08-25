from __future__ import annotations

import sys
from pathlib import Path
from runpy import run_path

SCRIPTS = Path(__file__).parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE = run_path(str(SCRIPTS / "audit_sleeve_atlas.py"))
audit_atlas = MODULE["audit_atlas"]


def test_audit_evaluates_every_cell_without_opening_returns() -> None:
    audit = audit_atlas()
    summary = audit["summary"]

    assert summary["cells_audited"] == 240
    assert summary["families_audited"] == 40
    assert summary["asset_groups_audited"] == 20
    assert summary["gate_evaluations"] == 2880
    assert summary["governance_rejections"] == 0
    assert summary["lineage_families"] == {
        "ACTIVE_FEASIBILITY": 10,
        "DUPLICATE_OVERLAP": 7,
        "IDENTITY_REDESIGN_REQUIRED": 2,
        "NOVEL_ATLAS": 16,
        "RETIRED_KILLED": 5,
    }
    assert summary["lineage_cells"] == {
        "ACTIVE_FEASIBILITY": 60,
        "DUPLICATE_OVERLAP": 42,
        "IDENTITY_REDESIGN_REQUIRED": 12,
        "NOVEL_ATLAS": 96,
        "RETIRED_KILLED": 30,
    }
    assert summary["retired_killed"] == 24
    assert summary["forward_only_monitoring"] == 6
    assert summary["overlap_review_required"] == 42
    assert summary["literature_review_required"] == 96
    assert summary["ready_for_key_free_feasibility"] == 60
    assert summary["identity_redesign_required"] == 12
    assert summary["return_data_opened"] == 0
    assert summary["return_hypotheses_spent"] == 0
    assert summary["family_return_data_opened"] == 1
    assert summary["family_return_hypotheses_spent"] == 1
    assert summary["new_sleeves_admitted"] == 0


def test_every_result_is_family_bound_and_fail_closed() -> None:
    audit = audit_atlas()

    assert len(audit["results"]) == 240
    assert all(result["structural_pass"] for result in audit["results"])
    assert all(result["gates"]["family_trial_account_bound"] for result in audit["results"])
    assert all(result["gates"]["returns_fail_closed"] for result in audit["results"])
    assert not any(result["return_data_opened"] for result in audit["results"])
    assert not any(result["return_hypotheses_spent"] for result in audit["results"])


def test_audit_hash_is_deterministic() -> None:
    assert audit_atlas()["content_hash"] == audit_atlas()["content_hash"]


def test_retired_and_forward_only_cells_fail_closed() -> None:
    audit = audit_atlas()
    by_family: dict[str, list[dict]] = {}
    for result in audit["results"]:
        by_family.setdefault(result["family_id"], []).append(result)

    assert {r["decision"] for r in by_family["closed_end_fund_discount"]} == {
        "FORWARD_ONLY_MONITORING"
    }
    assert not any(
        r["lineage_permits_feasibility"]
        for r in by_family["closed_end_fund_discount"]
    )
    assert {r["decision"] for r in by_family["short_interest_revision"]} == {
        "RETIRED_KILLED"
    }
    assert {r["decision"] for r in by_family["options_skew_carry"]} == {
        "OVERLAP_REVIEW_REQUIRED"
    }
