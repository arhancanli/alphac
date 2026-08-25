#!/usr/bin/env python3
"""Compare a fresh Binance archive acquisition with the frozen crypto-carry lake."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
PORTABILITY: Final = ROOT / "artifacts/publication/crypto_carry_portability_manifest.json"
OUTPUT: Final = ROOT / "artifacts/publication/crypto_carry_fresh_input_comparison.json"
BAR_FIELDS: Final = ("open", "high", "low", "close", "volume", "quote_volume", "n_trades")
REGIONAL_ROOT: Final = "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _local(dataset: str, instrument_id: str, columns: list[str]) -> pd.DataFrame:
    pattern = str(ROOT / "data/lake" / dataset / f"instrument_id={instrument_id}" / "**/*.parquet")
    files = sorted(glob.glob(pattern, recursive=True))
    return pd.concat([pd.read_parquet(path, columns=columns) for path in files])


def _daily_fallback(symbol: str, date: str) -> dict[str, str]:
    filename = f"{symbol}-1h-{date}.zip"
    key = f"data/futures/um/daily/klines/{symbol}/1h/{filename}"
    return {
        "symbol": symbol,
        "date": date,
        "filename": filename,
        "official_url": f"https://data.binance.vision/{key}",
        "regional_official_url": f"{REGIONAL_ROOT}/{key}",
        "checksum_url": f"https://data.binance.vision/{key}.CHECKSUM",
    }


def _bounds(index: pd.DatetimeIndex) -> dict[str, str | None]:
    return {
        "first_timestamp": index.min().isoformat() if len(index) else None,
        "last_timestamp": index.max().isoformat() if len(index) else None,
    }


def build(
    fresh_dir: Path,
    daily_supplement_dir: Path | None = None,
    funding_supplement_dir: Path | None = None,
) -> dict[str, Any]:
    portability = json.loads(PORTABILITY.read_text())
    source_manifest_path = fresh_dir / "source_manifest.json"
    acquisition = json.loads(source_manifest_path.read_text())
    if acquisition.get("content_hash") != _content_hash(acquisition):
        raise RuntimeError("fresh acquisition content hash is invalid")
    supplement = None
    if daily_supplement_dir is not None:
        supplement_path = daily_supplement_dir / "source_manifest.json"
        supplement = json.loads(supplement_path.read_text())
        if supplement.get("content_hash") != _content_hash(supplement):
            raise RuntimeError("daily supplement content hash is invalid")
        if not supplement.get("passes"):
            raise RuntimeError("daily supplement is incomplete")
    funding_supplement = None
    if funding_supplement_dir is not None:
        funding_supplement_path = funding_supplement_dir / "source_manifest.json"
        funding_supplement = json.loads(funding_supplement_path.read_text())
        if funding_supplement.get("content_hash") != _content_hash(funding_supplement):
            raise RuntimeError("funding supplement content hash is invalid")
        if not funding_supplement.get("passes"):
            raise RuntimeError("funding supplement is incomplete")
    start = pd.Timestamp(portability["frozen_run"]["start_inclusive"])
    end = pd.Timestamp(portability["frozen_run"]["end_exclusive"])
    metadata = {row["instrument_id"]: row for row in portability["instrument_metadata"]}
    records = []
    daily_fallbacks: dict[tuple[str, str], dict[str, str]] = {}
    for source_record in portability["records"]:
        instrument_id = source_record["instrument_id"]
        symbol = source_record["symbol"]
        local_bars = _local("ohlcv", instrument_id, ["ts_open", *BAR_FIELDS])
        local_bars = (
            local_bars[(local_bars["ts_open"] >= start) & (local_bars["ts_open"] < end)]
            .drop_duplicates("ts_open", keep="last")
            .sort_values("ts_open")
            .set_index("ts_open")
        )
        fresh_bars = pd.read_parquet(fresh_dir / "normalized/ohlcv" / f"{symbol}.parquet")
        if daily_supplement_dir is not None:
            supplement_path = daily_supplement_dir / "normalized/ohlcv" / f"{symbol}.parquet"
            if supplement_path.is_file():
                fresh_bars = pd.concat(
                    [fresh_bars, pd.read_parquet(supplement_path)], ignore_index=True
                ).drop_duplicates("ts_open", keep="last")
        fresh_bars = fresh_bars.set_index("ts_open").sort_index()
        overlap = local_bars.index.intersection(fresh_bars.index)
        local_overlap = local_bars.reindex(overlap)
        fresh_overlap = fresh_bars.reindex(overlap)
        field_comparisons = {}
        for field in BAR_FIELDS:
            local_values = local_overlap[field].to_numpy()
            fresh_values = fresh_overlap[field].to_numpy()
            differences = np.abs(local_values - fresh_values)
            field_comparisons[field] = {
                "mismatched_rows": int((local_values != fresh_values).sum()),
                "max_absolute_difference": float(differences.max()) if len(differences) else 0.0,
            }
        local_only = local_bars.index.difference(fresh_bars.index)
        fresh_only = fresh_bars.index.difference(local_bars.index)
        listed = pd.Timestamp(metadata[instrument_id]["listed_ts"], unit="ms", tz="UTC")
        delisted_ms = metadata[instrument_id]["delisted_ts"]
        delisted = pd.Timestamp(delisted_ms, unit="ms", tz="UTC") if delisted_ms else None
        before_listing = int((fresh_only < listed).sum())
        post_delisting = int((fresh_only >= delisted).sum()) if delisted is not None else 0
        inside_lifecycle = len(fresh_only) - before_listing - post_delisting
        for date in sorted(pd.Index(local_only.normalize()).unique()):
            key = (symbol, str(date.date()))
            daily_fallbacks[key] = _daily_fallback(*key)

        local_funding = _local("funding", instrument_id, ["ts_funding", "rate", "available_at"])
        local_funding = (
            local_funding[
                (local_funding["ts_funding"] >= start) & (local_funding["ts_funding"] < end)
            ]
            .drop_duplicates("ts_funding", keep="last")
            .sort_values("ts_funding")
            .set_index("ts_funding")
        )
        fresh_funding = pd.read_parquet(fresh_dir / "normalized/funding" / f"{symbol}.parquet")
        if funding_supplement_dir is not None:
            funding_path = funding_supplement_dir / "normalized/funding" / f"{symbol}.parquet"
            if funding_path.is_file():
                fresh_funding = pd.concat(
                    [fresh_funding, pd.read_parquet(funding_path)], ignore_index=True
                ).drop_duplicates("ts_funding", keep="last")
        fresh_funding = fresh_funding.set_index("ts_funding").sort_index()
        funding_overlap = local_funding.index.intersection(fresh_funding.index)
        local_rates = local_funding.reindex(funding_overlap)["rate"].to_numpy()
        fresh_rates = fresh_funding.reindex(funding_overlap)["rate"].to_numpy()
        funding_local_only = local_funding.index.difference(fresh_funding.index)
        funding_fresh_only = fresh_funding.index.difference(local_funding.index)
        funding_post_delisting = (
            int((funding_fresh_only >= delisted).sum()) if delisted is not None else 0
        )
        funding_before_listing = int((funding_fresh_only < listed).sum())
        funding_inside_lifecycle = (
            len(funding_fresh_only) - funding_before_listing - funding_post_delisting
        )
        records.append(
            {
                "instrument_id": instrument_id,
                "symbol": symbol,
                "ohlcv": {
                    "local_rows": len(local_bars),
                    "fresh_rows": len(fresh_bars),
                    "overlap_rows": len(overlap),
                    "local_only_rows": len(local_only),
                    "local_only_range": _bounds(local_only),
                    "fresh_only_rows": len(fresh_only),
                    "fresh_only_range": _bounds(fresh_only),
                    "fresh_only_before_listing": before_listing,
                    "fresh_only_at_or_after_delisting": post_delisting,
                    "fresh_only_inside_lifecycle": inside_lifecycle,
                    "field_comparisons_on_overlap": field_comparisons,
                },
                "funding": {
                    "local_rows": len(local_funding),
                    "fresh_rows": len(fresh_funding),
                    "overlap_rows": len(funding_overlap),
                    "local_only_rows": len(funding_local_only),
                    "local_only_range": _bounds(funding_local_only),
                    "fresh_only_rows": len(funding_fresh_only),
                    "fresh_only_range": _bounds(funding_fresh_only),
                    "fresh_only_before_listing": funding_before_listing,
                    "fresh_only_at_or_after_delisting": funding_post_delisting,
                    "fresh_only_inside_lifecycle": funding_inside_lifecycle,
                    "rate_mismatched_rows_on_overlap": int((local_rates != fresh_rates).sum()),
                    "max_absolute_rate_difference": (
                        float(np.abs(local_rates - fresh_rates).max()) if len(local_rates) else 0.0
                    ),
                },
            }
        )

    totals = {
        "ohlcv_local_rows": sum(row["ohlcv"]["local_rows"] for row in records),
        "ohlcv_fresh_rows": sum(row["ohlcv"]["fresh_rows"] for row in records),
        "ohlcv_overlap_rows": sum(row["ohlcv"]["overlap_rows"] for row in records),
        "ohlcv_local_only_rows": sum(row["ohlcv"]["local_only_rows"] for row in records),
        "ohlcv_fresh_only_rows": sum(row["ohlcv"]["fresh_only_rows"] for row in records),
        "ohlcv_fresh_only_at_or_after_delisting": sum(
            row["ohlcv"]["fresh_only_at_or_after_delisting"] for row in records
        ),
        "ohlcv_fresh_only_before_listing": sum(
            row["ohlcv"]["fresh_only_before_listing"] for row in records
        ),
        "ohlcv_fresh_only_inside_lifecycle": sum(
            row["ohlcv"]["fresh_only_inside_lifecycle"] for row in records
        ),
        "ohlcv_field_mismatches_on_overlap": sum(
            comparison["mismatched_rows"]
            for row in records
            for comparison in row["ohlcv"]["field_comparisons_on_overlap"].values()
        ),
        "funding_local_rows": sum(row["funding"]["local_rows"] for row in records),
        "funding_fresh_rows": sum(row["funding"]["fresh_rows"] for row in records),
        "funding_overlap_rows": sum(row["funding"]["overlap_rows"] for row in records),
        "funding_local_only_rows": sum(row["funding"]["local_only_rows"] for row in records),
        "funding_fresh_only_rows": sum(row["funding"]["fresh_only_rows"] for row in records),
        "funding_fresh_only_at_or_after_delisting": sum(
            row["funding"]["fresh_only_at_or_after_delisting"] for row in records
        ),
        "funding_fresh_only_before_listing": sum(
            row["funding"]["fresh_only_before_listing"] for row in records
        ),
        "funding_fresh_only_inside_lifecycle": sum(
            row["funding"]["fresh_only_inside_lifecycle"] for row in records
        ),
        "funding_rate_mismatches_on_overlap": sum(
            row["funding"]["rate_mismatched_rows_on_overlap"] for row in records
        ),
        "daily_fallback_objects_required": len(daily_fallbacks),
    }
    portable_complete = (
        not acquisition["unavailable_archive_objects"]
        and totals["ohlcv_local_only_rows"] == 0
        and totals["funding_local_only_rows"] == 0
    )
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-fresh-input-comparison.v1",
        "author": "Arhan Canli",
        "status": (
            "PASS_COMPLETE_PORTABLE_INPUT_EQUIVALENCE"
            if portable_complete
            else "INCOMPLETE_PORTABLE_INPUT_EQUIVALENCE_GAPS_QUANTIFIED"
        ),
        "comparison_executed": True,
        "portable_input_equivalence_complete": portable_complete,
        "portability_manifest_binding": {
            "path": str(PORTABILITY.relative_to(ROOT)),
            "sha256": _sha256(PORTABILITY),
            "content_hash": portability["content_hash"],
        },
        "fresh_acquisition_receipt": acquisition,
        "daily_supplement_receipt": supplement,
        "funding_supplement_receipt": funding_supplement,
        "totals": totals,
        "records": records,
        "daily_ohlcv_fallback_plan": list(daily_fallbacks.values()),
        "missing_funding_archive_objects": acquisition["unavailable_archive_objects"],
        "full_walkforward_replayed": False,
        "independent_replication": False,
        "claim_boundary": (
            "This comparator quantifies exact overlap, archive gaps, post-delisting extras, and "
            "current-archive revisions against the frozen local inputs. It does not fill any gap, "
            "declare revised rows equivalent, replay the strategy, or constitute independent "
            "review."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = json.loads(OUTPUT.read_text())
    if document.get("content_hash") != _content_hash(document):
        raise RuntimeError("published crypto-carry input comparison hash is invalid")
    binding = document["portability_manifest_binding"]
    portability_path = ROOT / binding["path"]
    if binding["sha256"] != _sha256(portability_path):
        # The comparison is a historical measurement artifact and is sealed into
        # the prospective trial.  A later inventory refresh must not silently
        # rewrite it.  Permit an inventory supersession only when the duplicated
        # acquisition receipt proves the original binding and every comparison-
        # relevant identity and local row count remains unchanged.  This does not
        # claim byte identity or a fresh comparison replay.
        historical = document["fresh_acquisition_receipt"]["manifest_binding"]
        if historical.get("sha256") != binding.get("sha256") or historical.get(
            "content_hash"
        ) != binding.get("content_hash"):
            raise RuntimeError("historical portability bindings disagree")
        portability = json.loads(portability_path.read_text())
        if portability.get("content_hash") != _content_hash(portability):
            raise RuntimeError("current portability manifest hash is invalid")
        current_records = portability.get("records", [])
        comparison_records = document.get("records", [])
        if len(current_records) != len(comparison_records):
            raise RuntimeError("current portability instrument count changed")
        for current, comparison in zip(current_records, comparison_records, strict=True):
            if (
                current.get("instrument_id") != comparison.get("instrument_id")
                or current.get("symbol") != comparison.get("symbol")
                or current.get("ohlcv", {}).get("rows_in_frozen_window")
                != comparison.get("ohlcv", {}).get("local_rows")
                or current.get("funding", {}).get("rows_in_frozen_window")
                != comparison.get("funding", {}).get("local_rows")
            ):
                raise RuntimeError("current portability selection or row counts changed")
        selected_symbols = document["fresh_acquisition_receipt"]["selection"]["symbols"]
        if selected_symbols != [record["symbol"] for record in current_records]:
            raise RuntimeError("fresh acquisition selection differs from current inventory")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh-dir", type=Path)
    parser.add_argument("--daily-supplement-dir", type=Path)
    parser.add_argument("--funding-supplement-dir", type=Path)
    parser.add_argument("--validate-published", action="store_true")
    arguments = parser.parse_args()
    if arguments.validate_published:
        document = validate_published()
    elif arguments.fresh_dir:
        document = build(
            arguments.fresh_dir.resolve(),
            arguments.daily_supplement_dir.resolve() if arguments.daily_supplement_dir else None,
            (
                arguments.funding_supplement_dir.resolve()
                if arguments.funding_supplement_dir
                else None
            ),
        )
        OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    else:
        parser.error("provide --fresh-dir or --validate-published")
    print(f"{document['status']}: {OUTPUT}")
    print(json.dumps(document["totals"], indent=2, sort_keys=True))
    print(f"content_hash: {document['content_hash']}")


if __name__ == "__main__":
    main()
