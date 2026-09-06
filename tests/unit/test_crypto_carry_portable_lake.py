from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from alphaforge.core.instruments import Instrument
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset, schema_for

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_crypto_carry_portable_lake.py"
SPEC = importlib.util.spec_from_file_location("crypto_portable_lake_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PortableLakeError = MODULE.PortableLakeError


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _seal(document: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    document["content_hash"] = "sha256:" + hashlib.sha256(_canonical(body)).hexdigest()
    return document


def _instrument(start: pd.Timestamp) -> Instrument:
    return Instrument(
        instrument_id="BINANCE:PERP:TESTUSDT",
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base="TEST",
        quote="USDT",
        tick_size=0.01,
        lot_size=0.1,
        min_qty=0.1,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=int((start + pd.Timedelta(hours=1)).timestamp() * 1000),
        delisted_ts=int((start + pd.Timedelta(hours=3)).timestamp() * 1000),
    )


def test_prepare_ohlcv_filters_lifecycle_and_casts_exact_schema(tmp_path: Path) -> None:
    start = pd.Timestamp("2022-01-01T00:00:00Z")
    times = pd.date_range(start, periods=4, freq="1h")
    source = tmp_path / "TESTUSDT.parquet"
    pd.DataFrame(
        {
            "instrument_id": "BINANCE:PERP:TESTUSDT",
            "ts_open": times,
            "open": [1.0, 2.0, 3.0, 4.0],
            "high": [1.1, 2.1, 3.1, 4.1],
            "low": [0.9, 1.9, 2.9, 3.9],
            "close": [1.0, 2.0, 3.0, 4.0],
            "volume": [10.0] * 4,
            "quote_volume": [10.0] * 4,
            "n_trades": [1] * 4,
            "quality_flags": [0] * 4,
        }
    ).to_parquet(source, index=False)
    table, receipt = MODULE._prepare_table(
        source,
        dataset=Dataset.OHLCV,
        instrument=_instrument(start),
        start=start,
        end=start + pd.Timedelta(hours=4),
        ingested_at=pd.Timestamp("2026-08-24T00:00:00Z"),
    )
    assert table.schema == schema_for(Dataset.OHLCV)
    assert table.num_rows == 2
    assert table.column("ts_open").to_pylist() == times[1:3].to_list()
    assert receipt["removed_before_listing"] == 1
    assert receipt["removed_at_or_after_delisting"] == 1


def test_prepare_table_rejects_duplicate_natural_keys(tmp_path: Path) -> None:
    start = pd.Timestamp("2022-01-01T00:00:00Z")
    source = tmp_path / "funding.parquet"
    timestamp = start + pd.Timedelta(hours=1)
    pd.DataFrame(
        {
            "instrument_id": ["BINANCE:PERP:TESTUSDT"] * 2,
            "ts_funding": [timestamp, timestamp],
            "rate": [0.0001, 0.0001],
            "available_at": [timestamp + pd.Timedelta(minutes=5)] * 2,
        }
    ).to_parquet(source, index=False)
    with pytest.raises(PortableLakeError, match="duplicate timestamps"):
        MODULE._prepare_table(
            source,
            dataset=Dataset.FUNDING,
            instrument=_instrument(start),
            start=start,
            end=start + pd.Timedelta(hours=4),
            ingested_at=pd.Timestamp("2026-08-24T00:00:00Z"),
        )


def test_validate_existing_fails_closed_on_leaf_tampering(tmp_path: Path) -> None:
    output = tmp_path / "portable"
    leaf = output / "lake/ohlcv/instrument_id=BINANCE:PERP:TESTUSDT/year=2022/data.parquet"
    leaf.parent.mkdir(parents=True)
    leaf.write_bytes(b"sealed-leaf")
    ops = output / "ops.sqlite"
    ops.write_bytes(b"sealed-ops")
    leaves = MODULE._leaf_inventory(output)
    manifest = _seal(
        {
            "schema": "canli.alphac-crypto-carry-portable-lake.v1",
            "status": "PASS_ISOLATED_PORTABLE_LAKE_BUILT_ZERO_RETURN",
            "output_inventory": {
                "leaves": leaves,
                "ops_sqlite_sha256": hashlib.sha256(ops.read_bytes()).hexdigest(),
            },
        }
    )
    (output / "portable_lake_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    assert MODULE.validate_existing(output)["content_hash"] == manifest["content_hash"]
    leaf.write_bytes(b"tampered")
    with pytest.raises(PortableLakeError, match="inventory or hash has drifted"):
        MODULE.validate_existing(output)


def test_build_refuses_to_overwrite_an_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(PortableLakeError, match="refusing to overwrite"):
        MODULE.build(tmp_path, tmp_path / "fresh", tmp_path / "readiness.json", output)
