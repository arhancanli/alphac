#!/usr/bin/env python3
"""Build an isolated, deterministic, return-free lake for crypto_carry_portable_v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Final, cast

import pandas as pd
import pyarrow as pa

from alphaforge.config.settings import UniverseCfg
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset, schema_for
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.builder import UniverseBuilder
from alphaforge.data.universe.store import UniverseStore

ROOT: Final = Path(__file__).resolve().parents[1]
READINESS: Final = ROOT / "artifacts/audit/crypto_carry_portable_prerun_readiness.json"
DEFAULT_OUTPUT: Final = ROOT / "var/portable_crypto_carry_v1"
MANIFEST_NAME: Final = "portable_lake_manifest.json"
SCHEMA: Final = "canli.alphac-crypto-carry-portable-lake.v1"
READINESS_SCHEMA: Final = "canli.alphac-crypto-carry-portable-prerun-readiness.v1"


class PortableLakeError(RuntimeError):
    """The isolated portable lake could not be built or validated safely."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PortableLakeError(f"required JSON is missing: {path}")
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise PortableLakeError(f"required JSON is unreadable: {path}") from error


def _verified_json(path: Path, schema: str | None = None) -> dict[str, Any]:
    document = _read_json(path)
    if schema is not None and document.get("schema") != schema:
        raise PortableLakeError(f"unexpected schema in {path}")
    if document.get("content_hash") != _content_hash(document):
        raise PortableLakeError(f"content hash mismatch: {path}")
    return document


def _timestamp_ms(value: str) -> int:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise PortableLakeError(f"timestamp must carry a UTC offset: {value}")
    return int(timestamp.tz_convert("UTC").timestamp() * 1000)


def _metadata_record(row: dict[str, Any]) -> Instrument:
    return Instrument(
        instrument_id=str(row["instrument_id"]),
        asset_class=AssetClass(str(row["asset_class"])),
        market_type=MarketType(str(row["market_type"])),
        base=str(row["base"]),
        quote=str(row["quote"]),
        tick_size=float(row["tick_size"]),
        lot_size=float(row["lot_size"]),
        min_qty=float(row["min_qty"]),
        min_notional=float(row["min_notional"]),
        contract_multiplier=float(row["contract_multiplier"]),
        can_short=bool(row["can_short"]),
        maker_fee_bps=float(row["maker_fee_bps"]),
        taker_fee_bps=float(row["taker_fee_bps"]),
        funding_interval_hours=int(row["funding_interval_hours"]),
        listed_ts=int(row["listed_ts"]),
        delisted_ts=None if row["delisted_ts"] is None else int(row["delisted_ts"]),
    )


def _source_binding(acquisition: dict[str, Any], dataset: str, symbol: str) -> dict[str, Any]:
    matches = [
        row
        for row in acquisition.get("normalized_objects", [])
        if isinstance(row, dict)
        and row.get("dataset") == dataset
        and row.get("symbol") == symbol
    ]
    if len(matches) != 1:
        raise PortableLakeError(f"expected one normalized source for {dataset}/{symbol}")
    return cast(dict[str, Any], matches[0])


def _prepare_table(
    source: Path,
    *,
    dataset: Dataset,
    instrument: Instrument,
    start: pd.Timestamp,
    end: pd.Timestamp,
    ingested_at: pd.Timestamp,
) -> tuple[pa.Table, dict[str, Any]]:
    frame = pd.read_parquet(source)
    time_column = "ts_open" if dataset is Dataset.OHLCV else "ts_funding"
    required = (
        {
            "instrument_id",
            "ts_open",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "n_trades",
            "quality_flags",
        }
        if dataset is Dataset.OHLCV
        else {"instrument_id", "ts_funding", "rate", "available_at"}
    )
    if not required.issubset(frame.columns):
        raise PortableLakeError(f"normalized source schema is incomplete: {source}")
    if set(frame["instrument_id"].drop_duplicates()) != {instrument.instrument_id}:
        raise PortableLakeError(f"normalized source instrument id drifted: {source}")
    if frame[time_column].duplicated().any():
        raise PortableLakeError(f"normalized source contains duplicate timestamps: {source}")

    timestamps = pd.to_datetime(frame[time_column], utc=True)
    listed = pd.Timestamp(instrument.listed_ts, unit="ms", tz="UTC")
    delisted = (
        None
        if instrument.delisted_ts is None
        else pd.Timestamp(instrument.delisted_ts, unit="ms", tz="UTC")
    )
    in_window = (timestamps >= start) & (timestamps < end)
    before_listing = timestamps < listed
    after_delisting = (
        timestamps >= delisted
        if delisted is not None
        else pd.Series(False, index=frame.index, dtype=bool)
    )
    keep = in_window & ~before_listing & ~after_delisting
    filtered = frame.loc[keep].copy()
    if filtered.empty:
        raise PortableLakeError(f"lifecycle filtering emptied required source: {source}")
    filtered["ingested_at"] = ingested_at
    if dataset is Dataset.OHLCV:
        columns = list(schema_for(Dataset.OHLCV).names)
    else:
        columns = list(schema_for(Dataset.FUNDING).names)
    table = pa.Table.from_pandas(
        filtered[columns], schema=schema_for(dataset), preserve_index=False
    )
    return table, {
        "dataset": dataset.value,
        "instrument_id": instrument.instrument_id,
        "source_path": str(source),
        "source_sha256": _sha256(source),
        "source_rows": len(frame),
        "retained_rows": table.num_rows,
        "removed_outside_run_window": int((~in_window).sum()),
        "removed_before_listing": int((in_window & before_listing).sum()),
        "removed_at_or_after_delisting": int((in_window & after_delisting).sum()),
        "first_timestamp": filtered[time_column].min().isoformat(),
        "last_timestamp": filtered[time_column].max().isoformat(),
    }


def _leaf_inventory(root: Path) -> list[dict[str, Any]]:
    leaves = []
    for path in sorted((root / "lake").rglob("data.parquet")):
        leaves.append(
            {
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if not leaves:
        raise PortableLakeError("portable lake contains no Parquet leaves")
    return leaves


def validate_existing(output: Path) -> dict[str, Any]:
    output = output.resolve()
    manifest = _verified_json(output / MANIFEST_NAME, SCHEMA)
    leaves = manifest.get("output_inventory", {}).get("leaves")
    if not isinstance(leaves, list) or not leaves:
        raise PortableLakeError("portable lake manifest has no output leaf inventory")
    observed = _leaf_inventory(output)
    if leaves != observed:
        raise PortableLakeError("portable lake leaf inventory or hash has drifted")
    ops = output / "ops.sqlite"
    if not ops.is_file() or _sha256(ops) != manifest["output_inventory"]["ops_sqlite_sha256"]:
        raise PortableLakeError("portable instrument store hash has drifted")
    tmp_files = sorted((output / "lake").rglob(".tmp-*"))
    if tmp_files:
        raise PortableLakeError("portable lake contains in-flight temporary files")
    return manifest


def build(
    repo: Path,
    fresh_dir: Path,
    readiness_path: Path,
    output: Path,
) -> dict[str, Any]:
    repo = repo.resolve()
    fresh_dir = fresh_dir.resolve()
    output = output.resolve()
    if output.exists():
        raise PortableLakeError(f"refusing to overwrite existing portable lake: {output}")

    readiness = _verified_json(readiness_path, READINESS_SCHEMA)
    if readiness.get("status") != (
        "PASS_DATA_ELIGIBILITY_LOCKED_READY_FOR_PORTABLE_LAKE_BUILD_RETURN_BLOCKED"
    ):
        raise PortableLakeError("pre-run readiness does not authorize a data-only lake build")
    if readiness.get("research_accounting") != {
        "experiment_ledger_mutated": False,
        "hypotheses_spent": 0,
        "new_return_trials_executed": 0,
        "return_metrics_computed": False,
        "strategy_imported_or_executed": False,
    }:
        raise PortableLakeError("pre-run readiness accounting boundary drifted")

    contract_path = repo / readiness["contract_binding"]["path"]
    contract = _verified_json(contract_path)
    if contract["content_hash"] != readiness["contract_binding"]["content_hash"]:
        raise PortableLakeError("pre-run contract binding drifted")
    acquisition_path = fresh_dir / "source_manifest.json"
    acquisition = _verified_json(acquisition_path)
    if acquisition["content_hash"] != readiness["fresh_acquisition_binding"]["content_hash"]:
        raise PortableLakeError("fresh acquisition binding drifted")

    metadata_binding = contract["pre_result_evidence_bindings"]["instrument_metadata"]
    metadata_path = repo / metadata_binding["path"]
    metadata = _verified_json(metadata_path)
    if metadata["content_hash"] != metadata_binding["content_hash"]:
        raise PortableLakeError("instrument metadata binding drifted")
    metadata_by_id = {
        row["instrument_id"]: row for row in metadata["records"] if isinstance(row, dict)
    }

    candidate = readiness["locked_candidate"]
    ids = cast(list[str], candidate["instrument_ids"])
    if len(ids) != len(set(ids)) or len(ids) != candidate["instrument_count"]:
        raise PortableLakeError("locked candidate instrument inventory is malformed")
    start = pd.Timestamp(candidate["start_inclusive"])
    end = pd.Timestamp(candidate["end_exclusive"])
    stamp = pd.Timestamp(contract["source_contract"]["deterministic_snapshot_ingested_at"])
    if any(timestamp.tzinfo is None for timestamp in (start, end, stamp)):
        raise PortableLakeError("contract timestamps must be timezone-aware")
    start = start.tz_convert("UTC")
    end = end.tz_convert("UTC")
    stamp = stamp.tz_convert("UTC")
    start_ms = _timestamp_ms(start.isoformat())
    end_ms = _timestamp_ms(end.isoformat())

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        paths = LakePaths(staging / "lake")
        writer = LakeWriter(paths)
        conversions: list[dict[str, Any]] = []
        instruments: list[Instrument] = []
        for instrument_id in ids:
            row = metadata_by_id.get(instrument_id)
            if row is None:
                raise PortableLakeError(f"metadata missing for {instrument_id}")
            instrument = _metadata_record(row)
            instruments.append(instrument)
            symbol = instrument_id.rsplit(":", 1)[-1]
            for dataset in (Dataset.OHLCV, Dataset.FUNDING):
                source_record = _source_binding(acquisition, dataset.value, symbol)
                source = fresh_dir / "normalized" / dataset.value / f"{symbol}.parquet"
                if _sha256(source) != source_record["sha256"]:
                    raise PortableLakeError(f"normalized source hash drifted: {source}")
                table, record = _prepare_table(
                    source,
                    dataset=dataset,
                    instrument=instrument,
                    start=start,
                    end=end,
                    ingested_at=stamp,
                )
                stats = writer.write(dataset, table, now=_timestamp_ms(stamp.isoformat()))
                if stats.rows_in != table.num_rows or stats.unclosed_dropped != 0:
                    raise PortableLakeError(f"writer dropped rows unexpectedly: {source}")
                record["written_partitions"] = stats.partitions
                conversions.append(record)

        ops_path = staging / "ops.sqlite"
        with InstrumentStore(ops_path) as store:
            for instrument in instruments:
                store.upsert(instrument, as_of=start_ms)

        universe_cfg_raw = contract["universe_contract"]
        universe_cfg = UniverseCfg(
            size=universe_cfg_raw["size"],
            rank_window_days=universe_cfg_raw["rank_window_days"],
            rebalance=universe_cfg_raw["rebalance"],
            entry_rank=universe_cfg_raw["entry_rank"],
            exit_rank=universe_cfg_raw["exit_rank"],
        )
        reader = PITDataReader(paths)
        universe_store = UniverseStore(paths)
        with InstrumentStore(ops_path) as store:
            universe_stats = UniverseBuilder(
                reader,
                store,
                universe_store,
                universe_cfg,
                min_days=universe_cfg_raw["minimum_distinct_volume_days"],
                min_listing_age_ms=universe_cfg_raw["minimum_listing_age_days"] * 86_400_000,
                rank_tf=Timeframe.H1,
                asset_class=AssetClass.CRYPTO_PERP,
            ).rebuild(start=start_ms, end=end_ms - 1, now=end_ms)

        intervals = universe_store.read_intervals()
        interval_ids = set(intervals.column("instrument_id").to_pylist())
        if not interval_ids or not interval_ids.issubset(set(ids)):
            raise PortableLakeError("rebuilt universe is empty or contains an ineligible id")
        if paths.tmp_files():
            raise PortableLakeError("portable lake writer left temporary files")

        leaves = _leaf_inventory(staging)
        leaf_root = hashlib.sha256(_canonical(leaves)).hexdigest()
        ops_sha = _sha256(ops_path)
        manifest: dict[str, Any] = {
            "schema": SCHEMA,
            "status": "PASS_ISOLATED_PORTABLE_LAKE_BUILT_ZERO_RETURN",
            "author": "Arhan Canli",
            "identity": "crypto_carry_portable_v1",
            "readiness_binding": {
                "path": str(readiness_path.resolve().relative_to(repo)),
                "sha256": _sha256(readiness_path),
                "content_hash": readiness["content_hash"],
            },
            "contract_binding": readiness["contract_binding"],
            "fresh_acquisition_binding": {
                "source_manifest_sha256": _sha256(acquisition_path),
                "source_manifest_content_hash": acquisition["content_hash"],
                "normalized_inventory_root_sha256": readiness["source_object_audit"][
                    "normalized_inventory_root_sha256"
                ],
            },
            "construction": {
                "isolated_from_existing_lake": True,
                "existing_repository_lake_read_or_mixed": False,
                "market_data_authority": contract["source_contract"][
                    "market_data_authority"
                ],
                "instrument_ids": ids,
                "instrument_count": len(ids),
                "excluded_symbols": candidate["excluded_symbols"],
                "start_inclusive": start.isoformat(),
                "end_exclusive": end.isoformat(),
                "deterministic_snapshot_ingested_at": stamp.isoformat(),
                "metadata_portable_valid_from_ms": start_ms,
                "metadata_source_valid_from_ms": sorted(
                    {int(metadata_by_id[instrument_id]["valid_from_ms"]) for instrument_id in ids}
                ),
                "funding_available_at_rule": contract["source_contract"][
                    "funding_available_at_rule"
                ],
                "universe_contract": universe_cfg_raw,
            },
            "conversion_records": conversions,
            "conversion_totals": {
                "source_objects": len(conversions),
                "source_rows": sum(record["source_rows"] for record in conversions),
                "retained_rows": sum(record["retained_rows"] for record in conversions),
                "removed_outside_run_window": sum(
                    record["removed_outside_run_window"] for record in conversions
                ),
                "removed_before_listing": sum(
                    record["removed_before_listing"] for record in conversions
                ),
                "removed_at_or_after_delisting": sum(
                    record["removed_at_or_after_delisting"] for record in conversions
                ),
            },
            "universe_rebuild": {
                "rebalances": universe_stats.rebalances,
                "intervals": universe_stats.intervals,
                "entries": universe_stats.entries,
                "exits": universe_stats.exits,
                "open_members": universe_stats.open_members,
                "interval_instruments": len(interval_ids),
            },
            "output_inventory": {
                "lake_relative_path": "lake",
                "ops_sqlite_relative_path": "ops.sqlite",
                "ops_sqlite_sha256": ops_sha,
                "leaves": leaves,
                "leaf_files": len(leaves),
                "leaf_bytes": sum(leaf["bytes"] for leaf in leaves),
                "leaf_inventory_root_sha256": leaf_root,
            },
            "research_accounting": {
                "new_return_trials_executed": 0,
                "return_metrics_computed": False,
                "hypotheses_spent": 0,
                "experiment_ledger_mutated": False,
                "strategy_imported_or_executed": False,
            },
            "raw_archives_included": False,
            "raw_or_derived_market_data_publication_authorized": False,
            "independent_replication": False,
            "claim_boundary": (
                "This private artifact proves a deterministic isolated lake and PIT universe "
                "were built from the bound eligible fresh archive normalization. It does not "
                "compute or imply returns, authorize a trial, grant data redistribution rights, "
                "repair the historical result, or constitute independent replication."
            ),
        }
        manifest["content_hash"] = _content_hash(manifest)
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(staging, output)
        return validate_existing(output)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh-dir", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, default=READINESS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-existing", action="store_true")
    args = parser.parse_args()
    if args.validate_existing:
        manifest = validate_existing(args.output)
    else:
        manifest = build(ROOT, args.fresh_dir, args.readiness, args.output)
    print(f"{manifest['status']}: {args.output}")
    print(json.dumps(manifest["conversion_totals"], indent=2, sort_keys=True))
    print(json.dumps(manifest["universe_rebuild"], indent=2, sort_keys=True))
    print(f"content_hash: {manifest['content_hash']}")


if __name__ == "__main__":
    main()
