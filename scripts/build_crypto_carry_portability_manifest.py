#!/usr/bin/env python3
"""Inventory every frozen input needed before attempting crypto-carry reacquisition."""

from __future__ import annotations

import glob
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Final

import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
WALKFORWARD: Final = ROOT / "artifacts/walkforward/crypto_carry_wk/walkforward.json"
OPS_DB: Final = ROOT / "var/ops.sqlite"
OUTPUT: Final = ROOT / "artifacts/publication/crypto_carry_portability_manifest.json"
DATA_ROOT: Final = ROOT / "data/lake"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _files(dataset: str, instrument_id: str) -> list[Path]:
    pattern = str(DATA_ROOT / dataset / f"instrument_id={instrument_id}" / "**/*.parquet")
    return sorted(Path(value) for value in glob.glob(pattern, recursive=True))


def _archive_url(kind: str, symbol: str, month: str) -> str:
    if kind == "klines":
        suffix = f"{symbol}-1h-{month}.zip"
        return f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/1h/{suffix}"
    suffix = f"{symbol}-fundingRate-{month}.zip"
    return f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{symbol}/{suffix}"


def _dataset_record(
    dataset: str, instrument_id: str, start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, Any]:
    files = _files(dataset, instrument_id)
    time_column = "ts_open" if dataset == "ohlcv" else "ts_funding"
    frames = [pd.read_parquet(path, columns=[time_column]) for path in files]
    timestamps = (
        pd.concat(frames, ignore_index=True)[time_column] if frames else pd.Series(dtype="object")
    )
    timestamps = pd.to_datetime(timestamps, utc=True)
    timestamps = (
        timestamps[(timestamps >= start) & (timestamps < end)].drop_duplicates().sort_values()
    )
    months = sorted(timestamps.dt.strftime("%Y-%m").unique().tolist())
    symbol = instrument_id.rsplit(":", 1)[-1]
    kind = "klines" if dataset == "ohlcv" else "fundingRate"
    archives = [
        {
            "month": month,
            "url": _archive_url(kind, symbol, month),
            "checksum_url": _archive_url(kind, symbol, month) + ".CHECKSUM",
        }
        for month in months
    ]
    return {
        "dataset": dataset,
        "rows_in_frozen_window": len(timestamps),
        "first_timestamp": timestamps.iloc[0].isoformat() if len(timestamps) else None,
        "last_timestamp": timestamps.iloc[-1].isoformat() if len(timestamps) else None,
        "local_files": [
            {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)} for path in files
        ],
        "official_monthly_archives": archives,
    }


def _instrument_metadata(ids: list[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in ids)
    query = f"""
        SELECT instrument_id, funding_interval_hours, listed_ts, delisted_ts,
               valid_from_ms, valid_to_ms
        FROM instruments_v
        WHERE valid_to_ms IS NULL AND instrument_id IN ({placeholders})
        ORDER BY instrument_id
    """
    with sqlite3.connect(OPS_DB) as connection:
        rows = connection.execute(query, ids).fetchall()
    return [
        {
            "instrument_id": row[0],
            "funding_interval_hours": row[1],
            "listed_ts": row[2],
            "delisted_ts": row[3],
            "valid_from_ms": row[4],
            "valid_to_ms": row[5],
        }
        for row in rows
    ]


def build() -> dict[str, Any]:
    walkforward = json.loads(WALKFORWARD.read_text())
    config = walkforward["config"]
    ids = list(config["instrument_ids"])
    start = pd.Timestamp(config["start"], unit="ms", tz="UTC")
    end = pd.Timestamp(config["end"], unit="ms", tz="UTC")
    records = []
    for instrument_id in ids:
        records.append(
            {
                "instrument_id": instrument_id,
                "symbol": instrument_id.rsplit(":", 1)[-1],
                "ohlcv": _dataset_record("ohlcv", instrument_id, start, end),
                "funding": _dataset_record("funding", instrument_id, start, end),
            }
        )
    metadata = _instrument_metadata(ids)
    failures = []
    if len(records) != 58:
        failures.append("FROZEN_UNIVERSE_NOT_58_INSTRUMENTS")
    if len(metadata) != len(ids):
        failures.append("CURRENT_INSTRUMENT_METADATA_INCOMPLETE")
    if any(not record["ohlcv"]["rows_in_frozen_window"] for record in records):
        failures.append("ONE_OR_MORE_INSTRUMENTS_HAVE_NO_OHLCV_IN_WINDOW")
    if any(not record["funding"]["rows_in_frozen_window"] for record in records):
        failures.append("ONE_OR_MORE_INSTRUMENTS_HAVE_NO_FUNDING_IN_WINDOW")

    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-portability-manifest.v1",
        "author": "Arhan Canli",
        "status": "PASS_FROZEN_SOURCE_INVENTORY_NOT_FRESH_ACQUISITION" if not failures else "FAIL",
        "passes": not failures,
        "frozen_run": {
            "path": str(WALKFORWARD.relative_to(ROOT)),
            "sha256": _sha256(WALKFORWARD),
            "start_inclusive": start.isoformat(),
            "end_exclusive": end.isoformat(),
            "instrument_count": len(ids),
            "alpha_names": config["alpha_names"],
            "allocator": config["allocator"],
            "rebalance_bars": config["rebalance_bars"],
            "train_bars": config["train_bars"],
            "test_bars": config["test_bars"],
            "embargo_bars": config["embargo_bars"],
            "purge_bars": config["purge_bars"],
            "no_trade_band": config["no_trade_band"],
        },
        "source": {
            "venue": "Binance USD-M Futures",
            "official_archive_project": "https://github.com/binance/binance-public-data",
            "official_archive_root": "https://data.binance.vision",
            "official_s3_path_style_root": (
                "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision"
            ),
            "credential_required": False,
            "archive_checksums_declared": True,
        },
        "instrument_metadata": metadata,
        "records": records,
        "totals": {
            "ohlcv_rows": sum(record["ohlcv"]["rows_in_frozen_window"] for record in records),
            "funding_rows": sum(record["funding"]["rows_in_frozen_window"] for record in records),
            "official_archive_objects": sum(
                len(record[dataset]["official_monthly_archives"])
                for record in records
                for dataset in ("ohlcv", "funding")
            ),
            "bound_local_parquet_files": sum(
                len(record[dataset]["local_files"])
                for record in records
                for dataset in ("ohlcv", "funding")
            ),
        },
        "availability_time_reconstruction": {
            "source_archive_provides_publication_timestamp": False,
            "frozen_lake_rule": "available_at = ts_funding + 5 minutes",
            "must_be_reconstructed_and_disclosed": True,
        },
        "fresh_archive_download_executed": False,
        "full_walkforward_replayed": False,
        "independent_replication": False,
        "failures": failures,
        "claim_boundary": (
            "This manifest binds the frozen 58-instrument run to its local hourly-bar, funding, "
            "and current instrument-metadata inventory and enumerates official monthly archive "
            "URLs and checksums. It does not prove those archives remain reachable, recreate "
            "historical universe or metadata state, perform a fresh download, replay the 25-leg "
            "walk-forward, establish redistribution permission, or constitute independent review."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = json.loads(OUTPUT.read_text())
    if document.get("content_hash") != _content_hash(document):
        raise RuntimeError("published crypto-carry portability manifest hash is invalid")
    current = build()
    if document != current:
        # The published manifest is a historical frozen-input inventory sealed
        # into the prospective trial, not a promise that mutable lake paths will
        # retain those exact bytes forever.  Preserve its original file hashes.
        # A current-lake comparison may differ only in those per-file hashes;
        # identities, paths, row counts, time bounds, run configuration, metadata,
        # source declarations, and all claim boundaries must remain identical.
        def semantic_inventory(value: dict[str, Any]) -> dict[str, Any]:
            projected = json.loads(json.dumps(value))
            projected.pop("content_hash", None)
            for record in projected.get("records", []):
                for dataset in ("ohlcv", "funding"):
                    for binding in record[dataset].get("local_files", []):
                        binding.pop("sha256", None)
            return projected

        if semantic_inventory(document) != semantic_inventory(current):
            raise RuntimeError("published crypto-carry portability manifest is substantively stale")
    return document


def main() -> None:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {OUTPUT}")
    print(json.dumps(document["totals"], indent=2, sort_keys=True))
    print(f"content_hash: {document['content_hash']}")
    if not document["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
