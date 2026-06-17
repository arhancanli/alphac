"""Unit tests for alphaforge.features.library.equity_price (EQUITIES_SLEEVE.md §4).

The first equities-sleeve factor library: 12-1 cross-sectional momentum, 1-month
reversal, the low-volatility anomaly, betting-against-beta, plus realized-vol and
Amihud-illiquidity context — all on daily (D1 session) bars. Coverage mirrors the
crypto factor-test discipline (test_factors_momentum / _reversal / _vol / _liquidity):

* Formula correctness against hand-computed exact values (``reversal`` log ratios,
  ``realized_vol`` sample-variance x√252, the crypto-kernel reuse for 12-1 momentum
  and BAB) to 1e-12.
* The PIT adjusted-close reconstruction (:func:`adjusted_close`) against a PLANTED
  mid-window split — the load-bearing EQUITIES_CRITIQUE B5 gate: a 2:1 split must NOT
  print as a -50% momentum return, and the split must be invisible to a decision row
  taken BEFORE its ``available_at`` and visible to a later one (per-decision-row PIT,
  asserted ACROSS rows, not at one timestamp). Plus the dividend total-return factor
  and the empty-actions identity.
* The corporate-actions surface (:func:`_adjusted_close_panel`, SPINE_ARC P1): raw
  pass-through ONLY when the context's ``corporate_actions`` returns an empty frame
  (no action in the window ⇒ ``C* == C_raw``, the crypto/real-engine path), adjusted
  output when a fake context exposes actions, and a FAIL-CLOSED raise when a context
  exposes no ``corporate_actions`` getter at all (never silently feed raw prices).
* Low-vol direction (``eq_lowvol_252.direction == -1``; CS-ranked low-vol scores
  higher) and BAB sign (a synthetic low-beta name outranks a high-beta name).
* Gap propagation (a missing endpoint NaNs exactly the touched windows, never
  bridged), input-mutation safety, registered-spec metadata, engine wiring (registered
  fn output == helper output on the identical panel, bit-for-bit), exact NaN-warmup
  boundaries, and truncation invariance + batch/asof parity via
  ``verify_truncation`` / ``verify_parity`` for EVERY registered equity factor
  (all finite-window ⇒ parity atol = 0 across the board).

GRID NOTE (the documented build-order gap, EQUITIES_CRITIQUE B1). The PIT-aware
engine/calendar wiring (``anchor_tf=D1`` + ``XNYSCalendar`` threaded through the
engine/context/parity) is a SEPARATE build. The factor BODIES are positional on
``ctx.panel`` — ``shift(k)`` is exactly "k grid slots back," whatever the physical
bar duration — so they are session-grid-correct by construction. These tests drive
the EXISTING engine, whose anchor grid is positional; the engine making that grid a
physical NYSE session grid is the other build's wiring and does not change a single
factor value or any parity/truncation result here. Lake bars are laid on a contiguous
grid; one grid slot == one session bar for every window in the factor formulas.

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

from alphaforge.core.errors import ConfigError
from alphaforge.core.instruments import InstrumentStore
from alphaforge.data.schemas import UNIVERSE_SCHEMA, Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.cross_section import CSPipeline
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library.equity_price import (
    SESSIONS_PER_YEAR,
    adjusted_close,
    realized_vol,
    reversal,
)
from alphaforge.features.library.mean_reversion import (
    market_return,
    rolling_beta,
)
from alphaforge.features.library.momentum import xs_momentum
from alphaforge.features.library.vol import log_returns
from alphaforge.features.parity import verify_parity, verify_truncation
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.spec import FeatureSpec

AAPL = "XNAS:CASH:AAPLUSD"
MSFT = "XNAS:CASH:MSFTUSD"
SPY = "ARCX:CASH:SPYUSD"
IDS = (AAPL, MSFT, SPY)

# The factors are valued on the daily SESSION grid (one grid slot == one session
# bar for every formula window — see module GRID NOTE). The PIT-aware D1 engine
# (EQUITIES_CRITIQUE B1: anchor_tf=D1 + XNYSCalendar) is a SEPARATE build; the EXISTING
# engine anchors on the crypto H1 grid. Because every factor body is POSITIONAL on
# ``ctx.panel`` (``shift(k)`` = k grid slots, whatever the physical bar duration) and
# the parity/truncation contract is itself purely positional, we lay the engine-driven
# synthetic lake on the engine's H1 anchor grid: each grid slot is one session bar, the
# 252/21/63-slot windows are exactly the equity windows, and the realized-vol √252
# annualization is a pure scalar that cancels in parity/truncation. The pure
# ``adjusted_close`` PIT tests below use a stand-alone DAY grid (they never touch the
# engine), so the corporate-action availability arithmetic is tested at true daily Δ.
HOUR = 3_600_000  # the engine anchor step; one slot == one session bar in these tests
DAY = 86_400_000  # true daily Δ for the stand-alone adjusted_close PIT tests
T0 = 1_577_836_800_000  # 2020-01-01T00:00:00Z (aligned)
N_BARS = 700  # > max equity lookback (eq_beta/eq_bab = 254) + ample sample headroom

# (name, lookback_bars, direction, cross_sectional)
SPEC_META = {
    "eq_mom_252_21": (253, 1, True),
    "eq_rev_21": (22, 1, True),
    "eq_lowvol_252": (253, -1, True),
    "eq_beta_252": (254, 0, False),
    "eq_bab_252": (254, 1, True),
    "eq_vol_252": (253, 0, False),
    "eq_amihud_63": (64, 0, False),
}
ALL_NAMES = tuple(SPEC_META)


# --------------------------------------------------------------------------- builders


def _make_ohlc(seed: int, n: int, level: float) -> dict[str, np.ndarray]:
    """Deterministic OHLC random walk with valid bar geometry (H >= max(O,C) >= L)."""
    rng = np.random.default_rng(seed)
    close = level * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))
    open_ = np.empty(n)
    open_[0] = level
    open_[1:] = close[:-1] * np.exp(rng.normal(0.0, 0.004, n - 1))
    wick = np.abs(rng.normal(0.0, 0.008, n))
    high = np.maximum(open_, close) * np.exp(wick)
    low = np.minimum(open_, close) * np.exp(-wick)
    return {"open": open_, "high": high, "low": low, "close": close}


def _ohlcv_table(per_inst: dict[str, dict[str, np.ndarray]]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    cols: dict[str, list[float]] = {"open": [], "high": [], "low": [], "close": []}
    qvs: list[float] = []
    for iid, ohlc in per_inst.items():
        n = len(ohlc["close"])
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        for name in cols:
            cols[name].extend(float(v) for v in ohlc[name])
        # Dollar (quote) volume: shares x price, so |r|/QV is a sane Amihud input.
        qvs.extend(float(1_000_000.0 * c) for c in ohlc["close"])
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(cols["open"], type=pa.float64()),
            "high": pa.array(cols["high"], type=pa.float64()),
            "low": pa.array(cols["low"], type=pa.float64()),
            "close": pa.array(cols["close"], type=pa.float64()),
            "volume": pa.array([1000.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array(qvs, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _universe_table() -> pa.Table:
    """All three names members from T0 (no mid-history entry needed for these tests)."""
    return pa.table(
        {
            "instrument_id": list(IDS),
            "effective_from": pa.array([T0, T0, T0], type=pa.timestamp("ms", tz="UTC")),
            "effective_to": pa.array([None, None, None], type=pa.timestamp("ms", tz="UTC")),
            "rank": pa.array([1, 2, 3], type=pa.int32()),
            "reason": ["enter_topN", "enter_topN", "enter_topN"],
        },
        schema=UNIVERSE_SCHEMA,
    )


@dataclass(frozen=True)
class Env:
    engine: FeatureEngine
    ohlc: dict[str, dict[str, np.ndarray]]


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("factors_equity_price")
    paths = LakePaths(tmp / "lake")
    ohlc = {
        AAPL: _make_ohlc(61, N_BARS, 150.0),
        MSFT: _make_ohlc(62, N_BARS, 250.0),
        SPY: _make_ohlc(63, N_BARS, 400.0),
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
    return [registry.get(name) for name in ALL_NAMES]


def _close_panel(env: Env) -> pd.DataFrame:
    index = pd.Index([T0 + k * HOUR for k in range(N_BARS)], name="ts_open")
    return pd.DataFrame({iid: env.ohlc[iid]["close"] for iid in IDS}, index=index)


def _qv_panel(env: Env) -> pd.DataFrame:
    index = pd.Index([T0 + k * HOUR for k in range(N_BARS)], name="ts_open")
    return pd.DataFrame({iid: 1_000_000.0 * env.ohlc[iid]["close"] for iid in IDS}, index=index)


# ----------------------------------------------------------------- reversal formula


class TestReversalFormula:
    CLOSES: ClassVar[list[float]] = [100.0, 101.5, 99.8, 102.3, 101.1, 103.7, 102.9, 104.4]

    def test_exact_negative_log_ratio(self) -> None:
        out = reversal(pd.DataFrame({"A": self.CLOSES}), window=3)
        for t in (3, 5, 7):
            expected = -math.log(self.CLOSES[t] / self.CLOSES[t - 3])
            assert abs(out.iloc[t, 0] - expected) < 1e-12
        assert out.iloc[:3, 0].isna().all()  # NaN until C_{t-W} exists

    def test_is_negated_skip_zero_momentum(self) -> None:
        # reversal(W) == -xs_momentum(lookback=W, skip=0): the recent-loser sign flip.
        close = pd.DataFrame({"A": self.CLOSES})
        rev = reversal(close, window=4)
        mom = xs_momentum(close, lookback=4, skip=0)
        np.testing.assert_allclose(rev.to_numpy(), -mom.to_numpy(), equal_nan=True)

    def test_recent_loser_is_positive(self) -> None:
        # A name that fell over the window has reversal > 0 (expected to bounce).
        falling = pd.DataFrame({"A": [100.0, 98.0, 96.0, 94.0, 92.0]})
        assert reversal(falling, window=4).iloc[-1, 0] > 0.0

    def test_invalid_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="window"):
            reversal(pd.DataFrame({"A": self.CLOSES}), window=0)

    def test_gap_poisons_exactly_the_endpoint_rows(self) -> None:
        closes = pd.DataFrame({"A": [float(100 + k) for k in range(12)]})
        closes.iloc[3] = np.nan
        out = reversal(closes, window=4)
        assert np.isnan(out.iloc[3, 0])  # C_3 is the C_t endpoint here
        assert np.isnan(out.iloc[7, 0])  # ... and the C_{t-4} endpoint there
        for t in (8, 9, 10, 11):  # neighbours untouched — never bridged
            assert np.isfinite(out.iloc[t, 0])


# --------------------------------------------------------------- realized_vol formula


class TestRealizedVolFormula:
    def test_brute_force_sample_variance_annualized(self) -> None:
        rng = np.random.default_rng(71)
        n, window = 40, 5
        close = pd.DataFrame({"A": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))})
        out = realized_vol(close, window=window, annualize=True)
        r = np.log(close["A"].to_numpy()[1:] / close["A"].to_numpy()[:-1])
        for t in (10, 20, 39):
            win = r[t - window : t]  # returns at indices t-window+1 .. t (r has offset 1)
            var = float(np.var(win, ddof=1))
            expected = math.sqrt(var) * math.sqrt(SESSIONS_PER_YEAR)
            assert abs(out.iloc[t, 0] - expected) < 1e-12, t

    def test_uses_252_not_365(self) -> None:
        # The annualization base is the calendared 252, not the 24/7 365.
        rng = np.random.default_rng(72)
        close = pd.DataFrame({"A": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 30)))})
        ann = realized_vol(close, window=5, annualize=True)
        per_bar = realized_vol(close, window=5, annualize=False)
        ratio = ann.iloc[-1, 0] / per_bar.iloc[-1, 0]
        assert abs(ratio - math.sqrt(252.0)) < 1e-9
        assert abs(ratio - math.sqrt(365.0)) > 1.0  # decisively not the crypto base

    def test_first_finite_at_window_plus_one(self) -> None:
        rng = np.random.default_rng(73)
        close = pd.DataFrame({"A": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 20)))})
        out = realized_vol(close, window=6)
        assert out.iloc[:6, 0].isna().all()  # needs window returns => window+1 closes
        assert np.isfinite(out.iloc[6, 0])

    def test_invalid_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="window"):
            realized_vol(pd.DataFrame({"A": [100.0, 101.0]}), window=1)


# ------------------------------------------------------ adjusted_close PIT (B5 gate)


class TestAdjustedClosePIT:
    @staticmethod
    def _actions(
        instrument_id: str, *, ex_date: int, available_at: int, ratio: float
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "instrument_id": [instrument_id],
                "ex_date": [ex_date],
                "available_at": [available_at],
                "action_type": ["split"],
                "ratio": [ratio],
                "cash_amount": [float("nan")],
            }
        )

    def test_empty_actions_is_identity(self) -> None:
        raw = pd.DataFrame({"A": [100.0, 101.0, 102.0]}, index=[T0, T0 + DAY, T0 + 2 * DAY])
        empty = pd.DataFrame(
            {
                c: pd.Series(dtype=t)
                for c, t in {
                    "instrument_id": "object",
                    "ex_date": "int64",
                    "available_at": "int64",
                    "action_type": "object",
                    "ratio": "float64",
                    "cash_amount": "float64",
                }.items()
            }
        )
        out = adjusted_close(raw, empty, tf_ms=DAY)
        pd.testing.assert_frame_equal(out, raw.astype("float64"))

    def test_two_for_one_split_is_not_a_minus_fifty_percent_return(self) -> None:
        # Raw: a 2:1 split halves the printed price on ex-date. Without adjustment the
        # close-to-close return across the ex-date is ln(0.5) ~= -69% (garbage). The
        # PIT adjustment must halve the PRE-ex prices (xratio=0.5) so the *adjusted*
        # return is ~0. Realistic timing: the split is DECLARED at row 0 (available_at
        # = idx[0]), so every pre-ex bar is knowable and folds — the standard case.
        n = 8
        ex_pos = 4
        idx = [T0 + k * DAY for k in range(n)]
        raw_px = [100.0] * ex_pos + [50.0] * (n - ex_pos)  # halve at ex-date
        raw = pd.DataFrame({"A": raw_px}, index=idx)
        actions = self._actions("A", ex_date=idx[ex_pos], available_at=idx[0], ratio=0.5)
        adj = adjusted_close(raw, actions, tf_ms=DAY)
        # Pre-ex prices (knowable from row 0) folded x0.5; post-ex untouched.
        assert adj["A"].iloc[ex_pos - 1] == pytest.approx(50.0, rel=1e-12)
        assert adj["A"].iloc[ex_pos] == pytest.approx(50.0, rel=1e-12)
        # The adjusted close-to-close return across the split is ~0, not -69%.
        adj_ret = math.log(adj["A"].iloc[ex_pos] / adj["A"].iloc[ex_pos - 1])
        assert abs(adj_ret) < 1e-12
        raw_ret = math.log(raw["A"].iloc[ex_pos] / raw["A"].iloc[ex_pos - 1])
        assert raw_ret < -0.6  # the un-adjusted garbage we are neutralizing

    def test_split_invisible_before_declaration_per_decision_row(self) -> None:
        # The CROSS-ROW PIT assertion (EQUITIES_CRITIQUE B5). A split is DECLARED
        # (knowable) at `decl_pos` and goes ex at `ex_pos` (decl < ex, the realistic
        # weeks-ahead announcement). The per-decision-row gate folds the split into a
        # pre-ex bar `s` ONLY when it is knowable at s's own close (available_at <=
        # ts_open_s + Δ) — so a pre-ex bar BEFORE the declaration stays RAW (a PIT
        # trader standing there did not know the split existed), while a pre-ex bar
        # AT/AFTER the declaration folds x0.5. This proves the factor is a function of
        # the ROW, not back-applied window-wide (the exact funding-finding-18 trap).
        n = 14
        decl_pos = 4  # declaration / available_at
        ex_pos = 9  # ex-date (5 bars after declaration)
        idx = [T0 + k * DAY for k in range(n)]
        raw = pd.DataFrame({"A": [100.0] * ex_pos + [50.0] * (n - ex_pos)}, index=idx)
        actions = self._actions("A", ex_date=idx[ex_pos], available_at=idx[decl_pos], ratio=0.5)
        adj = adjusted_close(raw, actions, tf_ms=DAY)
        # Pre-declaration pre-ex bars whose decision_ts is strictly < available_at:
        # UNKNOWABLE -> stay raw 100 (PIT). Row s has decision_ts = idx[s] + Δ, so the
        # last strictly-unknowable row is decl_pos - 2 (idx[decl_pos-2]+Δ = idx[decl_pos-1]
        # < available_at = idx[decl_pos]).
        for p in range(decl_pos - 1):  # rows 0..decl_pos-2
            assert adj["A"].iloc[p] == pytest.approx(100.0, rel=1e-12), p
        # The bar at decl_pos-1 has decision_ts = idx[decl_pos] == available_at, so it
        # is exactly knowable (boundary: available_at <= ts_open + Δ) -> folds x0.5.
        assert adj["A"].iloc[decl_pos - 1] == pytest.approx(50.0, rel=1e-12)
        # Declared-and-pre-ex bars: knowable AND future-relative -> fold x0.5.
        for p in range(decl_pos, ex_pos):
            assert adj["A"].iloc[p] == pytest.approx(50.0, rel=1e-12), p
        # Post-ex bars: already post-split -> raw.
        for p in range(ex_pos, n):
            assert adj["A"].iloc[p] == pytest.approx(50.0, rel=1e-12), p  # raw is already 50

    def test_post_ex_rows_are_never_back_adjusted(self) -> None:
        # A split only folds into rows STRICTLY BEFORE its ex-date; rows on/after the
        # ex-date are already on the post-split side and must be untouched (raw).
        n = 6
        ex_pos = 3
        idx = [T0 + k * DAY for k in range(n)]
        raw = pd.DataFrame({"A": [100.0] * ex_pos + [60.0] * (n - ex_pos)}, index=idx)
        actions = self._actions("A", ex_date=idx[ex_pos], available_at=idx[0], ratio=0.5)
        adj = adjusted_close(raw, actions, tf_ms=DAY)
        for p in range(ex_pos, n):  # post-ex rows raw-equal (not back-adjusted)
            assert adj["A"].iloc[p] == pytest.approx(raw["A"].iloc[p], rel=1e-12), p
        for p in range(ex_pos):  # pre-ex rows folded x0.5
            assert adj["A"].iloc[p] == pytest.approx(50.0, rel=1e-12), p

    def test_dividend_total_return_factor(self) -> None:
        # A $2 cash dividend on a $100 ex-price scales pre-ex prices by (1 - 2/100),
        # declared at row 0 so every pre-ex bar is knowable.
        n = 6
        ex_pos = 3
        idx = [T0 + k * DAY for k in range(n)]
        raw = pd.DataFrame({"A": [100.0] * n}, index=idx)
        actions = pd.DataFrame(
            {
                "instrument_id": ["A"],
                "ex_date": [idx[ex_pos]],
                "available_at": [idx[0]],
                "action_type": ["dividend"],
                "ratio": [1.0],
                "cash_amount": [2.0],
            }
        )
        adj = adjusted_close(raw, actions, tf_ms=DAY)
        assert adj["A"].iloc[ex_pos - 1] == pytest.approx(100.0 * (1.0 - 2.0 / 100.0), rel=1e-12)
        assert adj["A"].iloc[ex_pos] == pytest.approx(100.0, rel=1e-12)  # post-ex untouched

    def test_nan_close_propagates(self) -> None:
        idx = [T0 + k * DAY for k in range(4)]
        raw = pd.DataFrame({"A": [100.0, np.nan, 100.0, 50.0]}, index=idx)
        actions = self._actions("A", ex_date=idx[3], available_at=idx[0], ratio=0.5)
        adj = adjusted_close(raw, actions, tf_ms=DAY)
        assert np.isnan(adj["A"].iloc[1])

    def test_other_instrument_actions_ignored(self) -> None:
        raw = pd.DataFrame({"A": [100.0, 100.0]}, index=[T0, T0 + DAY])
        actions = self._actions("ZZZ", ex_date=T0 + DAY, available_at=T0, ratio=0.5)
        pd.testing.assert_frame_equal(
            adjusted_close(raw, actions, tf_ms=DAY), raw.astype("float64")
        )

    def test_invalid_tf_ms_rejected(self) -> None:
        raw = pd.DataFrame({"A": [100.0]}, index=[T0])
        with pytest.raises(ValueError, match="tf_ms"):
            adjusted_close(raw, raw, tf_ms=0)

    def test_no_input_mutation(self) -> None:
        raw = pd.DataFrame({"A": [100.0, 100.0, 50.0]}, index=[T0 + k * DAY for k in range(3)])
        actions = self._actions("A", ex_date=T0 + 2 * DAY, available_at=T0 + 2 * DAY, ratio=0.5)
        raw_snap, act_snap = raw.copy(deep=True), actions.copy(deep=True)
        adjusted_close(raw, actions, tf_ms=DAY)
        pd.testing.assert_frame_equal(raw, raw_snap)
        pd.testing.assert_frame_equal(actions, act_snap)


# ------------------------------------------------- _adjusted_close_panel feature-detect


class TestAdjustedClosePanelFeatureDetect:
    def test_raw_fallback_when_no_corporate_actions(self, env: Env) -> None:
        # The real engine context now exposes `corporate_actions`, but this synthetic
        # lake has none planted, so the served CA frame is EMPTY -> the adjusted-close
        # panel is the raw close unchanged (no action in the window ⇒ C* == C_raw, the
        # only legitimate raw pass-through). We assert the engine path (which uses
        # _adjusted_close_panel inside the bodies) equals the helper on the raw close —
        # i.e. no adjustment is silently applied when there are no actions.
        from alphaforge.features.library import equity_price as ep

        out = env.engine.compute_history(
            [default_registry().get("eq_rev_21")],
            list(IDS),
            start=T0 + 22 * HOUR,
            end=T0 + N_BARS * HOUR,
        )
        close = _close_panel(env)
        expected = reversal(close, window=21).iloc[22:]
        assert np.array_equal(
            out["eq_rev_21"].to_numpy(), expected.to_numpy().ravel(), equal_nan=True
        )
        # Sanity: the helper this relies on exists and is callable.
        assert callable(ep._adjusted_close_panel)

    def test_adjusts_when_context_exposes_actions(self, env: Env) -> None:
        # Forward-compat: a fake context that DOES expose `corporate_actions` makes the
        # bodies run on the adjusted panel — proving the feature-detect wires through.
        from alphaforge.features.library import equity_price as ep

        class _FakeCtx:
            def __init__(self, close: pd.DataFrame, actions: pd.DataFrame) -> None:
                self._close = close
                self._actions = actions

            def panel(self, column: str = "close") -> pd.DataFrame:
                assert column == "close"
                return self._close

            def corporate_actions(self) -> pd.DataFrame:
                return self._actions

        idx = [T0 + k * DAY for k in range(8)]
        raw = pd.DataFrame({"A": [100.0] * 4 + [50.0] * 4}, index=pd.Index(idx, name="ts_open"))
        actions = pd.DataFrame(
            {
                "instrument_id": ["A"],
                "ex_date": [idx[4]],
                "available_at": [idx[0]],  # declared at the window start -> all pre-ex fold
                "action_type": ["split"],
                "ratio": [0.5],
                "cash_amount": [float("nan")],
            }
        )
        panel = ep._adjusted_close_panel(_FakeCtx(raw, actions))  # type: ignore[arg-type]
        # Adjusted: pre-ex 100 folded x0.5 -> 50, so the whole adjusted series is flat.
        assert panel["A"].iloc[3] == pytest.approx(50.0, rel=1e-12)
        assert panel["A"].nunique() == 1  # split neutralized -> constant adjusted price

        # FAIL-CLOSED (SPINE_ARC §2.3, the P1 teeth): a context lacking corporate_actions
        # entirely must NOT silently pass raw unadjusted prices through — it raises, so a
        # 2:1 split can never print as a -50% return into the factors. (An EMPTY actions
        # frame is the only legitimate raw pass-through, covered by the empty-actions
        # identity tests above and by the real-engine raw-fallback test below.)
        class _NoCA:
            def panel(self, column: str = "close") -> pd.DataFrame:
                return raw

        with pytest.raises(ConfigError, match="corporate-actions surface"):
            ep._adjusted_close_panel(_NoCA())  # type: ignore[arg-type]


# ------------------------------------------------------ momentum / beta reuse fidelity


class TestCryptoKernelReuse:
    def test_12_1_momentum_equals_xs_momentum(self, env: Env) -> None:
        # eq_mom_252_21 IS the crypto skip-momentum kernel on the (raw, in this gap
        # state) close panel — bit-for-bit, only the windows differ.
        start = T0 + 253 * HOUR
        out = env.engine.compute_history(
            [default_registry().get("eq_mom_252_21")],
            list(IDS),
            start=start,
            end=T0 + N_BARS * HOUR,
        )
        close = _close_panel(env)
        expected = xs_momentum(close, lookback=252, skip=21).iloc[253:]
        assert np.array_equal(
            out["eq_mom_252_21"].to_numpy(), expected.to_numpy().ravel(), equal_nan=True
        )
        # Non-vacuous: the last timestamp's row across all instruments is real.
        last_ts = out.index.get_level_values("ts_open").max()
        assert out.loc[last_ts, "eq_mom_252_21"].notna().all()

    def test_beta_and_bab_are_negatives_on_same_panel(self, env: Env) -> None:
        # eq_bab_252 = -eq_beta_252 (the body negates; direction carries the rest).
        out = env.engine.compute_history(
            [default_registry().get("eq_beta_252"), default_registry().get("eq_bab_252")],
            list(IDS),
            start=T0 + 254 * HOUR,
            end=T0 + N_BARS * HOUR,
        )
        beta = out["eq_beta_252"].to_numpy()
        bab = out["eq_bab_252"].to_numpy()
        finite = np.isfinite(beta) & np.isfinite(bab)
        assert finite.any()
        np.testing.assert_allclose(bab[finite], -beta[finite], rtol=0, atol=0)

    def test_beta_matches_rolling_beta_helper(self, env: Env) -> None:
        # eq_beta_252 == rolling_beta vs the equal-weight PIT-universe market (window 252).
        out = env.engine.compute_history(
            [default_registry().get("eq_beta_252")],
            list(IDS),
            start=T0 + 254 * HOUR,
            end=T0 + N_BARS * HOUR,
        )
        close = _close_panel(env)
        returns = log_returns(close)
        mask = pd.DataFrame(True, index=close.index, columns=close.columns)  # all members from T0
        mkt = market_return(returns, mask)
        expected = rolling_beta(returns, mkt, window=252).iloc[254:]
        assert np.array_equal(
            out["eq_beta_252"].to_numpy(), expected.to_numpy().ravel(), equal_nan=True
        )


# ------------------------------------------------------------- low-vol direction / BAB sign


class TestEconomicsSigns:
    def test_lowvol_direction_is_minus_one(self) -> None:
        spec = default_registry().get("eq_lowvol_252")
        assert spec.direction == -1  # low vol => high expected return (the anomaly)

    def test_cs_ranked_lowvol_scores_low_vol_higher(self) -> None:
        # Build 3 names with clearly different realized vols; the low-vol name must
        # get the HIGHEST processed score once direction=-1 is applied (we model the
        # blend's sign-application: processed = direction * winsor->z(raw vol)).
        n, window = 80, 10
        rng = np.random.default_rng(81)
        closes = {
            "LO": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.003, n))),  # low vol
            "MID": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.012, n))),
            "HI": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.030, n))),  # high vol
        }
        close = pd.DataFrame(closes, index=[T0 + k * DAY for k in range(n)])
        raw_vol = realized_vol(close, window=window)  # the raw factor body output
        # The body returns vol (not negated); direction=-1 owns the sign. Verify the
        # raw ordering is HI > MID > LO, so direction=-1 -> LO scores highest.
        last = raw_vol.iloc[-1]
        assert last["HI"] > last["MID"] > last["LO"]
        # Apply the framework's CS winsor->z then the direction sign: low vol ranks top.
        from alphaforge.features.context import long_series

        panel = long_series(raw_vol, name="eq_lowvol_252").to_frame()
        mask = pd.Series(True, index=panel.index)
        # min_members=3 for this 3-name cross-section (the default 5 would NaN it).
        processed = CSPipeline(min_members=3).apply(panel, mask)["eq_lowvol_252"]
        last_z = processed.xs(close.index[-1], level="ts_open") * (-1)  # direction=-1
        assert last_z["LO"] > last_z["HI"]

    def test_bab_low_beta_outranks_high_beta(self) -> None:
        # A synthetic low-beta name must outrank a high-beta name in eq_bab (which
        # returns -beta, so lower beta -> higher value). We check the body's -beta
        # ordering directly via rolling_beta on planted betas.
        n, window = 120, 40
        rng = np.random.default_rng(82)
        mkt_ret = rng.normal(0.0, 0.012, n)
        # LOW beta ~0.3, HIGH beta ~1.8 (plus small idiosyncratic noise).
        returns = pd.DataFrame(
            {
                "LOW": 0.3 * mkt_ret + rng.normal(0.0, 0.002, n),
                "HIGH": 1.8 * mkt_ret + rng.normal(0.0, 0.002, n),
            }
        )
        mkt = pd.Series(mkt_ret)
        beta = rolling_beta(returns, mkt, window=window)
        bab = -beta  # the eq_bab_252 body
        last = bab.iloc[-1]
        assert last["LOW"] > last["HIGH"]  # low beta -> higher BAB signal
        assert beta.iloc[-1]["LOW"] < beta.iloc[-1]["HIGH"]  # sanity on the planted betas


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpecs:
    def test_metadata(self) -> None:
        registry = default_registry()
        families = {
            "eq_mom_252_21": Family.MOMENTUM,
            "eq_rev_21": Family.REVERSAL,
            "eq_lowvol_252": Family.VOLATILITY,
            "eq_beta_252": Family.MARKET,
            "eq_bab_252": Family.MARKET,
            "eq_vol_252": Family.VOLATILITY,
            "eq_amihud_63": Family.LIQUIDITY,
        }
        for name, (lookback, direction, cs) in SPEC_META.items():
            spec = registry.get(name)
            assert spec.family is families[name], name
            assert spec.direction == direction, name
            assert spec.cross_sectional is cs, name
            assert spec.lookback_bars == lookback, name
            assert not spec.is_ewma_family, name  # all finite-window: parity atol = 0

    def test_lowvol_and_vol_share_the_same_raw_number(self, env: Env) -> None:
        # EQUITIES_CRITIQUE N3: the alpha (eq_lowvol_252) and the context (eq_vol_252)
        # are the SAME realized-vol body — their raw outputs must be bit-identical.
        out = env.engine.compute_history(
            [default_registry().get("eq_lowvol_252"), default_registry().get("eq_vol_252")],
            list(IDS),
            start=T0 + 253 * HOUR,
            end=T0 + N_BARS * HOUR,
        )
        assert np.array_equal(
            out["eq_lowvol_252"].to_numpy(), out["eq_vol_252"].to_numpy(), equal_nan=True
        )

    def test_engine_output_equals_helpers_on_same_panel(self, env: Env) -> None:
        # Warm-up headroom (max lookback = 254) lands on the lake start so the context
        # panel == the hand-built panel: equality must be bit-for-bit.
        start = T0 + 254 * HOUR
        out = env.engine.compute_history(_specs(), list(IDS), start=start, end=T0 + N_BARS * HOUR)
        close = _close_panel(env)
        qv = _qv_panel(env)
        returns = log_returns(close)
        mask = pd.DataFrame(True, index=close.index, columns=close.columns)
        mkt = market_return(returns, mask)
        from alphaforge.features.library.liquidity import amihud_illiq

        checks = {
            "eq_mom_252_21": xs_momentum(close, lookback=252, skip=21),
            "eq_rev_21": reversal(close, window=21),
            "eq_lowvol_252": realized_vol(close, window=252),
            "eq_vol_252": realized_vol(close, window=252),
            "eq_beta_252": rolling_beta(returns, mkt, window=252),
            "eq_bab_252": -rolling_beta(returns, mkt, window=252),
            "eq_amihud_63": amihud_illiq(close, qv, window=63),
        }
        for name, helper in checks.items():
            expected = helper.iloc[254:]
            assert np.array_equal(
                out[name].to_numpy(), expected.to_numpy().ravel(), equal_nan=True
            ), name
        assert out[list(ALL_NAMES)].iloc[-1].notna().all()  # non-vacuous


# -------------------------------------------------------------- truncation + parity


class TestTruncationAndParity:
    TS_SAMPLES = (T0 + 660 * HOUR + 7 * 60_000, T0 + 690 * HOUR)

    def test_every_spec_truncation_exact(self, env: Env) -> None:
        # Live minimal window (exactly lookback_bars) vs full history: all equity
        # factors are finite-window -> bit-for-bit (atol = 0), no EWMA tolerance.
        registry = default_registry()
        for name in ALL_NAMES:
            spec = registry.get(name)
            report = verify_truncation(
                env.engine, spec, list(IDS), list(self.TS_SAMPLES), history_start=T0
            )
            result = report.result(name)
            assert result.passed, f"{name}: {result}"
            assert result.rtol == 0.0, name
            assert result.max_abs_diff == 0.0, name  # finite windows: bit-for-bit
            assert result.n_points == 6, name  # 2 samples x 3 instruments
            # Non-vacuous: the sampled live values are real numbers, not NaN==NaN.
            live = env.engine.compute_asof([spec], list(IDS), as_of=self.TS_SAMPLES[0])
            assert live[name].notna().all(), name

    def test_batch_vs_live_parity_all_specs(self, env: Env) -> None:
        report = verify_parity(
            env.engine, _specs(), list(IDS), list(self.TS_SAMPLES), history_start=T0
        )
        assert report.passed, [r for r in report.results if not r.passed]
        for name in ALL_NAMES:
            result = report.result(name)
            assert result.rtol == 0.0, name
            assert result.max_abs_diff == 0.0, name
