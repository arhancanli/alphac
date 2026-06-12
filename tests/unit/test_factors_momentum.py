"""Unit tests for alphaforge.features.library.momentum (alphaDesign.md §2.3).

Covers: ``xs_momentum`` / ``ts_momentum`` against hand-computed exact log ratios
(1e-12), the vol-normalization identity on constant drift (TSMOM == sqrt(L)
exactly), parameter validation, gap propagation (a missing endpoint bar yields
NaN, never a bridged ratio), input-mutation safety, registered-spec metadata
(names/directions/CS flags/derived lookbacks/EWMA-family convention), engine
wiring (registered fn output == helper output on the identical panel,
bit-for-bit), exact NaN-warmup boundaries, and truncation invariance via
``verify_truncation`` for EVERY registered momentum spec (finite-window
``mom_xs_*``: parity atol = 0; EWMA-family ``mom_ts_*``: rtol 1e-9).

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
from alphaforge.features.library.momentum import ts_momentum, xs_momentum
from alphaforge.features.library.vol import EWMA_HEADROOM_SPANS, EWMA_VOL_SPAN, ewma_vol
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
N_BARS = 2700  # > max momentum lookback (15*168 = 2520) + sample headroom

XS_SPECS = {"mom_xs_168_24": (168, 24), "mom_xs_504_48": (504, 48), "mom_xs_2160_168": (2160, 168)}
TS_SPECS = {"mom_ts_168": 168, "mom_ts_504": 504, "mom_ts_2160": 2160}
ALL_NAMES = (*XS_SPECS, *TS_SPECS)


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
    tmp = tmp_path_factory.mktemp("factors_momentum")
    paths = LakePaths(tmp / "lake")
    ohlc = {BTC: _make_ohlc(31, N_BARS, 100.0), ETH: _make_ohlc(32, N_BARS, 50.0)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(ohlc))
    instruments = InstrumentStore(tmp / "instruments.db")
    engine = FeatureEngine(PITDataReader(paths), instruments, UniverseStore(paths))
    yield Env(engine=engine, ohlc=ohlc)
    instruments.close()


def _specs() -> list[FeatureSpec]:
    registry = default_registry()
    return [registry.get(name) for name in ALL_NAMES]


def _close_panel(env: Env) -> pd.DataFrame:
    index = pd.Index([T0 + k * HOUR for k in range(N_BARS)], name="ts_open")
    return pd.DataFrame({iid: env.ohlc[iid]["close"] for iid in (BTC, ETH)}, index=index)


# ----------------------------------------------------------------- formula checks


class TestXsMomentumFormula:
    CLOSES: ClassVar[list[float]] = [100.0, 101.5, 99.8, 102.3, 101.1, 103.7, 102.9, 104.4]

    def test_exact_log_ratio(self) -> None:
        out = xs_momentum(pd.DataFrame({"A": self.CLOSES}), lookback=5, skip=2)
        for t in (5, 6, 7):
            expected = math.log(self.CLOSES[t - 2] / self.CLOSES[t - 5])
            assert abs(out.iloc[t, 0] - expected) < 1e-12
        assert out.iloc[:5, 0].isna().all()  # NaN until C_{t-L} exists

    def test_skip_zero_is_plain_lookback_return(self) -> None:
        out = xs_momentum(pd.DataFrame({"A": self.CLOSES}), lookback=3, skip=0)
        assert abs(out.iloc[7, 0] - math.log(self.CLOSES[7] / self.CLOSES[4])) < 1e-12

    def test_gap_poisons_exactly_the_endpoint_rows(self) -> None:
        closes = pd.DataFrame({"A": [float(100 + k) for k in range(12)]})
        gap = 3
        closes.iloc[gap] = np.nan
        out = xs_momentum(closes, lookback=5, skip=2)
        # C_gap is an endpoint of the ratio at t = gap+skip and t = gap+lookback only.
        assert np.isnan(out.iloc[gap + 2, 0])
        assert np.isnan(out.iloc[gap + 5, 0])
        for t in (6, 7, 9, 10, 11):  # neighbours untouched — never bridged
            assert np.isfinite(out.iloc[t, 0])

    def test_invalid_params_rejected(self) -> None:
        close = pd.DataFrame({"A": self.CLOSES})
        with pytest.raises(ValueError, match="lookback"):
            xs_momentum(close, lookback=0, skip=0)
        with pytest.raises(ValueError, match="skip"):
            xs_momentum(close, lookback=5, skip=5)
        with pytest.raises(ValueError, match="skip"):
            xs_momentum(close, lookback=5, skip=-1)


class TestTsMomentumFormula:
    def test_constant_drift_gives_sqrt_lookback(self) -> None:
        # Constant per-bar drift r: ln(C_t/C_{t-L}) = L·r and the zero-mean EWMA
        # sigma is exactly r, so TSMOM = L·r / (r·sqrt(L)) = sqrt(L).
        lookback = 4
        closes = pd.DataFrame({"A": [100.0 * math.exp(0.01 * k) for k in range(10)]})
        vol = ewma_vol(closes, span=2)
        out = ts_momentum(closes, lookback=lookback, vol=vol)
        assert out.iloc[-1, 0] == pytest.approx(math.sqrt(lookback), rel=1e-12)

    def test_brute_force_against_manual_recursion(self) -> None:
        closes_list = [100.0, 101.5, 99.8, 102.3, 101.1, 103.7, 102.9, 104.4]
        span, lookback = 3, 4
        closes = pd.DataFrame({"A": closes_list})
        out = ts_momentum(closes, lookback=lookback, vol=ewma_vol(closes, span=span))
        lam = 2.0 / (span + 1.0)
        r = [math.log(closes_list[k] / closes_list[k - 1]) for k in range(1, len(closes_list))]
        var = r[0] ** 2  # adjust=False seeds at the first valid observation
        for x in r[1:]:
            var = lam * x * x + (1.0 - lam) * var
        t = len(closes_list) - 1
        expected = math.log(closes_list[t] / closes_list[t - lookback]) / (
            math.sqrt(var) * math.sqrt(lookback)
        )
        assert out.iloc[t, 0] == pytest.approx(expected, rel=1e-12)

    def test_zero_vol_yields_nan_never_inf(self) -> None:
        closes = pd.DataFrame({"A": [100.0] * 10})  # r == 0 => sigma == 0
        out = ts_momentum(closes, lookback=4, vol=ewma_vol(closes, span=2))
        assert out["A"].iloc[4:].isna().all()
        assert not np.isinf(out["A"].to_numpy()).any()

    def test_invalid_lookback_rejected(self) -> None:
        closes = pd.DataFrame({"A": [100.0, 101.0]})
        with pytest.raises(ValueError, match="lookback"):
            ts_momentum(closes, lookback=0, vol=closes)


class TestNoInputMutation:
    def test_helpers_never_mutate_inputs(self) -> None:
        rng = np.random.default_rng(7)
        close = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 12)))})
        vol = ewma_vol(close, span=3)
        close_snap, vol_snap = close.copy(deep=True), vol.copy(deep=True)
        xs_momentum(close, lookback=5, skip=2)
        ts_momentum(close, lookback=4, vol=vol)
        pd.testing.assert_frame_equal(close, close_snap)
        pd.testing.assert_frame_equal(vol, vol_snap)


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpecs:
    def test_xs_metadata(self) -> None:
        registry = default_registry()
        for name, (lookback, skip) in XS_SPECS.items():
            spec = registry.get(name)
            assert spec.family is Family.MOMENTUM
            assert spec.direction == 1
            assert spec.cross_sectional is True  # raw values go through the CS pipeline
            assert spec.lookback_bars == lookback + 1  # consumes C_{t-L} and bar t
            assert spec.params["lookback"] == lookback
            assert spec.params["skip"] == skip
            assert not spec.is_ewma_family  # finite window: parity atol = 0

    def test_ts_metadata(self) -> None:
        registry = default_registry()
        for name, lookback in TS_SPECS.items():
            spec = registry.get(name)
            assert spec.family is Family.MOMENTUM
            assert spec.direction == 1
            assert spec.cross_sectional is False  # already vol-normalized
            assert spec.params["span"] == EWMA_VOL_SPAN
            assert spec.is_ewma_family
            # 15-span EWMA truncation headroom (EWMA_HEADROOM_SPANS), not the
            # machinery's 10-span floor: documented truncation error < 1e-12.
            assert spec.lookback_bars == max(lookback + 1, EWMA_HEADROOM_SPANS * EWMA_VOL_SPAN)

    def test_engine_output_equals_helper_on_same_panel(self, env: Env) -> None:
        # start is chosen so the engine's warm-up headroom (max lookback = 2520)
        # lands exactly on the lake start: the context panel and the hand-built
        # panel are then the identical array, so equality must be bit-for-bit —
        # including the EWMA-family mom_ts_* columns.
        specs = _specs()
        start = T0 + 2520 * HOUR
        out = env.engine.compute_history(specs, [BTC, ETH], start=start, end=T0 + N_BARS * HOUR)
        close = _close_panel(env)
        sigma = ewma_vol(close, span=EWMA_VOL_SPAN)
        for name, (lookback, skip) in XS_SPECS.items():
            expected = xs_momentum(close, lookback=lookback, skip=skip).iloc[2520:]
            assert np.array_equal(
                out[name].to_numpy(),
                expected.to_numpy().ravel(),
                equal_nan=True,
            ), name
        for name, lookback in TS_SPECS.items():
            expected = ts_momentum(close, lookback=lookback, vol=sigma).iloc[2520:]
            assert np.array_equal(
                out[name].to_numpy(),
                expected.to_numpy().ravel(),
                equal_nan=True,
            ), name
        assert out[list(ALL_NAMES)].iloc[-1].notna().all()  # non-vacuous

    def test_warmup_boundary(self, env: Env) -> None:
        # Lake history starts at T0, so grid index k has exactly k+1 bars.
        # mom_xs_*: first finite at index L (= lookback_bars - 1, the finite window).
        # mom_ts_*: first finite at index max(L, span) — the FORMULA warmup; the
        # declared lookback_bars (10·span EWMA truncation headroom) is deliberately
        # larger and is exercised by the truncation tests, not by warmup.
        out = env.engine.compute_history(_specs(), [BTC], start=T0, end=T0 + N_BARS * HOUR)
        first_finite = {
            name: int(np.flatnonzero(out[name].notna().to_numpy())[0]) for name in ALL_NAMES
        }
        for name, (lookback, _) in XS_SPECS.items():
            assert first_finite[name] == lookback, name
        for name, lookback in TS_SPECS.items():
            assert first_finite[name] == max(lookback, EWMA_VOL_SPAN), name


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    TS_SAMPLES = (T0 + 2600 * HOUR + 7 * 60_000, T0 + 2680 * HOUR)

    def test_xs_specs_exact_under_truncation(self, env: Env) -> None:
        registry = default_registry()
        for name in XS_SPECS:
            spec = registry.get(name)
            report = verify_truncation(
                env.engine, spec, [BTC, ETH], list(self.TS_SAMPLES), history_start=T0
            )
            result = report.result(name)
            assert result.passed, f"{name}: {result}"
            assert result.rtol == 0.0
            assert result.max_abs_diff == 0.0  # finite windows: bit-for-bit
            assert result.n_points == 4

    def test_ts_specs_within_ewma_tolerance(self, env: Env) -> None:
        registry = default_registry()
        for name in TS_SPECS:
            spec = registry.get(name)
            report = verify_truncation(
                env.engine, spec, [BTC, ETH], list(self.TS_SAMPLES), history_start=T0
            )
            result = report.result(name)
            assert result.passed, f"{name}: {result}"
            assert result.rtol == 1e-9
            assert math.isfinite(result.max_abs_diff)
            # Non-vacuous: the sampled values are real numbers, not NaN==NaN.
            live = env.engine.compute_asof([spec], [BTC, ETH], as_of=self.TS_SAMPLES[0])
            assert live[name].notna().all()
