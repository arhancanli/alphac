"""Unit tests for alphaforge.backtest.result (BacktestResult save/load).

Covers: the full artifact layout (execDesign.md §4.5), the parquet round-trip
(frames bit-equal, full float64 precision), the recomputed-on-load summary
matching the original, the ResultLike surface (tearsheet renders from the same
object), and schema validation on construction. Everything runs offline in
tmp_path against a synthetic 4-day lake.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.backtest.engine import EventDrivenBacktester, ScriptedStrategy, StaticCostInputs
from alphaforge.backtest.result import BacktestResult
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter

HOUR = 3_600_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z — UTC midnight
LISTED = 1_577_836_800_000  # 2020-01-01T00:00:00Z
BTC = "BINANCE:PERP:BTCUSDT"
ADV = 1e8
SIGMA = 0.02
N_BARS = 96  # 4 UTC days of 1h bars -> daily headline metrics are defined


def make_instrument(instrument_id: str = BTC) -> Instrument:
    symbol = instrument_id.split(":")[2]
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=symbol.removesuffix("USDT"),
        quote="USDT",
        tick_size=0.1,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=10.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=LISTED,
        delisted_ts=None,
    )


def ohlcv_table(rows: list[dict[str, object]]) -> pa.Table:
    def ts(name: str) -> pa.Array:
        return pa.array([r[name] for r in rows], type=pa.timestamp("ms", tz="UTC"))

    def f64(name: str) -> pa.Array:
        return pa.array([r[name] for r in rows], type=pa.float64())

    return pa.table(
        {
            "instrument_id": pa.array([r["instrument_id"] for r in rows], type=pa.string()),
            "ts_open": ts("ts_open"),
            "open": f64("open"),
            "high": f64("high"),
            "low": f64("low"),
            "close": f64("close"),
            "volume": f64("volume"),
            "quote_volume": f64("quote_volume"),
            "n_trades": pa.array([r["n_trades"] for r in rows], type=pa.int64()),
            "quality_flags": pa.array([r["quality_flags"] for r in rows], type=pa.int32()),
            "ingested_at": ts("ingested_at"),
        }
    )


def bar_row(instrument_id: str, ts_open: int, *, open_: float, close: float) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "ts_open": ts_open,
        "open": open_,
        "high": max(open_, close) * 1.01,
        "low": min(open_, close) * 0.99,
        "close": close,
        "volume": 10.0,
        "quote_volume": 1_000.0,
        "n_trades": 42,
        "quality_flags": 0,
        "ingested_at": ts_open + HOUR + 30_000,
    }


def funding_table(rows: list[tuple[str, int, float]]) -> pa.Table:
    # available_at == ts_funding so an event settling at the run end stays
    # visible to the engine's as_of=end read.
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "ts_funding": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "rate": pa.array([r[2] for r in rows], type=pa.float64()),
            "available_at": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "ingested_at": pa.array(
                [r[1] + 1_000 for r in rows], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> BacktestResult:
    """One 4-day single-asset run: buy-and-hold 50% BTC with 8h funding."""
    tmp = tmp_path_factory.mktemp("result")
    bars = [
        bar_row(BTC, T0 + k * HOUR, open_=100.0, close=100.0 + 0.2 * (k % 5)) for k in range(N_BARS)
    ]
    funding = [(BTC, T0 + 8 * HOUR * j, 1e-4) for j in range(1, 13)]  # every 8h to T0+96h
    paths = LakePaths(tmp / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV, ohlcv_table(bars))
    writer.write(Dataset.FUNDING, funding_table(funding))
    store = InstrumentStore(tmp / "ops.sqlite")
    store.upsert(make_instrument(BTC), as_of=1)
    engine = EventDrivenBacktester(
        PITDataReader(paths),
        store,
        TransactionCostModel(),
        cost_inputs=StaticCostInputs(adv_quote=ADV, sigma_daily=SIGMA),
        config_echo={"strategy": "scripted-test"},
    )
    return engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.5}}),
        [BTC],
        start=T0,
        end=T0 + N_BARS * HOUR,
    )


@pytest.fixture(scope="module")
def saved_dir(result: BacktestResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("artifacts") / "run"
    returned = result.save(out)
    assert returned == out
    return out


def assert_summary_equal(a: object, b: object) -> None:
    """Field-by-field PerfSummary comparison, NaN == NaN."""
    for f in dataclasses.fields(a):  # type: ignore[arg-type]
        va, vb = getattr(a, f.name), getattr(b, f.name)
        if isinstance(va, float) and math.isnan(va):
            assert isinstance(vb, float) and math.isnan(vb), f.name
        else:
            assert va == pytest.approx(vb, abs=1e-12), f.name


# ----------------------------------------------------------------- artifacts


def test_save_writes_complete_artifact_layout(saved_dir: Path) -> None:
    expected = {
        "equity.parquet",
        "fills.parquet",
        "funding.parquet",
        "corporate_actions.parquet",
        "financing.parquet",
        "orders.parquet",
        "positions.parquet",
        "run_meta.json",
        "summary.txt",
        "tearsheet.png",
        "tearsheet.txt",
    }
    assert expected.issubset({p.name for p in saved_dir.iterdir()})
    assert (saved_dir / "tearsheet.png").stat().st_size > 0
    assert (saved_dir / "summary.txt").read_text(encoding="utf-8").strip()


def test_run_meta_echoes_config_and_counters(saved_dir: Path, result: BacktestResult) -> None:
    meta = json.loads((saved_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["config"]["start"] == T0
    assert meta["config"]["end"] == T0 + N_BARS * HOUR
    assert meta["config"]["instrument_ids"] == [BTC]
    assert meta["config"]["strategy"] == "scripted-test"  # config_echo passthrough
    assert meta["config"]["fill_model"] == "NextOpenFill"
    assert meta["counters"] == result.counters


def test_round_trip_load(saved_dir: Path, result: BacktestResult) -> None:
    loaded = BacktestResult.load(saved_dir)
    pd.testing.assert_series_equal(loaded.equity, result.equity)
    pd.testing.assert_frame_equal(loaded.fills, result.fills)
    pd.testing.assert_frame_equal(loaded.funding_events, result.funding_events)
    pd.testing.assert_frame_equal(loaded.corporate_actions, result.corporate_actions)
    pd.testing.assert_frame_equal(loaded.financing_events, result.financing_events)
    pd.testing.assert_frame_equal(loaded.orders, result.orders)
    pd.testing.assert_frame_equal(loaded.positions, result.positions)
    assert loaded.counters == result.counters
    assert loaded.config["start"] == result.config["start"]
    assert loaded.config["instrument_ids"] == result.config["instrument_ids"]
    # the summary is RECOMPUTED from artifacts on load — identical inputs,
    # identical metrics (a stale summary file can never misrepresent the data)
    assert_summary_equal(loaded.summary, result.summary)


def test_load_missing_artifact_raises(saved_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        BacktestResult.load(tmp_path / "nope")


# ------------------------------------------------------------- result surface


def test_funding_property_is_signed_series(result: BacktestResult) -> None:
    funding = result.funding
    assert isinstance(funding, pd.Series)
    assert len(funding) == 12  # all 12 stored events settled against the long
    # long + positive rate -> every payment negative (longs pay), and the sum
    # reconciles with the headline funding_net
    assert (funding < 0.0).all()
    assert float(funding.sum()) == pytest.approx(result.summary.funding_net, abs=1e-12)


def test_fills_carry_notional_and_fee_for_analytics(result: BacktestResult) -> None:
    fills = result.fills
    assert {"ts", "notional", "fee"}.issubset(fills.columns)
    assert len(fills) == 1  # single buy-and-hold entry
    row = fills.iloc[0]
    assert row["notional"] == pytest.approx(row["qty"] * row["price"], abs=1e-9)
    assert result.summary.fees_paid == pytest.approx(float(fills["fee"].sum()), abs=1e-12)


def test_positions_snapshot_every_bar_close(result: BacktestResult) -> None:
    # one open position from C2 onward -> one snapshot row per remaining close
    positions = result.positions
    assert len(positions) == N_BARS - 1
    assert positions["ts"].is_monotonic_increasing
    # weight = qty*mark/equity stays near the 50% target (drift only)
    assert positions["weight"].between(0.45, 0.55).all()


def test_constructor_rejects_missing_columns(result: BacktestResult) -> None:
    with pytest.raises(ValueError, match="fills frame missing columns"):
        BacktestResult(
            equity=result.equity,
            fills=result.fills.drop(columns=["notional"]),
            funding_events=result.funding_events,
            orders=result.orders,
            positions=result.positions,
            summary=result.summary,
        )
    with pytest.raises(ValueError, match="orders frame missing columns"):
        BacktestResult(
            equity=result.equity,
            fills=result.fills,
            funding_events=result.funding_events,
            orders=result.orders.drop(columns=["status"]),
            positions=result.positions,
            summary=result.summary,
        )


def test_equity_full_precision_round_trip(saved_dir: Path, result: BacktestResult) -> None:
    # float64 survives parquet bit-exactly: no rounding anywhere before render
    loaded = BacktestResult.load(saved_dir)
    assert (loaded.equity.to_numpy() == result.equity.to_numpy()).all()
