"""Unit tests for alphaforge.features.library.mean_reversion (alphaDesign.md §2.4).

Covers: ``market_return`` (equal-weight over a per-timestamp member mask, NaN
skipping), ``rolling_beta`` (brute-force Cov/Var over the window ending t-1 to
1e-12, strictly-through-t-1 information, Var=0 guard), ``residual_reversal``
(full-pipeline brute force vs a manual loop to 1e-12), the reversal economics on
a 3-asset synthetic (the asset that deviates BELOW the market shows a strongly
positive factor; the relative winners go negative), gap propagation (a missing
bar NaNs exactly the windows that touch it — never bridged or shrunk),
input-mutation safety, registered-spec metadata, engine wiring against the
hand-built PIT membership mask (bit-for-bit, including a mid-history universe
entry that must change the result vs a naive everyone-is-a-member market), exact
NaN-warmup boundary, and truncation invariance via ``verify_truncation`` for
BOTH registered reversal specs (EWMA-family: rtol 1e-9).

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
    residual_reversal,
    rolling_beta,
)
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
N_BARS = 3400  # > mr lookback (720 + 15*168 = 3240) + sample headroom
SOL_ENTRY_BAR = 2600  # SOL joins the PIT universe mid-history
MR_LOOKBACK = BETA_WINDOW + EWMA_HEADROOM_SPANS * EWMA_VOL_SPAN  # 3240

MR_NAMES = ("mr_res_24", "mr_res_72")


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
    tmp = tmp_path_factory.mktemp("factors_reversal")
    paths = LakePaths(tmp / "lake")
    ohlc = {
        BTC: _make_ohlc(41, N_BARS, 100.0),
        ETH: _make_ohlc(42, N_BARS, 50.0),
        SOL: _make_ohlc(43, N_BARS, 20.0),
    }
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(ohlc))
    universe = UniverseStore(paths)
    universe.write_intervals(_universe_table())
    instruments = InstrumentStore(tmp / "instruments.db")
    engine = FeatureEngine(PITDataReader(paths), instruments, universe)
    yield Env(engine=engine, ohlc=ohlc)
    instruments.close()


def _specs() -> list[FeatureSpec]:
    registry = default_registry()
    return [registry.get(name) for name in MR_NAMES]


def _close_panel(env: Env) -> pd.DataFrame:
    index = pd.Index([T0 + k * HOUR for k in range(N_BARS)], name="ts_open")
    return pd.DataFrame({iid: env.ohlc[iid]["close"] for iid in IDS}, index=index)


def _pit_mask(index: pd.Index) -> pd.DataFrame:
    """The hand-built PIT membership mask matching ``_universe_table``."""
    mask = pd.DataFrame(True, index=index, columns=pd.Index(list(IDS)))
    mask.loc[mask.index < T0 + SOL_ENTRY_BAR * HOUR, SOL] = False
    return mask


# --------------------------------------------------------------------- market_return


class TestMarketReturn:
    def test_equal_weight_over_members(self) -> None:
        returns = pd.DataFrame({"A": [0.01, 0.02], "B": [0.03, 0.04], "C": [0.05, -0.04]})
        mask = pd.DataFrame({"A": [True, True], "B": [True, False], "C": [True, False]})
        out = market_return(returns, mask)
        assert out.iloc[0] == pytest.approx((0.01 + 0.03 + 0.05) / 3, rel=1e-15)
        assert out.iloc[1] == pytest.approx(0.02, rel=1e-15)  # A is the only member

    def test_nan_member_drops_out_of_the_average(self) -> None:
        returns = pd.DataFrame({"A": [0.01], "B": [np.nan]})
        mask = pd.DataFrame({"A": [True], "B": [True]})
        assert market_return(returns, mask).iloc[0] == pytest.approx(0.01, rel=1e-15)

    def test_no_members_is_nan(self) -> None:
        returns = pd.DataFrame({"A": [0.01], "B": [0.02]})
        mask = pd.DataFrame({"A": [False], "B": [False]})
        assert np.isnan(market_return(returns, mask).iloc[0])

    def test_shape_mismatch_rejected(self) -> None:
        with pytest.raises(ValueError, match="aligned shapes"):
            market_return(pd.DataFrame({"A": [0.01]}), pd.DataFrame({"A": [True], "B": [True]}))


# ---------------------------------------------------------------------- rolling_beta


class TestRollingBeta:
    @staticmethod
    def _fixture() -> tuple[pd.DataFrame, pd.Series]:
        rng = np.random.default_rng(51)
        m = pd.Series(rng.normal(0.0, 0.01, 10))
        r = pd.DataFrame({"A": 1.5 * m.to_numpy() + rng.normal(0.0, 0.002, 10)})
        return r, m

    def test_brute_force_window_ending_t_minus_1(self) -> None:
        r, m = self._fixture()
        window = 3
        out = rolling_beta(r, m, window=window)
        for t in (4, 6, 9):
            x = r["A"].to_numpy()[t - window : t]  # bars t-3 .. t-1: through t-1 ONLY
            y = m.to_numpy()[t - window : t]
            cov = float(np.sum((x - x.mean()) * (y - y.mean()))) / (window - 1)
            var = float(np.sum((y - y.mean()) ** 2)) / (window - 1)
            assert abs(out.iloc[t, 0] - cov / var) < 1e-12
        assert out.iloc[:window, 0].isna().all()  # first finite at index == window

    def test_strictly_through_t_minus_1_ignores_bar_t(self) -> None:
        r, m = self._fixture()
        out = rolling_beta(r, m, window=3)
        r2, m2 = r.copy(deep=True), m.copy(deep=True)
        r2.iloc[-1, 0] = 999.0  # poison bar t itself
        m2.iloc[-1] = -999.0
        out2 = rolling_beta(r2, m2, window=3)
        assert out2.iloc[-1, 0] == out.iloc[-1, 0]  # beta at t is unmoved

    def test_zero_market_variance_is_nan(self) -> None:
        r = pd.DataFrame({"A": [0.01, 0.02, 0.01, 0.03, 0.02]})
        m = pd.Series([0.01] * 5)  # constant => Var == 0
        assert rolling_beta(r, m, window=3)["A"].isna().all()

    def test_window_below_two_rejected(self) -> None:
        r, m = self._fixture()
        with pytest.raises(ValueError, match="window"):
            rolling_beta(r, m, window=1)


# ----------------------------------------------------------------- residual_reversal


class TestResidualReversalFormula:
    def test_brute_force_full_pipeline(self) -> None:
        rng = np.random.default_rng(52)
        n, window, beta_window, vol_span = 12, 2, 3, 2
        m_arr = rng.normal(0.0, 0.01, n)
        r_arr = 1.2 * m_arr + rng.normal(0.0, 0.003, n)
        out = residual_reversal(
            pd.DataFrame({"A": r_arr}),
            pd.Series(m_arr),
            window=window,
            beta_window=beta_window,
            vol_span=vol_span,
        )
        # Manual: beta_t over rows t-3..t-1; eps_t = r_t - beta_t*m_t (t >= 3);
        # zero-mean EWMA var seeded at eps_3 (adjust=False), lam = 2/(span+1);
        # sigma finite from the 2nd valid eps (min_periods = 2); MR from index 4.
        lam = 2.0 / (vol_span + 1.0)
        eps: dict[int, float] = {}
        for t in range(beta_window, n):
            x = r_arr[t - beta_window : t]
            y = m_arr[t - beta_window : t]
            cov = float(np.sum((x - x.mean()) * (y - y.mean()))) / (beta_window - 1)
            var_m = float(np.sum((y - y.mean()) ** 2)) / (beta_window - 1)
            eps[t] = r_arr[t] - (cov / var_m) * m_arr[t]
        var = eps[3] ** 2
        for t in range(4, n):
            var = lam * eps[t] ** 2 + (1.0 - lam) * var
            expected = -(eps[t] + eps[t - 1]) / (math.sqrt(var) * math.sqrt(window))
            assert abs(out.iloc[t, 0] - expected) < 1e-12, t
        assert out.iloc[:4, 0].isna().all()

    def test_window_below_one_rejected(self) -> None:
        r = pd.DataFrame({"A": [0.01, 0.02]})
        with pytest.raises(ValueError, match="window"):
            residual_reversal(r, pd.Series([0.01, 0.02]), window=0)


class TestReversalEconomics:
    def test_residual_loser_gets_positive_factor(self) -> None:
        # 3 assets tracking one market factor; in the last W bars asset A is hit
        # with an idiosyncratic -2% per bar. A is the residual loser => strongly
        # positive factor (expected to outperform); B and C, which outperformed
        # the (A-dragged) market, go negative. direction=+1 semantics.
        rng = np.random.default_rng(53)
        n, window = 60, 4
        base = rng.normal(0.0, 0.01, n)
        returns = pd.DataFrame(
            {
                "A": base + rng.normal(0.0, 0.001, n),
                "B": base + rng.normal(0.0, 0.001, n),
                "C": base + rng.normal(0.0, 0.001, n),
            }
        )
        returns.loc[n - window :, "A"] -= 0.02
        mask = pd.DataFrame(True, index=returns.index, columns=returns.columns)
        mkt = market_return(returns, mask)
        out = residual_reversal(returns, mkt, window=window, beta_window=20, vol_span=8)
        last = out.iloc[-1]
        assert last["A"] > 1.0  # vol-scaled, several sigma of residual underperformance
        assert last["B"] < 0.0
        assert last["C"] < 0.0
        assert last["A"] > last["B"] and last["A"] > last["C"]


class TestGapPropagation:
    def test_gap_nans_exactly_the_touched_windows(self) -> None:
        rng = np.random.default_rng(54)
        n, gap, window, beta_window, vol_span = 30, 15, 2, 3, 2
        m_arr = rng.normal(0.0, 0.01, n)
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
        out = residual_reversal(
            returns, mkt, window=window, beta_window=beta_window, vol_span=vol_span
        )
        # eps_A is NaN at the gap (r) and while any beta window ending t-1 touches
        # it (t in gap+1..gap+3); the W=2 sum then needs both eps -> NaN through
        # gap+4; finite again at gap+5 and untouched before the gap. Never a
        # silently shrunk window, never bridged.
        assert np.isfinite(out.iloc[gap - 1, 0])
        assert out.iloc[gap : gap + window + beta_window, 0].isna().all()
        assert np.isfinite(out.iloc[gap + window + beta_window, 0])
        # B is structurally untouched (its inputs have no gap).
        assert out.iloc[gap - 1 :, 1].notna().all()


class TestNoInputMutation:
    def test_helpers_never_mutate_inputs(self) -> None:
        rng = np.random.default_rng(55)
        n = 12
        returns = pd.DataFrame({"A": rng.normal(0.0, 0.01, n), "B": rng.normal(0.0, 0.01, n)})
        mask = pd.DataFrame(True, index=returns.index, columns=returns.columns)
        market = market_return(returns, mask)
        snaps = (returns.copy(deep=True), mask.copy(deep=True), market.copy(deep=True))
        rolling_beta(returns, market, window=3)
        residual_reversal(returns, market, window=2, beta_window=3, vol_span=2)
        market_return(returns, mask)
        pd.testing.assert_frame_equal(returns, snaps[0])
        pd.testing.assert_frame_equal(mask, snaps[1])
        pd.testing.assert_series_equal(market, snaps[2])


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpecs:
    def test_metadata(self) -> None:
        registry = default_registry()
        for name, window in zip(MR_NAMES, (24, 72), strict=True):
            spec = registry.get(name)
            assert spec.family is Family.REVERSAL
            assert spec.direction == 1  # positive = residual loser = expected winner
            assert spec.cross_sectional is True
            assert spec.is_ewma_family
            # beta window + the library's 15-span EWMA truncation headroom.
            assert spec.lookback_bars == MR_LOOKBACK == 3240
            assert spec.params["window"] == window
            assert spec.params["beta_window"] == BETA_WINDOW == 720
            assert spec.params["span"] == EWMA_VOL_SPAN == 168

    def test_engine_output_equals_helper_with_pit_mask(self, env: Env) -> None:
        # start is chosen so the engine's warm-up headroom (lookback 3240) lands
        # exactly on the lake start: the context panel and the hand-built panel
        # are the identical array, so equality must be bit-for-bit.
        out = env.engine.compute_history(
            _specs(), list(IDS), start=T0 + MR_LOOKBACK * HOUR, end=T0 + N_BARS * HOUR
        )
        close = _close_panel(env)
        returns = log_returns(close)
        mkt = market_return(returns, _pit_mask(close.index))
        for name, window in zip(MR_NAMES, (24, 72), strict=True):
            expected = residual_reversal(returns, mkt, window=window).iloc[MR_LOOKBACK:]
            assert np.array_equal(
                out[name].to_numpy(), expected.to_numpy().ravel(), equal_nan=True
            ), name
            assert out[name].notna().all(), name  # non-vacuous

    def test_pit_membership_changes_the_market(self, env: Env) -> None:
        # SOL enters the universe at bar 2600 — inside the beta windows of the
        # output range. A naive everyone-is-always-a-member market MUST disagree
        # with the engine's PIT-masked result (selection into m_t is time-varying).
        out = env.engine.compute_history(
            _specs(), list(IDS), start=T0 + MR_LOOKBACK * HOUR, end=T0 + N_BARS * HOUR
        )
        close = _close_panel(env)
        returns = log_returns(close)
        naive_mask = pd.DataFrame(True, index=close.index, columns=close.columns)
        naive = residual_reversal(returns, market_return(returns, naive_mask), window=24).iloc[
            MR_LOOKBACK:
        ]
        assert not np.array_equal(
            out["mr_res_24"].to_numpy(), naive.to_numpy().ravel(), equal_nan=True
        )

    def test_warmup_boundary(self, env: Env) -> None:
        # Lake history starts at T0. The FORMULA warmup: beta needs 720 returns
        # through t-1 (returns valid from index 1 => first beta/eps at 721), and
        # sigma_eps needs span=168 valid residuals => first finite factor at
        # exactly index 721 + 168 - 1 = 888 (the W-bar sum, W <= 72, is already
        # covered). The declared lookback_bars (3240) is truncation headroom,
        # exercised by the truncation tests.
        first_expected = (BETA_WINDOW + 1) + EWMA_VOL_SPAN - 1  # 888
        out = env.engine.compute_history(_specs(), list(IDS), start=T0, end=T0 + 1000 * HOUR)
        for name in MR_NAMES:
            col = out[name].xs(BTC, level="instrument_id")
            first_finite = int(np.flatnonzero(col.notna().to_numpy())[0])
            assert first_finite == first_expected, name
            assert np.isnan(col.iloc[first_expected - 1]), name


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    TS_SAMPLES = (T0 + 3300 * HOUR + 11 * 60_000, T0 + 3380 * HOUR)

    def test_mr_specs_within_ewma_tolerance(self, env: Env) -> None:
        # Live minimal window (exactly lookback_bars = 3240) vs full history:
        # the 15-span EWMA headroom keeps the truncation error ~1e-12 relative,
        # far inside the 1e-9 EWMA-family parity tolerance.
        for spec in _specs():
            report = verify_truncation(
                env.engine, spec, list(IDS), list(self.TS_SAMPLES), history_start=T0
            )
            result = report.result(spec.name)
            assert result.passed, f"{spec.name}: {result}"
            assert result.rtol == 1e-9
            assert result.n_points == 6  # 2 samples x 3 instruments
            assert math.isfinite(result.max_abs_diff)
            # Non-vacuous: the sampled values are real numbers, not NaN==NaN.
            live = env.engine.compute_asof([spec], list(IDS), as_of=self.TS_SAMPLES[0])
            assert live[spec.name].notna().all()
