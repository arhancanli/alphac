"""The forward packet index binds every register identity to its packet by hash, or names the debt.

WHY. The legacy index is sealed at 228 identities and cannot grow, so the 118 imported
identities, the governed crypto carry identity and every v2 batch identity were on disk and off
the site. The forward index lists every register row: a packet is bound by file hash and content
hash and refused on mismatch; a missing packet is PACKET_PENDING_SEAL with no public path; a key
present in both epochs fails closed; and the index binds the register it was built from so the
exporter can refuse a stale one.

Pure: a synthetic register, legacy index and packets in a temporary tree.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from alphaforge.validation.trial_reservation import _observed_content_hash

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "build_forward_identity_packet_index",
    REPO / "scripts" / "build_forward_identity_packet_index.py",
)
assert _SPEC is not None and _SPEC.loader is not None
MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MOD)


def _hashed(payload: dict[str, Any]) -> dict[str, Any]:
    payload["content_hash"] = _observed_content_hash(payload)
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _row(key: str, status: str, closure: str | None, disposition: str | None) -> dict[str, Any]:
    return {
        "hypothesis_key": key,
        "config_hash": key[:8],
        "family_trial_account": "fam",
        "return_identity_id": f"fam_{key[:4]}",
        "reservation_ordinal": 300,
        "status": status,
        "source": {"kind": "imported" if closure and "development" in closure else "canonical"},
        "closure_path": closure,
        "closure_kind": None
        if closure is None
        else ("development" if "development" in closure else "governed"),
        "closure_schema": None if closure is None else "test",
        "final_disposition": disposition,
        "admitted": False,
    }


def _packet(key: str, complete: bool = True) -> dict[str, Any]:
    return _hashed(
        {
            "schema": "canli.alphac-identity-trial-packet.v2",
            "hypothesis_key": key,
            "label": f"packet {key}",
            "packet_status": "COMPLETE_ACCOUNTING_FINAL_KILLED_NOT_ADMITTED"
            if complete
            else "INCOMPLETE",
            "complete": complete,
        }
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "engine"
    legacy_keys = ["1111111111111111", "2222222222222222"]
    _write(
        repo / MOD.LEGACY_INDEX_RELATIVE,
        _hashed({"schema": "legacy", "packets": [{"hypothesis_key": k} for k in legacy_keys]}),
    )
    rows = [
        _row(
            "aaaaaaaaaaaaaaaa",
            "DEVELOPMENT_CLOSURE_FINAL_NOT_ADMITTED",
            "artifacts/research/development_closures/a.json",
            "KILL",
        ),
        _row(
            "bbbbbbbbbbbbbbbb",
            "GOVERNED_SERIAL_PACKET_CLOSED",
            "artifacts/research/b_admission_closure.json",
            "INCOMPLETE",
        ),
        _row("cccccccccccccccc", "RESERVED_MEASURED_UNCLOSED", None, None),
    ]
    _write(repo / MOD.REGISTER_RELATIVE, _hashed({"schema": "register", "identities": rows}))
    _write(repo / MOD.IDENTITY_PACKET_DIR / "aaaaaaaaaaaaaaaa.json", _packet("aaaaaaaaaaaaaaaa"))
    _write(repo / MOD.IDENTITY_PACKET_DIR / "bbbbbbbbbbbbbbbb.json", _packet("bbbbbbbbbbbbbbbb"))
    return repo


def test_every_register_row_is_listed_and_bound_or_named_as_pending(repo: Path) -> None:
    index = MOD.build(repo)
    assert index["content_hash"] == _observed_content_hash(index)
    summary = index["summary"]
    assert summary["forward_identities"] == 3
    assert summary["published_packets"] == 2
    assert summary["pending_packets"] == 1
    assert summary["complete_packets"] == 2
    assert summary["closed_identities"] == 2
    assert summary["admitted_identities"] == 0
    assert summary["by_final_disposition"] == {"(unclosed)": 1, "INCOMPLETE": 1, "KILL": 1}
    rows = {r["hypothesis_key"]: r for r in index["packets"]}
    a = rows["aaaaaaaaaaaaaaaa"]
    packet_path = repo / MOD.IDENTITY_PACKET_DIR / "aaaaaaaaaaaaaaaa.json"
    assert a["public_path"] == "/glassbox/trial-packets/aaaaaaaaaaaaaaaa.json"
    assert a["packet_file_sha256"] == hashlib.sha256(packet_path.read_bytes()).hexdigest()
    assert a["packet_content_hash"] == json.loads(packet_path.read_text())["content_hash"]
    assert a["closure"] == {
        "path": "artifacts/research/development_closures/a.json",
        "kind": "development",
        "schema": "test",
        "final_disposition": "KILL",
        "admitted": False,
    }
    pending = rows["cccccccccccccccc"]
    assert pending["packet_status"] == MOD.PACKET_PENDING
    assert pending["public_path"] is None and pending["complete"] is False
    register = json.loads((repo / MOD.REGISTER_RELATIVE).read_text())
    assert (
        index["source_bindings"]["prospective_epoch_register"]["content_hash"]
        == register["content_hash"]
    )


def test_a_tampered_packet_is_refused(repo: Path) -> None:
    path = repo / MOD.IDENTITY_PACKET_DIR / "bbbbbbbbbbbbbbbb.json"
    packet = json.loads(path.read_text())
    packet["label"] = "edited after sealing"
    path.write_text(json.dumps(packet))
    with pytest.raises(ValueError, match="content hash mismatch"):
        MOD.build(repo)


def test_a_packet_filed_under_another_key_is_refused(repo: Path) -> None:
    path = repo / MOD.IDENTITY_PACKET_DIR / "bbbbbbbbbbbbbbbb.json"
    path.write_text(json.dumps(_packet("dddddddddddddddd")))
    with pytest.raises(ValueError, match="does not match its file name"):
        MOD.build(repo)


def test_a_key_in_both_epochs_fails_closed(repo: Path) -> None:
    register_path = repo / MOD.REGISTER_RELATIVE
    register = json.loads(register_path.read_text())
    register["identities"].append(
        _row("1111111111111111", "RESERVED_MEASURED_UNCLOSED", None, None)
    )
    _write(register_path, _hashed({k: v for k, v in register.items() if k != "content_hash"}))
    with pytest.raises(ValueError, match="both the legacy index and the register"):
        MOD.build(repo)


def test_the_real_index_reconciles_with_the_register_and_the_legacy_index() -> None:
    """Workspace only: the built index covers every register row and no legacy key."""
    path = REPO / MOD.OUTPUT_RELATIVE
    if not path.exists() or not (REPO / MOD.REGISTER_RELATIVE).exists():
        pytest.skip("the forward index lives in the working tree")
    index = json.loads(path.read_text())
    register = json.loads((REPO / MOD.REGISTER_RELATIVE).read_text())
    assert index["content_hash"] == _observed_content_hash(index)
    assert (
        index["source_bindings"]["prospective_epoch_register"]["content_hash"]
        == register["content_hash"]
    )
    assert {r["hypothesis_key"] for r in index["packets"]} == {
        r["hypothesis_key"] for r in register["identities"]
    }
    legacy = json.loads((REPO / MOD.LEGACY_INDEX_RELATIVE).read_text())
    assert not (
        {r["hypothesis_key"] for r in index["packets"]}
        & {r["hypothesis_key"] for r in legacy["packets"]}
    )
