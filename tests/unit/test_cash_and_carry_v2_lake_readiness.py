"""The cash-and-carry v2 readiness audit applies the draft's universe rule and nothing more."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pyarrow as pa

from alphaforge.core.time import Timeframe
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.writer import LakeWriter

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "cash_and_carry_v2_readiness_under_test",
    ROOT / "scripts" / "audit_crypto_cash_and_carry_v2_lake_readiness.py",
)
assert _SPEC and _SPEC.loader
AUDIT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(AUDIT)

END = pd.Timestamp("2021-06-30", tz="UTC")
DAYS = pd.date_range(END - pd.Timedelta(days=29), END, freq="D", tz="UTC")


def _daily(coin: str, days: pd.DatetimeIndex, volume: float) -> pd.DataFrame:
    return pd.DataFrame({"coin": coin, "day": days, "quote_volume": volume})


def _frames(**overrides: tuple[pd.DatetimeIndex, pd.DatetimeIndex, float]):
    perp, spot = [], []
    for coin, (perp_days, spot_days, volume) in overrides.items():
        perp.append(_daily(coin, perp_days, volume))
        spot.append(_daily(coin, spot_days, 1.0))
    return pd.concat(perp, ignore_index=True), pd.concat(spot, ignore_index=True)


def test_the_rule_needs_both_legs_every_day_and_the_volume_floor() -> None:
    perp, spot = _frames(
        OKUSDT=(DAYS, DAYS, 25e6),
        THINUSDT=(DAYS, DAYS, 19e6),
        NOSPOTDAYUSDT=(DAYS, DAYS.delete(3), 90e6),
        NOPERPDAYUSDT=(DAYS.delete(10), DAYS, 90e6),
    )
    eligible = AUDIT.eligible_by_month_end(perp, spot)
    assert eligible["2021-06-30"] == ["OKUSDT"]


def test_status_waits_for_a_complete_ingest_then_gates_on_ten_every_month() -> None:
    coins = {f"C{i:02d}USDT": (DAYS, DAYS, 30e6) for i in range(10)}
    perp, spot = _frames(**coins)
    partial = AUDIT.build(perp, spot, {"done": {}}, perp_symbols=10)
    assert partial["status"] == "INCOMPLETE_SPOT_INGEST_NOT_ASSESSABLE"
    complete = {"done": {}, "complete": {"at": "2026-09-24T09:00:00+00:00"}}
    document = AUDIT.build(perp, spot, complete, perp_symbols=10)
    # Only June 2021 has data, so every later month end has zero eligible coins.
    assert document["eligible_count_by_month_end"]["2021-06-30"] == 10
    assert document["status"] == "FAIL_UNIVERSE_BELOW_TOP_K"
    assert "2021-07-31" in document["months_below_gate"]
    assert document["content_hash"] == AUDIT._content_hash(document)


def test_daily_activity_reads_one_market_and_never_prices(tmp_path: Path) -> None:
    writer = LakeWriter(LakePaths(tmp_path))
    hours = pd.date_range("2021-06-01", periods=48, freq="h", tz="UTC")
    for instrument in ("BINANCE:PERP:BTCUSDT", "BINANCE:SPOT:BTCUSDT"):
        n = len(hours)
        writer.write(
            Dataset.OHLCV,
            pa.table(
                {
                    "instrument_id": [instrument] * n,
                    "ts_open": pa.array(hours, pa.timestamp("ms", tz="UTC")),
                    "open": [1.0] * n,
                    "high": [1.0] * n,
                    "low": [1.0] * n,
                    "close": [1.0] * n,
                    "volume": [1.0] * n,
                    "quote_volume": [2.0] * n,
                    "n_trades": [1] * n,
                    "quality_flags": pa.array([0] * n, pa.int32()),
                    "ingested_at": pa.array(hours, pa.timestamp("ms", tz="UTC")),
                }
            ),
            tf=Timeframe.H1,
        )
    daily = AUDIT.daily_activity(tmp_path, "PERP")
    assert set(daily.columns) == {"coin", "day", "quote_volume"}
    assert daily["coin"].unique().tolist() == ["BTCUSDT"]
    assert daily["quote_volume"].tolist() == [48.0, 48.0]
