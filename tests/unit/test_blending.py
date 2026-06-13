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
    KAPPA_FLOOR,
    BlendWeights,
    blend,
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
