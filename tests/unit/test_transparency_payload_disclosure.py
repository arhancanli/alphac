from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
from opentimestamps.core.serialize import BytesDeserializationContext
from opentimestamps.core.timestamp import DetachedTimestampFile

REPO = Path(__file__).resolve().parents[2]
VERIFIER = REPO / "scripts" / "verify_transparency.py"


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(
    key: Ed25519PrivateKey,
    *,
    seq: int,
    previous: str,
    payload: dict[str, object],
    disclose: bool,
) -> dict[str, object]:
    payload_hash = _sha256(_canonical(payload))
    date = f"2026-08-{22 + seq:02d}"
    chain_hash = _sha256(f"{previous}|{payload_hash}|{date}|{seq}".encode())
    entry: dict[str, object] = {
        "seq": seq,
        "date": date,
        "generated_at": f"{date}T00:00:00+00:00",
        "payload_sha256": payload_hash,
        "prev_chain_hash": previous,
        "chain_hash": chain_hash,
        "signature": key.sign(bytes.fromhex(chain_hash)).hex(),
    }
    if disclose:
        entry.update(
            {
                "payload_schema": "canli.alphac-track-record-daily-digest.v1",
                "payload": payload,
                "event": "PAYLOAD_DISCLOSURE_UPGRADE",
            }
        )
    return entry


def _document() -> dict[str, object]:
    key = Ed25519PrivateKey.generate()
    first = _entry(
        key,
        seq=0,
        previous="0" * 64,
        payload={"book_live": [{"date": "2026-08-22", "equity": 1.0}]},
        disclose=False,
    )
    second = _entry(
        key,
        seq=1,
        previous=str(first["chain_hash"]),
        payload={"book_live": [{"date": "2026-08-23", "equity": 0.99}]},
        disclose=True,
    )
    return {
        "schema": "glassbox.transparency_log/2",
        "public_key_ed25519_hex": key.public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
        .hex(),
        "entries": [first, second],
        "payload_disclosure": {
            "payload_schema": "canli.alphac-track-record-daily-digest.v1",
            "first_disclosed_seq": 1,
            "disclosed_entries": 1,
            "opaque_historical_entries": 1,
        },
    }


def _verify(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFIER), str(path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def test_verifier_accepts_a_disclosed_payload_after_an_explicit_opaque_epoch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "transparency_log.json"
    path.write_text(json.dumps(_document()))
    result = _verify(path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "disclosed payloads: 1" in result.stdout
    assert "opaque historical commitments: 1" in result.stdout


def test_verifier_rejects_payload_content_that_no_longer_matches_its_signed_hash(
    tmp_path: Path,
) -> None:
    document = _document()
    document["entries"][1]["payload"]["book_live"][0]["equity"] = 1.5  # type: ignore[index]
    path = tmp_path / "transparency_log.json"
    path.write_text(json.dumps(document))
    result = _verify(path)
    assert result.returncode != 0
    assert "transparency payload hash mismatch" in result.stdout


def test_next_site_does_not_restore_absolute_chain_claims() -> None:
    site = REPO.parent / "meridian-app"
    sources = "\n".join(
        (site / path).read_text()
        for path in (
            "components/marketing/HowItWorksFigures.tsx",
            "components/dashboard/ProvenancePanel.tsx",
        )
    )
    assert "provably append-only" not in sources
    assert "Every published day" not in sources
    assert "stamped into Bitcoin" not in sources


@pytest.mark.workspace_evidence
def test_current_public_chain_has_an_honest_rehashable_boundary() -> None:
    primary = REPO.parent / "meridian" / "public" / "glassbox" / "transparency_log.json"
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / "transparency_log.json"
    assert primary.read_bytes() == app.read_bytes()
    document = json.loads(primary.read_text())
    disclosure = document["payload_disclosure"]
    entries = document["entries"]
    first = disclosure["first_disclosed_seq"]

    assert document["schema"] == "glassbox.transparency_log/2"
    assert first is not None
    assert disclosure["opaque_historical_entries"] == first
    assert disclosure["disclosed_entries"] == len(entries) - first
    assert all("payload" not in entry for entry in entries[:first])
    assert all("payload" in entry for entry in entries[first:])
    for entry in entries[first:]:
        assert _sha256(_canonical(entry["payload"])) == entry["payload_sha256"]


@pytest.mark.workspace_evidence
def test_every_published_timestamp_proof_binds_its_head_file_and_declared_status() -> None:
    roots = (
        REPO.parent / "meridian" / "public" / "glassbox" / "ots",
        REPO.parent / "meridian-app" / "public" / "glassbox" / "ots",
    )
    assert (roots[0] / "anchors.json").read_bytes() == (
        roots[1] / "anchors.json"
    ).read_bytes()
    manifest = json.loads((roots[0] / "anchors.json").read_text())
    statuses = [anchor["status"] for anchor in manifest["anchors"]]
    assert manifest["bitcoin_confirmed_count"] == statuses.count("bitcoin")
    assert manifest["calendar_pending_count"] == statuses.count("pending")
    assert manifest["anchor_count"] == len(manifest["anchors"])

    for anchor in manifest["anchors"]:
        head = roots[0] / anchor["head_file"]
        proof = roots[0] / anchor["ots_file"]
        assert head.read_bytes() == (roots[1] / anchor["head_file"]).read_bytes()
        assert proof.read_bytes() == (roots[1] / anchor["ots_file"]).read_bytes()
        assert f"chain_hash: {anchor['chain_hash']}" in head.read_text()
        detached = DetachedTimestampFile.deserialize(
            BytesDeserializationContext(proof.read_bytes())
        )
        assert detached.timestamp.msg == hashlib.sha256(head.read_bytes()).digest()
        bitcoin = [
            attestation
            for _, attestation in detached.timestamp.all_attestations()
            if isinstance(attestation, BitcoinBlockHeaderAttestation)
        ]
        if anchor["status"] == "bitcoin":
            assert bitcoin
            assert anchor["bitcoin_block_height"] in {
                attestation.height for attestation in bitcoin
            }
        else:
            assert not bitcoin
