"""Unit tests for alphaforge.features.library.vol_premium (BUILD SLATE Pod C).

Covers the two volatility-premium alphas ``lowvol_720`` (low-volatility anomaly,
``- ln(sigma_YZ + eps)``) and ``semivar_skew_504`` (downside/upside semivariance
asymmetry):

* ``lowvol_720`` engine output equals ``- ln(yang_zhang(window=720, annualize=False)
  + eps)`` on the same panel (bit-exact on a like-for-like cross-section), and the
  SIGN: a LOWER-vol name has a HIGHER factor value (direction +1);
* ``semivar_skew_504`` against a brute-force signed-semivariance evaluation on a tiny
  hand-checkable fixture (1e-12), the bounded range, and the three sign regimes
  (all-up => +1, all-down => -1, symmetric => 0);
* gap propagation (no bridging) and the exact NaN-warmup boundary (first finite value
  at exactly ``lookback_bars`` bars);
* input-mutation safety of the ``semivariance_skew`` helper;
* registered-spec metadata (direction +1, cross-sectional, lookbacks, finite window);
* truncation invariance via ``verify_truncation`` for BOTH specs (atol = 0).

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
from alphaforge.features.library.vol import yang_zhang
from alphaforge.features.library.vol_premium import (
    LOWVOL_EPS,
    semivariance_skew,
)
from alphaforge.features.parity import verify_truncation
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.spec import FeatureSpec

BTC = "BINANCE:PERP:BTCUSDT"  # higher-vol random walk
ETH = "BINANCE:PERP:ETHUSDT"  # lower-vol random walk (for the lowvol SIGN test)

HOUR = 3_600_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z (1h-aligned)
N_BARS = 900  # > lowvol_720 lookback (721) so the slow factor is warm late in the run

SPEC_NAMES = ("lowvol_720", "semivar_skew_504")


# --------------------------------------------------------------------------- builders


def _make_ohlc(seed: int, n: int, level: float, sigma: float) -> dict[str, np.ndarray]:
    """Deterministic OHLC random walk with valid bar geometry (H >= max(O,C) >= L)."""
    rng = np.random.default_rng(seed)
    close = level * np.exp(np.cumsum(rng.normal(0.0, sigma, n)))
    open_ = np.empty(n)
    open_[0] = level
    open_[1:] = close[:-1] * np.exp(rng.normal(0.0, sigma * 0.2, n - 1))
    wick = np.abs(rng.normal(0.0, sigma * 0.4, n))
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
    tmp = tmp_path_factory.mktemp("factors_vol_premium")
    paths = LakePaths(tmp / "lake")
    # BTC clearly higher-vol than ETH (drives the lowvol SIGN test).
    ohlc = {
        BTC: _make_ohlc(11, N_BARS, 100.0, sigma=0.010),
        ETH: _make_ohlc(12, N_BARS, 50.0, sigma=0.003),
    }
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(ohlc))
    instruments = InstrumentStore(tmp / "instruments.db")
    engine = FeatureEngine(PITDataReader(paths), instruments, UniverseStore(paths))
    yield Env(engine=engine, ohlc=ohlc)
    instruments.close()


def _specs() -> list[FeatureSpec]:
    registry = default_registry()
    return [registry.get(name) for name in SPEC_NAMES]


def _panels(env: Env) -> dict[str, pd.DataFrame]:
    index = pd.Index([T0 + k * HOUR for k in range(N_BARS)], name="ts_open")
    return {
        field: pd.DataFrame({iid: env.ohlc[iid][field] for iid in (BTC, ETH)}, index=index)
        for field in ("open", "high", "low", "close")
    }


# ------------------------------------------------------------ semivariance brute-force


class TestSemivarianceSkewFormula:
    # Closes chosen so the 4 returns over window=4 have a known sign mix.
    C: ClassVar[list[float]] = [100.0, 102.0, 101.0, 103.0, 100.0]
    # returns: +ln(102/100), -ln(102/101), +ln(103/101), -ln(103/100)

    def test_matches_brute_force_to_1e12(self) -> None:
        close = pd.DataFrame({"A": self.C})
        out = semivariance_skew(close, window=4)
        r = [math.log(self.C[t] / self.C[t - 1]) for t in range(1, 5)]
        rs_up = sum(x * x for x in r if x > 0)
        rs_down = sum(x * x for x in r if x < 0)
        expected = (rs_up - rs_down) / (rs_up + rs_down)
        assert out.iloc[4, 0] == pytest.approx(expected, abs=1e-12)
        assert -1.0 <= out.iloc[4, 0] <= 1.0
        assert out.iloc[:4, 0].isna().all()  # needs window+1 closes (window returns)

    def test_all_up_window_is_plus_one(self) -> None:
        close = pd.DataFrame({"A": [100.0, 101.0, 102.0, 103.0, 104.0]})
        out = semivariance_skew(close, window=4)
        assert out.iloc[4, 0] == pytest.approx(1.0, abs=1e-12)

    def test_all_down_window_is_minus_one(self) -> None:
        close = pd.DataFrame({"A": [104.0, 103.0, 102.0, 101.0, 100.0]})
        out = semivariance_skew(close, window=4)
        assert out.iloc[4, 0] == pytest.approx(-1.0, abs=1e-12)

    def test_symmetric_window_is_zero(self) -> None:
        # Two equal-magnitude up moves and two equal-magnitude down moves.
        close = pd.DataFrame({"A": [100.0, 110.0, 100.0, 110.0, 100.0]})
        out = semivariance_skew(close, window=4)
        assert out.iloc[4, 0] == pytest.approx(0.0, abs=1e-12)

    def test_flat_window_is_nan_not_inf(self) -> None:
        # All-zero returns => total realized variance 0 => NaN (never 0/0 = nan-or-inf).
        close = pd.DataFrame({"A": [100.0, 100.0, 100.0, 100.0, 100.0]})
        out = semivariance_skew(close, window=4)
        assert np.isnan(out.iloc[4, 0])

    def test_window_below_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="window"):
            semivariance_skew(pd.DataFrame({"A": [1.0, 2.0]}), window=0)


class TestGapPropagation:
    def test_gap_poisons_exactly_the_windows_that_touch_it(self) -> None:
        ohlc = _make_ohlc(21, 30, 100.0, sigma=0.01)
        close = pd.DataFrame({"A": ohlc["close"]})
        gap = 12
        close.iloc[gap] = np.nan
        window = 5
        out = semivariance_skew(close, window=window)
        # r_gap and r_{gap+1} are both NaN (each touches the missing close); a window
        # sum of 5 returns ending at index t is NaN while it contains either bad return.
        # The bad returns sit at positions gap and gap+1 in the RETURN series; the sum
        # is NaN for the windows covering them, with the first clean value after.
        assert np.isfinite(out.iloc[gap - 1, 0])
        assert out.iloc[gap : gap + window + 1, 0].isna().all()
        assert np.isfinite(out.iloc[gap + window + 1, 0])


class TestNoInputMutation:
    def test_helper_never_mutates_inputs(self) -> None:
        rng = np.random.default_rng(7)
        close = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 20)))})
        snapshot = close.copy(deep=True)
        semivariance_skew(close, window=5)
        pd.testing.assert_frame_equal(close, snapshot)


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpecs:
    def test_metadata(self) -> None:
        registry = default_registry()
        expected_lookbacks = {
            "lowvol_720": 721,  # YZ consumes C_{t-1}
            "semivar_skew_504": 505,  # each 1h return consumes a previous close
        }
        for name, lookback in expected_lookbacks.items():
            spec = registry.get(name)
            assert spec.family is Family.VOLATILITY
            assert spec.direction == +1
            assert spec.cross_sectional is True
            assert spec.lookback_bars == lookback
            assert not spec.is_ewma_family  # finite windows: parity atol = 0

    def test_lowvol_equals_neg_log_yang_zhang(self, env: Env) -> None:
        out = env.engine.compute_history(_specs(), [BTC, ETH], start=T0, end=T0 + N_BARS * HOUR)
        panels = _panels(env)
        sigma = yang_zhang(
            panels["open"],
            panels["high"],
            panels["low"],
            panels["close"],
            window=720,
            annualize=False,
        )
        for k in (730, 800, 870):
            ts = T0 + k * HOUR
            for iid in (BTC, ETH):
                expected = -math.log(float(sigma.loc[ts, iid]) + LOWVOL_EPS)
                assert out["lowvol_720"].loc[(ts, iid)] == pytest.approx(expected, rel=1e-12)

    def test_lowvol_sign_lower_vol_scores_higher(self, env: Env) -> None:
        # ETH was built with 1/3 the BTC per-bar sigma, so it is the low-vol name and
        # must carry the HIGHER lowvol_720 value (direction +1 => low vol = good).
        ts = T0 + 870 * HOUR
        out = env.engine.compute_history(_specs(), [BTC, ETH], start=ts, end=ts + HOUR)
        eth = float(out["lowvol_720"].loc[(ts, ETH)])
        btc = float(out["lowvol_720"].loc[(ts, BTC)])
        assert eth > btc

    def test_warmup_boundary_first_value_at_exactly_lookback_bars(self, env: Env) -> None:
        out = env.engine.compute_history(_specs(), [BTC], start=T0, end=T0 + N_BARS * HOUR)
        for spec in _specs():
            col = out[spec.name].xs(BTC, level="instrument_id")
            first_valid = int(np.flatnonzero(col.notna().to_numpy())[0])
            assert first_valid == spec.lookback_bars - 1, spec.name
            assert np.isnan(col.iloc[spec.lookback_bars - 2]), spec.name


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    def test_both_specs_exact_under_truncation(self, env: Env) -> None:
        # Live minimal window (exactly lookback_bars) must reproduce full-history
        # batch values bit-for-bit: finite windows get atol = 0.
        ts_samples = [T0 + 800 * HOUR + 19 * 60_000, T0 + 870 * HOUR]
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
