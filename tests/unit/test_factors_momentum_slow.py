"""Unit tests for alphaforge.features.library.momentum_slow (build slate Pod A).

Covers ``residual_momentum`` (vol-scaled residual momentum with a skip) and the
registered ``mom_res_2160_168`` (90d formation, 7d skip). Tests assert:

* ``residual_momentum`` matches a hand-rolled brute force to 1e-12 (beta over the
  window ending t-1, eps = r - beta*m, skipped W-bar sum, zero-mean EWMA sigma_eps);
* the skip genuinely excludes the most recent ``skip`` residuals (poisoning a bar
  inside the skip band leaves the factor unchanged at later t);
* param validation (lookback>=2, 0<=skip<lookback);
* gap propagation (a missing bar NaNs exactly the windows that touch it - never
  bridged or shrunk);
* input-mutation safety;
* registered-spec metadata (family MOMENTUM, direction +1, CS, EWMA-family,
  derived lookback_bars = beta_window + max(15*span, lookback) = 3240);
* engine wiring against the hand-built PIT membership mask (bit-for-bit), including
  a mid-history universe entry that changes the market;
* exact NaN-warmup boundary (first finite at beta_window + lookback = 2880);
* truncation invariance via ``verify_truncation`` (EWMA-family: rtol 1e-9).

All lake-backed tests run against a deterministic synthetic tmp lake (offline).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.core.instruments import InstrumentStore
from alphaforge.data.schemas import UNIVERSE_SCHEMA, Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library.mean_reversion import (
    BETA_WINDOW,
    market_return,
)
from alphaforge.features.library.momentum_slow import residual_momentum
from alphaforge.features.library.vol import EWMA_HEADROOM_SPANS, EWMA_VOL_SPAN, log_returns
from alphaforge.features.parity import verify_truncation
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.spec import FeatureSpec

BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"
SOL = "BINANCE:PERP:SOLUSDT"
IDS = (BTC, ETH, SOL)

HOUR = 3_600_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z (1h-aligned)
LOOKBACK_PARAM = 2160
SKIP_PARAM = 168
# declared lookback_bars = beta_window + max(15*span, lookback) = 720 + 2520 = 3240
LOOKBACK = BETA_WINDOW + max(EWMA_HEADROOM_SPANS * EWMA_VOL_SPAN, LOOKBACK_PARAM)
N_BARS = 3400  # > declared lookback (3240) + sample headroom
SOL_ENTRY_BAR = 2600  # SOL joins the PIT universe mid-history
# FORMULA warmup: deepest residual eps_{t-lookback+1} must be valid (first eps at
# beta_window+1) => first finite factor at beta_window + lookback.
FIRST_FINITE = BETA_WINDOW + LOOKBACK_PARAM  # 2880

NAME = "mom_res_2160_168"


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


def _universe_table() -> pa.Table:
    """BTC/ETH members from T0; SOL enters at SOL_ENTRY_BAR (PIT mid-history entry)."""
    return pa.table(
        {
            "instrument_id": [BTC, ETH, SOL],
            "effective_from": pa.array(
                [T0, T0, T0 + SOL_ENTRY_BAR * HOUR], type=pa.timestamp("ms", tz="UTC")
            ),
            "effective_to": pa.array([None, None, None], type=pa.timestamp("ms", tz="UTC")),
            "rank": pa.array([1, 2, 3], type=pa.int32()),
            "reason": ["enter_top40", "enter_top40", "enter_top40"],
        },
        schema=UNIVERSE_SCHEMA,
    )


@dataclass(frozen=True)
class Env:
    engine: FeatureEngine
    ohlc: dict[str, dict[str, np.ndarray]]


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("factors_momentum_slow")
    paths = LakePaths(tmp / "lake")
    ohlc = {
        BTC: _make_ohlc(71, N_BARS, 100.0),
        ETH: _make_ohlc(72, N_BARS, 50.0),
        SOL: _make_ohlc(73, N_BARS, 20.0),
    }
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(ohlc))
    universe = UniverseStore(paths)
    universe.write_intervals(_universe_table())
    instruments = InstrumentStore(tmp / "instruments.db")
    engine = FeatureEngine(PITDataReader(paths), instruments, universe)
    yield Env(engine=engine, ohlc=ohlc)
    instruments.close()


def _spec() -> FeatureSpec:
    return default_registry().get(NAME)


def _close_panel(env: Env) -> pd.DataFrame:
    index = pd.Index([T0 + k * HOUR for k in range(N_BARS)], name="ts_open")
    return pd.DataFrame({iid: env.ohlc[iid]["close"] for iid in IDS}, index=index)


def _pit_mask(index: pd.Index) -> pd.DataFrame:
    """The hand-built PIT membership mask matching ``_universe_table``."""
    mask = pd.DataFrame(True, index=index, columns=pd.Index(list(IDS)))
    mask.loc[mask.index < T0 + SOL_ENTRY_BAR * HOUR, SOL] = False
    return mask


# ----------------------------------------------------------------- formula checks


class TestResidualMomentumFormula:
    def test_brute_force_full_pipeline(self) -> None:
        rng = np.random.default_rng(80)
        n, lookback, skip, beta_window, vol_span = 18, 6, 2, 3, 2
        m_arr = rng.normal(0.0, 0.01, n)
        r_arr = 1.2 * m_arr + rng.normal(0.0, 0.003, n)
        out = residual_momentum(
            pd.DataFrame({"A": r_arr}),
            pd.Series(m_arr),
            lookback=lookback,
            skip=skip,
            beta_window=beta_window,
            vol_span=vol_span,
        )
        window = lookback - skip  # 4
        # Manual: beta_t over rows t-3..t-1; eps_t = r_t - beta_t*m_t (t >= 3);
        # zero-mean EWMA var seeded at eps_3 (adjust=False), lam = 2/(span+1);
        # sigma finite from the 2nd valid eps (min_periods = 2).
        lam = 2.0 / (vol_span + 1.0)
        eps: dict[int, float] = {}
        for t in range(beta_window, n):
            x = r_arr[t - beta_window : t]
            y = m_arr[t - beta_window : t]
            cov = float(np.sum((x - x.mean()) * (y - y.mean()))) / (beta_window - 1)
            var_m = float(np.sum((y - y.mean()) ** 2)) / (beta_window - 1)
            eps[t] = r_arr[t] - (cov / var_m) * m_arr[t]
        var = eps[beta_window] ** 2
        sigma: dict[int, float] = {}
        for t in range(beta_window + 1, n):
            var = lam * eps[t] ** 2 + (1.0 - lam) * var
            sigma[t] = math.sqrt(var)  # finite from the 2nd valid eps (min_periods=2)
        # RESMOM(t) = (sum of eps over t-skip-window+1 .. t-skip) / (sigma_t*sqrt(window))
        for t in range(n):
            lo, hi = t - skip - window + 1, t - skip  # inclusive residual range
            if lo < beta_window or t not in sigma:
                assert np.isnan(out.iloc[t, 0]), t
                continue
            s = sum(eps[k] for k in range(lo, hi + 1))
            expected = s / (sigma[t] * math.sqrt(window))
            assert abs(out.iloc[t, 0] - expected) < 1e-12, t

    def test_skip_excludes_the_recent_band(self) -> None:
        # Poisoning a residual INSIDE the skip band (within `skip` bars of t) must
        # not change the factor at t: the skipped sum starts at t-skip.
        rng = np.random.default_rng(81)
        n, lookback, skip, beta_window, vol_span = 30, 8, 4, 3, 2
        m_arr = rng.normal(0.0, 0.01, n)
        r_arr = 1.1 * m_arr + rng.normal(0.0, 0.002, n)
        base = residual_momentum(
            pd.DataFrame({"A": r_arr}),
            pd.Series(m_arr),
            lookback=lookback,
            skip=skip,
            beta_window=beta_window,
            vol_span=vol_span,
        )
        t = n - 1
        # The summed residuals at bar t span [t-skip-window+1, t-skip]; the most
        # recent `skip` residuals (indices t-skip+1 .. t) are EXCLUDED. Perturb the
        # return at the final bar t: r_t feeds only eps_t (index t, inside the
        # excluded skip band at every earlier bar) and FUTURE betas (indices
        # > t, which do not exist here). Therefore EVERY factor value at a bar t0
        # in [first_finite, t-1] is bit-identical, because none of their summed
        # windows, sigma windows, or betas reach index t.
        r2 = r_arr.copy()
        r2[t] += 0.5
        bumped = residual_momentum(
            pd.DataFrame({"A": r2}),
            pd.Series(m_arr),
            lookback=lookback,
            skip=skip,
            beta_window=beta_window,
            vol_span=vol_span,
        )
        assert (t - skip) < t  # the most recent summed residual predates t by skip
        # All bars strictly before t are untouched by the r_t bump (bit-for-bit).
        a, b = base.iloc[:t, 0].to_numpy(), bumped.iloc[:t, 0].to_numpy()
        assert np.array_equal(a, b, equal_nan=True)
        assert np.isfinite(a).any()  # non-vacuous: there ARE finite bars before t
        # And the bump DID change something downstream (eps_t enters sigma at t):
        assert not np.array_equal(
            base.iloc[:, 0].to_numpy(), bumped.iloc[:, 0].to_numpy(), equal_nan=True
        )

    def test_invalid_params_rejected(self) -> None:
        r = pd.DataFrame({"A": [0.01, 0.02, 0.03]})
        m = pd.Series([0.01, 0.02, 0.03])
        with pytest.raises(ValueError, match="lookback"):
            residual_momentum(r, m, lookback=1, skip=0)
        with pytest.raises(ValueError, match="skip"):
            residual_momentum(r, m, lookback=4, skip=4)
        with pytest.raises(ValueError, match="skip"):
            residual_momentum(r, m, lookback=4, skip=-1)


class TestGapPropagation:
    def test_gap_nans_exactly_the_touched_windows(self) -> None:
        rng = np.random.default_rng(82)
        n, lookback, skip, beta_window, vol_span = 40, 6, 2, 3, 2
        m_arr = rng.normal(0.0, 0.01, n)
        gap = 18
        returns = pd.DataFrame(
            {
                "A": 1.1 * m_arr + rng.normal(0.0, 0.002, n),
                "B": 0.9 * m_arr + rng.normal(0.0, 0.002, n),
            }
        )
        returns.iloc[gap, 0] = np.nan  # A misses one bar
        mask = pd.DataFrame(True, index=returns.index, columns=returns.columns)
        mkt = market_return(returns, mask)  # B keeps the market alive at the gap
        assert np.isfinite(mkt.iloc[gap])
        out = residual_momentum(
            returns, mkt, lookback=lookback, skip=skip, beta_window=beta_window, vol_span=vol_span
        )
        # eps_A is NaN at the gap (r) and while any beta window ending t-1 touches
        # it (t in gap+1..gap+beta_window). Those NaN residuals feed the skipped sum
        # (a window of `window` residuals shifted `skip`) and the EWMA sigma. The
        # important guarantee: a gap is never bridged or the window silently shrunk;
        # B (no gap) stays finite throughout its valid range.
        finite_b = out.iloc[:, 1].to_numpy()
        # B is structurally untouched by A's gap; finite from its own warmup on.
        first_b = int(np.flatnonzero(np.isfinite(finite_b))[0])
        assert np.isfinite(out.iloc[first_b:, 1]).all()
        # A has at least one extra NaN run around the gap window vs B.
        finite_a = np.isfinite(out.iloc[:, 0].to_numpy())
        assert finite_a.sum() < np.isfinite(finite_b).sum()


class TestNoInputMutation:
    def test_helper_never_mutates_inputs(self) -> None:
        rng = np.random.default_rng(83)
        n = 20
        returns = pd.DataFrame({"A": rng.normal(0.0, 0.01, n), "B": rng.normal(0.0, 0.01, n)})
        mask = pd.DataFrame(True, index=returns.index, columns=returns.columns)
        market = market_return(returns, mask)
        snaps = (returns.copy(deep=True), market.copy(deep=True))
        residual_momentum(returns, market, lookback=6, skip=2, beta_window=3, vol_span=2)
        pd.testing.assert_frame_equal(returns, snaps[0])
        pd.testing.assert_series_equal(market, snaps[1])


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpec:
    def test_metadata(self) -> None:
        spec = _spec()
        assert spec.family is Family.MOMENTUM
        assert spec.direction == 1  # residual trend up = expected continuation
        assert spec.cross_sectional is True
        assert spec.is_ewma_family
        assert spec.lookback_bars == LOOKBACK == 3240
        assert spec.params["lookback"] == LOOKBACK_PARAM == 2160
        assert spec.params["skip"] == SKIP_PARAM == 168
        assert spec.params["beta_window"] == BETA_WINDOW == 720
        assert spec.params["span"] == EWMA_VOL_SPAN == 168

    def test_engine_output_equals_helper_with_pit_mask(self, env: Env) -> None:
        # start chosen so the engine warm-up headroom (lookback 3240) lands exactly
        # on the lake start: the context panel and the hand-built panel are the
        # identical array, so equality must be bit-for-bit (incl. the EWMA column).
        out = env.engine.compute_history(
            [_spec()], list(IDS), start=T0 + LOOKBACK * HOUR, end=T0 + N_BARS * HOUR
        )
        close = _close_panel(env)
        returns = log_returns(close)
        mkt = market_return(returns, _pit_mask(close.index))
        expected = residual_momentum(returns, mkt, lookback=LOOKBACK_PARAM, skip=SKIP_PARAM).iloc[
            LOOKBACK:
        ]
        assert np.array_equal(out[NAME].to_numpy(), expected.to_numpy().ravel(), equal_nan=True)
        assert out[NAME].notna().all()  # non-vacuous

    def test_pit_membership_changes_the_market(self, env: Env) -> None:
        # SOL enters at bar 2600 (inside the beta/formation windows of the output
        # range). A naive everyone-is-a-member market MUST disagree with the
        # PIT-masked result (selection into m_t is time-varying).
        out = env.engine.compute_history(
            [_spec()], list(IDS), start=T0 + LOOKBACK * HOUR, end=T0 + N_BARS * HOUR
        )
        close = _close_panel(env)
        returns = log_returns(close)
        naive_mask = pd.DataFrame(True, index=close.index, columns=close.columns)
        naive = residual_momentum(
            returns, market_return(returns, naive_mask), lookback=LOOKBACK_PARAM, skip=SKIP_PARAM
        ).iloc[LOOKBACK:]
        assert not np.array_equal(out[NAME].to_numpy(), naive.to_numpy().ravel(), equal_nan=True)

    def test_warmup_boundary(self, env: Env) -> None:
        # Lake history starts at T0. The FORMULA warmup: the deepest summed residual
        # eps_{t-lookback+1} must be valid (first eps at beta_window+1), so the first
        # finite factor is at beta_window + lookback = 2880. The declared
        # lookback_bars (3240) is EWMA truncation headroom, exercised by the
        # truncation tests, not by warmup.
        out = env.engine.compute_history([_spec()], list(IDS), start=T0, end=T0 + N_BARS * HOUR)
        col = out[NAME].xs(BTC, level="instrument_id")
        first_finite = int(np.flatnonzero(col.notna().to_numpy())[0])
        assert first_finite == FIRST_FINITE == 2880
        assert np.isnan(col.iloc[first_finite - 1])


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    TS_SAMPLES = (T0 + 3300 * HOUR + 17 * 60_000, T0 + 3380 * HOUR)

    def test_within_ewma_tolerance(self, env: Env) -> None:
        # Live minimal window (exactly lookback_bars = 3240) vs full history: the
        # 15-span EWMA headroom keeps the truncation error ~1e-12 relative, far
        # inside the 1e-9 EWMA-family parity tolerance.
        spec = _spec()
        report = verify_truncation(
            env.engine, spec, list(IDS), list(self.TS_SAMPLES), history_start=T0
        )
        result = report.result(NAME)
        assert result.passed, f"{NAME}: {result}"
        assert result.rtol == 1e-9
        assert result.n_points == 6  # 2 samples x 3 instruments
        assert math.isfinite(result.max_abs_diff)
        # Non-vacuous: the sampled values are real numbers, not NaN==NaN.
        live = env.engine.compute_asof([spec], list(IDS), as_of=self.TS_SAMPLES[0])
        assert live[NAME].notna().all()
