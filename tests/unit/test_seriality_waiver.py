"""Seriality guard closure-disposition check and waiver schema (plan task 2, spec 2(b)).

`_validate_forward_epoch_serial_completion` unblocks the next reservation once a prior packet has
`complete: true` and `missing_sections: []`. Packet completion records evidence accounting, not a
gate outcome (the sealed `crypto_carry_portable_v1` packet shows exactly this: `complete: true`
with disposition `INCOMPLETE`). This test proves the drafted, unwired
`_validate_prior_identity_admission_disposition` closes that gap: a prior identity's sealed
closure must disposition ADMIT or KILL, or carry a signed waiver bound to the exact sealed
packet's `content_hash`, so a re-seal invalidates any existing waiver.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from alphaforge.validation.trial_reservation import (
    SERIALITY_WAIVER_SCHEMA,
    ReservationError,
    _validate_prior_identity_admission_disposition,
)

IDENTITY = "test_identity"


def _observed_content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_closure(tmp_path: Path, *, disposition: str) -> tuple[Path, str]:
    closure: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-portable-admission-closure.v1",
        "decision": {"disposition": disposition},
    }
    closure["content_hash"] = _observed_content_hash(closure)
    path = tmp_path / "artifacts/research" / f"{IDENTITY}_admission_closure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(closure), encoding="utf-8")
    return path, str(closure["content_hash"])


def _packet(tmp_path: Path, closure_path: Path, closure_content_hash: str) -> dict[str, Any]:
    relative = closure_path.relative_to(tmp_path).as_posix()
    packet: dict[str, Any] = {
        "schema": "canli.alphac-identity-trial-packet.v2",
        "hypothesis_key": IDENTITY,
        "complete": True,
        "missing_sections": [],
        "required_sections": {
            "admission_or_kill_decision": {
                "evidence": [
                    {
                        "path": relative,
                        "sha256": _sha256(closure_path),
                        "content_hash": closure_content_hash,
                    }
                ],
            },
        },
    }
    packet["content_hash"] = _observed_content_hash(packet)
    return packet


def _write_waiver(tmp_path: Path, *, waived_packet_content_hash: str) -> None:
    waiver: dict[str, Any] = {
        "schema": SERIALITY_WAIVER_SCHEMA,
        "waived_hypothesis_key": IDENTITY,
        "waived_packet_content_hash": waived_packet_content_hash,
        "reason": "Owner accepts the evidentiary gap for this once-run identity.",
        "authorized_by": "Arhan Canli, owner, 2026-09-06",
    }
    waiver["content_hash"] = _observed_content_hash(waiver)
    waiver_path = tmp_path / "artifacts/research/seriality_waivers" / f"{IDENTITY}.json"
    waiver_path.parent.mkdir(parents=True, exist_ok=True)
    waiver_path.write_text(json.dumps(waiver), encoding="utf-8")


def test_a_disposition_that_is_neither_admit_nor_kill_blocks_without_a_waiver(
    tmp_path: Path,
) -> None:
    closure_path, closure_hash = _write_closure(tmp_path, disposition="INCOMPLETE")
    packet = _packet(tmp_path, closure_path, closure_hash)
    with pytest.raises(ReservationError, match="neither ADMIT nor KILL"):
        _validate_prior_identity_admission_disposition(tmp_path, IDENTITY, packet)


def test_a_valid_waiver_bound_to_the_sealed_packet_unblocks_it(tmp_path: Path) -> None:
    closure_path, closure_hash = _write_closure(tmp_path, disposition="INCOMPLETE")
    packet = _packet(tmp_path, closure_path, closure_hash)
    _write_waiver(tmp_path, waived_packet_content_hash=packet["content_hash"])

    _validate_prior_identity_admission_disposition(tmp_path, IDENTITY, packet)


def test_a_waiver_bound_to_a_stale_packet_hash_is_rejected(tmp_path: Path) -> None:
    closure_path, closure_hash = _write_closure(tmp_path, disposition="INCOMPLETE")
    packet = _packet(tmp_path, closure_path, closure_hash)
    _write_waiver(tmp_path, waived_packet_content_hash="sha256:" + "0" * 64)

    with pytest.raises(ReservationError, match="waiver does not match the sealed packet"):
        _validate_prior_identity_admission_disposition(tmp_path, IDENTITY, packet)


def test_a_disposition_of_admit_unblocks_without_a_waiver(tmp_path: Path) -> None:
    closure_path, closure_hash = _write_closure(tmp_path, disposition="ADMIT")
    packet = _packet(tmp_path, closure_path, closure_hash)
    _validate_prior_identity_admission_disposition(tmp_path, IDENTITY, packet)


def test_a_disposition_of_kill_unblocks_without_a_waiver(tmp_path: Path) -> None:
    closure_path, closure_hash = _write_closure(tmp_path, disposition="KILL")
    packet = _packet(tmp_path, closure_path, closure_hash)
    _validate_prior_identity_admission_disposition(tmp_path, IDENTITY, packet)
