"""Unit tests for alphaforge.features.library.market (buildabilityCritique.md §3.9).

Covers: ``adv_quote_30d`` — exact 30-day rolling MEDIAN of complete-UTC-day quote
volume on a hand-structured fixture (per-day constant volumes => exact medians at
day boundaries), robustness to a planted single-day 100x volume spike (the median
must not move), the complete-day PIT boundary (a day enters only once fully
elapsed at the decision time) and the warmup boundary; ``sigma_daily`` — the EWMA
recursion (halflife 240) against a manual loop, the ``sqrt(24)`` daily-horizon
scaling, the ``min_periods`` warmup, and the EWMA-family spec convention
(``lookback_bars = 12 * span >= 10 * span``). Truncation invariance via
``verify_truncation``: exact (atol = 0) for the finite-window ADV, and within the
1e-9 relative EWMA tolerance — with a genuinely nonzero truncation residual — for
``sigma_daily`` on a lake longer than its lookback.

All lake-backed tests run against deterministic synthetic tmp lakes (offline).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pytest

from alphaforge.core.instruments import InstrumentStore
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library.market import (
    BARS_PER_DAY,
    SIGMA_DAILY_HALFLIFE,
)
from alphaforge.features.parity import verify_truncation
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import EWMA_LOOKBACK_SPANS, Family

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.spec import FeatureSpec

BTC = "BINANCE:PERP:BTCUSDT"  # structured: per-day constant QV = 100 * (day + 1)
ETH = "BINANCE:PERP:ETHUSDT"  # constant QV = 100/bar, except day 45 spiked 100x

HOUR = 3_600_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z — midnight UTC (day-aligned)
N_STRUCT = 1_500  # 62.5 UTC days
N_BIG = 8_500  # > sigma_daily lookback (8316): truncation is genuinely exercised

SPIKE_DAY = 45


# --------------------------------------------------------------------------- builders


def _make_close(seed: int, n: int, level: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    walk: np.ndarray = level * np.exp(np.cumsum(rng.normal(0.0, 0.005, n)))
    return walk


def _qv_struct(k: int) -> float:
    """BTC quote volume: constant within each UTC day, day d => 100 * (d + 1)."""
    return 100.0 * (k // BARS_PER_DAY + 1)


def _qv_spiked(k: int) -> float:
    """ETH quote volume: 100/bar except the planted 100x spike day."""
    return 10_000.0 if k // BARS_PER_DAY == SPIKE_DAY else 100.0


def _ohlcv_table(per_inst: dict[str, tuple[np.ndarray, list[float]]]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    closes: list[float] = []
    qvs: list[float] = []
    for iid, (close, qv) in per_inst.items():
        n = len(close)
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        closes.extend(float(v) for v in close)
        qvs.extend(qv)
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(closes, type=pa.float64()),
            "high": pa.array([c * 1.001 for c in closes], type=pa.float64()),
            "low": pa.array([c * 0.999 for c in closes], type=pa.float64()),
            "close": pa.array(closes, type=pa.float64()),
            "volume": pa.array([10.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array(qvs, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


@dataclass(frozen=True)
class Env:
    engine: FeatureEngine
    close: dict[str, np.ndarray]


def _build_env(
    tmp_path_factory: pytest.TempPathFactory, name: str, n: int
) -> tuple[Env, InstrumentStore]:
    tmp = tmp_path_factory.mktemp(name)
    paths = LakePaths(tmp / "lake")
    close = {BTC: _make_close(41, n, 100.0), ETH: _make_close(42, n, 50.0)}
    per_inst = {
        BTC: (close[BTC], [_qv_struct(k) for k in range(n)]),
        ETH: (close[ETH], [_qv_spiked(k) for k in range(n)]),
    }
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(per_inst))
    instruments = InstrumentStore(tmp / "instruments.db")
    engine = FeatureEngine(PITDataReader(paths), instruments, UniverseStore(paths))
    return Env(engine=engine, close=close), instruments


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    built, instruments = _build_env(tmp_path_factory, "factors_market", N_STRUCT)
    yield built
    instruments.close()


@pytest.fixture(scope="module")
def env_big(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    built, instruments = _build_env(tmp_path_factory, "factors_market_big", N_BIG)
    yield built
    instruments.close()


def _spec(name: str) -> FeatureSpec:
    return default_registry().get(name)


def _adv(env: Env, ts: int, iid: str) -> float:
    out = env.engine.compute_history([_spec("adv_quote_30d")], [BTC, ETH], start=ts, end=ts + HOUR)
    return float(out.loc[(ts, iid), "adv_quote_30d"])


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpecs:
    def test_adv_metadata(self) -> None:
        spec = _spec("adv_quote_30d")
        assert spec.family is Family.MARKET
        assert spec.direction == 0  # shared utility input, not an alpha
        assert spec.cross_sectional is False  # consumed raw, in USDT/day
        assert spec.lookback_bars == 30 * BARS_PER_DAY + (BARS_PER_DAY - 1)  # 743
        assert not spec.is_ewma_family

    def test_sigma_daily_metadata_ewma_family(self) -> None:
        spec = _spec("sigma_daily")
        assert spec.family is Family.MARKET
        assert spec.direction == 0
        assert spec.cross_sectional is False
        assert spec.is_ewma_family
        # Span derived from the halflife-240 recursion: alpha = 1 - 2^(-1/240).
        alpha = 1.0 - 0.5 ** (1.0 / SIGMA_DAILY_HALFLIFE)
        span = math.ceil(2.0 / alpha - 1.0)
        assert spec.params["span"] == span == 693
        assert spec.lookback_bars == 12 * span  # above the 10x-span minimum
        assert spec.lookback_bars >= EWMA_LOOKBACK_SPANS * span


# ----------------------------------------------------------------------- ADV behavior


class TestAdvQuote30d:
    def test_exact_median_at_day_boundaries(self, env: Env) -> None:
        # BTC's daily quote volume is DQV(d) = 2400 * (d + 1) exactly.
        # Bar 719 decides at hour 720 == 30 full days: median over days 0..29
        # = 2400 * median(1..30) = 2400 * 15.5.
        assert _adv(env, T0 + 719 * HOUR, BTC) == 2400.0 * 15.5
        # Every bar of day 30 except its last still sees days 0..29.
        assert _adv(env, T0 + 720 * HOUR, BTC) == 2400.0 * 15.5
        assert _adv(env, T0 + 742 * HOUR, BTC) == 2400.0 * 15.5
        # Bar 743 decides at hour 744: day 30 completes, window slides to 1..30.
        assert _adv(env, T0 + 743 * HOUR, BTC) == 2400.0 * 16.5

    def test_complete_day_pit_boundary(self, env: Env) -> None:
        # The bar deciding exactly at midnight is the FIRST to include the day
        # that ends at that midnight — one bar earlier must not see it.
        before = _adv(env, T0 + 742 * HOUR, BTC)  # decides 23:00 of day 30
        at_midnight = _adv(env, T0 + 743 * HOUR, BTC)  # decides 00:00 of day 31
        assert before == 2400.0 * 15.5
        assert at_midnight == 2400.0 * 16.5
        assert at_midnight != before

    def test_median_resists_single_day_100x_spike(self, env: Env) -> None:
        # ETH: every day 2400 USDT except day 45 at 240000 (100x). A mean would
        # report (29 * 2400 + 240000) / 30 = 10320; the median must stay 2400.
        ts = T0 + 50 * BARS_PER_DAY * HOUR  # day 50: window (days 20..49) spans the spike
        assert _adv(env, ts, ETH) == 2400.0

    def test_nan_until_30_complete_days(self, env: Env) -> None:
        assert np.isnan(_adv(env, T0 + 718 * HOUR, BTC))  # 29 days + 23 bars
        assert np.isfinite(_adv(env, T0 + 719 * HOUR, BTC))


# --------------------------------------------------------------------- sigma behavior


class TestSigmaDaily:
    def test_matches_manual_ewma_recursion_and_sqrt24_scaling(self, env: Env) -> None:
        start, end = T0 + 240 * HOUR, T0 + 246 * HOUR
        out = env.engine.compute_history([_spec("sigma_daily")], [BTC], start=start, end=end)
        close = env.close[BTC]
        alpha = 1.0 - 0.5 ** (1.0 / SIGMA_DAILY_HALFLIFE)
        r = [math.log(close[k] / close[k - 1]) for k in range(1, len(close))]
        var = r[0] ** 2  # adjust=False seeds at the first valid observation
        history = [var]
        for x in r[1:]:
            var = alpha * x * x + (1.0 - alpha) * var
            history.append(var)
        for k in range(240, 246):
            expected = math.sqrt(history[k - 1]) * math.sqrt(BARS_PER_DAY)
            got = out.loc[(T0 + k * HOUR, BTC), "sigma_daily"]
            assert got == pytest.approx(expected, rel=1e-12)

    def test_nan_until_min_periods_returns(self, env: Env) -> None:
        out = env.engine.compute_history(
            [_spec("sigma_daily")], [BTC], start=T0 + 239 * HOUR, end=T0 + 241 * HOUR
        )
        col = out["sigma_daily"].xs(BTC, level="instrument_id")
        assert np.isnan(col.iloc[0])  # 239 valid returns < min_periods = 240
        assert np.isfinite(col.iloc[1])


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    def test_adv_exact_under_truncation(self, env: Env) -> None:
        spec = _spec("adv_quote_30d")
        ts_samples = [T0 + 1400 * HOUR + 7 * 60_000, T0 + 1450 * HOUR]
        report = verify_truncation(env.engine, spec, [BTC, ETH], ts_samples, history_start=T0)
        result = report.result(spec.name)
        assert result.passed, result
        assert result.rtol == 0.0
        assert result.max_abs_diff == 0.0
        assert result.n_points == 4
        live = env.engine.compute_asof([spec], [BTC, ETH], as_of=ts_samples[0])
        assert live["adv_quote_30d"].notna().all()  # non-vacuous

    def test_sigma_daily_within_ewma_tolerance_under_truncation(self, env_big: Env) -> None:
        # Lake (8500 bars) exceeds the lookback (8316): the live minimal window
        # genuinely truncates the infinite-memory recursion. The residual must be
        # nonzero (the truncation is real) yet inside the 1e-9 relative budget.
        spec = _spec("sigma_daily")
        ts_samples = [T0 + 8_450 * HOUR + 19 * 60_000, T0 + 8_470 * HOUR]
        report = verify_truncation(env_big.engine, spec, [BTC, ETH], ts_samples, history_start=T0)
        result = report.result(spec.name)
        assert result.passed, result
        assert result.rtol == 1e-9
        assert 0.0 < result.max_abs_diff < 1e-9
        live = env_big.engine.compute_asof([spec], [BTC, ETH], as_of=ts_samples[0])
        assert live["sigma_daily"].notna().all()  # non-vacuous
