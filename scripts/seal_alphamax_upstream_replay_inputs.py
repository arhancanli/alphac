#!/usr/bin/env python3
"""Seal a public hash manifest for AlphaMax's private reacquired replay inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
SNAPSHOT: Final = ROOT / "data/reproduction/alphamax_k30_dn_63_polygon_reacquired_20260824"
ACQUISITION: Final = SNAPSHOT / "acquisition_complete.json"
REFERENCE: Final = (
    ROOT / "artifacts/reproduction_private/alphamax_k30_dn_63_20260620/reference_output"
)
OUTPUT: Final = ROOT / "artifacts/publication/alphamax_upstream_replay_manifest.json"
SOURCE_COMMIT: Final = "fd3e930f41b0a62b222ecda4ab83bae21a4ce9f2"
EXPECTED_EQUITY_SHA256: Final = "76f82c8df3726f049144d7699c0f13069db6a1e0d1f1e4570babd8d82a85cfc9"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _validate_acquisition(document: dict[str, Any]) -> None:
    if document.get("content_hash") != _content_hash(document):
        raise ValueError("AlphaMax private acquisition receipt content hash is invalid")
    if document.get("status") != (
        "PASS_AVAILABLE_VENDOR_REACQUISITION_WINDOW_UNION_EXACT_"
        "FULL_LOOKBACK_GAP_DISCLOSED_REPLAY_PENDING"
    ):
        raise ValueError("AlphaMax private acquisition has not passed")
    if document["historical_run"]["source_commit"] != SOURCE_COMMIT:
        raise ValueError("AlphaMax source commit binding drifted")
    if not document["universe"]["strategy_window_instrument_id_set_exact"]:
        raise ValueError("AlphaMax reacquired strategy-window universe union is not exact")
    if document["universe"]["strategy_window_instrument_ids"] != 375:
        raise ValueError("AlphaMax reacquired strategy-window universe id count drifted")
    if document["vendor_reacquisition"]["full_historical_universe_lookback_reacquired"]:
        raise ValueError("AlphaMax acquisition overstates the unavailable full lookback")
    if document["vendor_reacquisition"]["strategy_sufficiency_established"]:
        raise ValueError("AlphaMax acquisition overstates pre-replay strategy sufficiency")
    gap = document["vendor_reacquisition"]["entitlement_gap"]
    if (
        gap["failed_sessions"] != 58
        or not gap["gap_intersects_global_feature_context"]
        or gap["acquisition_alone_establishes_strategy_sufficiency"]
    ):
        raise ValueError("AlphaMax entitlement-gap boundary drifted or is overstated")
    for record in document["snapshot"]["records"]:
        path = SNAPSHOT / record["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != record["bytes"] or _sha256(path) != record["sha256"]:
            raise ValueError(f"AlphaMax private input binding failed: {path}")


def _reference_records() -> list[dict[str, Any]]:
    if not REFERENCE.is_dir():
        raise FileNotFoundError(REFERENCE)
    records = [
        {
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(REFERENCE.iterdir())
        if path.is_file()
    ]
    equity = next(record for record in records if record["path"] == "equity.parquet")
    if equity["sha256"] != EXPECTED_EQUITY_SHA256:
        raise ValueError("AlphaMax reference equity hash drifted")
    return records


def build() -> dict[str, Any]:
    acquisition = json.loads(ACQUISITION.read_text(encoding="utf-8"))
    _validate_acquisition(acquisition)
    reference = _reference_records()
    document: dict[str, Any] = {
        "schema": "canli.alphac-alphamax-upstream-replay-manifest.v1",
        "author": "Arhan Canli",
        "evidence_date": "2026-08-24",
        "status": (
            "SEALED_AVAILABLE_VENDOR_REACQUISITION_FULL_LOOKBACK_GAP_"
            "DISCLOSED_REPLAY_PENDING_RIGHTS_WITHHELD"
        ),
        "historical_run": acquisition["historical_run"],
        "source_reconstruction": {
            "commit": SOURCE_COMMIT,
            "git_archive_sha256": acquisition["source"]["git_archive_sha256"],
            "tracked_source_reconstruction": acquisition["source"]["tracked_source_reconstruction"],
            "full_dirty_historical_source_tree_recovered": False,
            "basis": (
                "The exact run command appears in the 2026-06-20 author/Claude transcript. "
                "The run completed immediately before the dollar-neutral implementation was "
                "committed; no intervening tracked-source edit appears in that transcript. "
                "The clean replay, not chronology alone, determines strategy equivalence."
            ),
        },
        "private_input_snapshot": {
            "path": str(SNAPSHOT.relative_to(ROOT)),
            "files": acquisition["snapshot"]["files"],
            "bytes": acquisition["snapshot"]["bytes"],
            "tree_content_hash": acquisition["snapshot"]["tree_content_hash"],
            "private_inventory_receipt": {
                "path": str(ACQUISITION.relative_to(ROOT)),
                "sha256": _sha256(ACQUISITION),
                "content_hash": acquisition["content_hash"],
            },
            "instrument_store": acquisition["reconstruction"]["instrument_store"],
            "experiment_ledger": acquisition["reconstruction"]["experiment_ledger"],
            "universe": acquisition["universe"],
            "vendor_reacquisition": acquisition["vendor_reacquisition"],
        },
        "private_reference_output": {
            "path": str(REFERENCE.relative_to(ROOT)),
            "files": len(reference),
            "records": reference,
            "equity_parquet_sha256": EXPECTED_EQUITY_SHA256,
        },
        "rights_and_release": acquisition["rights_and_release"],
        "claim_boundary": (
            "This manifest binds freshly reacquired private Polygon inputs from 2021-08-23, the "
            "reconstructed historical instrument and 27-trial DSR state, an exact 375-id rebuilt "
            "universe union over the strategy window, the disclosed 58-session full-lookback "
            "entitlement gap, and the surviving five-file historical reference output. It does "
            "not by itself establish strategy sufficiency, an exact full 2021-06 universe "
            "rebuild, unchanged vendor "
            "rows, exact per-date memberships, an exact strategy curve, full historical source "
            "recovery, redistribution rights, or independent reproduction. The clean-workspace "
            "comparison adjudicates the output claims without regrading the stored historical "
            "result."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    published = cast(dict[str, Any], json.loads(OUTPUT.read_text(encoding="utf-8")))
    if published.get("content_hash") != _content_hash(published):
        raise ValueError("published AlphaMax replay manifest content hash is invalid")
    rebuilt = build()
    if published != rebuilt:
        raise ValueError("published AlphaMax replay manifest differs from private inputs")
    return published


def main() -> int:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
