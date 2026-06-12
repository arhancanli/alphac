"""Unit tests for alphaforge.features.cross_section (alphaDesign.md §3).

Covers: hand-computed MAD-winsorization (incl. the MAD==0 quantile fallback),
exact z-scores with the std==0 and min_members NaN rules, rank-to-[-1,1] with
average tie ranks, exact OLS neutralization (linear data → zero residual;
orthogonality), and CSPipeline universe masking — a planted outlier non-member
cannot move members' z-scores, and non-members come back NaN.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from alphaforge.features.cross_section import (
    CSPipeline,
    cs_rank,
    cs_zscore,
    neutralize,
    winsorize_mad,
)

HOUR = 3_600_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z
T1 = T0 + HOUR


def panel(rows: dict[tuple[int, str], float]) -> pd.Series:
    """Build a float panel Series from {(ts_open, instrument_id): value}."""
    index = pd.MultiIndex.from_tuples(list(rows), names=["ts_open", "instrument_id"])
    return pd.Series(list(rows.values()), index=index, dtype=float)


class TestWinsorizeMad:
    def test_hand_computed_clip(self) -> None:
        # med=3, MAD=median(|x-3|)=median([2,1,0,1,97])=1 → bounds 3 ± 5·1.4826·1
        s = panel({(T0, f"I{i}"): v for i, v in enumerate([1.0, 2.0, 3.0, 4.0, 100.0])})
        out = winsorize_mad(s, k=5.0)
        hi = 3.0 + 5.0 * 1.4826 * 1.0
        assert out.iloc[4] == pytest.approx(hi, abs=1e-12)
        assert out.iloc[:4].tolist() == [1.0, 2.0, 3.0, 4.0]  # within bounds: untouched

    def test_mad_zero_falls_back_to_quantile_clip(self) -> None:
        # [5,5,5,5,9]: MAD=0; q99 (linear) = 5 + 0.96·(9-5) = 8.84
        s = panel({(T0, f"I{i}"): v for i, v in enumerate([5.0, 5.0, 5.0, 5.0, 9.0])})
        out = winsorize_mad(s)
        assert out.iloc[4] == pytest.approx(8.84, abs=1e-12)
        assert out.iloc[:4].tolist() == [5.0] * 4

    def test_per_timestamp_independence_and_nan_passthrough(self) -> None:
        s = panel(
            {
                (T0, "A"): 1.0,
                (T0, "B"): 1000.0,
                (T1, "A"): 1000.0,
                (T1, "B"): np.nan,
            }
        )
        out = winsorize_mad(s, k=5.0)
        # T1's lone huge value must not be clipped by T0's stats; NaN stays NaN.
        assert out.loc[(T1, "A")] == 1000.0
        assert math.isnan(out.loc[(T1, "B")])

    def test_rejects_bad_k_and_bad_index(self) -> None:
        s = panel({(T0, "A"): 1.0})
        with pytest.raises(ValueError, match="k must be"):
            winsorize_mad(s, k=0.0)
        with pytest.raises(ValueError, match="MultiIndex"):
            winsorize_mad(pd.Series([1.0], index=[T0]))

    def test_does_not_mutate_input(self) -> None:
        s = panel({(T0, f"I{i}"): v for i, v in enumerate([1.0, 2.0, 3.0, 4.0, 100.0])})
        before = s.copy(deep=True)
        winsorize_mad(s)
        pd.testing.assert_series_equal(s, before)


class TestCsZscore:
    def test_exact_values(self) -> None:
        # mean 3, std(ddof=1)=sqrt(2.5)
        s = panel({(T0, f"I{i}"): float(i + 1) for i in range(5)})
        out = cs_zscore(s)
        sd = math.sqrt(2.5)
        expected = [(v - 3.0) / sd for v in [1.0, 2.0, 3.0, 4.0, 5.0]]
        np.testing.assert_allclose(out.to_numpy(), expected, atol=1e-12)

    def test_zero_std_emits_nan_for_whole_timestamp(self) -> None:
        s = panel({(T0, f"I{i}"): 2.0 for i in range(6)})
        assert cs_zscore(s).isna().all()

    def test_below_min_members_emits_nan(self) -> None:
        s = panel({(T0, f"I{i}"): float(i) for i in range(4)})  # n=4 < 5
        assert cs_zscore(s).isna().all()
        assert not cs_zscore(s, min_members=3).isna().any()

    def test_nan_member_does_not_count_toward_n(self) -> None:
        rows = {(T0, f"I{i}"): float(i) for i in range(5)}
        rows[(T0, "I4")] = np.nan  # 4 finite members < 5
        assert cs_zscore(panel(rows)).isna().all()


class TestCsRank:
    def test_average_tie_ranks_map_to_unit_interval(self) -> None:
        # ranks [1, 2.5, 2.5, 4, 5] → 2(r-1)/4 - 1
        s = panel({(T0, f"I{i}"): v for i, v in enumerate([10.0, 20.0, 20.0, 40.0, 50.0])})
        out = cs_rank(s)
        np.testing.assert_allclose(out.to_numpy(), [-1.0, -0.25, -0.25, 0.5, 1.0], atol=1e-12)

    def test_bounds_and_single_member(self) -> None:
        s = panel({(T0, "A"): 3.0, (T0, "B"): 7.0, (T1, "A"): 42.0})
        out = cs_rank(s)
        assert out.loc[(T0, "A")] == -1.0
        assert out.loc[(T0, "B")] == 1.0
        assert out.loc[(T1, "A")] == 0.0  # lone member → centre

    def test_nan_passthrough(self) -> None:
        s = panel({(T0, "A"): 1.0, (T0, "B"): np.nan, (T0, "C"): 2.0})
        out = cs_rank(s)
        assert math.isnan(out.loc[(T0, "B")])
        assert out.loc[(T0, "A")] == -1.0 and out.loc[(T0, "C")] == 1.0


class TestNeutralize:
    def test_exactly_linear_data_gives_zero_residual(self) -> None:
        beta = panel({(T0, f"I{i}"): b for i, b in enumerate([0.5, 1.0, 1.5, 2.0, 2.5])})
        s = 2.0 + 3.0 * beta  # s is exactly a + b·beta
        out = neutralize(s, beta)
        np.testing.assert_allclose(out.to_numpy(), np.zeros(5), atol=1e-12)

    def test_residual_orthogonal_to_beta_and_mean_zero(self) -> None:
        rng = np.random.default_rng(7)
        betas = rng.normal(size=20)
        values = 1.0 + 2.0 * betas + rng.normal(size=20)
        idx = {(T0, f"I{i}"): float(values[i]) for i in range(20)}
        bdx = {(T0, f"I{i}"): float(betas[i]) for i in range(20)}
        resid = neutralize(panel(idx), panel(bdx)).to_numpy()
        assert abs(resid.sum()) < 1e-10  # intercept removed
        assert abs(resid @ betas) < 1e-10  # beta removed

    def test_nan_rows_and_thin_timestamps_are_nan(self) -> None:
        s = panel({(T0, "A"): 1.0, (T0, "B"): np.nan, (T0, "C"): 3.0, (T1, "A"): 5.0})
        beta = panel({(T0, "A"): 1.0, (T0, "B"): 2.0, (T0, "C"): 3.0, (T1, "A"): 1.0})
        out = neutralize(s, beta)
        assert math.isnan(out.loc[(T0, "B")])
        assert math.isnan(out.loc[(T1, "A")])  # only 1 usable member at T1
        # A and C remain a valid 2-member regression (perfect fit → 0 residual)
        np.testing.assert_allclose([out.loc[(T0, "A")], out.loc[(T0, "C")]], [0.0, 0.0], atol=1e-12)

    def test_constant_beta_reduces_to_demeaning(self) -> None:
        s = panel({(T0, f"I{i}"): float(i) for i in range(5)})
        beta = panel({(T0, f"I{i}"): 1.0 for i in range(5)})
        out = neutralize(s, beta)
        np.testing.assert_allclose(out.to_numpy(), [-2.0, -1.0, 0.0, 1.0, 2.0], atol=1e-12)


class TestCSPipeline:
    @staticmethod
    def members_frame(extra: dict[tuple[int, str], float] | None = None) -> pd.DataFrame:
        rows = {(T0, f"M{i}"): v for i, v in enumerate([1.0, 2.0, 3.0, 4.0, 5.0])}
        if extra:
            rows.update(extra)
        return panel(rows).to_frame("alpha")

    @staticmethod
    def member_mask(index: pd.MultiIndex) -> pd.Series:
        return pd.Series([iid.startswith("M") for _, iid in index], index=index, dtype=bool)

    def test_planted_outlier_non_member_cannot_move_member_zscores(self) -> None:
        pipe = CSPipeline()
        clean = self.members_frame()
        with_outlier = self.members_frame(extra={(T0, "X"): 1e9})
        out_clean = pipe.apply(clean, self.member_mask(clean.index))
        out_dirty = pipe.apply(with_outlier, self.member_mask(with_outlier.index))
        members = [(T0, f"M{i}") for i in range(5)]
        np.testing.assert_allclose(
            out_dirty.loc[members, "alpha"].to_numpy(),
            out_clean.loc[members, "alpha"].to_numpy(),
            atol=1e-12,
        )
        assert math.isnan(out_dirty.loc[(T0, "X"), "alpha"])  # non-member → NaN out

    def test_default_chain_is_winsorize_then_zscore(self) -> None:
        frame = self.members_frame()
        mask = self.member_mask(frame.index)
        expected = cs_zscore(winsorize_mad(frame["alpha"]))
        out = CSPipeline().apply(frame, mask)
        np.testing.assert_allclose(out["alpha"].to_numpy(), expected.to_numpy(), atol=1e-12)

    def test_rows_missing_from_mask_are_fail_closed(self) -> None:
        frame = self.members_frame(extra={(T0, "X"): 50.0})
        members_only = self.member_mask(frame.index)
        partial_mask = members_only[members_only]  # mask omits X entirely
        out = CSPipeline().apply(frame, partial_mask)
        assert math.isnan(out.loc[(T0, "X"), "alpha"])

    def test_neutralize_step_requires_exposures(self) -> None:
        pipe = CSPipeline(steps=("winsorize", "neutralize", "zscore"))
        frame = self.members_frame()
        with pytest.raises(ValueError, match="exposures"):
            pipe.apply(frame, self.member_mask(frame.index))

    def test_neutralize_step_removes_beta(self) -> None:
        frame = self.members_frame()
        mask = self.member_mask(frame.index)
        beta = pd.Series([0.5, 1.0, 1.5, 2.0, 2.5], index=frame.index, dtype=float)
        out = CSPipeline(steps=("neutralize",)).apply(frame, mask, exposures=beta)
        # frame values are exactly linear in beta → residuals are 0
        np.testing.assert_allclose(out["alpha"].to_numpy(), np.zeros(5), atol=1e-12)

    def test_rank_step_and_validation(self) -> None:
        frame = self.members_frame()
        mask = self.member_mask(frame.index)
        out = CSPipeline(steps=("rank",)).apply(frame, mask)
        np.testing.assert_allclose(out["alpha"].to_numpy(), [-1.0, -0.5, 0.0, 0.5, 1.0], atol=1e-12)
        with pytest.raises(ValueError, match="unknown CSPipeline steps"):
            CSPipeline(steps=("zscore", "sparkle"))
        with pytest.raises(ValueError, match="min_members"):
            CSPipeline(min_members=1)

    def test_does_not_mutate_inputs(self) -> None:
        frame = self.members_frame(extra={(T0, "X"): 1e9})
        mask = self.member_mask(frame.index)
        frame_before = frame.copy(deep=True)
        mask_before = mask.copy(deep=True)
        CSPipeline().apply(frame, mask)
        pd.testing.assert_frame_equal(frame, frame_before)
        pd.testing.assert_series_equal(mask, mask_before)
