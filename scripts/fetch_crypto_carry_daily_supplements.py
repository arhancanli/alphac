#!/usr/bin/env python3
"""Fetch checksum-verified official daily archives needed by the crypto-carry replay."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
FETCHER: Final = ROOT / "scripts/fetch_crypto_carry_archives_portable.py"
COMPARISON: Final = ROOT / "artifacts/publication/crypto_carry_fresh_input_comparison.json"


def _fetcher():
    spec = importlib.util.spec_from_file_location("crypto_carry_portable_fetch", FETCHER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {FETCHER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(comparison_path: Path, output: Path, workers: int) -> dict[str, Any]:
    comparison = json.loads(comparison_path.read_text())
    if comparison.get("content_hash") != _content_hash(comparison):
        raise RuntimeError("comparison plan content hash is invalid")
    plan = comparison["daily_ohlcv_fallback_plan"]
    if not plan:
        raise RuntimeError("comparison contains no daily fallback objects")
    fetcher = _fetcher()
    tasks = [
        fetcher.ArchiveTask(
            dataset="ohlcv",
            symbol=row["symbol"],
            month=row["date"],
            url=row["official_url"],
            checksum_url=row["checksum_url"],
        )
        for row in plan
    ]
    archive_root = output / "archives"
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda task: fetcher._acquire_safe(task, archive_root), tasks))
    acquired = [row for row in results if row["passes"]]
    failures = [row for row in results if not row["passes"]]
    normalized = []
    for symbol in sorted({task.symbol for task in tasks}):
        symbol_rows = [row for row in acquired if row["symbol"] == symbol]
        paths = [Path(row["archive_path"]) for row in symbol_rows]
        first_date = min(pd.Timestamp(row["month"], tz="UTC") for row in symbol_rows)
        last_date = max(pd.Timestamp(row["month"], tz="UTC") for row in symbol_rows)
        frame = fetcher._normalize_ohlcv(
            paths,
            symbol,
            int(first_date.timestamp() * 1000),
            int((last_date + pd.Timedelta(days=1)).timestamp() * 1000),
        )
        destination = output / "normalized/ohlcv" / f"{symbol}.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(destination, index=False)
        normalized.append(
            {
                "symbol": symbol,
                "rows": len(frame),
                "sha256": _sha256(destination),
                "path": str(destination),
            }
        )
    passes = not failures and len(acquired) == len(tasks)
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-daily-supplement.v1",
        "author": "Arhan Canli",
        "status": (
            "PASS_OFFICIAL_DAILY_OHLCV_SUPPLEMENT" if passes else "INCOMPLETE_DAILY_SUPPLEMENT"
        ),
        "passes": passes,
        "comparison_plan_binding": {
            "path": str(comparison_path),
            "sha256": _sha256(comparison_path),
            "content_hash": comparison["content_hash"],
        },
        "fallback_plan": plan,
        "archive_objects": [
            {key: value for key, value in row.items() if key not in {"archive_path", "passes"}}
            for row in acquired
        ],
        "unavailable_archive_objects": [
            {key: value for key, value in row.items() if key != "passes"} for row in failures
        ],
        "normalized_objects": normalized,
        "totals": {
            "archive_objects_requested": len(tasks),
            "archive_objects_acquired": len(acquired),
            "archive_objects_unavailable": len(failures),
            "archive_bytes": sum(row["bytes"] for row in acquired),
            "normalized_rows": sum(row["rows"] for row in normalized),
        },
        "strategy_replayed": False,
        "independent_replication": False,
        "claim_boundary": (
            "This receipt proves checksum-verified acquisition and normalization of official "
            "daily OHLCV archives selected by the frozen-versus-fresh gap comparator. A separate "
            "comparison must establish whether they close those gaps."
        ),
    }
    document["content_hash"] = _content_hash(document)
    (output / "source_manifest.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", type=Path, default=COMPARISON)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    arguments = parser.parse_args()
    if not 1 <= arguments.workers <= 32:
        parser.error("--workers must be between 1 and 32")
    document = build(arguments.comparison.resolve(), arguments.output.resolve(), arguments.workers)
    print(json.dumps(document, indent=2, sort_keys=True))
    if not document["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
