"""Unit tests for alphaforge.features.library.vol (alphaDesign.md §2.2).

Covers: Yang-Zhang and Parkinson against brute-force formula evaluations on tiny
hand-checkable fixtures (1e-12), the EWMA sigma_hat recursion against a manual loop,
input-mutation safety, registered-spec metadata (names/directions/lookbacks),
engine wiring (registered fn output == helper output on the same panel), exact
NaN-warmup boundaries (first finite value at exactly ``lookback_bars`` bars of
history), gap propagation (no bridging), and truncation invariance via
``verify_truncation`` for EVERY registered vol spec (finite windows: parity
atol = 0, asserted as ``max_abs_diff == 0.0``).

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
from alphaforge.features.library.vol import (
    BARS_PER_YEAR_H1,
    ewma_vol,
    ewma_vol_from_returns,
    log_returns,
    parkinson,
    yang_zhang,
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

VOL_SPEC_NAMES = ("vol_yz_168", "vol_yz_720", "vol_pk_168", "vol_ratio_168_720")


# --------------------------------------------------------------------------- builders


def _make_ohlc(seed: int, n: int, level: float) -> dict[str, np.ndarray]:
    """Deterministic OHLC random walk with valid bar geometry (H >= max(O,C) >= L)."""
    rng = np.random.default_rng(seed)
    close = level * np.exp(np.cumsum(rng.normal(0.0, 0.005, n)))
    open_ = np.empty(n)
    open_[0] = level
    open_[1:] = close[:-1] * np.exp(rng.normal(0.0, 0.001, n - 1))
    wick = np.abs(rng.normal(0.0, 0.002, n))
    high = np.maximum(open_, close) * np.exp(wick)
    low = np.minimum(open_, close) * np.exp(-wick)
    return {"open": open_, "high": high, "low": low, "close": close}


def _ohlcv_table(per_inst: dict[str, dict[str, np.ndarray]]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    cols: dict[str, list[float]] = {"open": [], "high": [], "low": [], "close": []}
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
            "quote_volume": pa.array([1000.0] * n_rows, type=pa.float64()),
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
    tmp = tmp_path_factory.mktemp("factors_vol")
    paths = LakePaths(tmp / "lake")
    ohlc = {BTC: _make_ohlc(11, N_BARS, 100.0), ETH: _make_ohlc(12, N_BARS, 50.0)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(ohlc))
    instruments = InstrumentStore(tmp / "instruments.db")
    engine = FeatureEngine(PITDataReader(paths), instruments, UniverseStore(paths))
    yield Env(engine=engine, ohlc=ohlc)
    instruments.close()


def _specs() -> list[FeatureSpec]:
    registry = default_registry()
    return [registry.get(name) for name in VOL_SPEC_NAMES]


def _panels(env: Env) -> dict[str, pd.DataFrame]:
    """Wide panels (rows = bar index 0..N-1) built directly from the raw arrays."""
    index = pd.Index([T0 + k * HOUR for k in range(N_BARS)], name="ts_open")
    return {
        field: pd.DataFrame({iid: env.ohlc[iid][field] for iid in (BTC, ETH)}, index=index)
        for field in ("open", "high", "low", "close")
    }


# ----------------------------------------------------------------- brute-force checks


class TestYangZhangFormula:
    # 6 bars, window 5: the single valid output (index 5) uses bars 1..5 plus C_0.
    O: ClassVar[list[float]] = [100.0, 101.0, 99.5, 102.0, 101.5, 100.5]  # noqa: E741
    H: ClassVar[list[float]] = [102.0, 103.5, 101.0, 104.0, 103.0, 102.5]
    L: ClassVar[list[float]] = [99.0, 100.0, 98.0, 100.5, 99.5, 99.0]
    C: ClassVar[list[float]] = [101.2, 100.1, 100.8, 101.9, 100.2, 101.7]

    def _frames(self) -> tuple[pd.DataFrame, ...]:
        return tuple(pd.DataFrame({"A": vals}) for vals in (self.O, self.H, self.L, self.C))

    def _brute_force(self) -> float:
        n = 5
        o = [math.log(self.O[t] / self.C[t - 1]) for t in range(1, 6)]
        c = [math.log(self.C[t] / self.O[t]) for t in range(1, 6)]
        u = [math.log(self.H[t] / self.O[t]) for t in range(1, 6)]
        d = [math.log(self.L[t] / self.O[t]) for t in range(1, 6)]
        o_bar = sum(o) / n
        c_bar = sum(c) / n
        var_o = sum((x - o_bar) ** 2 for x in o) / (n - 1)
        var_c = sum((x - c_bar) ** 2 for x in c) / (n - 1)
        var_rs = sum(u[i] * (u[i] - c[i]) + d[i] * (d[i] - c[i]) for i in range(n)) / n
        k = 0.34 / (1.34 + (n + 1) / (n - 1))
        return math.sqrt(var_o + k * var_c + (1.0 - k) * var_rs)

    def test_per_bar_matches_brute_force_to_1e12(self) -> None:
        open_, high, low, close = self._frames()
        out = yang_zhang(open_, high, low, close, window=5)
        assert abs(out.iloc[5, 0] - self._brute_force()) < 1e-12

    def test_annualized_is_sqrt_8760_times_per_bar(self) -> None:
        open_, high, low, close = self._frames()
        per_bar = yang_zhang(open_, high, low, close, window=5)
        ann = yang_zhang(open_, high, low, close, window=5, annualize=True)
        assert ann.iloc[5, 0] == per_bar.iloc[5, 0] * math.sqrt(BARS_PER_YEAR_H1)
        assert BARS_PER_YEAR_H1 == 8760.0

    def test_warmup_nan_before_window_plus_one_bars(self) -> None:
        open_, high, low, close = self._frames()
        out = yang_zhang(open_, high, low, close, window=5)
        assert out.iloc[:5, 0].isna().all()  # o_1 needs C_0: first finite at index 5
        assert np.isfinite(out.iloc[5, 0])

    def test_window_below_two_rejected(self) -> None:
        open_, high, low, close = self._frames()
        with pytest.raises(ValueError, match="window"):
            yang_zhang(open_, high, low, close, window=1)


class TestParkinsonFormula:
    H: ClassVar[list[float]] = [102.0, 103.5, 101.0, 104.0, 103.0]
    L: ClassVar[list[float]] = [99.0, 100.0, 98.0, 100.5, 99.5]

    def test_matches_brute_force_to_1e12(self) -> None:
        high = pd.DataFrame({"A": self.H})
        low = pd.DataFrame({"A": self.L})
        out = parkinson(high, low, window=4)
        for t in (3, 4):
            expected = math.sqrt(
                sum(math.log(self.H[i] / self.L[i]) ** 2 for i in range(t - 3, t + 1))
                / (4.0 * 4.0 * math.log(2.0))
            )
            assert abs(out.iloc[t, 0] - expected) < 1e-12
        assert out.iloc[:3, 0].isna().all()  # exactly window bars needed

    def test_annualized_variant(self) -> None:
        high = pd.DataFrame({"A": self.H})
        low = pd.DataFrame({"A": self.L})
        per_bar = parkinson(high, low, window=4)
        ann = parkinson(high, low, window=4, annualize=True)
        assert ann.iloc[4, 0] == per_bar.iloc[4, 0] * math.sqrt(BARS_PER_YEAR_H1)

    def test_window_below_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="window"):
            parkinson(pd.DataFrame({"A": self.H}), pd.DataFrame({"A": self.L}), window=0)


class TestEwmaVol:
    def test_matches_manual_recursion(self) -> None:
        closes = [100.0, 101.0, 99.5, 102.0, 101.5, 100.5, 103.0, 102.2]
        span = 3
        out = ewma_vol(pd.DataFrame({"A": closes}), span=span)
        lam = 2.0 / (span + 1.0)
        r = [math.log(closes[k] / closes[k - 1]) for k in range(1, len(closes))]
        var = r[0] ** 2  # adjust=False seeds at the first valid observation
        manual: list[float] = [var]
        for x in r[1:]:
            var = lam * x * x + (1.0 - lam) * var
            manual.append(var)
        # min_periods = span: first finite at the 3rd valid return (bar index 3).
        assert out.iloc[:3, 0].isna().all()
        for k in range(3, len(closes)):
            assert out.iloc[k, 0] == pytest.approx(math.sqrt(manual[k - 1]), rel=1e-14)

    def test_zero_mean_no_drift_subtraction(self) -> None:
        # Constant positive drift: per-bar returns are constant r, so the zero-mean
        # EWMA variance is exactly r^2 (a mean-subtracting estimator would give 0).
        closes = [100.0 * math.exp(0.01 * k) for k in range(6)]
        out = ewma_vol(pd.DataFrame({"A": closes}), span=2)
        assert out.iloc[-1, 0] == pytest.approx(0.01, rel=1e-12)

    def test_invalid_span_rejected(self) -> None:
        with pytest.raises(ValueError, match="span"):
            ewma_vol_from_returns(pd.DataFrame({"A": [0.0]}), span=0)


class TestNoInputMutation:
    def test_helpers_never_mutate_inputs(self) -> None:
        rng = np.random.default_rng(5)
        n = 12
        close = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))})
        open_ = close * 1.001
        high = close * 1.01
        low = close * 0.99
        copies = [f.copy(deep=True) for f in (open_, high, low, close)]
        yang_zhang(open_, high, low, close, window=4)
        parkinson(high, low, window=4)
        ewma_vol(close, span=3)
        log_returns(close)
        for original, snapshot in zip((open_, high, low, close), copies, strict=True):
            pd.testing.assert_frame_equal(original, snapshot)


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpecs:
    def test_metadata(self) -> None:
        registry = default_registry()
        expected_lookbacks = {
            "vol_yz_168": 169,  # YZ consumes C_{t-1}
            "vol_yz_720": 721,
            "vol_pk_168": 168,  # range-only
            "vol_ratio_168_720": 721,  # bound by the slow YZ window
        }
        for name, lookback in expected_lookbacks.items():
            spec = registry.get(name)
            assert spec.family is Family.VOLATILITY
            assert spec.direction == 0  # features, not alphas
            assert spec.cross_sectional is False
            assert spec.lookback_bars == lookback
            assert not spec.is_ewma_family  # finite windows: parity atol = 0

    def test_engine_output_equals_helper_on_same_panel(self, env: Env) -> None:
        out = env.engine.compute_history(_specs(), [BTC, ETH], start=T0, end=T0 + N_BARS * HOUR)
        panels = _panels(env)
        expected_yz = yang_zhang(
            panels["open"],
            panels["high"],
            panels["low"],
            panels["close"],
            window=168,
            annualize=True,
        )
        expected_pk = parkinson(panels["high"], panels["low"], window=168, annualize=True)
        for k in (200, 500, 750):
            ts = T0 + k * HOUR
            for iid in (BTC, ETH):
                assert out["vol_yz_168"].loc[(ts, iid)] == expected_yz.loc[ts, iid]
                assert out["vol_pk_168"].loc[(ts, iid)] == expected_pk.loc[ts, iid]

    def test_vol_ratio_is_ratio_of_per_bar_yz(self, env: Env) -> None:
        # Same [BTC, ETH] cross-section as the helper panels: bit-exact equality
        # is only guaranteed when both pipelines reduce windows over the same
        # array layout (the window-sum reduction order depends on the column
        # stride — exactly why the parity contract compares like-for-like sets).
        out = env.engine.compute_history(
            _specs(), [BTC, ETH], start=T0 + 750 * HOUR, end=T0 + 751 * HOUR
        )
        panels = _panels(env)
        fast = yang_zhang(
            panels["open"], panels["high"], panels["low"], panels["close"], window=168
        )
        slow = yang_zhang(
            panels["open"], panels["high"], panels["low"], panels["close"], window=720
        )
        ts = T0 + 750 * HOUR
        for iid in (BTC, ETH):
            assert out["vol_ratio_168_720"].loc[(ts, iid)] == fast.loc[ts, iid] / slow.loc[ts, iid]

    def test_warmup_boundary_first_value_at_exactly_lookback_bars(self, env: Env) -> None:
        # The lake's history starts at T0, so bar index k has exactly k+1 bars of
        # history: the first finite value must sit at index lookback_bars - 1.
        out = env.engine.compute_history(_specs(), [BTC], start=T0, end=T0 + N_BARS * HOUR)
        for spec in _specs():
            col = out[spec.name].xs(BTC, level="instrument_id")
            first_valid = int(np.flatnonzero(col.notna().to_numpy())[0])
            assert first_valid == spec.lookback_bars - 1, spec.name
            assert np.isnan(col.iloc[spec.lookback_bars - 2]), spec.name


class TestGapPropagation:
    def test_gap_poisons_exactly_the_windows_that_touch_it(self) -> None:
        # Helper-level on a complete grid with one NaN row (== a missing bar).
        ohlc = _make_ohlc(21, 30, 100.0)
        frames = {
            name: pd.DataFrame({"A": ohlc[name]}) for name in ("open", "high", "low", "close")
        }
        gap = 12
        for frame in frames.values():
            frame.iloc[gap] = np.nan
        window = 5
        out_yz = yang_zhang(
            frames["open"], frames["high"], frames["low"], frames["close"], window=window
        )
        out_pk = parkinson(frames["high"], frames["low"], window=window)
        # YZ: o_{gap+1} consumes C_gap, so indices gap .. gap+window are all NaN
        # (window of 5 ending there touches the gap or the poisoned o), and the
        # first finite value reappears at gap + window + 1. Never bridged.
        assert out_yz.iloc[gap - 1, 0] > 0
        assert out_yz.iloc[gap : gap + window + 1, 0].isna().all()
        assert out_yz.iloc[gap + window + 1, 0] > 0
        # Parkinson has no C_{t-1} term: NaN only while the window contains the gap.
        assert out_pk.iloc[gap - 1, 0] > 0
        assert out_pk.iloc[gap : gap + window, 0].isna().all()
        assert out_pk.iloc[gap + window, 0] > 0


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    def test_all_vol_specs_exact_under_truncation(self, env: Env) -> None:
        # Live minimal window (exactly lookback_bars) must reproduce the full-
        # history batch values bit-for-bit: finite windows get atol = 0.
        ts_samples = [T0 + 770 * HOUR + 19 * 60_000, T0 + 793 * HOUR]
        for spec in _specs():
            report = verify_truncation(env.engine, spec, [BTC, ETH], ts_samples, history_start=T0)
            result = report.result(spec.name)
            assert result.passed, f"{spec.name}: {result}"
            assert result.rtol == 0.0
            assert result.max_abs_diff == 0.0
            assert result.n_points == 4
            # Non-vacuous: the sampled values are real numbers, not NaN==NaN.
            live = env.engine.compute_asof([spec], [BTC, ETH], as_of=ts_samples[0])
            assert live[spec.name].notna().all()
