#!/usr/bin/env -S uv run --isolated --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pandas==3.0.3",
#   "pyarrow==24.0.0",
# ]
# ///
"""Resume-safe acquisition of frozen crypto-carry inputs from official Binance archives."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Final, NamedTuple

import pandas as pd

BRANDED_ROOT: Final = "https://data.binance.vision"
REGIONAL_ROOT: Final = "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision"
KLINE_COLUMNS: Final = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)
FUNDING_COLUMNS: Final = ("calc_time", "funding_interval_hours", "last_funding_rate")


class ArchiveTask(NamedTuple):
    dataset: str
    symbol: str
    month: str
    url: str
    checksum_url: str

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _regional(url: str) -> str:
    if not url.startswith(BRANDED_ROOT):
        raise ValueError(f"unexpected archive root: {url}")
    return REGIONAL_ROOT + url[len(BRANDED_ROOT) :]


def _request(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "alphac-portable-research/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _download(url: str, destination: Path, retries: int = 4) -> None:
    error: Exception | None = None
    for attempt in range(retries):
        try:
            payload = _request(url)
            temporary = destination.with_name(destination.name + ".part")
            temporary.write_bytes(payload)
            temporary.replace(destination)
            return
        except Exception as exc:
            error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                break
            if attempt + 1 < retries:
                time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"download failed after {retries} attempts: {url}: {error}")


def _expected_checksum(path: Path, filename: str) -> str:
    values = path.read_text().strip().split()
    if len(values) != 2 or values[1].lstrip("*") != filename:
        raise RuntimeError(f"malformed checksum file: {path}")
    if len(values[0]) != 64:
        raise RuntimeError(f"malformed SHA-256 digest: {path}")
    return values[0].lower()


def _acquire(task: ArchiveTask, archive_root: Path) -> dict[str, Any]:
    directory = archive_root / task.dataset / task.symbol
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / task.filename
    checksum = directory / f"{task.filename}.CHECKSUM"
    reused = False
    if checksum.is_file() and archive.is_file():
        try:
            reused = _sha256(archive) == _expected_checksum(checksum, archive.name)
        except (OSError, RuntimeError):
            reused = False
    if not reused:
        _download(_regional(task.checksum_url), checksum)
        _download(_regional(task.url), archive)
    expected = _expected_checksum(checksum, archive.name)
    observed = _sha256(archive)
    if observed != expected:
        raise RuntimeError(f"checksum mismatch after acquisition: {archive}")
    return {
        "passes": True,
        "dataset": task.dataset,
        "symbol": task.symbol,
        "month": task.month,
        "filename": task.filename,
        "official_url": task.url,
        "regional_official_url": _regional(task.url),
        "sha256": observed,
        "bytes": archive.stat().st_size,
        "cache_reused": reused,
        "archive_path": str(archive),
    }


def _acquire_safe(task: ArchiveTask, archive_root: Path) -> dict[str, Any]:
    try:
        return _acquire(task, archive_root)
    except Exception as exc:  # acquisition boundary must preserve every failed object
        return {
            "passes": False,
            "dataset": task.dataset,
            "symbol": task.symbol,
            "month": task.month,
            "filename": task.filename,
            "official_url": task.url,
            "regional_official_url": _regional(task.url),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _csv_from_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"expected one CSV in {path}")
        payload = archive.read(names[0])
    first_token = payload.split(b",", 1)[0].strip()
    if first_token in {b"open_time", b"calc_time"}:
        return pd.read_csv(io.BytesIO(payload))
    field_count = payload.splitlines()[0].count(b",") + 1
    if field_count == len(KLINE_COLUMNS):
        return pd.read_csv(io.BytesIO(payload), header=None, names=KLINE_COLUMNS)
    if field_count == len(FUNDING_COLUMNS):
        return pd.read_csv(io.BytesIO(payload), header=None, names=FUNDING_COLUMNS)
    raise RuntimeError(f"unrecognized headerless archive schema in {path}: {field_count} fields")


def _normalize_ohlcv(paths: list[Path], symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    source = pd.concat([_csv_from_zip(path) for path in paths], ignore_index=True)
    source = source[(source["open_time"] >= start_ms) & (source["open_time"] < end_ms)]
    output = pd.DataFrame(
        {
            "instrument_id": f"BINANCE:PERP:{symbol}",
            "ts_open": pd.to_datetime(source["open_time"], unit="ms", utc=True),
            "open": pd.to_numeric(source["open"]),
            "high": pd.to_numeric(source["high"]),
            "low": pd.to_numeric(source["low"]),
            "close": pd.to_numeric(source["close"]),
            "volume": pd.to_numeric(source["volume"]),
            "quote_volume": pd.to_numeric(source["quote_volume"]),
            "n_trades": pd.to_numeric(source["count"]).astype("int64"),
            "quality_flags": 0,
        }
    )
    return output.drop_duplicates("ts_open", keep="last").sort_values("ts_open").reset_index(
        drop=True
    )


def _normalize_funding(paths: list[Path], symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    source = pd.concat([_csv_from_zip(path) for path in paths], ignore_index=True)
    source = source[(source["calc_time"] >= start_ms) & (source["calc_time"] < end_ms)]
    timestamps = pd.to_datetime(source["calc_time"], unit="ms", utc=True)
    output = pd.DataFrame(
        {
            "instrument_id": f"BINANCE:PERP:{symbol}",
            "ts_funding": timestamps,
            "rate": pd.to_numeric(source["last_funding_rate"]),
            "funding_interval_hours": pd.to_numeric(source["funding_interval_hours"]).astype(
                "int64"
            ),
            "available_at": timestamps + pd.Timedelta(minutes=5),
        }
    )
    return output.drop_duplicates("ts_funding", keep="last").sort_values(
        "ts_funding"
    ).reset_index(drop=True)


def _tasks(
    manifest: dict[str, Any], symbols: set[str] | None, months: set[str] | None
) -> list[ArchiveTask]:
    tasks: list[ArchiveTask] = []
    for record in manifest["records"]:
        symbol = record["symbol"]
        if symbols is not None and symbol not in symbols:
            continue
        for key, dataset in (("ohlcv", "ohlcv"), ("funding", "funding")):
            for archive in record[key]["official_monthly_archives"]:
                if months is not None and archive["month"] not in months:
                    continue
                tasks.append(
                    ArchiveTask(
                        dataset=dataset,
                        symbol=symbol,
                        month=archive["month"],
                        url=archive["url"],
                        checksum_url=archive["checksum_url"],
                    )
                )
    return sorted(tasks, key=lambda task: (task.symbol, task.dataset, task.month))


def build(
    manifest_path: Path,
    output: Path,
    workers: int,
    symbols: set[str] | None,
    months: set[str] | None,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    tasks = _tasks(manifest, symbols, months)
    if not tasks:
        raise RuntimeError("selection produced zero archive tasks")
    archive_root = output / "archives"
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        acquisition_results = list(
            pool.map(lambda task: _acquire_safe(task, archive_root), tasks)
        )
    records = [record for record in acquisition_results if record["passes"]]
    failures = [record for record in acquisition_results if not record["passes"]]
    selected_symbols = sorted({task.symbol for task in tasks})
    start_ms = int(pd.Timestamp(manifest["frozen_run"]["start_inclusive"]).timestamp() * 1000)
    end_ms = int(pd.Timestamp(manifest["frozen_run"]["end_exclusive"]).timestamp() * 1000)
    normalized_records = []
    normalized_root = output / "normalized"
    for symbol in selected_symbols:
        symbol_records = [record for record in records if record["symbol"] == symbol]
        for dataset, normalizer in (("ohlcv", _normalize_ohlcv), ("funding", _normalize_funding)):
            paths = [
                Path(record["archive_path"])
                for record in symbol_records
                if record["dataset"] == dataset
            ]
            frame = normalizer(paths, symbol, start_ms, end_ms)
            destination = normalized_root / dataset / f"{symbol}.parquet"
            destination.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(destination, index=False)
            normalized_records.append(
                {
                    "dataset": dataset,
                    "symbol": symbol,
                    "rows": len(frame),
                    "first_timestamp": (
                        frame["ts_open" if dataset == "ohlcv" else "ts_funding"].min().isoformat()
                        if len(frame)
                        else None
                    ),
                    "last_timestamp": (
                        frame["ts_open" if dataset == "ohlcv" else "ts_funding"].max().isoformat()
                        if len(frame)
                        else None
                    ),
                    "sha256": _sha256(destination),
                    "path": str(destination),
                }
            )
    full_selection = symbols is None and months is None
    passes = not failures
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-portable-fetch.v1",
        "status": (
            "INCOMPLETE_OFFICIAL_ARCHIVE_COVERAGE"
            if failures
            else (
                "PASS_FRESH_OFFICIAL_ARCHIVE_ACQUISITION"
                if full_selection
                else "PASS_PARTIAL_FRESH_OFFICIAL_ARCHIVE_ACQUISITION"
            )
        ),
        "passes": passes,
        "manifest_binding": {
            "path": str(manifest_path),
            "sha256": _sha256(manifest_path),
            "content_hash": manifest["content_hash"],
        },
        "selection": {
            "full_frozen_inventory": full_selection,
            "symbols": selected_symbols,
            "months": sorted(months) if months is not None else None,
        },
        "official_source": {
            "branded_root": BRANDED_ROOT,
            "regional_path_style_root": REGIONAL_ROOT,
            "all_archives_checksum_verified": True,
        },
        "archive_objects": [
            {key: value for key, value in record.items() if key not in {"archive_path", "passes"}}
            for record in records
        ],
        "unavailable_archive_objects": [
            {key: value for key, value in record.items() if key != "passes"}
            for record in failures
        ],
        "normalized_objects": normalized_records,
        "totals": {
            "archive_objects": len(records),
            "archive_objects_requested": len(tasks),
            "archive_objects_unavailable": len(failures),
            "archive_bytes": sum(record["bytes"] for record in records),
            "cache_reused": sum(bool(record["cache_reused"]) for record in records),
            "normalized_rows": sum(record["rows"] for record in normalized_records),
        },
        "funding_availability_rule": "available_at = ts_funding + 5 minutes",
        "raw_archives_redistribution_authorized": False,
        "strategy_replayed": False,
        "independent_replication": False,
        "claim_boundary": (
            "This receipt proves checksum-verified acquisition and deterministic normalization "
            "for the selected official Binance archive objects. It does not grant redistribution "
            "rights, establish equality to the frozen lake until a separate comparator runs, "
            "replay the strategy, or constitute independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    (output / "source_manifest.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    return document


def _selection(value: str | None) -> set[str] | None:
    if value is None:
        return None
    selected = {item.strip() for item in value.split(",") if item.strip()}
    if not selected:
        raise ValueError("empty selection")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--symbols")
    parser.add_argument("--months")
    arguments = parser.parse_args()
    if arguments.workers < 1 or arguments.workers > 32:
        parser.error("--workers must be between 1 and 32")
    document = build(
        arguments.manifest.resolve(),
        arguments.output.resolve(),
        arguments.workers,
        _selection(arguments.symbols),
        _selection(arguments.months),
    )
    print(json.dumps(document, indent=2, sort_keys=True))
    if not document["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
