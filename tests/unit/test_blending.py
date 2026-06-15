"""Unit tests for alphaforge.signals.blending (alphaDesign.md §9.1).

The load-bearing properties:

* LAG ENFORCEMENT — a Rank-IC observation whose label is not yet fully realized
  at grid point t (t' + h·Δ > t) can NEVER move the weights used at t. On the
  uniform h-grid that is exactly a one-grid-step shift; perturbing the RIC at
  grid point j must leave every weight row <= j bit-identical.
* κ FLOOR (leakage finding 19) — all smoothed ICs <= 0 degrades to EQUAL
  weights, never 0/0 or NaN.
* Cold start — no realized RIC yet => equal weights (emergent from the floor).
* Monotonicity — a better-IC alpha gets strictly more weight.
* blend() — A = Σ w·z under the step-function weights, re-standardized via
  cs_zscore under the SAME universe mask; strict NaN discipline.

Offline, pure pandas/numpy; no lake, no I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaforge.core.time import Timeframe
from alphaforge.signals.blending import (
    ALPHA_BLEND_COLUMN,
    DEFAULT_COST_FRAC,
    DEFAULT_IC_TARGET,
    DEFAULT_SIGMA_H_TYP,
    KAPPA_FLOOR,
    BlendWeights,
    blend,
    default_lambda_cost,
    estimate_blend_weights,
)

HOUR = 3_600_000
H = 72  # horizon_bars used throughout (matches SignalsCfg default)
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z


def _grid(n: int) -> pd.Index:
    """Non-overlapping h-grid: n points spaced exactly H bars apart."""
    return pd.Index(np.arange(n, dtype=np.int64) * H * HOUR + T0, name="ts_open")


def _ics(values_by_alpha: dict[str, list[float]]) -> dict[str, pd.Series]:
    n = len(next(iter(values_by_alpha.values())))
    grid = _grid(n)
    return {
        k: pd.Series(np.asarray(v, dtype=float), index=grid) for k, v in values_by_alpha.items()
    }


def _to(values_by_alpha: dict[str, list[float]]) -> dict[str, pd.Series]:
    """Per-factor turnover series on the SAME non-overlapping h-grid as the ICs.

    Stand-in for :func:`alphaforge.validation.metrics.factor_turnover` (owned by a
    sibling module) — these tests only need a turnover series shaped like the IC
    series, not the metric itself, to exercise the cost haircut in blending.py."""
    return _ics(values_by_alpha)


class TestLagEnforcement:
    def test_huge_ic_at_last_grid_point_changes_nothing(self) -> None:
        """An IC printed in the last h bars (the final grid point) is not yet
        usable anywhere — the entire weights frame must be identical whether
        that observation is +0.99 or -0.99."""
        base = [0.10, 0.08, 0.12, 0.09, 0.11, 0.10]
        hot = estimate_blend_weights(_ics({"a": [*base, 0.99], "b": [0.05] * 7}), horizon_bars=H)
        cold = estimate_blend_weights(_ics({"a": [*base, -0.99], "b": [0.05] * 7}), horizon_bars=H)
        pd.testing.assert_frame_equal(hot.weights, cold.weights, check_exact=True)

    def test_perturbation_at_grid_j_only_affects_rows_after_j(self) -> None:
        a = [0.10, 0.08, 0.12, 0.09, 0.11, 0.10, 0.07, 0.09]
        a_pert = list(a)
        j = 4
        a_pert[j] = 0.95  # label for this RIC realizes at grid j+1, not at j
        b = [0.05] * len(a)
        w = estimate_blend_weights(_ics({"a": a, "b": b}), horizon_bars=H).weights
        w_pert = estimate_blend_weights(_ics({"a": a_pert, "b": b}), horizon_bars=H).weights
        pd.testing.assert_frame_equal(w.iloc[: j + 1], w_pert.iloc[: j + 1], check_exact=True)
        assert not np.allclose(w.iloc[j + 1 :].to_numpy(), w_pert.iloc[j + 1 :].to_numpy()), (
            "rows after j must SEE the realized perturbation"
        )

    def test_non_uniform_grid_is_refused(self) -> None:
        """The shift-is-the-rule equivalence holds only on a uniform h-grid."""
        idx = pd.Index(np.array([T0, T0 + H * HOUR, T0 + 3 * H * HOUR], dtype=np.int64))
        ics = {"a": pd.Series([0.1, 0.1, 0.1], index=idx)}
        with pytest.raises(ValueError, match="uniformly spaced"):
            estimate_blend_weights(ics, horizon_bars=H)


class TestKappaFloor:
    def test_all_negative_ics_degrade_to_equal_weights(self) -> None:
        """Finding 19 regression: w = max(IC,0) + κ with κ floored — all ICs <= 0
        must yield exactly equal weights, no 0/0, no NaN."""
        w = estimate_blend_weights(
            _ics({"a": [-0.3] * 8, "b": [-0.1] * 8, "c": [0.0] * 8}), horizon_bars=H
        ).weights
        assert np.isfinite(w.to_numpy()).all()
        np.testing.assert_allclose(w.to_numpy(), 1.0 / 3.0, rtol=1e-15)

    def test_floor_value_keeps_weights_strictly_positive(self) -> None:
        w = estimate_blend_weights(_ics({"a": [0.5] * 8, "b": [-0.5] * 8}), horizon_bars=H).weights
        assert (w.to_numpy() > 0.0).all()  # dead alpha decays toward κ, never to 0
        # dead alpha's weight is exactly κ_floor/(0.5 + κ_shrink·0.25 + 2κ) at steady state
        # — just assert it is small but nonzero and rows sum to 1.
        np.testing.assert_allclose(w.sum(axis=1).to_numpy(), 1.0, rtol=1e-12)
        assert (w["b"].iloc[2:] < 0.1).all()


class TestWeightFormula:
    def test_constant_ics_reproduce_the_formula_exactly(self) -> None:
        """Constant realized ICs => EWMA == the constant; with IC_a=0.10,
        IC_b=0.05: κ = max(0.2·mean(0.10, 0.05), 0.01) = 0.015,
        w_a = 0.115/0.18, w_b = 0.065/0.18 (alphaDesign.md §9.1 verbatim)."""
        w = estimate_blend_weights(_ics({"a": [0.10] * 6, "b": [0.05] * 6}), horizon_bars=H).weights
        np.testing.assert_allclose(w["a"].iloc[1:].to_numpy(), 0.115 / 0.18, rtol=1e-12)
        np.testing.assert_allclose(w["b"].iloc[1:].to_numpy(), 0.065 / 0.18, rtol=1e-12)

    def test_better_ic_alpha_gets_more_weight(self) -> None:
        rng = np.random.default_rng(7)
        good = (0.25 + 0.02 * rng.standard_normal(12)).tolist()
        weak = (0.05 + 0.02 * rng.standard_normal(12)).tolist()
        w = estimate_blend_weights(_ics({"good": good, "weak": weak}), horizon_bars=H).weights
        assert (w["good"].iloc[1:] > w["weak"].iloc[1:]).all()
        np.testing.assert_allclose(w.sum(axis=1).to_numpy(), 1.0, rtol=1e-12)

    def test_cold_start_equal_weights(self) -> None:
        """First grid point has no realized RIC (the shift) — and an all-NaN IC
        history (thin cross-sections) stays equal-weighted throughout."""
        w = estimate_blend_weights(_ics({"a": [0.4] * 5, "b": [0.1] * 5}), horizon_bars=H).weights
        np.testing.assert_allclose(w.iloc[0].to_numpy(), 0.5, rtol=0, atol=0)
        w_nan = estimate_blend_weights(
            _ics({"a": [float("nan")] * 5, "b": [float("nan")] * 5}), horizon_bars=H
        ).weights
        np.testing.assert_allclose(w_nan.to_numpy(), 0.5, rtol=0, atol=0)

    def test_empty_grid_yields_equal_weight_object(self) -> None:
        bw = estimate_blend_weights(
            {"a": pd.Series(dtype=float), "b": pd.Series(dtype=float)}, horizon_bars=H
        )
        np.testing.assert_allclose(bw.asof(T0).to_numpy(), 0.5)

    def test_validation_errors(self) -> None:
        with pytest.raises(ValueError, match="horizon_bars"):
            estimate_blend_weights(_ics({"a": [0.1] * 3}), horizon_bars=0)
        with pytest.raises(ValueError, match="at least one alpha"):
            estimate_blend_weights({}, horizon_bars=H)
        with pytest.raises(ValueError, match="kappa_floor"):
            estimate_blend_weights(_ics({"a": [0.1] * 3}), horizon_bars=H, kappa_floor=0.0)
        assert KAPPA_FLOOR == 0.01  # leakage finding 19 constant


class TestAsof:
    def test_step_function_semantics(self) -> None:
        bw = estimate_blend_weights(_ics({"a": [0.10] * 4, "b": [0.05] * 4}), horizon_bars=H)
        grid = bw.weights.index.to_numpy()
        # before the first grid point: equal weights (cold start)
        np.testing.assert_allclose(bw.asof(int(grid[0]) - 1).to_numpy(), 0.5)
        # exactly at a grid point: that row
        np.testing.assert_allclose(
            bw.asof(int(grid[2])).to_numpy(), bw.weights.iloc[2].to_numpy(), rtol=0
        )
        # strictly between grid points: the PREVIOUS row (no future weights)
        np.testing.assert_allclose(
            bw.asof(int(grid[2]) + HOUR).to_numpy(), bw.weights.iloc[2].to_numpy(), rtol=0
        )

    def test_equal_constructor(self) -> None:
        bw = BlendWeights.equal(("x", "y", "z"))
        np.testing.assert_allclose(bw.asof(T0).to_numpy(), 1.0 / 3.0)
        assert len(bw.weights) == 0


def _panel_index(ts_list: list[int], iids: list[str]) -> pd.MultiIndex:
    return pd.MultiIndex.from_product([ts_list, iids], names=("ts_open", "instrument_id"))


class TestBlend:
    def test_blend_is_weighted_sum_then_cs_zscore(self) -> None:
        iids = [f"I{k}" for k in range(6)]
        ts = [T0, T0 + HOUR]
        index = _panel_index(ts, iids)
        rng = np.random.default_rng(3)
        za = pd.Series(rng.standard_normal(len(index)), index=index)
        zb = pd.Series(rng.standard_normal(len(index)), index=index)
        row = pd.DataFrame(
            [[0.7, 0.3]], index=pd.Index(np.array([T0 - HOUR], dtype=np.int64)), columns=["a", "b"]
        )
        bw = BlendWeights(alpha_names=("a", "b"), weights=row, smoothed_ic=row * np.nan)
        mask = pd.Series(True, index=index)
        out = blend({"a": za, "b": zb}, bw, mask)
        assert out.name == ALPHA_BLEND_COLUMN
        a_raw = 0.7 * za + 0.3 * zb
        for t in ts:
            got = out.xs(t, level="ts_open")
            exp_raw = a_raw.xs(t, level="ts_open")
            exp = (exp_raw - exp_raw.mean()) / exp_raw.std(ddof=1)
            np.testing.assert_allclose(got.to_numpy(), exp.to_numpy(), rtol=1e-12)

    def test_non_member_is_nan_and_excluded_from_stats(self) -> None:
        iids = [f"I{k}" for k in range(6)]
        index = _panel_index([T0], iids)
        z = pd.Series(np.arange(6, dtype=float), index=index)
        bw = BlendWeights.equal(("a",))
        mask = pd.Series(index.get_level_values(1) != "I5", index=index)
        out = blend({"a": z}, bw, mask)
        assert np.isnan(out.loc[(T0, "I5")])
        members = out.drop((T0, "I5"))
        np.testing.assert_allclose(float(members.mean()), 0.0, atol=1e-12)  # zscored over 5 only

    def test_missing_alpha_for_one_instrument_drops_it(self) -> None:
        """Strict NaN discipline: an instrument missing ANY alpha leaves the
        cross-section (a partially-informed blend would re-weight silently)."""
        iids = [f"I{k}" for k in range(6)]
        index = _panel_index([T0], iids)
        za = pd.Series(np.arange(6, dtype=float), index=index)
        zb = za.copy()
        zb.loc[(T0, "I2")] = np.nan
        bw = BlendWeights.equal(("a", "b"))
        out = blend({"a": za, "b": zb}, bw, pd.Series(True, index=index))
        assert np.isnan(out.loc[(T0, "I2")])
        assert np.isfinite(out.drop((T0, "I2")).to_numpy()).all()

    def test_alpha_set_mismatch_raises(self) -> None:
        index = _panel_index([T0], ["I0", "I1", "I2", "I3", "I4"])
        z = pd.Series(np.arange(5, dtype=float), index=index)
        with pytest.raises(ValueError, match="alpha_names"):
            blend({"other": z}, BlendWeights.equal(("a",)), pd.Series(True, index=index))

    def test_timeframe_default_is_engine_anchor(self) -> None:
        # the grid spacing assertion is in ANCHOR (1h) milliseconds
        assert Timeframe.H1.ms == HOUR


class TestNetCostWeighting:
    """Net-of-cost IC weighting (slate §2 — the single highest-leverage change).

    netIC_{k,t} = ÎC_{k,t} - λ_cost·c·T̂O_{k,t}; the weight formula + κ floor then
    operate on netIC. ``grid_turnover=None`` MUST reproduce the gross path exactly.
    """

    def test_no_turnover_is_bitwise_backcompat(self) -> None:
        """grid_turnover=None reproduces the gross-IC weights bit-for-bit, and the
        net IC frame equals the gross IC frame."""
        ics = _ics({"a": [0.10] * 8, "b": [0.05] * 8, "c": [0.02] * 8})
        gross = estimate_blend_weights(ics, horizon_bars=H)
        netnone = estimate_blend_weights(ics, horizon_bars=H, grid_turnover=None)
        pd.testing.assert_frame_equal(gross.weights, netnone.weights, check_exact=True)
        # the audit frames are now populated and consistent
        pd.testing.assert_frame_equal(
            netnone.smoothed_ic, netnone.gross_smoothed_ic, check_exact=True
        )
        pd.testing.assert_frame_equal(
            netnone.net_smoothed_ic, netnone.gross_smoothed_ic, check_exact=True
        )

    def test_zero_turnover_equals_gross(self) -> None:
        """An all-zero turnover map applies a zero haircut → identical to gross."""
        ics = _ics({"a": [0.10] * 8, "b": [0.05] * 8})
        gross = estimate_blend_weights(ics, horizon_bars=H).weights
        zero_to = estimate_blend_weights(
            ics, horizon_bars=H, grid_turnover=_to({"a": [0.0] * 8, "b": [0.0] * 8})
        ).weights
        pd.testing.assert_frame_equal(gross, zero_to, check_exact=True)

    def test_high_turnover_low_net_factor_is_downweighted_vs_gross(self) -> None:
        """THE regression (slate §2): two factors with the SAME gross IC; the one
        that churns its ranking every grid point (high turnover) must get strictly
        LESS weight under net-of-cost than under gross weighting, and strictly less
        than its slow, equal-gross-IC sibling."""
        ic = 0.10
        ics = _ics({"slow": [ic] * 10, "fast": [ic] * 10})
        # identical gross IC -> equal weight under the old (gross) formula
        gross = estimate_blend_weights(ics, horizon_bars=H).weights
        np.testing.assert_allclose(
            gross["slow"].iloc[1:].to_numpy(), gross["fast"].iloc[1:].to_numpy(), rtol=1e-12
        )
        # slow factor barely re-ranks (TO~0.10); fast factor churns (TO~0.70)
        turnover = _to({"slow": [0.10] * 10, "fast": [0.70] * 10})
        net = estimate_blend_weights(ics, horizon_bars=H, grid_turnover=turnover).weights
        steady = slice(2, None)  # past the lag + first EWMA point
        # the costly factor is DOWN-weighted relative to gross ...
        assert (net["fast"].iloc[steady] < gross["fast"].iloc[steady]).all()
        # ... and relative to its slow, equal-gross-IC sibling
        assert (net["fast"].iloc[steady] < net["slow"].iloc[steady]).all()
        # the slow factor PICKS UP the weight the fast one shed
        assert (net["slow"].iloc[steady] > gross["slow"].iloc[steady]).all()
        np.testing.assert_allclose(net.sum(axis=1).to_numpy(), 1.0, rtol=1e-12)

    def test_costly_factor_driven_to_kappa_floor(self) -> None:
        """A fast factor whose cost drag exceeds its gross IC has netIC <= 0 and is
        driven to the κ floor (equal-with-the-other-dead-alpha share), NEVER to a
        negative or NaN weight (finding-19 floor survives the haircut)."""
        # gross IC 0.05 for the fast factor; haircut λ·c·TO ≈ 588·0.001·0.9 ≈ 0.53 >> 0.05
        ics = _ics({"good": [0.20] * 8, "bleeder": [0.05] * 8})
        turnover = _to({"good": [0.05] * 8, "bleeder": [0.90] * 8})
        bw = estimate_blend_weights(ics, horizon_bars=H, grid_turnover=turnover)
        w = bw.weights
        assert np.isfinite(w.to_numpy()).all()
        assert (w.to_numpy() > 0.0).all()  # κ floor keeps it strictly positive
        np.testing.assert_allclose(w.sum(axis=1).to_numpy(), 1.0, rtol=1e-12)
        # bleeder's NET smoothed IC went negative even though gross was positive
        steady = slice(2, None)
        assert (bw.gross_smoothed_ic["bleeder"].iloc[steady] > 0.0).all()
        assert (bw.net_smoothed_ic["bleeder"].iloc[steady] < 0.0).all()
        # ... so it collapses to the κ-floor share (positive=0) while the survivor
        # carries its net IC plus the floor — the costly leg gets far less weight.
        net_good = 0.20 - default_lambda_cost() * DEFAULT_COST_FRAC * 0.05
        kappa = max(0.2 * 0.5 * net_good, KAPPA_FLOOR)  # bleeder contributes 0 to the mean
        floor_share = kappa / (net_good + 2.0 * kappa)
        np.testing.assert_allclose(w["bleeder"].iloc[steady].to_numpy(), floor_share, rtol=1e-9)
        assert (w["bleeder"].iloc[steady] < 0.25 * w["good"].iloc[steady]).all()

    def test_net_ic_matches_closed_form_haircut(self) -> None:
        """Constant IC + constant TO => EWMA == the constants; net IC equals the
        exact closed form ÎC - λ·c·T̂O, and the weights follow the §9.1 formula on
        that net IC."""
        ic_a, ic_b = 0.12, 0.10
        to_a, to_b = 0.10, 0.50
        lam = default_lambda_cost()
        c = DEFAULT_COST_FRAC
        bw = estimate_blend_weights(
            _ics({"a": [ic_a] * 8, "b": [ic_b] * 8}),
            horizon_bars=H,
            grid_turnover=_to({"a": [to_a] * 8, "b": [to_b] * 8}),
        )
        net_a = ic_a - lam * c * to_a
        net_b = ic_b - lam * c * to_b
        steady = slice(2, None)
        np.testing.assert_allclose(
            bw.net_smoothed_ic["a"].iloc[steady].to_numpy(), net_a, rtol=1e-9
        )
        np.testing.assert_allclose(
            bw.net_smoothed_ic["b"].iloc[steady].to_numpy(), net_b, rtol=1e-9
        )
        pos_a, pos_b = max(net_a, 0.0), max(net_b, 0.0)
        kappa = max(0.2 * 0.5 * (pos_a + pos_b), KAPPA_FLOOR)
        denom = (pos_a + kappa) + (pos_b + kappa)
        np.testing.assert_allclose(
            bw.weights["a"].iloc[steady].to_numpy(), (pos_a + kappa) / denom, rtol=1e-9
        )
        np.testing.assert_allclose(
            bw.weights["b"].iloc[steady].to_numpy(), (pos_b + kappa) / denom, rtol=1e-9
        )

    def test_turnover_is_lagged_like_ic_no_lookahead(self) -> None:
        """A turnover spike at grid point j (label/cost realizes for the row USED at
        j+1) must leave every weight row <= j bit-identical — same one-grid-step lag
        the IC obeys. This is the leak-safety property for the cost leg."""
        # IC high + low baseline turnover so the baseline net IC stays POSITIVE
        # (off the κ floor) — only then is a turnover perturbation observable.
        base_to = [0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
        spiked = list(base_to)
        j = 4
        spiked[j] = 0.95  # the cost realized AT j; usable only from j+1
        ics = _ics({"a": [0.30] * 8, "b": [0.30] * 8})
        w = estimate_blend_weights(
            ics, horizon_bars=H, grid_turnover=_to({"a": base_to, "b": [0.05] * 8})
        ).weights
        w_pert = estimate_blend_weights(
            ics, horizon_bars=H, grid_turnover=_to({"a": spiked, "b": [0.05] * 8})
        ).weights
        pd.testing.assert_frame_equal(w.iloc[: j + 1], w_pert.iloc[: j + 1], check_exact=True)
        assert not np.allclose(w.iloc[j + 1 :].to_numpy(), w_pert.iloc[j + 1 :].to_numpy()), (
            "rows after j MUST see the realized turnover spike (else the cost leg is inert)"
        )

    def test_turnover_at_last_grid_point_changes_nothing(self) -> None:
        """A turnover printed at the FINAL grid point is not usable anywhere — the
        whole weights frame is identical whether it is 0.05 or 0.95."""
        ics = _ics({"a": [0.10] * 7, "b": [0.10] * 7})
        lo = estimate_blend_weights(
            ics, horizon_bars=H, grid_turnover=_to({"a": [*([0.2] * 6), 0.05], "b": [0.2] * 7})
        ).weights
        hi = estimate_blend_weights(
            ics, horizon_bars=H, grid_turnover=_to({"a": [*([0.2] * 6), 0.95], "b": [0.2] * 7})
        ).weights
        pd.testing.assert_frame_equal(lo, hi, check_exact=True)

    def test_missing_turnover_name_defaults_to_zero_haircut(self) -> None:
        """A factor absent from grid_turnover gets a zero haircut (no cost
        evidence); a present sibling is still haircut."""
        ics = _ics({"a": [0.10] * 8, "b": [0.10] * 8})
        # only "b" has a (high) turnover series; "a" omitted -> no haircut on a
        bw = estimate_blend_weights(ics, horizon_bars=H, grid_turnover=_to({"b": [0.80] * 8}))
        steady = slice(2, None)
        np.testing.assert_allclose(
            bw.net_smoothed_ic["a"].iloc[steady].to_numpy(),
            bw.gross_smoothed_ic["a"].iloc[steady].to_numpy(),
            rtol=1e-12,
        )
        assert (bw.net_smoothed_ic["b"].iloc[steady] < bw.gross_smoothed_ic["b"].iloc[steady]).all()
        assert (bw.weights["a"].iloc[steady] > bw.weights["b"].iloc[steady]).all()

    def test_nan_turnover_is_no_haircut(self) -> None:
        """NaN turnover (no cost evidence yet) contributes zero haircut, never NaN
        weights."""
        ics = _ics({"a": [0.10] * 8, "b": [0.10] * 8})
        bw = estimate_blend_weights(
            ics,
            horizon_bars=H,
            grid_turnover=_to({"a": [float("nan")] * 8, "b": [float("nan")] * 8}),
        )
        assert np.isfinite(bw.weights.to_numpy()).all()
        # all-NaN turnover -> no haircut -> identical to the gross path
        gross = estimate_blend_weights(ics, horizon_bars=H).weights
        pd.testing.assert_frame_equal(bw.weights, gross, check_exact=True)

    def test_lambda_cost_override_scales_the_haircut(self) -> None:
        """A larger λ_cost (or cost_frac) yields a strictly larger haircut → strictly
        smaller weight for the costly factor; λ_cost=0 reproduces gross."""
        ics = _ics({"a": [0.10] * 8, "b": [0.10] * 8})
        turn = _to({"a": [0.10] * 8, "b": [0.60] * 8})
        gross = estimate_blend_weights(ics, horizon_bars=H).weights
        zero_lam = estimate_blend_weights(
            ics, horizon_bars=H, grid_turnover=turn, lambda_cost=0.0
        ).weights
        pd.testing.assert_frame_equal(zero_lam, gross, check_exact=True)
        small = estimate_blend_weights(
            ics, horizon_bars=H, grid_turnover=turn, lambda_cost=100.0
        ).weights
        large = estimate_blend_weights(
            ics, horizon_bars=H, grid_turnover=turn, lambda_cost=400.0
        ).weights
        steady = slice(2, None)
        assert (large["b"].iloc[steady] < small["b"].iloc[steady]).all()

    def test_cold_start_equal_weights_with_turnover(self) -> None:
        """The first grid row (no realized IC nor turnover after the shift) is still
        equal weights even with a turnover map supplied."""
        bw = estimate_blend_weights(
            _ics({"a": [0.4] * 5, "b": [0.1] * 5}),
            horizon_bars=H,
            grid_turnover=_to({"a": [0.2] * 5, "b": [0.7] * 5}),
        )
        np.testing.assert_allclose(bw.weights.iloc[0].to_numpy(), 0.5, rtol=0, atol=0)

    def test_validation_errors(self) -> None:
        ics = _ics({"a": [0.1] * 4, "b": [0.1] * 4})
        with pytest.raises(ValueError, match="cost_frac"):
            estimate_blend_weights(ics, horizon_bars=H, cost_frac=-1.0)
        with pytest.raises(ValueError, match="lambda_cost"):
            estimate_blend_weights(ics, horizon_bars=H, lambda_cost=-1.0)
        with pytest.raises(ValueError, match="absent from grid_ics"):
            estimate_blend_weights(ics, horizon_bars=H, grid_turnover=_to({"ghost": [0.1] * 4}))
        # turnover index must match the IC grid
        bad = {"a": pd.Series([0.1, 0.1], index=_grid(2))}
        with pytest.raises(ValueError, match="index differs"):
            estimate_blend_weights(ics, horizon_bars=H, grid_turnover=bad)

    def test_default_lambda_cost_formula(self) -> None:
        lam = default_lambda_cost()
        np.testing.assert_allclose(lam, 1.0 / (DEFAULT_IC_TARGET * DEFAULT_SIGMA_H_TYP), rtol=1e-12)
        assert 500.0 < lam < 700.0  # ~588 at the documented defaults
        with pytest.raises(ValueError, match="ic_target"):
            default_lambda_cost(ic_target=0.0)
        with pytest.raises(ValueError, match="sigma_h_typ"):
            default_lambda_cost(sigma_h_typ=0.0)


class TestBlendWeightsAuditFrames:
    def test_optional_audit_frames_default_none(self) -> None:
        """Back-compat: BlendWeights can still be built WITHOUT the audit frames
        (legacy callers), and asof() works."""
        row = pd.DataFrame(
            [[0.6, 0.4]], index=pd.Index(np.array([T0], dtype=np.int64)), columns=["a", "b"]
        )
        bw = BlendWeights(alpha_names=("a", "b"), weights=row, smoothed_ic=row)
        assert bw.gross_smoothed_ic is None
        assert bw.net_smoothed_ic is None
        np.testing.assert_allclose(bw.asof(T0).to_numpy(), [0.6, 0.4])

    def test_audit_frame_column_mismatch_raises(self) -> None:
        row = pd.DataFrame(
            [[0.6, 0.4]], index=pd.Index(np.array([T0], dtype=np.int64)), columns=["a", "b"]
        )
        bad = pd.DataFrame(
            [[0.1, 0.2]], index=pd.Index(np.array([T0], dtype=np.int64)), columns=["a", "x"]
        )
        with pytest.raises(ValueError, match="gross_smoothed_ic"):
            BlendWeights(
                alpha_names=("a", "b"), weights=row, smoothed_ic=row, gross_smoothed_ic=bad
            )
