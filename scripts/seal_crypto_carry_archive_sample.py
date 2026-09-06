#!/usr/bin/env python3
"""Seal one checksum-verified Binance archive month against the frozen carry lake."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Final

import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "artifacts/publication/crypto_carry_archive_sample.json"
SYMBOL: Final = "BTCUSDT"
MONTH: Final = "2022-01"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _read_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"expected one CSV in {path}")
        return pd.read_csv(archive.open(names[0]))


def _verify_checksum(zip_path: Path) -> dict[str, str]:
    checksum_path = zip_path.with_name(zip_path.name + ".CHECKSUM")
    expected, filename = checksum_path.read_text().strip().split(maxsplit=1)
    if filename != zip_path.name or expected != _sha256(zip_path):
        raise RuntimeError(f"official checksum mismatch: {zip_path}")
    return {"zip_sha256": expected, "checksum_file_sha256": _sha256(checksum_path)}


def _local(dataset: str, columns: list[str]) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    pattern = str(
        ROOT / "data/lake" / dataset / f"instrument_id=BINANCE:PERP:{SYMBOL}" / "**/*.parquet"
    )
    files = sorted(Path(value) for value in glob.glob(pattern, recursive=True))
    time_column = columns[0]
    start = pd.Timestamp(f"{MONTH}-01", tz="UTC")
    end = start + pd.offsets.MonthBegin(1)
    selected_frames: list[pd.DataFrame] = []
    bindings: list[dict[str, str]] = []
    for path in files:
        partition = pd.read_parquet(path, columns=columns)
        selected = partition[(partition[time_column] >= start) & (partition[time_column] < end)]
        if selected.empty:
            continue
        selected_frames.append(selected)
        bindings.append({"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)})
    if not selected_frames:
        raise RuntimeError(f"no local {dataset} rows found for {SYMBOL} in {MONTH}")
    frame = pd.concat(selected_frames, ignore_index=True)
    frame = frame.drop_duplicates(time_column).sort_values(time_column).reset_index(drop=True)
    return frame, bindings


def build(download_dir: Path) -> dict[str, Any]:
    bar_zip = download_dir / f"{SYMBOL}-1h-{MONTH}.zip"
    funding_zip = download_dir / f"{SYMBOL}-fundingRate-{MONTH}.zip"
    bar_checksums = _verify_checksum(bar_zip)
    funding_checksums = _verify_checksum(funding_zip)
    fresh_bars = _read_zip(bar_zip)
    fresh_funding = _read_zip(funding_zip)
    local_bars, bar_bindings = _local(
        "ohlcv", ["ts_open", "open", "high", "low", "close", "volume", "quote_volume", "n_trades"]
    )
    local_funding, funding_bindings = _local("funding", ["ts_funding", "rate", "available_at"])

    bar_columns = {
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "quote_volume": "quote_volume",
        "count": "n_trades",
    }
    bar_timestamps_equal = pd.Series(
        pd.to_datetime(fresh_bars["open_time"], unit="ms", utc=True)
    ).equals(local_bars["ts_open"])
    bar_value_checks = {
        source: bool(
            (pd.to_numeric(fresh_bars[source]).to_numpy() == local_bars[target].to_numpy()).all()
        )
        for source, target in bar_columns.items()
    }
    funding_timestamps_equal = pd.Series(
        pd.to_datetime(fresh_funding["calc_time"], unit="ms", utc=True)
    ).equals(local_funding["ts_funding"])
    funding_rates_equal = bool(
        (
            pd.to_numeric(fresh_funding["last_funding_rate"]).to_numpy()
            == local_funding["rate"].to_numpy()
        ).all()
    )
    availability_rule_equal = bool(
        (
            local_funding["available_at"] - local_funding["ts_funding"] == pd.Timedelta(minutes=5)
        ).all()
    )
    passes = all(
        [
            len(fresh_bars) == len(local_bars) == 744,
            len(fresh_funding) == len(local_funding) == 93,
            bar_timestamps_equal,
            *bar_value_checks.values(),
            funding_timestamps_equal,
            funding_rates_equal,
            availability_rule_equal,
        ]
    )
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-official-archive-sample.v1",
        "author": "Arhan Canli",
        "status": "PASS_EXACT_SINGLE_SYMBOL_MONTH_ARCHIVE_EQUIVALENCE" if passes else "FAIL",
        "passes": passes,
        "sample": {"symbol": SYMBOL, "month": MONTH},
        "official_archives": {
            "ohlcv": {"filename": bar_zip.name, **bar_checksums},
            "funding": {"filename": funding_zip.name, **funding_checksums},
            "regional_official_root": (
                "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision"
            ),
        },
        "comparisons": {
            "ohlcv_rows": len(local_bars),
            "ohlcv_timestamps_exact": bar_timestamps_equal,
            "ohlcv_fields_exact": bar_value_checks,
            "funding_rows": len(local_funding),
            "funding_timestamps_exact": funding_timestamps_equal,
            "funding_rates_exact": funding_rates_equal,
            "funding_interval_hours": sorted(
                pd.to_numeric(fresh_funding["funding_interval_hours"]).unique().tolist()
            ),
            "available_at_equals_settlement_plus_5_minutes": availability_rule_equal,
        },
        "local_source_bindings": {
            "ohlcv": bar_bindings,
            "funding": funding_bindings,
        },
        "raw_archives_released": False,
        "fresh_full_universe_download_completed": False,
        "full_walkforward_replayed": False,
        "independent_replication": False,
        "claim_boundary": (
            "This checksum-verified test proves exact source equivalence only for BTCUSDT hourly "
            "bars and funding in January 2022. It does not establish equivalence for the other "
            "57 instruments or months, recreate point-in-time metadata, replay the strategy, "
            "grant redistribution rights, or constitute independent review."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = json.loads(OUTPUT.read_text())
    if document.get("content_hash") != _content_hash(document):
        raise RuntimeError("published crypto-carry sample receipt hash is invalid")
    for bindings in document["local_source_bindings"].values():
        for binding in bindings:
            if binding["sha256"] != _sha256(ROOT / binding["path"]):
                raise RuntimeError(f"bound local source changed: {binding['path']}")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path)
    parser.add_argument("--validate-published", action="store_true")
    arguments = parser.parse_args()
    if arguments.validate_published:
        document = validate_published()
    elif arguments.download_dir:
        document = build(arguments.download_dir.resolve())
        OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    else:
        parser.error("provide --download-dir or --validate-published")
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    if not document["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
