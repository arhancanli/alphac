"""The trial-reasoning dataset carries our own trials with honest rights tiers and never guesses."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "trial_reasoning_dataset_under_test", ROOT / "scripts" / "build_trial_reasoning_dataset.py"
)
assert _SPEC and _SPEC.loader
DATASET = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(DATASET)


def test_rights_tier_is_commercial_only_when_every_source_is_public_reuse() -> None:
    assert DATASET.rights_tier(["SEC_PUBLIC_DATA_AND_FILINGS"]) == "COMMERCIAL_CANDIDATE"
    assert DATASET.rights_tier(["SEC_PUBLIC_DATA_AND_FILINGS", "EIA_PUBLIC_DATA"]) == (
        "COMMERCIAL_CANDIDATE"
    )
    assert DATASET.rights_tier(["SEC_PUBLIC_DATA_AND_FILINGS", "NASDAQ_SHARADAR"]) == (
        "FREE_RESULTS_ONLY"
    )
    assert DATASET.rights_tier([]) == "UNMAPPED"
    assert DATASET.rights_tier(None) == "UNMAPPED"


def test_family_sources_join_the_rights_audit_to_trial_families_by_sleeve() -> None:
    audit = {
        "records": [
            {"registry_key": "alphatrend", "source_dependencies": [{"source_key": "YAHOO"}]},
            {"registry_key": "orphan", "source_dependencies": [{"source_key": "SEC"}]},
        ]
    }
    evidence = {"sleeves": {"alphatrend": {"trial_family_key": "managed_futures_trend"}}}
    assert DATASET.family_sources(audit, evidence) == {"managed_futures_trend": ["YAHOO"]}


def _packet(key: str, family: str = "managed_futures_trend") -> dict:
    return {
        "schema": "canli.alphac-identity-trial-packet.v2",
        "hypothesis_key": key,
        "research_family_key": family,
        "label": None,
        "packet_status": "COMPLETE_ACCOUNTING_FINAL_KILLED_NOT_ADMITTED",
        "complete": True,
        "configuration": {"allocator": "rank"},
        "immutable_first_measurement": {"annualized_sharpe": -0.2, "observations": 900},
        "required_sections": {"preregistration_and_hashes": {"status": "VERIFIED"}},
        "missing_sections": [],
        "content_hash": "sha256:" + "0" * 64,
    }


def test_a_record_carries_the_sealed_verdict_and_the_preregistration_only_at_its_hash(
    tmp_path: Path,
) -> None:
    prereg = {"hypothesis": "trend survives costs", "gates": ["net_sharpe >= 0.15"]}
    raw = json.dumps(prereg).encode()
    (tmp_path / "study").mkdir()
    (tmp_path / "study" / "preregistration.json").write_bytes(raw)
    closure = {
        "schema": "canli.alphac-development-trial-admission-closure.v1",
        "decision": {
            "disposition": "KILL",
            "admitted": False,
            "external_disposition": "REJECT_UNDER_FROZEN_SCENARIO",
            "statement": "Development rule failed.",
        },
        "lineage": {
            "decision_evidence": [
                {"path": "study/preregistration.json", "sha256": hashlib.sha256(raw).hexdigest()}
            ]
        },
    }
    record = DATASET.build_record(_packet("aaaa"), closure, ["YAHOO"], tmp_path)
    assert record["decision"]["disposition"] == "KILL"
    assert record["decision"]["statement"] == "Development rule failed."
    assert record["preregistration"]["document"] == prereg
    assert record["rights_tier"] == "FREE_RESULTS_ONLY"
    assert record["content_hash"] == DATASET._content_hash(record)

    (tmp_path / "study" / "preregistration.json").write_bytes(raw + b" ")
    moved = DATASET.build_record(_packet("aaaa"), closure, ["YAHOO"], tmp_path)
    assert moved["preregistration"] is None  # a file that moved since sealing is cited, never used


def test_a_narrative_closure_keeps_every_failed_gate_and_no_closure_means_no_verdict() -> None:
    closure = {
        "schema": "canli.alphac-narrative-change-admission-closure.v1",
        "decision": {"disposition": "KILL", "checks_evaluated": 86, "failures": ["a:1", "b:2"]},
        "headline": {"net_sharpe": -0.34},
    }
    record = DATASET.build_record(_packet("bbbb"), closure, None)
    assert record["decision"]["failed_gates"] == ["a:1", "b:2"]
    assert record["decision"]["headline"] == {"net_sharpe": -0.34}
    assert record["rights_tier"] == "UNMAPPED"
    assert DATASET.build_record(_packet("cccc"), None, ["YAHOO"])["decision"] is None
