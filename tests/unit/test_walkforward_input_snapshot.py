from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.universe.store import UniverseStore
from alphaforge.validation.input_snapshot import (
    seal_walkforward_input_snapshot,
    validate_input_snapshot,
)

INSTRUMENT = "BINANCE:PERP:BTCUSDT"
START = 1_767_225_600_000  # 2026-01-01 UTC
END = START + 48 * 3_600_000


def _instrument() -> Instrument:
    return Instrument(
        instrument_id=INSTRUMENT,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base="BTC",
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=START - 365 * 24 * 3_600_000,
        delisted_ts=None,
    )


def _fake_repo(root: Path) -> None:
    source = root / "src" / "alphaforge" / "demo.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    (root / "configs").mkdir()
    (root / "configs" / "base.yaml").write_text("profile: test\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='snapshot-test'\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")


def test_snapshot_is_atomic_complete_and_immune_to_lake_replacement(tmp_path: Path) -> None:
    paths = LakePaths(tmp_path / "lake")
    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array([INSTRUMENT], type=pa.string()),
                "effective_from": pa.array([START], type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None], type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1], type=pa.int32()),
                "reason": pa.array(["enter_top40"], type=pa.string()),
            }
        )
    )
    ohlcv = paths.partition_path(Dataset.OHLCV, INSTRUMENT, 2026)
    funding = paths.partition_path(Dataset.FUNDING, INSTRUMENT, 2026)
    ohlcv.parent.mkdir(parents=True)
    funding.parent.mkdir(parents=True)
    ohlcv.write_bytes(b"frozen-ohlcv")
    funding.write_bytes(b"frozen-funding")
    store = InstrumentStore(tmp_path / "ops.sqlite")
    store.upsert(_instrument(), as_of=START - 1)
    repo = tmp_path / "repo"
    _fake_repo(repo)
    signal = pd.DataFrame(
        {
            "ts_open": [START],
            "instrument_id": [INSTRUMENT],
            "alpha_blend": [0.25],
            "mu_ann": [0.10],
        }
    ).set_index(["ts_open", "instrument_id"])
    destination = tmp_path / "result" / "input_snapshot"
    binding = seal_walkforward_input_snapshot(
        destination,
        signal_frame=signal,
        instrument_ids=[INSTRUMENT],
        universe=universe,
        instruments=store,
        lake_paths=paths,
        start=START,
        end=END,
        timeframe=Timeframe.H1,
        asset_class=AssetClass.CRYPTO_PERP,
        declared_run={"allocator": "rank"},
        resolved_settings={"risk": {"max_gross": 1.0}},
        repo_root=repo,
    )
    store.close()

    manifest = validate_input_snapshot(destination)
    assert binding["content_hash"] == manifest["content_hash"]
    assert manifest["status"] == "SEALED_PRE_RUN_PRIVATE_INPUT_SNAPSHOT"
    assert manifest["scope"]["instrument_metadata_rows"] == 1
    assert manifest["raw_execution_partitions"]["files"] == 2
    assert manifest["data_rights"]["public_release_allowed"] is False
    frozen_ohlcv = destination / "raw_partitions" / ohlcv.relative_to(paths.root)
    assert frozen_ohlcv.read_bytes() == b"frozen-ohlcv"

    replacement = ohlcv.with_name("replacement.parquet")
    replacement.write_bytes(b"new-lake-value")
    os.replace(replacement, ohlcv)
    assert ohlcv.read_bytes() == b"new-lake-value"
    assert frozen_ohlcv.read_bytes() == b"frozen-ohlcv"
    validate_input_snapshot(destination)


def test_snapshot_validator_fails_on_any_payload_mutation(tmp_path: Path) -> None:
    paths = LakePaths(tmp_path / "lake")
    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array([INSTRUMENT], type=pa.string()),
                "effective_from": pa.array([START], type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None], type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1], type=pa.int32()),
                "reason": pa.array(["enter_top40"], type=pa.string()),
            }
        )
    )
    store = InstrumentStore(tmp_path / "ops.sqlite")
    store.upsert(_instrument(), as_of=START - 1)
    repo = tmp_path / "repo"
    _fake_repo(repo)
    signal = pd.DataFrame(
        {"alpha_blend": [0.25], "mu_ann": [0.10]},
        index=pd.MultiIndex.from_tuples([(START, INSTRUMENT)], names=["ts_open", "instrument_id"]),
    )
    destination = tmp_path / "input_snapshot"
    seal_walkforward_input_snapshot(
        destination,
        signal_frame=signal,
        instrument_ids=[INSTRUMENT],
        universe=universe,
        instruments=store,
        lake_paths=paths,
        start=START,
        end=END,
        timeframe=Timeframe.H1,
        asset_class=AssetClass.CRYPTO_PERP,
        declared_run={},
        resolved_settings={},
        repo_root=repo,
    )
    store.close()
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["content_hash"].startswith("sha256:")
    (destination / "derived_signal_frame.parquet").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="file inventory drift"):
        validate_input_snapshot(destination)
