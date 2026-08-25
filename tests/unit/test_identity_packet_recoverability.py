from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts" / "audit_identity_packet_recoverability.py"
    spec = importlib.util.spec_from_file_location("identity_packet_recoverability_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_distinguishes_historical_evidence_debt_from_strategy_quality() -> None:
    payload = _module().build_audit()
    assert payload["summary"] == {
        "audited_identities": 226,
        "audited_currently_completable": 0,
        "audited_exact_replay_candidates": 0,
        "audited_exact_replays_failed_data_quality": 4,
        "audited_exact_replays_failed_reproduction": 0,
        "audited_corrected_reproductions_kill_preserved": 1,
        "failed_replays_with_support_evidence_complete": 4,
        "union_identities_after_aborted_replay": 228,
        "walkforward_artifacts_indexed": 579,
        "walkforward_corpus_hash": (
            "sha256:e78c7e69c30c05125d85d7d4f797e241cce9876476a7c4403d6db28489f2ee56"
        ),
        "systematic_recoverability_classes": {
            "AMBIGUOUS_EXACT_ARTIFACT_MATCHES": 12,
            "LEDGER_SUMMARY_ONLY_NO_ARTIFACT_MATCH": 17,
            "METRIC_MATCH_CONFIG_MISMATCH": 2,
            "UNIQUE_EXACT_ARTIFACT_BINDING": 37,
        },
    }
    identities = payload["identities"]
    deep_audit_identities = {
        "4eb98b8f5dad412c",
        "1d2924f28fe31a9a",
        "2d966892fb5db520",
        "6c08c11a04ef43c5",
        "6d151a184bf3e743",
        "7c522581b35475e3",
        "97dec5f23e5fcf27",
        "a238c1a5ecc5d1e3",
        "c6100630d688b4d7",
        "cb54117502489bf8",
        "d614fdc1daa2906c",
        "e5f48adc25065ce9",
        "e86109044ab18734",
    }
    assert len(identities) == 226
    assert deep_audit_identities.issubset(identities)
    assert sum(
        item["status"] == "AUDITED_NOT_CURRENTLY_COMPLETABLE"
        for item in identities.values()
    ) == 221
    assert identities["131745bc21f41d5f"]["family_audit"] == (
        "artifacts/research/crypto_momentum_family.json"
    )
    assert identities["131745bc21f41d5f"]["status"] == (
        "AUDITED_NOT_CURRENTLY_COMPLETABLE"
    )
    assert identities["0a85fa2eca9afeb8"]["forensic_reconciliation"] == (
        "artifacts/audit/trial_debt_reconciliation.json"
    )
    assert identities["0a85fa2eca9afeb8"]["evidence_grade"] == (
        "complete_walkforward_curve_and_config"
    )
    assert identities["e5f48adc25065ce9"]["status"] == (
        "AUDITED_CORRECTED_REPRODUCTION_KILL_PRESERVED"
    )
    failed_replays = {
        "1d2924f28fe31a9a",
        "2d966892fb5db520",
        "a238c1a5ecc5d1e3",
        "e86109044ab18734",
    }
    assert all(
        identities[identity]["status"] == "AUDITED_EXACT_REPLAY_FAILED_DATA_QUALITY"
        for identity in failed_replays
    )
    carry_codes = {item["code"] for item in identities["6d151a184bf3e743"]["blockers"]}
    assert carry_codes == {
        "PREREGISTRATION_POSTDATES_FIRST_MEASUREMENT",
        "ORIGINAL_RUN_LACKS_CODE_AND_ENVIRONMENT_STAMP",
        "CARRY_SPECIFIC_CAPACITY_UNMEASURED",
    }
    for identity in _module().PREREG_CROSS_ASSET_TRIALS:
        trial = identities[identity]["blockers"][0]
        assert trial["code"] == "CURRENT_ENGINE_REJECTS_LEGACY_CROSS_ASSET_UNIVERSE"
        assert trial["evidence"][0]["non_equity_ids"] == 60
        assert trial["evidence"][0]["ledger_n_obs"] == 5384
    for identity in _module().EXACT_REPLAY_CANDIDATES:
        codes = {item["code"] for item in identities[identity]["blockers"]}
        if identity in failed_replays:
            assert codes == {"EXACT_CURRENT_ENGINE_REPLAY_FAILED_DATA_QUALITY"}
            evidence = identities[identity]["blockers"][0]["evidence"]
            assert len(evidence) == 8
            public = [item["public_path"] for item in evidence if "public_path" in item]
            assert len(public) == 6
            for public_path in public:
                relative = public_path.removeprefix("/glassbox/")
                assert (REPO.parent / "meridian/public/glassbox" / relative).is_file()
                assert (REPO.parent / "meridian-app/public/glassbox" / relative).is_file()
        elif identity == "e5f48adc25065ce9":
            assert codes == {
                "CORRECTED_REPLAY_EXECUTION_STRESS_NOT_PRESERVED",
                "CORRECTED_REPLAY_RISK_AND_DIVERSIFICATION_PACKET_PENDING",
            }
            evidence = identities[identity]["blockers"][0]["evidence"]
            corrected_seals = [
                item
                for item in evidence
                if item.get("path", "").endswith(
                    "operating_margin_corrected_reproduction.json"
                )
            ]
            assert len(corrected_seals) == 1
            assert corrected_seals[0]["public_path"].endswith(
                "operating_margin_corrected_reproduction.json"
            )
        else:
            assert codes == {
                "EXACT_CURRENT_ENGINE_REPLAY_PENDING",
                "IDENTITY_LEVEL_DATA_MANIFEST_PENDING",
                "CAPACITY_AND_DIVERSIFICATION_PENDING",
            }


@pytest.mark.workspace_evidence
def test_recoverability_audit_is_byte_identical_across_public_hosts() -> None:
    source = REPO / "artifacts" / "research" / "identity_packet_recoverability.json"
    hosts = (
        REPO.parent / "meridian" / "public" / "glassbox" / source.name,
        REPO.parent / "meridian-app" / "public" / "glassbox" / source.name,
    )
    assert source.exists() and all(path.exists() for path in hosts)
    assert source.read_bytes() == hosts[0].read_bytes() == hosts[1].read_bytes()
    payload = json.loads(source.read_text())
    assert payload["summary"]["union_identities_after_aborted_replay"] == 228
