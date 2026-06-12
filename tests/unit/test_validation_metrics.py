"""Unit tests for alphaforge.validation.metrics (alphaDesign.md §7.2).

Covers: hand-computed Spearman rank IC fixtures (including average tie ranks),
universe masking (a planted extreme non-member cannot move the members' IC),
the min_members NaN rule, the Newey-West HAC t-stat against a fully hand-computed
2-lag example to 1e-12 (plus the lags=0 plain-t reduction), ic_summary fields and
per-year bucketing, and non-overlapping grid subsampling.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from alphaforge.validation import (
    ic_summary,
    newey_west_tstat,
    non_overlapping,
    rank_ic,
)

HOUR = 3_600_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z
T1 = T0 + HOUR

TS_2021 = 1_609_459_200_000  # 2021-01-01T00:00:00Z
TS_2022 = 1_640_995_200_000  # 2022-01-01T00:00:00Z


def panel(rows: dict[tuple[int, str], float]) -> pd.Series:
    index = pd.MultiIndex.from_tuples(list(rows), names=["ts_open", "instrument_id"])
    return pd.Series(list(rows.values()), index=index, dtype=float)


def full_mask(s: pd.Series) -> pd.Series:
    return pd.Series(True, index=s.index)


class TestRankIc:
    def test_hand_computed_spearman_with_ties(self) -> None:
        # factor [1, 2, 2, 4] → ranks [1, 2.5, 2.5, 4]; fwd [10, 30, 20, 40] → [1, 3, 2, 4]
        # Pearson on ranks: Σdxdy = 4.5, Σdx² = 4.5, Σdy² = 5 → 4.5/√22.5
        factor = panel({(T0, f"I{i}"): v for i, v in enumerate([1.0, 2.0, 2.0, 4.0])})
        fwd = panel({(T0, f"I{i}"): v for i, v in enumerate([10.0, 30.0, 20.0, 40.0])})
        out = rank_ic(factor, fwd, full_mask(factor), min_members=4)
        assert out.name == "rank_ic"
        assert out.loc[T0] == pytest.approx(4.5 / math.sqrt(22.5), abs=1e-12)

    def test_perfect_monotone_and_inverted(self) -> None:
        factor = panel({(T0, f"I{i}"): float(i) for i in range(6)})
        fwd_up = panel({(T0, f"I{i}"): math.exp(i) for i in range(6)})  # monotone ↑
        fwd_dn = panel({(T0, f"I{i}"): -math.exp(i) for i in range(6)})  # monotone ↓
        assert rank_ic(factor, fwd_up, full_mask(factor)).loc[T0] == pytest.approx(1.0)
        assert rank_ic(factor, fwd_dn, full_mask(factor)).loc[T0] == pytest.approx(-1.0)

    def test_non_member_outlier_cannot_move_members_ic(self) -> None:
        members = {(T0, f"M{i}"): float(i) for i in range(5)}
        fwd_members = {(T0, f"M{i}"): float([3, 1, 4, 0, 2][i]) for i in range(5)}
        factor = panel({**members, (T0, "X"): 1e9})
        fwd = panel({**fwd_members, (T0, "X"): -1e9})
        mask = pd.Series([iid.startswith("M") for _, iid in factor.index], index=factor.index)
        with_x = rank_ic(factor, fwd, mask)
        without_x = rank_ic(panel(members), panel(fwd_members), full_mask(panel(members)))
        assert with_x.loc[T0] == pytest.approx(without_x.loc[T0], abs=1e-12)

    def test_min_members_emits_nan_not_a_value(self) -> None:
        factor = panel({(T0, f"I{i}"): float(i) for i in range(3)})  # n=3 < 5
        fwd = panel({(T0, f"I{i}"): float(i) for i in range(3)})
        out = rank_ic(factor, fwd, full_mask(factor))
        assert T0 in out.index and math.isnan(out.loc[T0])

    def test_nan_fwd_rows_do_not_count_as_members(self) -> None:
        factor = panel({(T0, f"I{i}"): float(i) for i in range(5)})
        fwd_rows = {(T0, f"I{i}"): float(i) for i in range(5)}
        fwd_rows[(T0, "I4")] = np.nan  # 4 usable < 5
        out = rank_ic(factor, panel(fwd_rows), full_mask(factor))
        assert math.isnan(out.loc[T0])

    def test_rows_absent_from_mask_are_fail_closed(self) -> None:
        factor = panel({(T0, f"I{i}"): float(i) for i in range(5)})
        fwd = panel({(T0, f"I{i}"): float(i) for i in range(5)})
        partial_mask = pd.Series(True, index=factor.index[:4])  # I4 missing → non-member
        assert math.isnan(rank_ic(factor, fwd, partial_mask).loc[T0])

    def test_constant_factor_cross_section_is_nan(self) -> None:
        factor = panel({(T0, f"I{i}"): 1.0 for i in range(5)})
        fwd = panel({(T0, f"I{i}"): float(i) for i in range(5)})
        assert math.isnan(rank_ic(factor, fwd, full_mask(factor)).loc[T0])

    def test_one_entry_per_timestamp_sorted(self) -> None:
        rows = {(t, f"I{i}"): float(i * (1 if t == T0 else -1)) for t in (T1, T0) for i in range(5)}
        factor = panel(rows)
        fwd = panel({k: float(i) for i, k in enumerate(rows)})
        out = rank_ic(factor, fwd, full_mask(factor))
        assert list(out.index) == [T0, T1]


class TestNeweyWestTstat:
    def test_hand_computed_two_lag_example_to_1e12(self) -> None:
        # x = [1..5]: x̄=3, d=[-2,-1,0,1,2]
        # gamma0 = 10/5 = 2; gamma1 = (2+0+0+2)/5 = 0.8; gamma2 = (0-1+0)/5 = -0.2
        # w1 = 2/3, w2 = 1/3 → S = 2 + 2(2/3·0.8 + 1/3·(-0.2)) = 44/15
        # t = 3 / sqrt((44/15)/5)
        x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        expected = 3.0 / math.sqrt((44.0 / 15.0) / 5.0)
        assert newey_west_tstat(x, 2) == pytest.approx(expected, abs=1e-12)

    def test_lags_zero_reduces_to_plain_tstat(self) -> None:
        x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        expected = 3.0 / math.sqrt((10.0 / 5.0) / 5.0)  # mean / sqrt(gamma0/n)
        assert newey_west_tstat(x, 0) == pytest.approx(expected, abs=1e-12)

    def test_nans_are_dropped(self) -> None:
        x = pd.Series([1.0, np.nan, 2.0, 3.0, np.nan, 4.0, 5.0])
        assert newey_west_tstat(x, 2) == pytest.approx(
            newey_west_tstat(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]), 2), abs=1e-15
        )

    def test_degenerate_inputs(self) -> None:
        assert math.isnan(newey_west_tstat(pd.Series([1.0]), 2))  # n < 2
        assert math.isnan(newey_west_tstat(pd.Series([2.0, 2.0, 2.0]), 1))  # zero variance
        with pytest.raises(ValueError, match="lags"):
            newey_west_tstat(pd.Series([1.0, 2.0]), -1)

    def test_lags_beyond_sample_are_capped(self) -> None:
        x = pd.Series([1.0, 2.0, 3.0])
        assert math.isfinite(newey_west_tstat(x, 100))


class TestIcSummary:
    def test_fields_and_by_year_bucketing(self) -> None:
        ic = pd.Series(
            [0.1, 0.2, -0.1, 0.3, np.nan],
            index=pd.Index(
                [TS_2021, TS_2021 + HOUR, TS_2022, TS_2022 + HOUR, TS_2022 + 2 * HOUR],
                name="ts_open",
            ),
        )
        summary = ic_summary(ic, lags=0)
        assert summary.n == 4  # NaN dropped
        assert summary.mean == pytest.approx(0.125, abs=1e-12)
        assert summary.std == pytest.approx(
            float(pd.Series([0.1, 0.2, -0.1, 0.3]).std(ddof=1)), abs=1e-12
        )
        assert summary.hit_rate == pytest.approx(0.75, abs=1e-12)
        assert summary.ic_ir == pytest.approx(summary.mean / summary.std, abs=1e-12)
        assert summary.t_nw == pytest.approx(
            newey_west_tstat(pd.Series([0.1, 0.2, -0.1, 0.3]), 0), abs=1e-12
        )
        assert summary.by_year == {
            2021: pytest.approx(0.15, abs=1e-12),
            2022: pytest.approx(0.1, abs=1e-12),
        }

    def test_empty_series(self) -> None:
        summary = ic_summary(pd.Series([np.nan], index=pd.Index([TS_2021])), lags=3)
        assert summary.n == 0
        assert math.isnan(summary.mean)
        assert summary.by_year == {}


class TestNonOverlapping:
    def test_keeps_every_hth_grid_point(self) -> None:
        ts = [T0 + i * HOUR for i in range(10)]
        s = pd.Series(range(10), index=pd.Index(ts, name="ts_open"), dtype=float)
        out = non_overlapping(s, 3)
        assert list(out.index) == [ts[0], ts[3], ts[6], ts[9]]
        assert out.tolist() == [0.0, 3.0, 6.0, 9.0]

    def test_multiindex_panel_keeps_all_instruments_at_kept_ts(self) -> None:
        rows = {(T0 + i * HOUR, iid): float(i) for i in range(6) for iid in ("A", "B")}
        s = panel(rows)
        out = non_overlapping(s, 2)
        kept_ts = sorted(set(out.index.get_level_values(0)))
        assert kept_ts == [T0, T0 + 2 * HOUR, T0 + 4 * HOUR]
        assert len(out) == 6  # both instruments survive at each kept ts

    def test_grid_is_unique_timestamps_not_row_positions(self) -> None:
        # duplicate timestamps across instruments must count once on the grid
        rows = {(T0 + i * HOUR, iid): 1.0 for i in range(4) for iid in ("A", "B", "C")}
        out = non_overlapping(panel(rows), 2)
        assert sorted(set(out.index.get_level_values(0))) == [T0, T0 + 2 * HOUR]

    def test_h_one_is_identity_and_bad_h_raises(self) -> None:
        s = pd.Series([1.0, 2.0], index=pd.Index([T0, T1]))
        pd.testing.assert_series_equal(non_overlapping(s, 1), s)
        with pytest.raises(ValueError, match="h_bars"):
            non_overlapping(s, 0)
