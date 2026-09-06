from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build_external_reviewer_packets.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("external_reviewer_packets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flagship_packets_are_hash_bound_and_claim_zero_review(tmp_path: Path) -> None:
    module = _module()
    document = module.generate(tmp_path / "reviewer_packets")

    assert document["status"] == "PASS_PREPARATION_ONLY_ZERO_REVIEWERS_ZERO_REVIEWS"
    assert document["flagship_packets"] == 5
    assert document["review_roles"] == 10
    assert document["assigned_reviewers"] == 0
    assert document["completed_reviews"] == 0
    assert document["outreach_authorized"] is False
    assert document["content_hash"] == module._content_hash(document)
    assert {record["registry_key"] for record in document["records"]} == {
        "alphavintage_macro_surprise",
        "alphaforge_crypto_carry",
        "alphamax_equity_momentum",
        "alphatrend_managed_futures",
        "crypto_multifactor_engine",
    }

    for record in document["records"]:
        packet_path = tmp_path / "reviewer_packets" / record["packet"]
        packet = json.loads(packet_path.read_text())
        assert packet["review_claimed"] is False
        assert packet["submission_claimed"] is False
        assert all(role["assigned"] is False for role in packet["requested_reviews"])
        assert all(role["reviewer_identity"] is None for role in packet["requested_reviews"])
        assert packet["content_hash"] == module._content_hash(packet)


def test_persisted_reviewer_packet_manifest_matches_current_sources() -> None:
    module = _module()
    persisted = json.loads(module.OUTPUT.read_text())
    assert persisted["content_hash"] == module._content_hash(persisted)
    assert persisted["assigned_reviewers"] == 0
    assert persisted["completed_reviews"] == 0
