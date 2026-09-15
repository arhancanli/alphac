"""An identity batch is atomic, sealed before the first return, and blocks everything else.

WHY. The v2 full-evidence reservation needs a probability-of-backtest-overfitting matrix, and a
matrix needs at least two counted return columns. The serial guard admitted one identity at a
time, so a second column could never be reserved before the first had run. These tests pin the
batch semantics the evidence-classes policy declares
(config/trial_accounting_evidence_classes.json):

- a sibling reserved in the same sealed batch is allowed to be undecided; it is never allowed to
  be unreserved (the registry and the reservations on disk both have to say so);
- the batch cannot be edited after sealing: a member added, removed or reordered is refused;
- every reservation OUTSIDE an open batch is blocked until the batch decides;
- ordinals move past reserved-but-unrun siblings, so two members hold two ordinals;
- declared diagnostics before the run are assumptions only: a result is an outcome field.

Every test reaches the state through validate_reservation, never by calling the private helpers
with fabricated inputs, so the guard is exercised on the path the runner uses.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from alphaforge.validation.experiments import ExperimentLog, hypothesis_hash
from alphaforge.validation.trial_reservation import (
    IDENTITY_BATCH_DIR,
    IDENTITY_BATCH_SCHEMA,
    RESERVATION_DIR,
    RESERVATION_FILENAME,
    ReservationError,
    _observed_content_hash,
    batch_content_hash,
    validate_reservation,
)

REPO = Path(__file__).resolve().parents[2]
_HARNESS = importlib.util.spec_from_file_location(
    "forward_trial_reservation_harness",
    REPO / "tests" / "unit" / "test_validate_forward_trial_reservation.py",
)
assert _HARNESS is not None and _HARNESS.loader is not None
harness = importlib.util.module_from_spec(_HARNESS)
_HARNESS.loader.exec_module(harness)

FAMILY = "new_family"


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _seal_registry(tmp_path: Path, batch_id: str, configs: list[dict[str, Any]]) -> dict[str, Any]:
    hashes = [hypothesis_hash(c) for c in configs]
    registry: dict[str, Any] = {
        "schema": IDENTITY_BATCH_SCHEMA,
        "batch_id": batch_id,
        "family_trial_account": FAMILY,
        "identity_configs": configs,
        "identity_hashes": hashes,
        "batch_content_hash": batch_content_hash(batch_id, FAMILY, hashes),
        "pbo_columns": len(hashes),
        "all_identities_reserved_before_first_return": True,
        "interim_result_access_forbidden": True,
        "sealed_at": "2026-09-14T19:00:00+00:00",
    }
    registry["content_hash"] = _observed_content_hash(registry)
    path = tmp_path / IDENTITY_BATCH_DIR / f"{batch_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry), encoding="utf-8")
    return registry


def _batch_block(batch_id: str, configs: list[dict[str, Any]]) -> dict[str, Any]:
    hashes = [hypothesis_hash(c) for c in configs]
    return {
        "batch_id": batch_id,
        "family_trial_account": FAMILY,
        "identity_configs": configs,
        "identity_hashes": hashes,
        "batch_content_hash": batch_content_hash(batch_id, FAMILY, hashes),
        "registry_path": (IDENTITY_BATCH_DIR / f"{batch_id}.json").as_posix(),
        "all_identities_reserved_before_first_return": True,
        "interim_result_access_forbidden": True,
        "pbo_columns": len(hashes),
    }


def _member(
    tmp_path: Path,
    base: dict[str, Any],
    *,
    trial: dict[str, Any],
    identity_id: str,
    ordinal: int,
    batch: dict[str, Any],
) -> dict[str, Any]:
    reservation = copy.deepcopy(base)
    reservation["return_identity_id"] = identity_id
    reservation["trial_config"] = trial
    reservation["hypothesis_identity"] = hypothesis_hash(trial)
    reservation["packet_public_path"] = f"/glassbox/trial-packets/{identity_id}.json"
    reservation["paper_public_path"] = f"/research/{identity_id}"
    reservation["governance_epoch"]["reservation_ordinal"] = ordinal
    reservation["identity_batch"] = copy.deepcopy(batch)
    return reservation


def _outsider(first: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """An unrelated identity (no batch block) in the same governed repository."""
    outsider = copy.deepcopy(first)
    outsider.pop("identity_batch")
    trial_o = {**first["trial_config"], "alpha_names": ["outsider_edge"]}
    outsider["trial_config"] = trial_o
    outsider["hypothesis_identity"] = hypothesis_hash(trial_o)
    outsider["return_identity_id"] = "outsider_v1"
    outsider["packet_public_path"] = "/glassbox/trial-packets/outsider_v1.json"
    outsider["paper_public_path"] = "/research/outsider-v1"
    return outsider, trial_o


def _write_reservation(tmp_path: Path, reservation: dict[str, Any]) -> None:
    path = tmp_path / RESERVATION_DIR / reservation["return_identity_id"] / RESERVATION_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reservation), encoding="utf-8")


def _two_member_batch(
    tmp_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    base, trial_a = harness._fixture(tmp_path)
    trial_b = {**trial_a, "alpha_names": ["new_edge_mdna"]}
    configs = [trial_a, trial_b]
    _seal_registry(tmp_path, "new_family_batch_1", configs)
    batch = _batch_block("new_family_batch_1", configs)
    first = _member(
        tmp_path, base, trial=trial_a, identity_id="new_family_a", ordinal=229, batch=batch
    )
    second = _member(
        tmp_path, base, trial=trial_b, identity_id="new_family_b", ordinal=230, batch=batch
    )
    return first, second, trial_a, trial_b


def test_two_members_reserve_back_to_back_with_consecutive_ordinals_and_no_run_between(
    tmp_path: Path,
) -> None:
    first, second, trial_a, trial_b = _two_member_batch(tmp_path)
    result = validate_reservation(first, trial_config=trial_a, repo=tmp_path)
    assert result["identity_batch"]["position"] == 1
    assert result["identity_batch"]["pbo_defined"] is True
    assert result["governance_epoch"]["reservation_ordinal"] == 229
    _write_reservation(tmp_path, first)

    # Nothing has run: the first member has no packet. A second member of the SAME batch is
    # still reservable, at the next ordinal, because the batch decides together.
    result = validate_reservation(second, trial_config=trial_b, repo=tmp_path)
    assert result["identity_batch"]["position"] == 2
    assert result["governance_epoch"]["reservation_ordinal"] == 230
    assert result["forward_epoch_seriality"]["policy"].startswith("ATOMIC_BATCH")


def test_a_member_that_precedes_this_one_must_already_be_reserved_on_disk(tmp_path: Path) -> None:
    _, second, _, trial_b = _two_member_batch(tmp_path)
    # The first member's reservation was never written: the second cannot claim the batch.
    with pytest.raises(ReservationError, match="has no reservation on disk"):
        validate_reservation(second, trial_config=trial_b, repo=tmp_path)


def test_an_identity_cannot_claim_a_batch_that_did_not_reserve_it(tmp_path: Path) -> None:
    first, second, trial_a, _ = _two_member_batch(tmp_path)
    _write_reservation(tmp_path, first)
    trial_c = {**trial_a, "alpha_names": ["unreserved_edge"]}
    intruder = copy.deepcopy(second)
    intruder["trial_config"] = trial_c
    intruder["hypothesis_identity"] = hypothesis_hash(trial_c)
    with pytest.raises(ReservationError, match="not a member of its own identity_batch"):
        validate_reservation(intruder, trial_config=trial_c, repo=tmp_path)


def test_a_member_added_after_sealing_is_refused(tmp_path: Path) -> None:
    first, second, trial_a, trial_b = _two_member_batch(tmp_path)
    _write_reservation(tmp_path, first)
    trial_c = {**trial_a, "alpha_names": ["late_edge"]}
    grown = _batch_block("new_family_batch_1", [trial_a, trial_b, trial_c])
    second["identity_batch"] = grown
    with pytest.raises(ReservationError, match="added, removed or reordered"):
        validate_reservation(second, trial_config=trial_b, repo=tmp_path)


def test_a_reordered_batch_is_refused(tmp_path: Path) -> None:
    first, second, trial_a, trial_b = _two_member_batch(tmp_path)
    _write_reservation(tmp_path, first)
    second["identity_batch"] = _batch_block("new_family_batch_1", [trial_b, trial_a])
    with pytest.raises(ReservationError, match="added, removed or reordered"):
        validate_reservation(second, trial_config=trial_b, repo=tmp_path)


def test_a_batch_with_the_same_identity_twice_is_refused(tmp_path: Path) -> None:
    base, trial_a = harness._fixture(tmp_path)
    _seal_registry(tmp_path, "dup_batch", [trial_a, trial_a])
    reservation = _member(
        tmp_path,
        base,
        trial=trial_a,
        identity_id="dup_a",
        ordinal=229,
        batch=_batch_block("dup_batch", [trial_a, trial_a]),
    )
    with pytest.raises(ReservationError, match="same hypothesis identity twice"):
        validate_reservation(reservation, trial_config=trial_a, repo=tmp_path)


def test_a_tampered_batch_hash_is_refused(tmp_path: Path) -> None:
    first, _, trial_a, _ = _two_member_batch(tmp_path)
    first["identity_batch"]["batch_content_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ReservationError, match="does not seal its members"):
        validate_reservation(first, trial_config=trial_a, repo=tmp_path)


def test_an_open_batch_blocks_every_unrelated_reservation(tmp_path: Path) -> None:
    first, _, trial_a, _ = _two_member_batch(tmp_path)
    validate_reservation(first, trial_config=trial_a, repo=tmp_path)
    _write_reservation(tmp_path, first)
    # Nobody in the batch has decided. An unrelated identity (no batch block) is blocked.
    outsider, trial_o = _outsider(first)
    with pytest.raises(ReservationError, match="identity batch new_family_batch_1 is open"):
        validate_reservation(outsider, trial_config=trial_o, repo=tmp_path)


def _log_run(tmp_path: Path, trial: dict[str, Any], now_ms: int) -> None:
    """The real path to a decided identity: it ran (a ledger record), then it was closed."""
    ledger = ExperimentLog(tmp_path / "artifacts" / "forward" / "experiments.jsonl")
    ledger.record(
        trial,
        sharpe_ann=0.0,
        sharpe_per_period=0.0,
        n_obs=10,
        skew=0.0,
        kurtosis=3.0,
        now_ms=now_ms,
    )


def test_a_decided_batch_releases_unrelated_reservations(tmp_path: Path) -> None:
    first, second, trial_a, trial_b = _two_member_batch(tmp_path)
    _write_reservation(tmp_path, first)
    _write_reservation(tmp_path, second)
    for now_ms, trial in ((1, trial_a), (2, trial_b)):
        _log_run(tmp_path, trial, now_ms)
        harness._write_complete_forward_packet(tmp_path, hypothesis_hash(trial), disposition="KILL")
    outsider, trial_o = _outsider(first)
    # Both members decided (KILL): the batch is closed and the outsider takes the next ordinal.
    outsider["governance_epoch"]["reservation_ordinal"] = 231
    result = validate_reservation(outsider, trial_config=trial_o, repo=tmp_path)
    assert result["identity_batch"] is None
    assert result["status"] == "VALIDATED_BEFORE_RETURN_COMPUTE"


def test_a_single_member_batch_validates_but_cannot_define_pbo(tmp_path: Path) -> None:
    base, trial_a = harness._fixture(tmp_path)
    _seal_registry(tmp_path, "solo_batch", [trial_a])
    reservation = _member(
        tmp_path,
        base,
        trial=trial_a,
        identity_id="solo_a",
        ordinal=229,
        batch=_batch_block("solo_batch", [trial_a]),
    )
    result = validate_reservation(reservation, trial_config=trial_a, repo=tmp_path)
    assert result["identity_batch"]["pbo_defined"] is False
    assert result["identity_batch"]["pbo_columns"] == 1


def test_declared_diagnostics_are_assumptions_only_before_the_run(tmp_path: Path) -> None:
    reservation, trial = harness._fixture(tmp_path)
    assumptions = {"fee_multiplier": 2.0, "spread_multiplier": 2.0}
    reservation["diagnostic_scenarios"] = {
        "cost_stress_scenarios": [
            {
                "scenario_id": "cost_x2",
                "assumptions": assumptions,
                "assumptions_sha256": _canonical_sha256(assumptions),
            }
        ]
    }
    result = validate_reservation(reservation, trial_config=trial, repo=tmp_path)
    assert result["declared_diagnostic_scenarios"] == {
        "declared_diagnostic_scenarios": 1,
        "classes": {"cost_stress_scenarios": 1},
    }

    with_result = copy.deepcopy(reservation)
    with_result["diagnostic_scenarios"]["cost_stress_scenarios"][0]["result"] = {"sharpe": 1.0}
    with pytest.raises(ReservationError, match="outcome field"):
        validate_reservation(with_result, trial_config=trial, repo=tmp_path)

    duplicated = copy.deepcopy(reservation)
    duplicated["diagnostic_scenarios"]["capacity_scenarios"] = list(
        reservation["diagnostic_scenarios"]["cost_stress_scenarios"]
    )
    with pytest.raises(ReservationError, match="duplicate diagnostic scenario_id"):
        validate_reservation(duplicated, trial_config=trial, repo=tmp_path)

    tampered = copy.deepcopy(reservation)
    tampered["diagnostic_scenarios"]["cost_stress_scenarios"][0]["assumptions"][
        "fee_multiplier"
    ] = 1.0
    with pytest.raises(ReservationError, match="assumptions_sha256 does not match"):
        validate_reservation(tampered, trial_config=trial, repo=tmp_path)


def test_the_evidence_classes_policy_binds_the_sealed_trial_policy_and_names_the_validators() -> (
    None
):
    classes = json.loads(
        (REPO / "config" / "trial_accounting_evidence_classes.json").read_text(encoding="utf-8")
    )
    policy = json.loads((REPO / "config" / "trial_accounting.json").read_text(encoding="utf-8"))
    assert classes["schema"] == "canli.alphac-trial-evidence-classes.v1"
    binding = classes["policy_binding"]
    assert binding["path"] == "config/trial_accounting.json"
    assert binding["schema"] == policy["schema"]
    assert binding["identity_definition"] == policy["definitions"]["hypothesis_identity"]
    batch = classes["classes"]["identity_batch"]
    assert batch["registry_schema"] == IDENTITY_BATCH_SCHEMA
    assert batch["registry_path_pattern"].startswith(IDENTITY_BATCH_DIR.as_posix())
    diagnostic = classes["classes"]["mandatory_diagnostic_scenario"]
    assert diagnostic["counts_in_union_dsr"] is False and diagnostic["may_become_winner"] is False
    assert set(diagnostic["declared_before_first_return_with"]) == {
        "scenario_id",
        "assumptions",
        "assumptions_sha256",
    }
    selectable = classes["classes"]["selectable_return_identity"]
    assert selectable["counts_in_union_dsr"] is True and selectable["may_become_winner"] is True


def test_the_batch_matrix_receipt_never_sits_at_the_registry_top_level() -> None:
    """The validator reads every top-level JSON in the registry directory as a batch registry
    and fails closed on any other schema. The runner once wrote its PBO matrix receipt there and
    the second batch attempt died at its first ledger record (2026-09-15 02:32Z), with both
    sections computed and nothing recorded. The receipt lives inside the batch's directory."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "narrative_runner_for_registry_test",
        REPO / "scripts" / "run_earnings_narrative_change_v1.py",
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    registry_dir = REPO / IDENTITY_BATCH_DIR
    assert runner.BATCH_MATRIX_PATH.parent != registry_dir
    assert runner.BATCH_MATRIX_PATH.parent.parent == registry_dir
    assert runner.BATCH_MATRIX_PATH.parent.name == runner.BATCH_ID
