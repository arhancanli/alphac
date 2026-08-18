from __future__ import annotations

from pathlib import Path
from runpy import run_path

MODULE = run_path(
    str(Path(__file__).parents[2] / "scripts" / "audit_sleeve_family_lineage.py")
)
audit_lineage = MODULE["audit_lineage"]


def fixtures() -> tuple[dict, dict, dict, dict]:
    registry = {
        "current_sleeves": [{"id": "alpha"}],
        "families": {
            "new": {
                "classification": "NOVEL_ATLAS",
                "aliases": [],
                "evidence": [],
            },
            "old": {
                "classification": "RETIRED_KILLED",
                "aliases": ["old_probe"],
                "evidence": ["public_kill_ledger#screen_stage_kills:old_probe"],
            },
            "active": {
                "classification": "ACTIVE_FEASIBILITY",
                "aliases": [],
                "evidence": ["config/sleeve_discovery.json#candidates:active"],
            },
        },
    }
    kill_log = {
        "killed_strategies": [],
        "screen_stage_kills": [{"name": "old_probe"}, {"name": "unrelated"}],
    }
    paper_state = {"book": {"sleeves": [{"key": "alpha"}]}}
    discovery = {"candidates": [{"id": "active"}]}
    return registry, kill_log, paper_state, discovery


def test_lineage_audit_matches_current_and_historical_ledgers() -> None:
    result = audit_lineage(*fixtures())

    assert result["summary"]["decision"] == "PASS"
    assert result["summary"]["current_book_exact_match"] is True
    assert result["summary"]["kill_identities_mapped_to_atlas"] == 1
    assert result["unmapped_kill_identities"] == ["unrelated"]
    assert result["summary"]["return_data_opened"] == 0
    assert result["summary"]["return_hypotheses_spent"] == 0


def test_missing_kill_alias_fails_closed() -> None:
    registry, kill_log, paper_state, discovery = fixtures()
    registry["families"]["old"]["aliases"] = ["invented_alias"]
    result = audit_lineage(registry, kill_log, paper_state, discovery)

    assert result["summary"]["decision"] == "FAIL_CLOSED"
    assert result["failed_families"] == ["old"]


def test_current_book_drift_fails_closed() -> None:
    registry, kill_log, paper_state, discovery = fixtures()
    paper_state["book"]["sleeves"].append({"key": "beta"})
    result = audit_lineage(registry, kill_log, paper_state, discovery)

    assert result["summary"]["decision"] == "FAIL_CLOSED"
    assert result["summary"]["current_book_exact_match"] is False


def test_novel_family_cannot_carry_a_hidden_historical_alias() -> None:
    registry, kill_log, paper_state, discovery = fixtures()
    registry["families"]["new"]["aliases"] = ["old_probe"]
    result = audit_lineage(registry, kill_log, paper_state, discovery)

    assert result["summary"]["decision"] == "FAIL_CLOSED"
    assert result["failed_families"] == ["new"]


def test_outside_queue_feasibility_review_reference_resolves() -> None:
    registry, kill_log, paper_state, discovery = fixtures()
    registry["families"]["active"]["evidence"] = [
        "config/sleeve_discovery.json#feasibility_reviews:active"
    ]
    discovery["candidates"] = []
    discovery["feasibility_reviews"] = [{"id": "active"}]

    result = audit_lineage(registry, kill_log, paper_state, discovery)

    assert result["summary"]["decision"] == "PASS"
    assert result["failed_families"] == []
