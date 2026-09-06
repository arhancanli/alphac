#!/usr/bin/env python3
"""Seal the private inputs and reference output for AlphaTrend's 2026-08-23 replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
SNAPSHOT: Final = ROOT / "data/reproduction/alphatrend_mf_live_fwd_20260823"
REFERENCE: Final = (
    ROOT
    / "artifacts/reproduction_private/alphatrend_mf_live_fwd_20260823/reference_output"
)
OUTPUT: Final = ROOT / "artifacts/publication/alphatrend_upstream_replay_manifest.json"
SOURCE_COMMIT: Final = "577555f12636e4df81e42a3940184678d0cceb7e"
EXPECTED_INPUT_FILES: Final = 410
EXPECTED_REFERENCE_FILES: Final = 467
EXPECTED_EQUITY_SHA256: Final = (
    "e3ccf8948e3dd1626d1d7c089d4a301817cc4c7e9b55b87870b305e663669041"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _records(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    return [
        {
            "path": str(path.relative_to(directory)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    ]


def _tree_hash(records: list[dict[str, Any]]) -> str:
    return f"sha256:{hashlib.sha256(_canonical(records)).hexdigest()}"


def build() -> dict[str, Any]:
    inputs = _records(SNAPSHOT)
    reference = _records(REFERENCE)
    if len(inputs) != EXPECTED_INPUT_FILES:
        raise ValueError(f"input snapshot file count drifted: {len(inputs)}")
    if len(reference) != EXPECTED_REFERENCE_FILES:
        raise ValueError(f"reference output file count drifted: {len(reference)}")
    equity = REFERENCE / "equity.parquet"
    if _sha256(equity) != EXPECTED_EQUITY_SHA256:
        raise ValueError("reference equity curve no longer matches the sealed target")

    input_paths = {record["path"] for record in inputs}
    required_state = {"var_mf/ops.sqlite", "var_mf/experiments.jsonl"}
    if not required_state.issubset(input_paths):
        raise ValueError("private snapshot is missing required instrument or experiment state")
    market_files = [record for record in inputs if record["path"].startswith("lake_mf/")]
    if len(market_files) != 408:
        raise ValueError(f"expected 408 frozen market-lake files, found {len(market_files)}")

    document: dict[str, Any] = {
        "schema": "canli.alphac-alphatrend-upstream-replay-manifest.v1",
        "author": "Arhan Canli",
        "evidence_date": "2026-08-24",
        "status": "SEALED_LOCAL_INPUTS_AND_REFERENCE_OUTPUT_RIGHTS_WITHHELD",
        "historical_run": {
            "run_started_utc": "2026-08-23T05:30:04Z",
            "run_finished_utc": "2026-08-23T05:31:55Z",
            "declared_end_exclusive": "2026-08-24",
            "source_commit_reconstruction": SOURCE_COMMIT,
            "command": (
                ".venv/bin/python3 scripts/mf_gauntlet.py "
                "--alphas mf_trend_63,mf_trend_126,mf_trend_252 "
                "--rebalance 10 --cash 100000 --start 2003-01-01 "
                "--end 2026-08-24 --out artifacts/walkforward/mf_live_fwd"
            ),
            "operational_log": {
                "path": "var/log/mf_tick.log",
                "redistributed": False,
                "reason": "The log includes broker-operational detail outside this replay packet.",
            },
        },
        "private_input_snapshot": {
            "path": str(SNAPSHOT.relative_to(ROOT)),
            "files": len(inputs),
            "bytes": sum(record["bytes"] for record in inputs),
            "tree_content_hash": _tree_hash(inputs),
            "records": inputs,
            "market_lake_files": len(market_files),
            "instrument_state_files": 1,
            "experiment_context_files": 1,
            "copied_before_next_scheduled_vendor_refresh": True,
        },
        "private_reference_output": {
            "path": str(REFERENCE.relative_to(ROOT)),
            "files": len(reference),
            "bytes": sum(record["bytes"] for record in reference),
            "tree_content_hash": _tree_hash(reference),
            "equity_parquet_sha256": EXPECTED_EQUITY_SHA256,
            "records": reference,
        },
        "rights_and_release": {
            "market_source": "Yahoo Finance chart endpoint; adjusted daily ETF bars",
            "raw_or_normalized_rows_publication_authorized": False,
            "private_snapshot_may_be_published": False,
            "hash_manifest_may_be_published": True,
            "public_bundle_must_withhold_private_snapshot_and_reference_rows": True,
            "fresh_reacquisition_is_not_claimed_by_this_manifest": True,
        },
        "claim_boundary": (
            "This manifest binds a local author-workspace snapshot and the historical derived "
            "output. It does not establish redistribution rights, fresh vendor reacquisition, "
            "an independent reproduction, or an exact reconstruction of the historical DSR "
            "selection context."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    published = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if published.get("content_hash") != _content_hash(published):
        raise ValueError("published AlphaTrend replay manifest content hash is invalid")
    rebuilt = build()
    if published != rebuilt:
        raise ValueError("published AlphaTrend replay manifest differs from sealed local files")
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
