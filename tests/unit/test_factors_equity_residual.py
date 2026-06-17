"""Unit tests for alphaforge.features.library.equity_residual (EQUITIES_SLEEVE.md §4, S6).

The beta-residualized 1-month reversal ``eq_rev_resid_21`` — the institutionally
credible reversal: it strips the 252-session market-beta exposure out of daily returns
and reverses the idiosyncratic residual (plain ``eq_rev_21`` is microstructure-
contaminated and a hidden beta bet).

EQUITY-SLEEVE OPT-IN — synthetic-context discipline. This factor is registered but is
NOT in any crypto/default active set; it runs on the EQUITY/D1 path and CANNOT compute
through the real ``FeatureEngine`` until the equity guard lifts (the
``_adjusted_close_panel`` fail-closed gate also requires a corporate-actions surface).
So — exactly like the pure ``adjusted_close`` PIT tests in
``test_factors_equity_price.py`` exercise the math off-engine — these tests drive the
registered body against a SYNTHETIC :class:`FeatureContext`-shaped fixture (a fake
exposing ``panel`` / ``corporate_actions`` / ``universe_asof``, the only surfaces the
body touches) on a deterministic session grid. Coverage:

* shape / index contract of the long output (the (ts_open, instrument_id) Cartesian
  product over the requested cross-section);
* the direction sign on a PLANTED idiosyncratic loser (a name whose residual return
  fell over the formation window scores POSITIVE — ``direction=+1``);
* NaN policy — NaN through the warmup (until the beta window + reversal sum are full),
  and a gap inside the window NaNs exactly the touched name (never bridged);
* the cross-sectional z-score: after the framework's winsor→z pipeline the PIT
  cross-section at a timestamp is mean ~0 / std ~1;
* the helper :func:`residual_reversal_finite` formula (the negated cumulative residual)
  to 1e-12, and the residual = ``r - β·m`` identity;
* registered-spec metadata (finite-window: parity atol = 0).

The synthetic grid is laid at the true daily Δ; the body is positional on the panel
(``shift(k)`` = k grid slots), so one grid slot == one session bar for every window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from alphaforge.features.cross_section import CSPipeline
from alphaforge.features.library.equity_residual import (
    EQ_BETA_WINDOW,
    eq_rev_resid_21,
    residual_reversal_finite,
)
from alphaforge.features.library.mean_reversion import market_return, rolling_beta
from alphaforge.features.library.vol import log_returns
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family

if TYPE_CHECKING:
    from collections.abc import Sequence

A = "XNAS:CASH:AAAAUSD"
B = "XNAS:CASH:BBBBUSD"
C = "XNAS:CASH:CCCCUSD"
D = "XNAS:CASH:DDDDUSD"
E = "XNAS:CASH:EEEEUSD"
IDS = (A, B, C, D, E)

DAY = 86_400_000
T0 = 1_577_836_800_000  # 2020-01-01T00:00:00Z (aligned)
WINDOW = 21
BETA_WINDOW = EQ_BETA_WINDOW  # 252
N_BARS = BETA_WINDOW + WINDOW + 1 + 40  # ample headroom past the 274-bar warmup


# --------------------------------------------------------------------- synthetic ctx


class _SyntheticCtx:
    """A FeatureContext-shaped stand-in exposing only the surfaces the body calls.

    The equity residual body reads ``panel("close")`` / ``panel("quote_volume")``,
    ``corporate_actions()`` (empty ⇒ raw == adjusted, the only legitimate
    pass-through) and ``universe_asof(ts)`` (the PIT membership set, frozenset for the
    ``_member_mask`` cache). All names are members from T0 — no mid-history entry.
    """

    def __init__(self, close: pd.DataFrame) -> None:
        self._close = close
        self._members = frozenset(str(c) for c in close.columns)

    def panel(self, column: str = "close") -> pd.DataFrame:
        if column == "close":
            return self._close
        if column == "quote_volume":
            return 1_000_000.0 * self._close
        raise KeyError(column)  # pragma: no cover - body only asks for the two above

    def corporate_actions(self) -> pd.DataFrame:
        return pd.DataFrame(
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

    def universe_asof(self, ts: int) -> frozenset[str]:
        del ts  # all names are members from T0; the timestamp is unused
        return self._members


def _index(n: int) -> pd.Index:
    return pd.Index([T0 + k * DAY for k in range(n)], name="ts_open")


def _walk(seed: int, n: int, level: float, sigma: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out: np.ndarray = level * np.exp(np.cumsum(rng.normal(0.0, sigma, n)))
    return out


def _close_panel(seeds: Sequence[int], n: int = N_BARS) -> pd.DataFrame:
    cols = {
        iid: _walk(seed, n, 100.0 + 10.0 * i, 0.015)
        for i, (iid, seed) in enumerate(zip(IDS, seeds, strict=True))
    }
    return pd.DataFrame(cols, index=_index(n))


# ------------------------------------------------------------- residual_reversal_finite


class TestResidualReversalFiniteFormula:
    def test_exact_negated_cumulative_residual(self) -> None:
        # Plant returns/beta/market and check REV = -Σ_{k<W} (r - β·m) exactly.
        n, window = 30, 4
        rng = np.random.default_rng(11)
        returns = pd.DataFrame(
            {"X": rng.normal(0.0, 0.01, n), "Y": rng.normal(0.0, 0.01, n)},
            index=_index(n),
        )
        beta = pd.DataFrame({"X": np.full(n, 0.8), "Y": np.full(n, 1.3)}, index=_index(n))
        mkt = pd.Series(rng.normal(0.0, 0.008, n), index=_index(n))
        out = residual_reversal_finite(returns, beta, mkt, window=window)
        resid = returns.sub(beta.mul(mkt, axis=0))
        for t in (10, 20, 29):
            for col in ("X", "Y"):
                expected = -float(resid[col].to_numpy()[t - window + 1 : t + 1].sum())
                assert abs(out.iloc[t][col] - expected) < 1e-12, (t, col)

    def test_nan_until_window_full(self) -> None:
        n, window = 12, 4
        returns = pd.DataFrame({"X": np.full(n, 0.01)}, index=_index(n))
        beta = pd.DataFrame({"X": np.full(n, 1.0)}, index=_index(n))
        mkt = pd.Series(np.full(n, 0.005), index=_index(n))
        out = residual_reversal_finite(returns, beta, mkt, window=window)
        assert out["X"].iloc[: window - 1].isna().all()  # need W residuals
        assert np.isfinite(out["X"].iloc[window - 1])

    def test_gap_poisons_exactly_the_window(self) -> None:
        n, window = 14, 4
        returns = pd.DataFrame({"X": np.full(n, 0.01)}, index=_index(n))
        returns.iloc[6, 0] = np.nan  # a gapped residual
        beta = pd.DataFrame({"X": np.full(n, 1.0)}, index=_index(n))
        mkt = pd.Series(np.full(n, 0.0), index=_index(n))
        out = residual_reversal_finite(returns, beta, mkt, window=window)
        # The W-bar sums covering index 6 are NaN (windows ending 6..9), neighbours live.
        for t in (6, 7, 8, 9):
            assert np.isnan(out["X"].iloc[t]), t
        assert np.isfinite(out["X"].iloc[10])  # window 7..10 has no gap

    def test_invalid_window_rejected(self) -> None:
        df = pd.DataFrame({"X": [0.01, 0.02]}, index=_index(2))
        with pytest.raises(ValueError, match="window"):
            residual_reversal_finite(df, df, df["X"], window=0)

    def test_no_input_mutation(self) -> None:
        n, window = 10, 3
        returns = pd.DataFrame({"X": np.full(n, 0.01)}, index=_index(n))
        beta = pd.DataFrame({"X": np.full(n, 1.0)}, index=_index(n))
        mkt = pd.Series(np.full(n, 0.005), index=_index(n))
        r_snap, b_snap, m_snap = returns.copy(deep=True), beta.copy(deep=True), mkt.copy(deep=True)
        residual_reversal_finite(returns, beta, mkt, window=window)
        pd.testing.assert_frame_equal(returns, r_snap)
        pd.testing.assert_frame_equal(beta, b_snap)
        pd.testing.assert_series_equal(mkt, m_snap)


# ----------------------------------------------------------- body via synthetic context


class TestBodyOnSyntheticContext:
    def test_shape_and_index_contract(self) -> None:
        spec = eq_rev_resid_21()
        ctx = _SyntheticCtx(_close_panel((61, 62, 63, 64, 65)))
        out = spec.fn(ctx, spec)  # type: ignore[arg-type]
        assert out.name == "eq_rev_resid_21"
        assert isinstance(out.index, pd.MultiIndex)
        assert out.index.nlevels == 2
        assert out.index.names == ["ts_open", "instrument_id"]
        assert len(out) == N_BARS * len(IDS)  # full Cartesian product
        # Non-vacuous: the last timestamp's row across all names is real.
        last_ts = out.index.get_level_values("ts_open").max()
        assert out.xs(last_ts, level="ts_open").notna().all()

    def test_body_equals_helper_on_same_panel(self) -> None:
        # The body must equal residual_reversal_finite on the (raw == adjusted, no
        # actions) panel, bit-for-bit, with the same beta/market the helpers build.
        spec = eq_rev_resid_21()
        close = _close_panel((71, 72, 73, 74, 75))
        ctx = _SyntheticCtx(close)
        out = spec.fn(ctx, spec)  # type: ignore[arg-type]
        returns = log_returns(close)
        mask = pd.DataFrame(True, index=close.index, columns=close.columns)
        mkt = market_return(returns, mask)
        beta = rolling_beta(returns, mkt, window=BETA_WINDOW)
        expected = residual_reversal_finite(returns, beta, mkt, window=WINDOW)
        assert np.array_equal(out.to_numpy(), expected.to_numpy().ravel(), equal_nan=True)

    def test_warmup_nan_boundary(self) -> None:
        # NaN until lookback_bars-1 grid slots exist behind t: beta needs window+1
        # returns ending t-1 (first finite beta at index BETA_WINDOW+1), then the
        # W-residual sum needs W-1 more -> first finite at BETA_WINDOW + W.
        spec = eq_rev_resid_21()
        close = _close_panel((81, 82, 83, 84, 85))
        ctx = _SyntheticCtx(close)
        out = spec.fn(ctx, spec).unstack(level="instrument_id")  # type: ignore[arg-type]
        first_finite = BETA_WINDOW + WINDOW
        assert out.iloc[first_finite - 1].isna().all()
        assert out.iloc[first_finite].notna().all()


# ------------------------------------------------------------- direction / economics


class TestDirectionSign:
    def test_residual_loser_scores_positive(self) -> None:
        # Plant an idiosyncratic loser: name A has a strongly NEGATIVE residual over
        # the last W sessions while the market is flat. -Σε > 0 => positive signal
        # (direction=+1 reads "expected outperformer"). We use the helper directly on
        # planted residuals to isolate the sign.
        n, window = 60, WINDOW
        idx = _index(n)
        mkt = pd.Series(np.zeros(n), index=idx)  # flat market => residual == return
        returns = pd.DataFrame(
            {
                A: np.concatenate([np.zeros(n - window), np.full(window, -0.02)]),  # loser
                B: np.concatenate([np.zeros(n - window), np.full(window, +0.02)]),  # winner
            },
            index=idx,
        )
        beta = pd.DataFrame({A: np.full(n, 1.0), B: np.full(n, 1.0)}, index=idx)
        out = residual_reversal_finite(returns, beta, mkt, window=window)
        last = out.iloc[-1]
        assert last[A] > 0.0  # recent residual loser => positive reversal signal
        assert last[B] < 0.0  # recent residual winner => negative
        assert last[A] > last[B]

    def test_strips_the_market_beta_bet(self) -> None:
        # A name that fell ONLY because the market fell (return == β·m) has ~zero
        # residual => ~zero reversal: the factor does NOT fade the market itself.
        n, window = 60, WINDOW
        idx = _index(n)
        rng = np.random.default_rng(91)
        m = rng.normal(-0.01, 0.005, n)  # a steadily falling market
        mkt = pd.Series(m, index=idx)
        beta_val = 1.4
        returns = pd.DataFrame({A: beta_val * m}, index=idx)  # pure market exposure
        beta = pd.DataFrame({A: np.full(n, beta_val)}, index=idx)
        out = residual_reversal_finite(returns, beta, mkt, window=window)
        # Residual ≈ 0 everywhere => reversal ≈ 0 despite the big raw drawdown.
        assert abs(out[A].iloc[-1]) < 1e-12
        # Sanity: the RAW (un-residualized) reversal would be large and positive.
        raw_rev = -float(returns[A].to_numpy()[-window:].sum())
        assert raw_rev > 0.05


# --------------------------------------------------------------- cross-sectional zscore


class TestCrossSectionalZScore:
    def test_pit_cross_section_is_mean0_std1(self) -> None:
        # After the framework winsor->z pipeline, the PIT cross-section at a timestamp
        # is standardized (mean ~0, std ~1 over the members) — the contract a
        # cross_sectional=True factor relies on before blending.
        spec = eq_rev_resid_21()
        ctx = _SyntheticCtx(_close_panel((101, 102, 103, 104, 105)))
        raw = spec.fn(ctx, spec).to_frame()  # type: ignore[arg-type]
        mask = pd.Series(True, index=raw.index)
        processed = CSPipeline(min_members=3).apply(raw, mask)["eq_rev_resid_21"]
        last_ts = raw.index.get_level_values("ts_open").max()
        xs = processed.xs(last_ts, level="ts_open").dropna()
        assert len(xs) == len(IDS)  # all members survive
        assert abs(float(xs.mean())) < 1e-9
        assert abs(float(xs.std(ddof=1)) - 1.0) < 1e-9

    def test_zscore_preserves_the_reversal_ranking(self) -> None:
        # The z-score is a monotone affine transform per timestamp, so the planted
        # residual loser still scores above the winner after standardization.
        spec = eq_rev_resid_21()
        ctx = _SyntheticCtx(_close_panel((111, 112, 113, 114, 115)))
        raw = spec.fn(ctx, spec).to_frame()  # type: ignore[arg-type]
        mask = pd.Series(True, index=raw.index)
        processed = CSPipeline(min_members=3).apply(raw, mask)["eq_rev_resid_21"]
        last_ts = raw.index.get_level_values("ts_open").max()
        raw_xs = raw["eq_rev_resid_21"].xs(last_ts, level="ts_open")
        z_xs = processed.xs(last_ts, level="ts_open")
        top_raw = raw_xs.idxmax()
        top_z = z_xs.idxmax()
        assert top_raw == top_z  # ranking preserved through winsor->z


# ------------------------------------------------------------------- registered spec


class TestRegisteredSpec:
    def test_metadata(self) -> None:
        spec = default_registry().get("eq_rev_resid_21")
        assert spec.family is Family.REVERSAL
        assert spec.direction == 1
        assert spec.cross_sectional is True
        # The oldest residual in the W-session sum carries its OWN beta window, so the
        # formation window SHIFTS the beta window back by W-1 (it does not vanish under
        # the larger beta_window): lookback = beta_window + window + 1 = 274.
        assert spec.lookback_bars == BETA_WINDOW + WINDOW + 1
        assert not spec.is_ewma_family  # finite window: parity atol = 0
        assert spec.params["window"] == WINDOW
        assert spec.params["beta_window"] == BETA_WINDOW

    def test_is_equity_opt_in_not_in_crypto_default(self) -> None:
        # The factor must be registered but NEVER auto-included in any crypto/default
        # active set: assert it is reachable by name but its id prefix marks it equity.
        assert "eq_rev_resid_21" in default_registry()
        # Pure registration check; the crypto active-set wiring lives elsewhere and is
        # owned by the lead — we only assert this factor does not masquerade as crypto.
        assert default_registry().get("eq_rev_resid_21").name.startswith("eq_")
