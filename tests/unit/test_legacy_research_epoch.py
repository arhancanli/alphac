from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from alphaforge.validation.trial_reservation import (
    ReservationError,
    _validate_historical_packet_coverage,
)

REPO = Path(__file__).resolve().parents[2]
CONTRACT_FILES = (
    Path("artifacts/research/trial_packet_manifest.json"),
    Path("artifacts/research/trial_packets/index.json"),
    Path("artifacts/research/identity_packet_recoverability.json"),
    Path("artifacts/research/historical_curve_evidence/index.json"),
    Path("artifacts/research/legacy_research_epoch_closure.json"),
)


def _module():
    path = REPO / "scripts" / "seal_legacy_research_epoch.py"
    spec = importlib.util.spec_from_file_location("legacy_research_epoch_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_contract(repo: Path) -> None:
    for relative in CONTRACT_FILES:
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, destination)


def test_legacy_epoch_retires_every_identity_without_creating_eligibility() -> None:
    closure = _module().build_closure()
    assert closure["summary"] == {
        "retired_identities": 228,
        "retired_complete_evidenced_kills": 2,
        "retired_incomplete_evidence_debt": 226,
        "retired_unassessed_identities": 0,
        "eligible_for_admission": 0,
        "identity_reuse_permitted": 0,
    }
    assert len(closure["identities"]) == 228
    assert all(item["eligible_for_admission"] is False for item in closure["identities"])
    assert all(item["identity_reuse_permitted"] is False for item in closure["identities"])


def test_current_reservation_gate_accepts_only_the_sealed_retirement_mode() -> None:
    coverage = _validate_historical_packet_coverage(REPO)
    assert coverage["coverage_mode"] == "FAIL_CLOSED_LEGACY_EPOCH_RETIREMENT"
    assert coverage["historical_identities"] == 228
    assert coverage["retired_incomplete_trial_packets"] == 226
    assert coverage["historical_identities_eligible_for_admission"] == 0


def test_legacy_epoch_closure_mutation_fails_closed(tmp_path: Path) -> None:
    _copy_contract(tmp_path)
    path = tmp_path / "artifacts/research/legacy_research_epoch_closure.json"
    closure = json.loads(path.read_text(encoding="utf-8"))
    closure["summary"]["eligible_for_admission"] = 1
    path.write_text(json.dumps(closure), encoding="utf-8")
    with pytest.raises(ReservationError, match="closure content hash mismatch"):
        _validate_historical_packet_coverage(tmp_path)


def test_legacy_epoch_bound_source_mutation_fails_closed(tmp_path: Path) -> None:
    _copy_contract(tmp_path)
    path = tmp_path / "artifacts/research/historical_curve_evidence/index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["claim_boundary"] += " drift"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReservationError, match="historical_curve_index file hash mismatch"):
        _validate_historical_packet_coverage(tmp_path)


def test_legacy_epoch_closure_is_byte_identical_across_public_hosts() -> None:
    source = REPO / "artifacts/research/legacy_research_epoch_closure.json"
    hosts = (
        REPO.parent / "meridian/public/glassbox" / source.name,
        REPO.parent / "meridian-app/public/glassbox" / source.name,
    )
    assert source.read_bytes() == hosts[0].read_bytes() == hosts[1].read_bytes()
