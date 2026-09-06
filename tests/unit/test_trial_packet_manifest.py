from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build_trial_packet_manifest.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_trial_packet_manifest_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.workspace_evidence
def test_manifest_enumerates_every_union_identity_without_claiming_false_completion() -> None:
    module = _module()
    manifest = module.build_manifest()
    identities = manifest["identities"]
    keys = [item["hypothesis_key"] for item in identities]

    assert len(identities) == len(set(keys)) == 228
    assert manifest["summary"]["distinct_hypothesis_identities"] == len(identities)
    assert manifest["summary"]["distinct_research_families"] == len(manifest["research_families"])
    assert sum(
        family["distinct_hypothesis_identities"] for family in manifest["research_families"]
    ) == len(identities)
    assert all(item["research_family_key"] for item in identities)
    assert manifest["summary"]["complete_trial_packets"] == 2
    assert manifest["summary"]["incomplete_trial_packets"] == len(identities) - 2
    assert manifest["summary"]["coverage_status"] == "INCOMPLETE_BACKFILL_REQUIRED"
    assert manifest["summary"]["published_identity_packets"] == len(identities)
    assert manifest["summary"]["audited_not_currently_completable"] == 221
    assert manifest["summary"]["audited_exact_replay_candidates"] == 0
    assert manifest["summary"]["audited_exact_replays_failed_data_quality"] == 4
    assert manifest["summary"]["audited_exact_replays_failed_reproduction"] == 0
    assert manifest["summary"]["audited_corrected_reproductions_kill_preserved"] == 1
    assert manifest["summary"]["incomplete_not_yet_audited"] == 0
    assert all(item["verified_packet_path"] for item in identities)
    assert all(item["identity_packet_content_hash"].startswith("sha256:") for item in identities)
    alphamax = [
        item for item in identities if item["research_family_key"] == "alphamax_equity_momentum"
    ]
    assert len(alphamax) == 115
    assert all(item["candidate_match_is_verified"] is True for item in alphamax)
    assert all(
        item["coverage_status"] == "VERIFIED_INCOMPLETE_IDENTITY_PACKET" for item in alphamax
    )
    assert all(item["verified_sections"] for item in alphamax)
    assert all("preregistration_and_hashes" in item["missing_sections"] for item in alphamax)
    crypto_carry = [item for item in identities if item["research_family_key"] == "crypto_carry"]
    assert len(crypto_carry) == 25
    assert all(item["candidate_match_is_verified"] is True for item in crypto_carry)
    assert all(
        item["coverage_status"] == "VERIFIED_INCOMPLETE_IDENTITY_PACKET" for item in crypto_carry
    )
    assert all(
        item["verified_family_paper_path"] == "/research/crypto-carry-lineage.md"
        for item in crypto_carry
    )
    assert all("preregistration_and_hashes" in item["missing_sections"] for item in crypto_carry)
    crypto_momentum = [
        item for item in identities if item["research_family_key"] == "crypto_momentum"
    ]
    assert len(crypto_momentum) == 18
    assert all(item["candidate_match_is_verified"] is True for item in crypto_momentum)
    assert all(
        item["verified_family_paper_path"] == "/research/crypto-momentum-lineage.md"
        for item in crypto_momentum
    )
    assert all(
        item["coverage_status"] == "VERIFIED_INCOMPLETE_IDENTITY_PACKET" for item in crypto_momentum
    )
    crypto_multifactor = [
        item for item in identities if item["research_family_key"] == "crypto_multifactor_engine"
    ]
    assert len(crypto_multifactor) == 7
    assert all(item["label"] != "unlabelled_identity" for item in crypto_multifactor)
    assert all(item["candidate_match_is_verified"] is True for item in crypto_multifactor)
    assert all(
        item["verified_family_paper_path"] == "/research/crypto-multifactor-engine-lineage.md"
        for item in crypto_multifactor
    )
    crypto_vrp = [
        item
        for item in identities
        if item["research_family_key"] == "crypto_volatility_risk_premium"
    ]
    assert len(crypto_vrp) == 1
    assert crypto_vrp[0]["candidate_match_is_verified"] is True
    assert crypto_vrp[0]["verified_family_paper_path"] == "/research/crypto-vrp-lineage.md"
    narrative = [
        item for item in identities if item["research_family_key"] == "equity_narrative_change"
    ]
    assert len(narrative) == 1
    assert narrative[0]["candidate_match_is_verified"] is True
    assert narrative[0]["coverage_status"] == "COMPLETE"
    assert narrative[0]["missing_sections"] == []
    energy = [item for item in identities if item["research_family_key"] == "energy_inventory"]
    assert len(energy) == 1
    assert energy[0]["coverage_status"] == "COMPLETE"
    assert energy[0]["identity_packet_status"] == "COMPLETE_EVIDENCED_KILL"
    assert energy[0]["missing_sections"] == []
    carry_selected = next(
        item for item in identities if item["hypothesis_key"] == "6d151a184bf3e743"
    )
    assert (
        carry_selected["completion_assessment"]["status"]
        == "AUDITED_NOT_CURRENTLY_COMPLETABLE"
    )
    assert (
        narrative[0]["verified_family_paper_path"] == "/research/equity-narrative-change-lineage.md"
    )
    quality = [
        item for item in identities if item["research_family_key"] == "equity_fundamental_quality"
    ]
    value = [
        item
        for item in identities
        if item["research_family_key"] == "equity_fundamental_value_investment"
    ]
    assert len(quality) == 11 and len(value) == 13
    assert all(
        item["verified_family_paper_path"] == "/research/equity-quality-lineage.md"
        for item in quality
    )
    assert all(
        item["verified_family_paper_path"] == "/research/equity-value-investment-lineage.md"
        for item in value
    )
    alphatrend = [
        item for item in identities if item["research_family_key"] == "managed_futures_trend"
    ]
    assert len(alphatrend) == 21
    assert all(item["candidate_match_is_verified"] is True for item in alphatrend)
    assert all(
        item["verified_family_paper_path"] == "/research/alphatrend-managed-futures-lineage.md"
        for item in alphatrend
    )
    assert manifest["summary"]["identities_with_verified_family_papers"] == 228
    assert all(
        item["family_paper_binding_status"] == "VERIFIED_TAXONOMY_BINDING" for item in identities
    )


@pytest.mark.workspace_evidence
def test_published_manifest_is_byte_identical_across_hosts() -> None:
    hosts = (
        REPO.parent / "meridian" / "public" / "glassbox" / "trial_packet_manifest.json",
        REPO.parent / "meridian-app" / "public" / "glassbox" / "trial_packet_manifest.json",
    )
    assert all(path.exists() for path in hosts)
    assert hosts[0].read_bytes() == hosts[1].read_bytes()
    published = json.loads(hosts[0].read_text())
    assert published["schema"] == "canli.alphac-trial-packet-manifest.v2"
    assert published["source_provenance"]["public_hosts_byte_identical"] is True
