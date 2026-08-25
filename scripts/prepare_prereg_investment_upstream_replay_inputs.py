#!/usr/bin/env python3
"""Prepare private inputs for a raw-to-artifact ``prereg_investment`` replay.

The four licensed Sharadar bulk archives and the append-only instrument/experiment
history survive locally.  This harness copies and hash-binds those inputs, reconstructs
the historical SCD2 instrument view, preserves the first 75 experiment identities, and
copies the exact historical output as a private comparison target.

The successful historical run also inherited 60 Binance membership identities from a
different asset-class lake.  The artifact proves those identities were in the resolved
window, while its 933,091 stored position rows prove none became a position.  Their raw
daily bars survive, but four original membership partitions do not.  The replay packet
therefore uses an explicit artifact-informed minimal membership interval for all 60 and
labels that reconstruction.  It may establish strategy-output equivalence; it cannot
establish byte-exact recovery of every historical input.

Licensed rows and the private reference remain outside the public publication bundle.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from alphaforge.data.schemas import UNIVERSE_SCHEMA

ROOT: Final = Path(__file__).resolve().parents[1]
SNAPSHOT: Final = ROOT / "data/reproduction/prereg_investment_raw_upstream_20260824"
REFERENCE: Final = (
    ROOT / "artifacts/reproduction_private/prereg_investment_20260621/reference_output"
)
TARGET: Final = ROOT / "artifacts/walkforward/prereg_investment"
SOURCE_DB: Final = ROOT / "var/ops.sqlite"
SOURCE_LEDGER: Final = ROOT / "var/experiments.jsonl"
SOURCE_RAW: Final = ROOT / "data/sharadar_raw"
SOURCE_LAKE: Final = ROOT / "data/lake"
LINEAGE: Final = ROOT / "artifacts/publication/prereg_investment_historical_lineage.json"

RUN_LAUNCHED_MS: Final = 1_782_019_284_293
TRIAL_NOW_MS: Final = 1_782_027_281_509
START_MS: Final = 946_684_800_000
END_MS: Final = 1_780_272_000_000
EXPECTED_INSTRUMENT_ROWS: Final = 16_613
EXPECTED_INSTRUMENTS_BY_VENUE: Final = {"BINANCE": 777, "XUSE": 15_836}
EXPECTED_DELISTED: Final = 10_090
EXPECTED_LEDGER_ROWS: Final = 75
EXPECTED_LEDGER_VARIANCE: Final = 0.0011398070210704527
EXPECTED_TARGET_FILES: Final = 779
EXPECTED_POSITION_ROWS: Final = 933_091
EXPECTED_CRYPTO_CONFIG_IDS: Final = 60
EXPECTED_EQUITY_CONFIG_IDS: Final = 6_820
EXPECTED_CONFIG_IDS: Final = 6_880
EXPECTED_EQUITY_SHA256: Final = "e81f22c716da8590ee0a7129760ffa65f56b6967f8ef8c3c2ed86845cdf1645b"
EXPECTED_RAW_ARCHIVES: Final[dict[str, tuple[int, str]]] = {
    "ACTIONS.zip": (
        9_766_443,
        "166d6ae17921b6a3a1f13a734e43bfd32ca5d9e88398030290a5246c89d7185c",
    ),
    "SEP.zip": (
        994_782_292,
        "d537322141302331cc3dc43f4eefe1222057e329525a835cc93bd0a079db92b3",
    ),
    "SF1.zip": (
        170_695_165,
        "701c3ac5ea8c65c6621461f51d4ff23358c46a3b019c6acf3a1e85ee2998487a",
    ),
    "TICKERS.zip": (
        3_919_917,
        "8f3e03012dd25d0a2fb3950e39d81f1ddff106391cd20eb9e547cd53f92525f5",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_bound(source: Path, destination: Path, expected_sha: str) -> None:
    if _sha256(source) != expected_sha:
        raise ValueError(f"source binding drifted: {source}")
    if destination.exists():
        if not destination.is_file() or _sha256(destination) != expected_sha:
            raise ValueError(f"existing private copy differs: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if _sha256(destination) != expected_sha:
        raise ValueError(f"private copy verification failed: {destination}")


def _artifact_config() -> tuple[list[str], list[str]]:
    document = json.loads((TARGET / "walkforward.json").read_text(encoding="utf-8"))
    ids = list(document["config"]["instrument_ids"])
    equity = sorted(iid for iid in ids if iid.startswith("XUSE:"))
    crypto = sorted(iid for iid in ids if iid.startswith("BINANCE:"))
    if len(ids) != EXPECTED_CONFIG_IDS:
        raise ValueError(f"target config id count drifted: {len(ids)}")
    if len(equity) != EXPECTED_EQUITY_CONFIG_IDS:
        raise ValueError(f"target equity id count drifted: {len(equity)}")
    if len(crypto) != EXPECTED_CRYPTO_CONFIG_IDS:
        raise ValueError(f"target crypto id count drifted: {len(crypto)}")
    return equity, crypto


def _copy_raw_archives() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for name, (expected_bytes, expected_sha) in sorted(EXPECTED_RAW_ARCHIVES.items()):
        source = SOURCE_RAW / name
        if source.stat().st_size != expected_bytes:
            raise ValueError(f"raw archive size drifted: {source}")
        destination = SNAPSHOT / "data/sharadar_raw" / name
        _copy_bound(source, destination, expected_sha)
        records.append(
            {
                "path": str(destination.relative_to(SNAPSHOT)),
                "bytes": expected_bytes,
                "sha256": expected_sha,
            }
        )
    return records


def _historical_instrument_rows(source: sqlite3.Connection) -> list[tuple[Any, ...]]:
    columns = [
        "instrument_id",
        "asset_class",
        "market_type",
        "base",
        "quote",
        "tick_size",
        "lot_size",
        "min_qty",
        "min_notional",
        "contract_multiplier",
        "can_short",
        "maker_fee_bps",
        "taker_fee_bps",
        "funding_interval_hours",
        "listed_ts",
        "delisted_ts",
        "valid_from_ms",
        "valid_to_ms",
    ]
    return source.execute(
        f"""
        SELECT {", ".join(columns)}
          FROM instruments_v
         WHERE valid_from_ms <= ?
           AND (valid_to_ms IS NULL OR valid_to_ms > ?)
         ORDER BY instrument_id
        """,
        (RUN_LAUNCHED_MS, RUN_LAUNCHED_MS),
    ).fetchall()


def _prepare_instrument_state() -> dict[str, Any]:
    destination = SNAPSHOT / "var/ops.sqlite"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(SOURCE_DB, timeout=60) as source:
            source.execute("PRAGMA busy_timeout=60000")
            rows = _historical_instrument_rows(source)
            if len(rows) != EXPECTED_INSTRUMENT_ROWS:
                raise ValueError(f"historical instrument row count drifted: {len(rows)}")
            with sqlite3.connect(destination) as target:
                source.backup(target)
                target.execute("DELETE FROM instruments_v")
                placeholders = ",".join("?" for _ in range(18))
                target.executemany(
                    f"INSERT INTO instruments_v VALUES ({placeholders})",
                    [(*row[:-1], None) for row in rows],
                )
                target.execute("DELETE FROM watermarks")
                target.execute("DELETE FROM runs")
                target.commit()

    with sqlite3.connect(destination) as check:
        total, delisted = check.execute(
            "SELECT COUNT(*), SUM(delisted_ts IS NOT NULL) FROM instruments_v"
        ).fetchone()
        venue_rows = check.execute(
            """
            SELECT CASE
                     WHEN instrument_id LIKE 'BINANCE:%' THEN 'BINANCE'
                     WHEN instrument_id LIKE 'XUSE:%' THEN 'XUSE'
                     ELSE 'OTHER'
                   END AS venue,
                   COUNT(*)
              FROM instruments_v
             GROUP BY 1
             ORDER BY 1
            """
        ).fetchall()
    venues = {str(venue): int(count) for venue, count in venue_rows}
    if int(total) != EXPECTED_INSTRUMENT_ROWS or int(delisted or 0) != EXPECTED_DELISTED:
        raise ValueError("reconstructed historical instrument state drifted")
    if venues != EXPECTED_INSTRUMENTS_BY_VENUE:
        raise ValueError(f"historical instrument venue counts drifted: {venues}")
    return {
        "path": str(destination.relative_to(SNAPSHOT)),
        "rows": int(total),
        "delisted": int(delisted),
        "rows_by_venue": venues,
        "sha256": _sha256(destination),
        "historical_as_of_ms": RUN_LAUNCHED_MS,
    }


def _prepare_experiment_context() -> dict[str, Any]:
    destination = SNAPSHOT / "var/experiments.jsonl"
    all_rows = [
        json.loads(line) for line in SOURCE_LEDGER.read_text(encoding="utf-8").splitlines() if line
    ]
    rows = all_rows[:EXPECTED_LEDGER_ROWS]
    if len(rows) != EXPECTED_LEDGER_ROWS:
        raise ValueError("historical experiment context is incomplete")
    if len({row["config_hash"] for row in rows}) != EXPECTED_LEDGER_ROWS:
        raise ValueError("historical experiment context is not distinct")
    values = [float(row["sharpe_per_period"]) for row in rows]
    variance = float(pa.array(values).to_numpy().var(ddof=1))
    if variance != EXPECTED_LEDGER_VARIANCE:
        raise ValueError(f"historical experiment variance drifted: {variance}")
    rendered = "".join(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n" for row in rows)
    if destination.exists() and destination.read_text(encoding="utf-8") != rendered:
        raise ValueError("existing reconstructed experiment context differs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    return {
        "path": str(destination.relative_to(SNAPSHOT)),
        "distinct_trials": len(rows),
        "sample_variance": variance,
        "sha256": _sha256(destination),
        "target_identity_preseeded_for_idempotent_no_regrade_replay": True,
    }


def _copy_crypto_daily_bars(crypto_ids: list[str]) -> dict[str, Any]:
    source_root = SOURCE_LAKE / "ohlcv_1d"
    destination_root = SNAPSHOT / "data/lake/ohlcv_1d"
    copied_files = 0
    copied_bytes = 0
    for instrument_id in crypto_ids:
        source_dir = source_root / f"instrument_id={instrument_id}"
        files = sorted(source_dir.glob("year=*/data.parquet"))
        if not files:
            raise FileNotFoundError(source_dir)
        for source in files:
            relative = source.relative_to(source_root)
            destination = destination_root / relative
            expected_sha = _sha256(source)
            _copy_bound(source, destination, expected_sha)
            copied_files += 1
            copied_bytes += source.stat().st_size
    return {
        "instrument_ids": len(crypto_ids),
        "files": copied_files,
        "bytes": copied_bytes,
        "source": "surviving_pre_run_Binance_D1_partitions",
    }


def _write_crypto_membership(crypto_ids: list[str]) -> dict[str, Any]:
    destination_root = SNAPSHOT / "data/lake/universe_membership"
    ts_type = pa.timestamp("ms", tz="UTC")
    start = datetime.fromtimestamp(START_MS / 1000, tz=UTC)
    for rank, instrument_id in enumerate(crypto_ids, start=1):
        destination = destination_root / f"instrument_id={instrument_id}" / "year=2000/data.parquet"
        table = pa.Table.from_arrays(
            [
                pa.array([instrument_id], type=pa.string()),
                pa.array([start], type=ts_type),
                pa.array([None], type=ts_type),
                pa.array([rank], type=pa.int32()),
                pa.array(["artifact_informed_zero_held_reconstruction"], type=pa.string()),
            ],
            schema=UNIVERSE_SCHEMA,
        )
        if destination.exists():
            if not pq.ParquetFile(destination).read().equals(table):  # type: ignore[no-untyped-call]
                raise ValueError(f"existing synthetic membership differs: {destination}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table, destination)  # type: ignore[no-untyped-call]
    return {
        "instrument_ids": len(crypto_ids),
        "intervals": len(crypto_ids),
        "source": "artifact_config_instrument_ids",
        "classification": "ARTIFACT_INFORMED_MINIMAL_ZERO_HELD_RECONSTRUCTION",
        "historical_membership_intervals_exact": False,
    }


def _prepare_reference() -> dict[str, Any]:
    target_files = sorted(path for path in TARGET.rglob("*") if path.is_file())
    if len(target_files) != EXPECTED_TARGET_FILES:
        raise ValueError(f"target reference inventory drifted: {len(target_files)}")
    if _sha256(TARGET / "equity.parquet") != EXPECTED_EQUITY_SHA256:
        raise ValueError("target equity binding drifted")
    if not REFERENCE.exists():
        REFERENCE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(TARGET, REFERENCE)
    reference_files = sorted(path for path in REFERENCE.rglob("*") if path.is_file())
    if len(reference_files) != EXPECTED_TARGET_FILES:
        raise ValueError("private reference inventory differs")
    for source, copied in zip(target_files, reference_files, strict=True):
        if source.relative_to(TARGET) != copied.relative_to(REFERENCE):
            raise ValueError("private reference path set differs")
        if _sha256(source) != _sha256(copied):
            raise ValueError(f"private reference file differs: {copied}")
    return {
        "path": str(REFERENCE.relative_to(ROOT)),
        "files": len(reference_files),
        "bytes": sum(path.stat().st_size for path in reference_files),
        "equity_sha256": EXPECTED_EQUITY_SHA256,
    }


def _validate_zero_crypto_positions() -> dict[str, Any]:
    connection = duckdb.connect()
    result = connection.execute(
        f"""
        SELECT count(*) AS total_rows,
               sum(CASE WHEN instrument_id LIKE 'BINANCE:%' THEN 1 ELSE 0 END)
          FROM read_parquet('{TARGET}/legs/*/positions.parquet')
        """
    ).fetchone()
    if result is None:
        raise ValueError("position query returned no aggregate row")
    total_rows, crypto_rows = result
    if int(total_rows) != EXPECTED_POSITION_ROWS or int(crypto_rows or 0) != 0:
        raise ValueError(
            f"zero-held crypto evidence drifted: rows={total_rows}, crypto={crypto_rows}"
        )
    return {
        "reference_position_rows": int(total_rows),
        "crypto_position_rows": int(crypto_rows or 0),
        "supports_minimal_membership_non_effect_claim": True,
    }


def _inventory(directory: Path, excluded: set[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path in excluded:
            continue
        records.append(
            {
                "path": str(path.relative_to(directory)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return records


def build() -> dict[str, Any]:
    if not LINEAGE.is_file():
        raise FileNotFoundError(LINEAGE)
    _, crypto_ids = _artifact_config()
    raw = _copy_raw_archives()
    instrument_state = _prepare_instrument_state()
    experiment_context = _prepare_experiment_context()
    crypto_bars = _copy_crypto_daily_bars(crypto_ids)
    crypto_membership = _write_crypto_membership(crypto_ids)
    reference = _prepare_reference()
    zero_crypto_positions = _validate_zero_crypto_positions()

    receipt_path = SNAPSHOT / "reconstruction_complete.json"
    inventory_path = SNAPSHOT / "input_inventory.jsonl"
    records = _inventory(SNAPSHOT, {receipt_path, inventory_path})
    inventory_text = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    inventory_path.write_text(inventory_text, encoding="utf-8")
    tree_hash = hashlib.sha256(_canonical(records)).hexdigest()
    document: dict[str, Any] = {
        "schema": "canli.alphac-prereg-investment-private-input-reconstruction.v1",
        "author": "Arhan Canli",
        "prepared_at": datetime.now(UTC).isoformat(),
        "status": (
            "SEALED_RAW_ARCHIVES_AND_HISTORICAL_STATE_WITH_ARTIFACT_INFORMED_"
            "ZERO_HELD_CRYPTO_MEMBERSHIP"
        ),
        "private_snapshot": {
            "path": str(SNAPSHOT.relative_to(ROOT)),
            "files_excluding_inventory_and_receipt": len(records),
            "bytes_excluding_inventory_and_receipt": sum(record["bytes"] for record in records),
            "tree_hash": f"sha256:{tree_hash}",
            "inventory_path": str(inventory_path.relative_to(SNAPSHOT)),
            "inventory_sha256": _sha256(inventory_path),
        },
        "raw_vendor_archives": raw,
        "instrument_state": instrument_state,
        "experiment_context": experiment_context,
        "crypto_daily_bars": crypto_bars,
        "crypto_membership": crypto_membership,
        "zero_held_crypto_evidence": zero_crypto_positions,
        "private_reference": reference,
        "lineage_binding": {
            "path": str(LINEAGE.relative_to(ROOT)),
            "sha256": _sha256(LINEAGE),
            "content_hash": json.loads(LINEAGE.read_text(encoding="utf-8"))["content_hash"],
        },
        "rights_and_release": {
            "raw_vendor_rows_publication_authorized": False,
            "private_snapshot_publication_authorized": False,
            "aggregate_hash_receipt_may_be_public": True,
        },
        "claim_boundary": (
            "This packet preserves the raw Sharadar archives, historical instrument and trial "
            "state, surviving Binance D1 bars, and the private derived-output target. The 60 "
            "zero-held Binance memberships are artifact-informed minimal intervals, not exact "
            "historical membership recovery. No strategy equivalence is claimed until a clean "
            "raw-loader and strategy replay passes."
        ),
    }
    _write_json(receipt_path, document)
    return document


def main() -> int:
    document = build()
    print(f"{document['status']}: {SNAPSHOT}")
    print(document["private_snapshot"]["tree_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
