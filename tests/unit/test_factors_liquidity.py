"""Unit tests for alphaforge.features.library.liquidity (alphaDesign.md §2.6).

Covers: Amihud illiquidity, the abnormal-volume z-score (plain and 24h-sum
variants) and the Corwin-Schultz spread estimator against brute-force formula
evaluations on tiny hand-checkable fixtures (1e-12), the declared missing-data
policies (Amihud SKIPS QV==0/gap bars; z-score and CS smoothing are STRICT),
the CS negative-spread floor, input-mutation safety, registered-spec metadata
(names/directions/lookbacks derived from params), engine wiring (registered fn
output == helper output on the same panel), warmup boundaries, and truncation
invariance via ``verify_truncation`` for EVERY registered liquidity spec
(finite windows: parity atol = 0, asserted as ``max_abs_diff == 0.0``).

All lake-backed tests run against a deterministic synthetic tmp lake (offline).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.core.instruments import InstrumentStore
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library.liquidity import (
    AMIHUD_EPS,
    CS_DENOM,
    amihud_illiq,
    corwin_schultz_spread,
    volume_zscore,
)
from alphaforge.features.parity import verify_truncation
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.spec import FeatureSpec

BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"

HOUR = 3_600_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z (1h-aligned)
N_BARS = 800

LIQ_SPEC_NAMES = ("liq_amihud_720", "liq_volz_720", "liq_volz_24h_sum", "liq_cs_spread_168")


# --------------------------------------------------------------------------- builders


def _make_ohlc(seed: int, n: int, level: float) -> dict[str, np.ndarray]:
    """Deterministic OHLC random walk with valid bar geometry and positive QV."""
    rng = np.random.default_rng(seed)
    close = level * np.exp(np.cumsum(rng.normal(0.0, 0.005, n)))
    open_ = np.empty(n)
    open_[0] = level
    open_[1:] = close[:-1] * np.exp(rng.normal(0.0, 0.001, n - 1))
    wick = np.abs(rng.normal(0.0, 0.002, n))
    high = np.maximum(open_, close) * np.exp(wick)
    low = np.minimum(open_, close) * np.exp(-wick)
    qv = 1_000.0 + 500.0 * rng.random(n)
    return {"open": open_, "high": high, "low": low, "close": close, "qv": qv}


def _ohlcv_table(per_inst: dict[str, dict[str, np.ndarray]]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    cols: dict[str, list[float]] = {"open": [], "high": [], "low": [], "close": [], "qv": []}
    for iid, ohlc in per_inst.items():
        n = len(ohlc["close"])
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        for name in cols:
            cols[name].extend(float(v) for v in ohlc[name])
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(cols["open"], type=pa.float64()),
            "high": pa.array(cols["high"], type=pa.float64()),
            "low": pa.array(cols["low"], type=pa.float64()),
            "close": pa.array(cols["close"], type=pa.float64()),
            "volume": pa.array([10.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array(cols["qv"], type=pa.float64()),
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
    ohlc: dict[str, dict[str, np.ndarray]]


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("factors_liquidity")
    paths = LakePaths(tmp / "lake")
    ohlc = {BTC: _make_ohlc(31, N_BARS, 100.0), ETH: _make_ohlc(32, N_BARS, 50.0)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(ohlc))
    instruments = InstrumentStore(tmp / "instruments.db")
    engine = FeatureEngine(PITDataReader(paths), instruments, UniverseStore(paths))
    yield Env(engine=engine, ohlc=ohlc)
    instruments.close()


def _specs() -> list[FeatureSpec]:
    registry = default_registry()
    return [registry.get(name) for name in LIQ_SPEC_NAMES]


def _panels(env: Env) -> dict[str, pd.DataFrame]:
    """Wide panels built directly from the raw arrays (rows == grid slots)."""
    index = pd.Index([T0 + k * HOUR for k in range(N_BARS)], name="ts_open")
    fields = {"open": "open", "high": "high", "low": "low", "close": "close", "qv": "qv"}
    return {
        out: pd.DataFrame({iid: env.ohlc[iid][src] for iid in (BTC, ETH)}, index=index)
        for out, src in fields.items()
    }


# ----------------------------------------------------------------- brute-force checks


class TestAmihudFormula:
    C: ClassVar[list[float]] = [100.0, 101.0, 99.5, 102.0, 101.5, 100.5]
    QV: ClassVar[list[float]] = [1000.0, 1200.0, 0.0, 1100.0, 1300.0, 900.0]

    def _frames(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        return pd.DataFrame({"A": self.C}), pd.DataFrame({"A": self.QV})

    def _ratio(self, t: int) -> float:
        return abs(math.log(self.C[t] / self.C[t - 1])) / self.QV[t]

    def test_matches_brute_force_skipping_zero_qv_to_1e12(self) -> None:
        close, qv = self._frames()
        out = amihud_illiq(close, qv, window=3)
        # t=4, window {2,3,4}: bar 2 has QV == 0 => SKIPPED, mean over 2 valid bars.
        expected_4 = math.log((self._ratio(3) + self._ratio(4)) / 2 + AMIHUD_EPS)
        assert abs(out.iloc[4, 0] - expected_4) < 1e-12
        # t=2, window {0,1,2}: bar 0 has no return, bar 2 zero QV => only bar 1.
        expected_2 = math.log(self._ratio(1) + AMIHUD_EPS)
        assert abs(out.iloc[2, 0] - expected_2) < 1e-12
        # t=5, full window of valid bars {3,4,5}.
        expected_5 = math.log((self._ratio(3) + self._ratio(4) + self._ratio(5)) / 3 + AMIHUD_EPS)
        assert abs(out.iloc[5, 0] - expected_5) < 1e-12

    def test_all_invalid_window_is_nan(self) -> None:
        close = pd.DataFrame({"A": [100.0, 101.0, 102.0, 103.0]})
        qv = pd.DataFrame({"A": [0.0, 0.0, 0.0, 0.0]})
        out = amihud_illiq(close, qv, window=2)
        assert out["A"].isna().all()  # nothing to average — NaN, not log(eps)

    def test_first_bar_is_nan_then_partial_windows_allowed(self) -> None:
        # min_periods = 1 semantics: bar 0 has no return (NaN); bar 1 is already
        # a (partial-window) value — the documented Amihud "skip" reading.
        close, qv = self._frames()
        out = amihud_illiq(close, qv, window=3)
        assert np.isnan(out.iloc[0, 0])
        assert abs(out.iloc[1, 0] - math.log(self._ratio(1) + AMIHUD_EPS)) < 1e-12

    def test_window_below_one_rejected(self) -> None:
        close, qv = self._frames()
        with pytest.raises(ValueError, match="window"):
            amihud_illiq(close, qv, window=0)


class TestVolumeZscoreFormula:
    QV: ClassVar[list[float]] = [10.0, 20.0, 15.0, 30.0, 25.0]

    def test_matches_brute_force_to_1e12(self) -> None:
        out = volume_zscore(pd.DataFrame({"A": self.QV}), window=3)
        x = [math.log1p(v) for v in self.QV]
        for t in (2, 3, 4):
            win = x[t - 2 : t + 1]
            mu = sum(win) / 3
            sd = math.sqrt(sum((v - mu) ** 2 for v in win) / 2)  # ddof = 1
            assert abs(out.iloc[t, 0] - (x[t] - mu) / sd) < 1e-12
        assert out.iloc[:2, 0].isna().all()  # STRICT: NaN before `window` bars

    def test_sum_bars_variant_matches_brute_force(self) -> None:
        out = volume_zscore(pd.DataFrame({"A": self.QV}), window=2, sum_bars=2)
        sums = [self.QV[t] + self.QV[t - 1] for t in range(1, 5)]  # defined from t=1
        x = [math.log1p(s) for s in sums]
        # First defined z at t=2 (two summed observations: x[0] at t=1, x[1] at t=2).
        for t in (2, 3, 4):
            win = x[t - 2 : t]
            mu = sum(win) / 2
            sd = math.sqrt(sum((v - mu) ** 2 for v in win) / 1)
            assert abs(out.iloc[t, 0] - (x[t - 1] - mu) / sd) < 1e-12
        assert out.iloc[:2, 0].isna().all()

    def test_constant_volume_is_nan(self) -> None:
        out = volume_zscore(pd.DataFrame({"A": [50.0] * 6}), window=3)
        assert out["A"].isna().all()  # s = 0: no abnormality measurable, never ±inf

    def test_invalid_params_rejected(self) -> None:
        frame = pd.DataFrame({"A": self.QV})
        with pytest.raises(ValueError, match="window"):
            volume_zscore(frame, window=1)
        with pytest.raises(ValueError, match="sum_bars"):
            volume_zscore(frame, window=3, sum_bars=0)


class TestCorwinSchultzFormula:
    H: ClassVar[list[float]] = [102.0, 103.5, 101.0]
    L: ClassVar[list[float]] = [99.0, 100.0, 98.0]

    @staticmethod
    def _spread(h0: float, l0: float, h1: float, l1: float) -> float:
        beta = math.log(h0 / l0) ** 2 + math.log(h1 / l1) ** 2
        gamma = math.log(max(h0, h1) / min(l0, l1)) ** 2
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / CS_DENOM - math.sqrt(gamma / CS_DENOM)
        s = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
        return max(s, 0.0)

    def test_denominator_constant_is_exact(self) -> None:
        assert 3.0 - 2.0 * math.sqrt(2.0) == CS_DENOM
        assert abs(CS_DENOM - 0.171573) < 1e-6  # the design's rounded value

    def test_matches_brute_force_to_1e12(self) -> None:
        high = pd.DataFrame({"A": self.H})
        low = pd.DataFrame({"A": self.L})
        out = corwin_schultz_spread(high, low, smooth=1)
        for t in (1, 2):
            expected = self._spread(self.H[t - 1], self.L[t - 1], self.H[t], self.L[t])
            assert abs(out.iloc[t, 0] - expected) < 1e-12
        assert np.isnan(out.iloc[0, 0])  # needs the previous bar

    def test_smoothing_is_strict_mean(self) -> None:
        high = pd.DataFrame({"A": self.H})
        low = pd.DataFrame({"A": self.L})
        per_bar = corwin_schultz_spread(high, low, smooth=1)
        out = corwin_schultz_spread(high, low, smooth=2)
        assert out.iloc[:2, 0].isna().all()  # window must hold 2 defined estimates
        expected = (per_bar.iloc[1, 0] + per_bar.iloc[2, 0]) / 2
        assert abs(out.iloc[2, 0] - expected) < 1e-12

    def test_negative_spread_floored_at_zero(self) -> None:
        # Disjoint consecutive ranges: gamma dominates beta => alpha < 0 => floor.
        high = pd.DataFrame({"A": [101.0, 103.0]})
        low = pd.DataFrame({"A": [100.0, 102.0]})
        raw = self._spread(101.0, 100.0, 103.0, 102.0)
        assert raw == 0.0  # fixture sanity: the un-floored estimate IS negative
        out = corwin_schultz_spread(high, low, smooth=1)
        assert out.iloc[1, 0] == 0.0

    def test_smooth_below_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="smooth"):
            corwin_schultz_spread(
                pd.DataFrame({"A": self.H}), pd.DataFrame({"A": self.L}), smooth=0
            )


class TestGapPolicy:
    def test_gap_skipped_by_amihud_but_poisons_strict_zscore(self) -> None:
        n, gap, window = 30, 12, 5
        rng = np.random.default_rng(7)
        close = pd.DataFrame({"A": 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))})
        qv = pd.DataFrame({"A": 1000.0 + 100.0 * rng.random(n)})
        close.iloc[gap] = np.nan
        qv.iloc[gap] = np.nan
        # Amihud: gap bar and the bar after lose their return => SKIPPED, value
        # stays finite (mean over the remaining valid bars in the window).
        out_a = amihud_illiq(close, qv, window=window)
        assert np.isfinite(out_a.iloc[gap + 1, 0])
        ratios = (np.log(close / close.shift(1)).abs() / qv)["A"].to_numpy()
        valid = ratios[gap - window + 2 : gap + 2]
        expected = math.log(float(np.nanmean(valid)) + AMIHUD_EPS)
        assert abs(out_a.iloc[gap + 1, 0] - expected) < 1e-12
        # Z-score: STRICT window — every window touching the gap is NaN.
        out_z = volume_zscore(qv, window=window)
        assert out_z.iloc[gap : gap + window, 0].isna().all()
        assert np.isfinite(out_z.iloc[gap - 1, 0])
        assert np.isfinite(out_z.iloc[gap + window, 0])


class TestNoInputMutation:
    def test_helpers_never_mutate_inputs(self) -> None:
        rng = np.random.default_rng(9)
        n = 12
        close = pd.DataFrame({"A": 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))})
        qv = pd.DataFrame({"A": 1000.0 + 100.0 * rng.random(n)})
        high = close * 1.01
        low = close * 0.99
        copies = [f.copy(deep=True) for f in (close, qv, high, low)]
        amihud_illiq(close, qv, window=4)
        volume_zscore(qv, window=4, sum_bars=2)
        corwin_schultz_spread(high, low, smooth=3)
        for original, snapshot in zip((close, qv, high, low), copies, strict=True):
            pd.testing.assert_frame_equal(original, snapshot)


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpecs:
    def test_metadata(self) -> None:
        registry = default_registry()
        expected_lookbacks = {
            "liq_amihud_720": 721,  # returns consume C_{t-1}
            "liq_volz_720": 720,  # no shift needed
            "liq_volz_24h_sum": 743,  # window + sum_bars - 1
            "liq_cs_spread_168": 169,  # beta consumes the previous bar
        }
        for name, lookback in expected_lookbacks.items():
            spec = registry.get(name)
            assert spec.family is Family.LIQUIDITY
            assert spec.direction == 0  # risk/cost features, not alphas (v1 ruling)
            assert spec.cross_sectional is False
            assert spec.lookback_bars == lookback
            assert not spec.is_ewma_family

    def test_engine_output_equals_helper_on_same_panel(self, env: Env) -> None:
        out = env.engine.compute_history(_specs(), [BTC, ETH], start=T0, end=T0 + N_BARS * HOUR)
        panels = _panels(env)
        expected = {
            "liq_amihud_720": amihud_illiq(panels["close"], panels["qv"], window=720),
            "liq_volz_720": volume_zscore(panels["qv"], window=720),
            "liq_volz_24h_sum": volume_zscore(panels["qv"], window=720, sum_bars=24),
            "liq_cs_spread_168": corwin_schultz_spread(panels["high"], panels["low"], smooth=168),
        }
        for k in (300, 600, 790):
            ts = T0 + k * HOUR
            for iid in (BTC, ETH):
                for name, frame in expected.items():
                    got = out[name].loc[(ts, iid)]
                    want = frame.loc[ts, iid]
                    assert got == want or (np.isnan(got) and np.isnan(want)), name

    def test_strict_warmup_boundaries(self, env: Env) -> None:
        # Lake history starts at T0, so bar k has exactly k+1 bars of history.
        out = env.engine.compute_history(_specs(), [BTC], start=T0, end=T0 + N_BARS * HOUR)
        boundaries = {  # first finite bar index for each STRICT-window spec
            "liq_volz_720": 719,
            "liq_volz_24h_sum": 742,
            "liq_cs_spread_168": 168,
        }
        for name, first in boundaries.items():
            col = out[name].xs(BTC, level="instrument_id")
            first_valid = int(np.flatnonzero(col.notna().to_numpy())[0])
            assert first_valid == first, name
        # Amihud allows partial windows (skip semantics): bar 0 lacks a return,
        # bar 1 is the first value.
        col = out["liq_amihud_720"].xs(BTC, level="instrument_id")
        assert np.isnan(col.iloc[0])
        assert np.isfinite(col.iloc[1])


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    def test_all_liquidity_specs_exact_under_truncation(self, env: Env) -> None:
        ts_samples = [T0 + 770 * HOUR + 19 * 60_000, T0 + 793 * HOUR]
        for spec in _specs():
            report = verify_truncation(env.engine, spec, [BTC, ETH], ts_samples, history_start=T0)
            result = report.result(spec.name)
            assert result.passed, f"{spec.name}: {result}"
            assert result.rtol == 0.0
            assert result.max_abs_diff == 0.0
            assert result.n_points == 4
            live = env.engine.compute_asof([spec], [BTC, ETH], as_of=ts_samples[0])
            assert live[spec.name].notna().all()  # non-vacuous
