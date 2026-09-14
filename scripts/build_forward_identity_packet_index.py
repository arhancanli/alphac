#!/usr/bin/env python3
"""Index every forward-epoch identity packet for publication, bound by hash to its closure.

WHY. The legacy index (artifacts/research/trial_packets/index.json) is sealed at 228 identities
by the legacy epoch closure and cannot grow. Every identity measured since is a row of the
prospective-epoch register, and each has (or is owed) a packet in the same directory: the 118
imported development identities closed KILL on 2026-09-14, the governed crypto carry identity,
and every v2 batch identity the seal closes. Until this index existed those packets were on disk
and off the site; the published count said 228 + 1.

One row per register identity. A row with a packet binds the packet's file hash and content hash
(verified here, refused on mismatch) and its final closure; a row whose packet the seal has not
yet written is listed as PACKET_PENDING_SEAL with no public path, so the record names the debt
rather than hiding the identity. No key may appear in both the legacy and the forward index.

Reads the register, the legacy index and the packets; computes nothing about returns.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from alphaforge.validation.trial_reservation import (  # noqa: E402
    IDENTITY_PACKET_DIR,
    _observed_content_hash,
)

REGISTER_RELATIVE: Final[Path] = Path("artifacts/research/prospective_epoch_register.json")
LEGACY_INDEX_RELATIVE: Final[Path] = Path("artifacts/research/trial_packets/index.json")
OUTPUT_RELATIVE: Final[Path] = Path("artifacts/research/trial_packets/forward_index.json")
assert OUTPUT_RELATIVE.parent == IDENTITY_PACKET_DIR == LEGACY_INDEX_RELATIVE.parent
SCHEMA: Final[str] = "canli.alphac-forward-identity-packet-index.v1"
PUBLIC_DIR: Final[str] = "/glassbox/trial-packets"
PACKET_PENDING: Final[str] = "PACKET_PENDING_SEAL"
AUTHOR: Final[str] = "Arhan Canli"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_hashed(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("content_hash") != _observed_content_hash(payload):
        raise ValueError(f"content hash mismatch: {path}")
    return payload


def build(repo: Path = REPO, *, now: dt.datetime | None = None) -> dict[str, Any]:
    register = _load_hashed(repo / REGISTER_RELATIVE)
    legacy_index = _load_hashed(repo / LEGACY_INDEX_RELATIVE)
    legacy_keys = {str(row["hypothesis_key"]) for row in legacy_index["packets"]}
    rows: list[dict[str, Any]] = []
    for identity in register["identities"]:
        key = str(identity["hypothesis_key"])
        if key in legacy_keys:
            raise ValueError(f"identity {key} is in both the legacy index and the register")
        packet_path = repo / IDENTITY_PACKET_DIR / f"{key}.json"
        row: dict[str, Any] = {
            "hypothesis_key": key,
            "config_hash": identity["config_hash"],
            "research_family_key": identity["family_trial_account"],
            "return_identity_id": identity["return_identity_id"],
            "reservation_ordinal": identity["reservation_ordinal"],
            "register_status": identity["status"],
            "source": identity["source"]["kind"],
            "closure": {
                "path": identity["closure_path"],
                "kind": identity["closure_kind"],
                "schema": identity["closure_schema"],
                "final_disposition": identity["final_disposition"],
                "admitted": identity["admitted"],
            },
        }
        if not packet_path.is_file():
            row.update(
                {
                    "packet_status": PACKET_PENDING,
                    "public_path": None,
                    "packet_content_hash": None,
                    "packet_file_sha256": None,
                    "label": None,
                    "complete": False,
                }
            )
            rows.append(row)
            continue
        packet = _load_hashed(packet_path)
        if packet.get("hypothesis_key") != key:
            raise ValueError(f"{packet_path}: packet key does not match its file name")
        row.update(
            {
                "packet_status": packet["packet_status"],
                "public_path": f"{PUBLIC_DIR}/{key}.json",
                "packet_content_hash": packet["content_hash"],
                "packet_file_sha256": _sha256(packet_path),
                "label": packet.get("label"),
                "complete": bool(packet.get("complete")),
            }
        )
        rows.append(row)
    published = [r for r in rows if r["public_path"] is not None]
    by_packet_status: dict[str, int] = {}
    for row in rows:
        by_packet_status[row["packet_status"]] = by_packet_status.get(row["packet_status"], 0) + 1
    by_disposition: dict[str, int] = {}
    for row in rows:
        disposition = row["closure"]["final_disposition"] or "(unclosed)"
        by_disposition[disposition] = by_disposition.get(disposition, 0) + 1
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "author": AUTHOR,
        "generated_at": (now or dt.datetime.now(dt.UTC)).isoformat(),
        "claim_boundary": (
            "One row per identity measured after the legacy epoch closed, bound by hash to its "
            "published packet and its final closure. A packet being complete means every "
            "required accounting section is evidenced; it does not mean the trial passed, was "
            "admitted, or predicts returns. A PACKET_PENDING_SEAL row is an identity whose "
            "packet the seal has not yet written; it is listed so the debt is visible."
        ),
        "source_bindings": {
            "prospective_epoch_register": {
                "path": str(REGISTER_RELATIVE),
                "content_hash": register["content_hash"],
            },
            "legacy_identity_packet_index": {
                "path": str(LEGACY_INDEX_RELATIVE),
                "content_hash": legacy_index["content_hash"],
                "identities": len(legacy_keys),
            },
        },
        "summary": {
            "forward_identities": len(rows),
            "published_packets": len(published),
            "pending_packets": len(rows) - len(published),
            "complete_packets": sum(1 for r in published if r["complete"]),
            "closed_identities": sum(1 for r in rows if r["closure"]["path"] is not None),
            "admitted_identities": sum(1 for r in rows if r["closure"]["admitted"]),
            "by_packet_status": dict(sorted(by_packet_status.items())),
            "by_final_disposition": dict(sorted(by_disposition.items())),
            "legacy_identities": len(legacy_keys),
            "identities_in_both_epochs": 0,
        },
        "packets": rows,
    }
    payload["content_hash"] = _observed_content_hash(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    payload = build(repo)
    out = repo / OUTPUT_RELATIVE
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = payload["summary"]
    print(
        f"forward identity packets: {summary['published_packets']} published, "
        f"{summary['pending_packets']} pending, {summary['closed_identities']} closed, "
        f"{summary['admitted_identities']} admitted -> {OUTPUT_RELATIVE}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
