from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from alphaforge.validation.experiments import ExperimentLog, hypothesis_hash
from alphaforge.validation.trial_reservation import _validate_prior_identity_admission_disposition

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_forward_trial_reservation.py"
ROOT = SCRIPT.parents[1]
SPEC = importlib.util.spec_from_file_location("forward_trial_reservation_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ReservationError = MODULE.ReservationError
validate_reservation = MODULE.validate_reservation


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _governance_fixture(tmp_path: Path, *, ordinal: int = 229) -> dict[str, object]:
    bindings = {}
    for relative in (
        "config/sleeve_admission_contract.json",
        "config/trial_accounting.json",
        "config/admission_v7_promotion.json",
    ):
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        key = {
            "config/sleeve_admission_contract.json": "admission_contract",
            "config/trial_accounting.json": "trial_policy",
            "config/admission_v7_promotion.json": "promotion_receipt",
        }[relative]
        bindings[f"{key}_path"] = relative
        bindings[f"{key}_sha256"] = _sha(target)
    contract = json.loads((tmp_path / "config/sleeve_admission_contract.json").read_text())
    bindings["effective_contract_hash"] = contract["prospective_scope"][
        "effective_contract_content_hash"
    ]
    bindings["reservation_ordinal"] = ordinal
    return bindings


def _fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    manifest = {
        "schema": "canli.alphac-trial-packet-manifest.v2",
        "summary": {
            "distinct_hypothesis_identities": 228,
            "complete_trial_packets": 228,
            "incomplete_trial_packets": 0,
            "published_identity_packets": 228,
            "coverage_status": "COMPLETE",
        },
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    manifest_path = tmp_path / "artifacts" / "research" / "trial_packet_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest))
    trial = {"alpha_names": ["new_edge"], "allocator": "rank", "start": 1, "end": 2}
    evidence: dict[str, dict[str, str]] = {}
    for name in (
        "preregistration",
        "input_data_manifest",
        "runner",
        "python_project",
        "locked_environment",
    ):
        path = tmp_path / f"{name}.txt"
        path.write_text(name, encoding="utf-8")
        evidence[name] = {"path": path.name, "sha256": _sha(path)}
    reservation: dict[str, object] = {
        "schema": "canli.alphac-forward-trial-reservation.v1",
        "status": "RETURN_IDENTITY_RESERVED",
        "family_trial_account": "new_family",
        "return_identity_id": "new_family_v1",
        "hypotheses_spent": 1,
        "reserved_at": "2026-08-23T01:30:00+00:00",
        "trial_config": trial,
        "hypothesis_identity": hypothesis_hash(trial),
        "packet_public_path": "/glassbox/trial-packets/new_family_v1.json",
        "paper_public_path": "/research/new-family-v1",
        "governance_epoch": _governance_fixture(tmp_path),
        "evidence": evidence,
    }
    return reservation, trial


def _log_prior_forward_identity(tmp_path: Path) -> tuple[str, dict[str, object]]:
    trial: dict[str, object] = {
        "alpha_names": ["prior_forward_edge"],
        "allocator": "rank",
        "start": 1,
        "end": 2,
    }
    ledger = ExperimentLog(tmp_path / "artifacts" / "forward" / "experiments.jsonl")
    ledger.record(
        trial,
        sharpe_ann=0.0,
        sharpe_per_period=0.0,
        n_obs=10,
        skew=0.0,
        kurtosis=3.0,
        now_ms=1,
    )
    return ledger._hypothesis_key(trial), trial


def _write_complete_forward_packet(tmp_path: Path, identity: str) -> None:
    packet: dict[str, object] = {
        "schema": "canli.alphac-identity-trial-packet.v2",
        "hypothesis_key": identity,
        "complete": True,
        "missing_sections": [],
    }
    canonical = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    packet["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    path = tmp_path / "artifacts" / "research" / "trial_packets" / f"{identity}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet), encoding="utf-8")


def test_valid_reservation_binds_all_pre_result_evidence(tmp_path: Path) -> None:
    reservation, trial = _fixture(tmp_path)
    result = validate_reservation(reservation, trial_config=trial, repo=tmp_path)
    assert result["status"] == "VALIDATED_BEFORE_RETURN_COMPUTE"
    assert result["hypothesis_identity"] == hypothesis_hash(trial)
    assert set(result["evidence"]) == {
        "preregistration",
        "input_data_manifest",
        "runner",
        "python_project",
        "locked_environment",
    }
    assert result["historical_packet_coverage"]["complete_trial_packets"] == 228
    assert result["forward_epoch_seriality"]["forward_identities_already_logged"] == 0


def test_reservation_blocks_second_forward_identity_until_prior_packet_is_complete(
    tmp_path: Path,
) -> None:
    reservation, trial = _fixture(tmp_path)
    identity, _ = _log_prior_forward_identity(tmp_path)
    with pytest.raises(ReservationError, match="prior forward identity has no complete packet"):
        validate_reservation(reservation, trial_config=trial, repo=tmp_path)

    _write_complete_forward_packet(tmp_path, identity)
    reservation["governance_epoch"]["reservation_ordinal"] = 230
    result = validate_reservation(reservation, trial_config=trial, repo=tmp_path)
    assert result["forward_epoch_seriality"]["forward_identities_already_logged"] == 1
    assert result["forward_epoch_seriality"]["complete_forward_packets_verified"] == 1


def test_reservation_rejects_incomplete_historical_packet_coverage(tmp_path: Path) -> None:
    reservation, trial = _fixture(tmp_path)
    path = tmp_path / "artifacts" / "research" / "trial_packet_manifest.json"
    manifest = json.loads(path.read_text())
    manifest.pop("content_hash")
    manifest["summary"].update(
        {
            "complete_trial_packets": 2,
            "incomplete_trial_packets": 1,
            "coverage_status": "INCOMPLETE_BACKFILL_REQUIRED",
        }
    )
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ReservationError, match=r"historical trial-packet coverage is incomplete"):
        validate_reservation(reservation, trial_config=trial, repo=tmp_path)


@pytest.mark.parametrize("field", ["sharpe", "max_drawdown", "verdict", "result"])
def test_reservation_rejects_outcome_fields(tmp_path: Path, field: str) -> None:
    reservation, trial = _fixture(tmp_path)
    reservation[field] = 0.0
    with pytest.raises(ReservationError, match="outcome fields"):
        validate_reservation(reservation, trial_config=trial, repo=tmp_path)


def test_reservation_rejects_trial_mutation(tmp_path: Path) -> None:
    reservation, trial = _fixture(tmp_path)
    mutated = {**trial, "allocator": "mvo"}
    with pytest.raises(ReservationError, match="does not exactly match"):
        validate_reservation(reservation, trial_config=mutated, repo=tmp_path)


def test_reservation_requires_the_exact_promoted_governance_epoch(tmp_path: Path) -> None:
    reservation, trial = _fixture(tmp_path)
    del reservation["governance_epoch"]
    with pytest.raises(ReservationError, match="governance_epoch"):
        validate_reservation(reservation, trial_config=trial, repo=tmp_path)


def test_reservation_rejects_contract_mutation_after_freeze(tmp_path: Path) -> None:
    reservation, trial = _fixture(tmp_path)
    path = tmp_path / "config/sleeve_admission_contract.json"
    contract = json.loads(path.read_text())
    contract["thresholds"]["net_sharpe_min"] = 0.16
    path.write_text(json.dumps(contract))
    with pytest.raises(ReservationError, match="admission_contract hash mismatch"):
        validate_reservation(reservation, trial_config=trial, repo=tmp_path)


def test_reservation_ordinal_must_be_next_and_within_budget(tmp_path: Path) -> None:
    reservation, trial = _fixture(tmp_path)
    reservation["governance_epoch"]["reservation_ordinal"] = 230
    with pytest.raises(ReservationError, match="reservation_ordinal"):
        validate_reservation(reservation, trial_config=trial, repo=tmp_path)


def test_reservation_rejects_changed_evidence_bytes(tmp_path: Path) -> None:
    reservation, trial = _fixture(tmp_path)
    (tmp_path / "runner.txt").write_text("changed after reservation", encoding="utf-8")
    with pytest.raises(ReservationError, match="runner evidence hash mismatch"):
        validate_reservation(reservation, trial_config=trial, repo=tmp_path)


def test_reservation_rejects_path_escape(tmp_path: Path) -> None:
    reservation, trial = _fixture(tmp_path)
    evidence = reservation["evidence"]
    assert isinstance(evidence, dict)
    evidence["runner"] = {"path": "../runner.py", "sha256": "0" * 64}
    with pytest.raises(ReservationError, match="escapes repository"):
        validate_reservation(reservation, trial_config=trial, repo=tmp_path)


# Plan task 3: prove the drafted, unwired _validate_prior_identity_admission_disposition against
# today's real sealed crypto_carry_portable_v1 state, replayed byte-for-byte rather than
# reconstructed. validate_reservation itself is untouched by this task -- reserving ordinal 230
# today still passes the seriality check (plan task 4, owner-gated, is what would change that).
SEALED_V1_IDENTITY = "da5f5f47f99f9bd2"
SEALED_V1_PACKET = Path("artifacts/research/trial_packets/da5f5f47f99f9bd2.json")
SEALED_V1_CLOSURE = Path("artifacts/research/crypto_carry_portable_v1_admission_closure.json")
# artifacts/ is gitignored, so a clean checkout (CI) cannot read the sealed files. Byte-identical
# copies live under tests/fixtures; the workspace_evidence test below keeps them bound to the
# originals on the machine that holds them, so the fixture cannot drift from the seal.
SEALED_V1_FIXTURES = (
    Path(__file__).resolve().parent.parent / "fixtures" / "crypto_carry_portable_v1"
)
SEALED_V1_PACKET_FIXTURE = SEALED_V1_FIXTURES / SEALED_V1_PACKET.name
SEALED_V1_CLOSURE_FIXTURE = SEALED_V1_FIXTURES / SEALED_V1_CLOSURE.name


def _replay_sealed_v1_state(tmp_path: Path) -> dict[str, object]:
    """Copy the real, sealed crypto_carry_portable_v1 packet and closure byte-for-byte."""
    packet_target = tmp_path / SEALED_V1_PACKET
    closure_target = tmp_path / SEALED_V1_CLOSURE
    packet_target.parent.mkdir(parents=True, exist_ok=True)
    closure_target.parent.mkdir(parents=True, exist_ok=True)
    packet_target.write_bytes(SEALED_V1_PACKET_FIXTURE.read_bytes())
    closure_target.write_bytes(SEALED_V1_CLOSURE_FIXTURE.read_bytes())
    return json.loads(packet_target.read_text(encoding="utf-8"))


@pytest.mark.workspace_evidence
def test_the_sealed_v1_fixtures_are_byte_identical_to_the_originals() -> None:
    """On the machine that holds artifacts/, the tracked fixtures must equal the sealed files
    exactly; a fixture that drifted would let the replay above prove something about a state
    that was never sealed."""
    assert (ROOT / SEALED_V1_PACKET).read_bytes() == SEALED_V1_PACKET_FIXTURE.read_bytes()
    assert (ROOT / SEALED_V1_CLOSURE).read_bytes() == SEALED_V1_CLOSURE_FIXTURE.read_bytes()


def _observed_content_hash(payload: dict[str, object]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def test_prior_identity_admission_disposition_blocks_the_sealed_incomplete_v1_state(
    tmp_path: Path,
) -> None:
    packet = _replay_sealed_v1_state(tmp_path)
    assert packet["complete"] is True
    assert packet["content_hash"] == (
        "sha256:9ba408cb3c1d9accd91eddd25a079995a8d42aa6b7456dd6afd22539917ce40a"
    )
    closure = json.loads((tmp_path / SEALED_V1_CLOSURE).read_text(encoding="utf-8"))
    assert closure["decision"]["disposition"] == "INCOMPLETE"
    assert closure["content_hash"] == (
        "sha256:ac2ef258f30ee20dc8a915866cbc72e52c3f5ae93a21fb336cdd627406c0d451"
    )
    with pytest.raises(ReservationError, match="neither ADMIT nor KILL"):
        _validate_prior_identity_admission_disposition(tmp_path, SEALED_V1_IDENTITY, packet)


def test_a_valid_seriality_waiver_unblocks_the_sealed_incomplete_v1_state(
    tmp_path: Path,
) -> None:
    packet = _replay_sealed_v1_state(tmp_path)
    waiver = {
        "schema": "canli.alphac-seriality-waiver.v1",
        "waived_hypothesis_key": SEALED_V1_IDENTITY,
        "waived_packet_content_hash": packet["content_hash"],
        "reason": (
            "Owner accepts the nine unfrozen evidence fields as a permanent evidentiary gap for "
            "this once-run identity and authorizes reserving the next ordinal without regrading "
            "v1."
        ),
        "authorized_by": "Arhan Canli, owner, 2026-09-06",
    }
    assert waiver["waived_packet_content_hash"] == (
        "sha256:9ba408cb3c1d9accd91eddd25a079995a8d42aa6b7456dd6afd22539917ce40a"
    )
    waiver["content_hash"] = _observed_content_hash(waiver)
    waiver_path = (
        tmp_path / "artifacts" / "research" / "seriality_waivers" / f"{SEALED_V1_IDENTITY}.json"
    )
    waiver_path.parent.mkdir(parents=True, exist_ok=True)
    waiver_path.write_text(json.dumps(waiver), encoding="utf-8")

    _validate_prior_identity_admission_disposition(tmp_path, SEALED_V1_IDENTITY, packet)
