#!/usr/bin/env python3
"""Publish a hash-only manifest for private ``prereg_investment`` replay inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
SNAPSHOT: Final = ROOT / "data/reproduction/prereg_investment_raw_upstream_20260824"
PRIVATE_RECEIPT: Final = SNAPSHOT / "reconstruction_complete.json"
PRIVATE_INVENTORY: Final = SNAPSHOT / "input_inventory.jsonl"
LINEAGE: Final = ROOT / "artifacts/publication/prereg_investment_historical_lineage.json"
OUTPUT: Final = ROOT / "artifacts/publication/prereg_investment_upstream_replay_manifest.json"
SOURCE_COMMIT: Final = "8417cb850a27306b30f6c70365c3565f3d209ddf"
EXPECTED_EQUITY_SHA256: Final = "e81f22c716da8590ee0a7129760ffa65f56b6967f8ef8c3c2ed86845cdf1645b"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _private_records() -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in PRIVATE_INVENTORY.read_text(encoding="utf-8").splitlines()
        if line
    ]
    for record in records:
        path = SNAPSHOT / record["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
            raise ValueError(f"private input binding failed: {path}")
    return records


def build() -> dict[str, Any]:
    for path in (PRIVATE_RECEIPT, PRIVATE_INVENTORY, LINEAGE):
        if not path.is_file():
            raise FileNotFoundError(path)
    private = json.loads(PRIVATE_RECEIPT.read_text(encoding="utf-8"))
    lineage = json.loads(LINEAGE.read_text(encoding="utf-8"))
    records = _private_records()
    private_snapshot = private["private_snapshot"]
    if len(records) != private_snapshot["files_excluding_inventory_and_receipt"]:
        raise ValueError("private input file count drifted")
    if _sha256(PRIVATE_INVENTORY) != private_snapshot["inventory_sha256"]:
        raise ValueError("private inventory binding drifted")
    if private["private_reference"]["equity_sha256"] != EXPECTED_EQUITY_SHA256:
        raise ValueError("private reference equity binding drifted")
    if lineage["source"]["predecessor_commit"] != SOURCE_COMMIT:
        raise ValueError("lineage source commit binding drifted")

    document: dict[str, Any] = {
        "schema": "canli.alphac-prereg-investment-upstream-replay-manifest.v1",
        "author": "Arhan Canli",
        "evidence_date": "2026-08-24",
        "status": (
            "SEALED_PRIVATE_RAW_INPUTS_WITH_ARTIFACT_INFORMED_ZERO_HELD_"
            "CRYPTO_MEMBERSHIP_REPLAY_PENDING"
        ),
        "classification": {
            "artifact_role": "HISTORICAL_GATE_INPUT_ONLY",
            "not_a_sleeve": True,
            "later_preregistration_covered_historical_run": False,
        },
        "historical_run": {
            "source": lineage["source"],
            "strategy_command": lineage["historical_run"]["expanded_strategy_command"],
            "upstream_replay_commands": [
                "uv run python scripts/sharadar_load.py --min-dollar 500000",
                ("uv run af universe rebuild --profile equity --start 2000-01-01 --end 2026-06-01"),
                lineage["historical_run"]["expanded_strategy_command"],
            ],
        },
        "private_input_snapshot": {
            "files": len(records),
            "bytes": sum(record["bytes"] for record in records),
            "tree_hash": private_snapshot["tree_hash"],
            "inventory_sha256": private_snapshot["inventory_sha256"],
            "raw_vendor_archives": [
                {
                    "name": Path(record["path"]).name,
                    "bytes": record["bytes"],
                    "sha256": record["sha256"],
                }
                for record in private["raw_vendor_archives"]
            ],
            "instrument_state": {
                "rows": private["instrument_state"]["rows"],
                "rows_by_venue": private["instrument_state"]["rows_by_venue"],
                "sha256": private["instrument_state"]["sha256"],
            },
            "experiment_context": {
                "distinct_trials": private["experiment_context"]["distinct_trials"],
                "sample_variance": private["experiment_context"]["sample_variance"],
                "sha256": private["experiment_context"]["sha256"],
            },
            "crypto_membership": private["crypto_membership"],
            "raw_or_normalized_rows_redistributed": False,
        },
        "private_reference_output": {
            "files": private["private_reference"]["files"],
            "bytes": private["private_reference"]["bytes"],
            "equity_sha256": private["private_reference"]["equity_sha256"],
            "redistributed": False,
        },
        "lineage_binding": {
            "path": str(LINEAGE.relative_to(ROOT)),
            "sha256": _sha256(LINEAGE),
            "content_hash": lineage["content_hash"],
        },
        "replay_status": {
            "clean_workspace_completed": False,
            "strategy_output_equivalence_established": False,
            "independent_human_reproduction_completed": False,
        },
        "rights_and_release": private["rights_and_release"],
        "claim_boundary": (
            "This public manifest binds a private raw-input packet and comparison target without "
            "redistributing licensed rows. The 60 zero-held Binance membership intervals are "
            "artifact-informed minimal reconstructions. The manifest does not establish exact "
            "historical input recovery, strategy-output equivalence, valid prospective evidence, "
            "sleeve admission, or independent reproduction."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = cast(dict[str, Any], json.loads(OUTPUT.read_text(encoding="utf-8")))
    if document.get("content_hash") != _content_hash(document):
        raise ValueError("published prereg_investment input manifest content hash is invalid")
    return document


def main() -> int:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
