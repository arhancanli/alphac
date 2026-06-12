"""Unit tests for alphaforge.features.parity — the anti-skew harnesses.

Built on a deterministic synthetic tmp_path lake (seeded random walk, one data gap,
8h funding throughout). Verifies:

* batch-vs-live parity is EXACT (atol=0, max_abs_diff == 0.0) for the finite-window
  reference features across sampled decision times;
* the truncation harness passes an honest finite-window feature bit-for-bit, passes an
  EWMA-family feature within the documented 1e-9 relative tolerance, and FAILS a
  deliberately broken full-history feature (expanding mean with an understated
  lookback) and a funding feature whose lookback under-covers its recency horizon;
* funding-consuming features are parity-exact when their lookback honestly covers the
  settlement interval + publication lag (per-row ``available_at`` joins inside the
  batch window).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.context import FeatureContext
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.parity import (
    EWMA_PARITY_RTOL,
    parity_tolerance,
    verify_parity,
    verify_truncation,
)
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from collections.abc import Iterator

BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"

HOUR = 3_600_000
MIN5 = 300_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z
N_BARS = 300
GAP_K = 150  # BTC bar missing from the lake
FUNDING_8H = 8 * HOUR

# Five sampled decision times (epoch ms): seeded-random bar offsets with non-aligned
# intra-bar offsets, all deep enough into history that minimal windows are truncated.
_RNG = np.random.default_rng(7)
SAMPLE_HOURS = sorted(int(h) for h in _RNG.choice(np.arange(100, 296), size=5, replace=False))
TS_SAMPLES = [T0 + h * HOUR + 37 * 60_000 for h in SAMPLE_HOURS]


def _closes(seed: int, level: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return level * np.exp(np.cumsum(rng.normal(0.0, 0.005, N_BARS)))


BTC_CLOSE = _closes(42, 100.0)
ETH_CLOSE = _closes(43, 50.0)


# --------------------------------------------------------------------------- builders


def _ohlcv_table(rows: list[tuple[str, int, float]]) -> pa.Table:
    """rows: (instrument_id, ts_open, close)."""
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "ts_open": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array([r[2] * 0.999 for r in rows], type=pa.float64()),
            "high": pa.array([r[2] * 1.01 for r in rows], type=pa.float64()),
            "low": pa.array([r[2] * 0.99 for r in rows], type=pa.float64()),
            "close": pa.array([r[2] for r in rows], type=pa.float64()),
            "volume": pa.array([10.0 for _ in rows], type=pa.float64()),
            "quote_volume": pa.array([1_000.0 for _ in rows], type=pa.float64()),
            "n_trades": pa.array([7 for _ in rows], type=pa.int64()),
            "quality_flags": pa.array([0 for _ in rows], type=pa.int32()),
            "ingested_at": pa.array(
                [r[1] + HOUR + 30_000 for r in rows], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _funding_table(rows: list[tuple[str, int, float]]) -> pa.Table:
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "ts_funding": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "rate": pa.array([r[2] for r in rows], type=pa.float64()),
            "available_at": pa.array(
                [r[1] + MIN5 for r in rows], type=pa.timestamp("ms", tz="UTC")
            ),
            "ingested_at": pa.array(
                [r[1] + MIN5 + 1_000 for r in rows], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _universe_table() -> pa.Table:
    return pa.table(
        {
            "instrument_id": pa.array([BTC, ETH], type=pa.string()),
            "effective_from": pa.array([T0, T0], type=pa.timestamp("ms", tz="UTC")),
            "effective_to": pa.array([None, None], type=pa.timestamp("ms", tz="UTC")),
            "rank": pa.array([1, 2], type=pa.int32()),
            "reason": pa.array(["enter_top40", "enter_top40"], type=pa.string()),
        }
    )


def _instrument(instrument_id: str, base: str) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=base,
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


@dataclass(frozen=True)
class Env:
    engine: FeatureEngine
    instruments: InstrumentStore


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    paths = LakePaths(tmp_path / "lake")
    writer = LakeWriter(paths)

    bars: list[tuple[str, int, float]] = []
    for k in range(N_BARS):
        if k != GAP_K:
            bars.append((BTC, T0 + k * HOUR, float(BTC_CLOSE[k])))
        bars.append((ETH, T0 + k * HOUR, float(ETH_CLOSE[k])))
    writer.write(Dataset.OHLCV, _ohlcv_table(bars))

    funding: list[tuple[str, int, float]] = []
    for j in range(N_BARS * HOUR // FUNDING_8H):
        rate = 0.0001 * ((j % 7) - 3)
        funding.append((BTC, T0 + j * FUNDING_8H, rate))
        funding.append((ETH, T0 + j * FUNDING_8H, -rate))
    writer.write(Dataset.FUNDING, _funding_table(funding))

    universe = UniverseStore(paths)
    universe.write_intervals(_universe_table())

    instruments = InstrumentStore(tmp_path / "instruments.db")
    instruments.upsert(_instrument(BTC, "BTC"), as_of=T0 - 30 * 24 * HOUR)
    instruments.upsert(_instrument(ETH, "ETH"), as_of=T0 - 30 * 24 * HOUR)

    reader = PITDataReader(paths)
    yield Env(engine=FeatureEngine(reader, instruments, universe), instruments=instruments)
    instruments.close()


# -------------------------------------------------------------- test feature bodies


def _honest_mean_3_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """3-bar mean via pure elementwise shifts: m_t = (C_t + C_{t-1} + C_{t-2}) / 3.

    Bitwise window-invariant by construction (no streaming-sum state), the honest
    finite-window control for the truncation harness.
    """
    from alphaforge.features.context import long_series

    px = ctx.panel("close")
    out = (px + px.shift(1) + px.shift(2)) / 3.0
    return long_series(out, name=spec.name)


def _broken_expanding_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """DELIBERATELY BROKEN: expanding mean over the FULL context window while
    declaring lookback_bars=3 — the exact full-sample-statistic bug the truncation
    harness exists to catch."""
    from alphaforge.features.context import long_series

    px = ctx.panel("close")
    out = px.expanding(min_periods=1).mean()
    return long_series(out, name=spec.name)


def _ewma_close_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """EWMA of close with span S: v_t = sum_i (1-a)^i C_{t-i} / sum_i (1-a)^i,
    a = 2/(S+1) (pandas ewm, adjust=True). Infinite memory => EWMA-family
    truncation convention (lookback = 10x span, parity rtol 1e-9)."""
    from alphaforge.features.context import long_series

    span = int(spec.params["span"])
    px = ctx.panel("close")
    out = px.ewm(span=span, adjust=True, ignore_na=False).mean()
    return long_series(out, name=spec.name)


def _funding_last_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Last-known funding rate at each bar's decision time, via the sanctioned
    available_at as-of join (leakage findings 6/18)."""
    px = ctx.panel("close")
    index = pd.MultiIndex.from_product([px.index, px.columns], names=("ts_open", "instrument_id"))
    return ctx.funding_asof_join(index).rename(spec.name)


def _spec(
    name: str, fn: object, lookback: int, params: dict[str, object] | None = None
) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        family=Family.MARKET,
        direction=0,
        cross_sectional=False,
        lookback_bars=lookback,
        params=params or {},
        fn=fn,  # type: ignore[arg-type]
    )


HONEST_MEAN_3 = _spec("honest_mean_3", _honest_mean_3_fn, lookback=3)
BROKEN_EXPANDING = _spec("broken_expanding_mean", _broken_expanding_fn, lookback=3)
EWMA_CLOSE_8 = _spec(
    "ewma_close_8", _ewma_close_fn, lookback=80, params={"span": 8, "ewma_family": True}
)
FUND_LAST_24 = _spec("fund_last_24", _funding_last_fn, lookback=24)
FUND_LAST_UNDERDECLARED = _spec("fund_last_2", _funding_last_fn, lookback=2)


# ------------------------------------------------------------------------- tolerance


class TestParityTolerance:
    def test_finite_window_is_exact(self) -> None:
        assert parity_tolerance(HONEST_MEAN_3) == 0.0

    def test_ewma_family_gets_relative_tolerance(self) -> None:
        assert parity_tolerance(EWMA_CLOSE_8) == EWMA_PARITY_RTOL == 1e-9


# ---------------------------------------------------------------------- verify_parity


class TestVerifyParity:
    def test_reference_features_exact_across_sampled_ts(self, env: Env) -> None:
        registry = default_registry()
        specs = [registry.get("ret_log_1"), registry.get("close_px")]
        report = verify_parity(env.engine, specs, [BTC, ETH], TS_SAMPLES)
        assert report.passed
        for spec in specs:
            result = report.result(spec.name)
            assert result.rtol == 0.0
            assert result.max_abs_diff == 0.0  # atol=0: bit-for-bit
            assert result.n_points == len(TS_SAMPLES) * 2
            assert result.n_mismatched == 0

    def test_funding_feature_parity_exact(self, env: Env) -> None:
        # The available_at as-of join must be PIT per evaluation row INSIDE the
        # batch window, not just at its end — exactness across deep-history batch
        # vs minimal live window proves it.
        report = verify_parity(env.engine, [FUND_LAST_24], [BTC, ETH], TS_SAMPLES, history_start=T0)
        assert report.passed
        assert report.result("fund_last_24").max_abs_diff == 0.0

    def test_broken_feature_fails_parity_with_early_history_start(self, env: Env) -> None:
        report = verify_parity(
            env.engine, [BROKEN_EXPANDING], [BTC, ETH], TS_SAMPLES, history_start=T0
        )
        assert not report.passed

    def test_empty_samples_rejected(self, env: Env) -> None:
        with pytest.raises(ValueError, match="ts_sample"):
            verify_parity(env.engine, [HONEST_MEAN_3], [BTC], [])

    def test_history_start_after_samples_rejected(self, env: Env) -> None:
        with pytest.raises(ValueError, match="history_start"):
            verify_parity(
                env.engine,
                [HONEST_MEAN_3],
                [BTC],
                [TS_SAMPLES[0]],
                history_start=TS_SAMPLES[-1],
            )

    def test_report_result_unknown_spec(self, env: Env) -> None:
        report = verify_parity(env.engine, [HONEST_MEAN_3], [BTC], [TS_SAMPLES[0]])
        with pytest.raises(KeyError, match="nope"):
            report.result("nope")


# ------------------------------------------------------------------ verify_truncation


class TestVerifyTruncation:
    def test_honest_finite_window_feature_passes_exactly(self, env: Env) -> None:
        report = verify_truncation(
            env.engine, HONEST_MEAN_3, [BTC, ETH], TS_SAMPLES, history_start=T0
        )
        assert report.passed
        assert report.result("honest_mean_3").max_abs_diff == 0.0

    def test_broken_full_history_feature_fails(self, env: Env) -> None:
        # The harness MUST catch a feature consuming more history than declared:
        # full-history expanding mean vs the exactly-lookback_bars live window.
        report = verify_truncation(
            env.engine, BROKEN_EXPANDING, [BTC, ETH], TS_SAMPLES, history_start=T0
        )
        result = report.result("broken_expanding_mean")
        assert not report.passed
        assert result.n_mismatched > 0
        assert result.max_abs_diff > 0.0

    def test_ewma_family_passes_within_documented_tolerance(self, env: Env) -> None:
        report = verify_truncation(
            env.engine, EWMA_CLOSE_8, [BTC, ETH], TS_SAMPLES, history_start=T0
        )
        result = report.result("ewma_close_8")
        assert report.passed
        assert result.rtol == EWMA_PARITY_RTOL
        # The truncated window genuinely differs from full history (so the relative
        # tolerance is exercised), but by far less than the convention's bound.
        assert 0.0 < result.max_abs_diff < 1e-6

    def test_funding_lookback_honesty_enforced(self, env: Env) -> None:
        # lookback=24 covers the 8h settlement interval + 5 min publication lag.
        ok = verify_truncation(env.engine, FUND_LAST_24, [BTC, ETH], TS_SAMPLES, history_start=T0)
        assert ok.passed
        # lookback=2 under-covers it: at decision bars > 2h after the last
        # settlement the minimal window contains no funding row at all.
        bad_sample = T0 + 295 * HOUR + 30 * 60_000  # 295 % 8 == 7h since settlement
        bad = verify_truncation(
            env.engine, FUND_LAST_UNDERDECLARED, [BTC, ETH], [bad_sample], history_start=T0
        )
        assert not bad.passed
        assert bad.result("fund_last_2").max_abs_diff == np.inf  # NaN-vs-value mismatch
