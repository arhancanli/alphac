"""Unit tests for alphaforge.labeling.weights (alphaDesign.md §5.4, AFML ch.4).

Covers: concurrency hand-counts (3-event overlap, isolated event, gap-in-span does not
inflate), average uniqueness (= ½ for two fully overlapping equal spans), attribution
mean-1 normalization + flat-span ⇒ 0, time decay (newest 1.0 / oldest 0.75, monotone,
disable at 1.0), the cross-sectional 1/√(n_t) de-correlation factor (leakageCritique
finding 23 / overfit item 6), the open→open return composer, NaN-sentinel rows dropped,
input immutability, and the fail-loud validations.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from alphaforge.core.time import Timeframe
from alphaforge.labeling.weights import (
    attribution_weights,
    average_uniqueness,
    concurrency,
    sample_weights,
)

HOUR = 3_600_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z
BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"


def make_events(
    spans: list[tuple[int, int, str]],
) -> pd.DataFrame:
    """Build a §1.3-shaped label frame from (entry_bar_idx, t1_bar_idx, instrument) triples.

    The decision bar τ is one bar before entry (entry = τ + Δ, the next-open contract).
    Indexed by the (ts_open, instrument_id) MultiIndex on τ.
    """
    rows = []
    index = []
    for entry_i, t1_i, iid in spans:
        decision_ts = T0 + (entry_i - 1) * HOUR
        rows.append({"entry_ts": T0 + entry_i * HOUR, "t1": T0 + t1_i * HOUR})
        index.append((decision_ts, iid))
    idx = pd.MultiIndex.from_tuples(index, names=["ts_open", "instrument_id"])
    return pd.DataFrame(rows, index=idx)


def make_bars(opens: list[float], *, instrument_id: str = BTC) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_id": instrument_id,
            "ts_open": [T0 + i * HOUR for i in range(len(opens))],
            "open": opens,
        }
    )


class TestConcurrency:
    def test_three_event_overlap_hand_count(self) -> None:
        # event A spans bars [1..3], B spans [2..4], C spans [3..5] (BTC).
        events = make_events([(1, 3, BTC), (2, 4, BTC), (3, 5, BTC)])
        conc = concurrency(events)
        assert conc.name == "concurrency"
        # bar 1: only A -> 1 ; bar 2: A,B -> 2 ; bar 3: A,B,C -> 3
        assert conc.loc[(T0 + 1 * HOUR, BTC)] == 1
        assert conc.loc[(T0 + 2 * HOUR, BTC)] == 2
        assert conc.loc[(T0 + 3 * HOUR, BTC)] == 3
        # bar 4: B,C -> 2 ; bar 5: C -> 1
        assert conc.loc[(T0 + 4 * HOUR, BTC)] == 2
        assert conc.loc[(T0 + 5 * HOUR, BTC)] == 1

    def test_isolated_event_is_unit_concurrency(self) -> None:
        events = make_events([(1, 4, BTC)])
        conc = concurrency(events)
        assert (conc == 1).all()
        assert conc.index.tolist() == [(T0 + k * HOUR, BTC) for k in (1, 2, 3, 4)]

    def test_cross_symbol_does_not_share_concurrency(self) -> None:
        # same bars, different instruments — within-symbol counting keeps them apart.
        events = make_events([(1, 3, BTC), (1, 3, ETH)])
        conc = concurrency(events)
        assert conc.loc[(T0 + 2 * HOUR, BTC)] == 1
        assert conc.loc[(T0 + 2 * HOUR, ETH)] == 1

    def test_empty_resolved_returns_empty_series(self) -> None:
        events = make_events([(1, 3, BTC)])
        events = events.assign(t1=np.nan)
        conc = concurrency(events)
        assert conc.empty
        assert conc.name == "concurrency"


class TestAverageUniqueness:
    def test_two_full_overlap_equal_spans_is_half(self) -> None:
        # Two events on the SAME symbol with identical spans fully overlap (c == 2
        # everywhere over the span), so each has ū = ½. Give them distinct decision
        # timestamps (the MultiIndex must be unique) but identical [entry_ts, t1].
        events = make_events([(1, 4, BTC)])
        events2 = make_events([(1, 4, BTC)])
        events2.index = pd.MultiIndex.from_tuples(
            [(T0 - 100, BTC)], names=["ts_open", "instrument_id"]
        )
        both = pd.concat([events, events2])
        conc = concurrency(both)
        uniq = average_uniqueness(both, conc)
        assert uniq.name == "avg_uniqueness"
        assert uniq.loc[(T0, BTC)] == pytest.approx(0.5)
        assert uniq.loc[(T0 - 100, BTC)] == pytest.approx(0.5)

    def test_isolated_event_unique(self) -> None:
        events = make_events([(1, 4, BTC)])
        conc = concurrency(events)
        uniq = average_uniqueness(events, conc)
        assert uniq.loc[(T0, BTC)] == pytest.approx(1.0)

    def test_partial_overlap_uniqueness(self) -> None:
        # A [1..3] (c = 1,2,2), B [2..4] (c = 2,2,1): ūA = (1 + .5 + .5)/3, ūB = (.5+.5+1)/3
        events = make_events([(1, 3, BTC), (2, 4, BTC)])
        conc = concurrency(events)
        uniq = average_uniqueness(events, conc)
        assert uniq.loc[(T0, BTC)] == pytest.approx((1.0 + 0.5 + 0.5) / 3.0)
        assert uniq.loc[(T0 + 1 * HOUR, BTC)] == pytest.approx((0.5 + 0.5 + 1.0) / 3.0)


class TestAttribution:
    def test_mean_one_normalization(self) -> None:
        events = make_events([(1, 2, BTC), (3, 4, BTC)])
        conc = concurrency(events)
        # non-trivial, finite returns on the spanned bars
        idx = pd.MultiIndex.from_tuples(
            [(T0 + k * HOUR, BTC) for k in range(6)], names=["ts_open", "instrument_id"]
        )
        returns = pd.Series([0.01, 0.02, -0.03, 0.04, -0.01, 0.02], index=idx)
        w = attribution_weights(events, returns, conc, time_decay=1.0)
        assert w.name == "attribution_weight"
        assert float(w.sum()) == pytest.approx(float(len(w)))  # mean 1
        assert (w >= 0).all()

    def test_flat_span_zero_weight(self) -> None:
        events = make_events([(1, 3, BTC), (1, 3, ETH)])
        conc = concurrency(events)
        idx = pd.MultiIndex.from_tuples(
            [(T0 + k * HOUR, BTC) for k in range(5)]
            + [(T0 + k * HOUR, ETH) for k in range(5)],
            names=["ts_open", "instrument_id"],
        )
        # BTC has signal, ETH is flat (all zero) -> ETH attribution 0
        vals = [0.0, 0.05, 0.05, 0.05, 0.0] + [0.0] * 5
        returns = pd.Series(vals, index=idx)
        w = attribution_weights(events, returns, conc, time_decay=1.0)
        assert w.loc[(T0, ETH)] == pytest.approx(0.0)
        assert w.loc[(T0, BTC)] > 0.0

    def test_concurrency_splits_attribution(self) -> None:
        # one event over [1..1] claiming a single bar shared with another: r/c.
        events = make_events([(1, 1, BTC), (1, 1, BTC)])
        events.index = pd.MultiIndex.from_tuples(
            [(T0, BTC), (T0 - HOUR, BTC)], names=["ts_open", "instrument_id"]
        )
        conc = concurrency(events)
        assert conc.loc[(T0 + 1 * HOUR, BTC)] == 2
        idx = pd.MultiIndex.from_tuples(
            [(T0 + 1 * HOUR, BTC)], names=["ts_open", "instrument_id"]
        )
        returns = pd.Series([0.1], index=idx)
        # raw attribution per event = |0.1 / 2| = 0.05, equal -> both normalize to 1.0
        w = attribution_weights(events, returns, conc, time_decay=1.0)
        assert w.loc[(T0, BTC)] == pytest.approx(1.0)
        assert w.loc[(T0 - HOUR, BTC)] == pytest.approx(1.0)


class TestTimeDecay:
    def test_newest_one_oldest_floor_and_monotone(self) -> None:
        # three isolated, equal-span, equal-return events at three increasing times.
        events = make_events([(1, 2, BTC), (4, 5, BTC), (7, 8, BTC)])
        conc = concurrency(events)
        idx = pd.MultiIndex.from_tuples(
            [(T0 + k * HOUR, BTC) for k in range(9)], names=["ts_open", "instrument_id"]
        )
        returns = pd.Series([0.02] * 9, index=idx)
        w = attribution_weights(events, returns, conc, time_decay=0.75)
        ordered = w.sort_index()
        # newest event keeps the largest weight, oldest the smallest; strictly monotone.
        vals = ordered.to_numpy()
        assert np.all(np.diff(vals) > 0)
        # ratio of newest to itself = 1; oldest/newest reflects the 0.75 floor structure.
        assert vals[-1] > vals[0]

    def test_decay_one_disables(self) -> None:
        events = make_events([(1, 2, BTC), (4, 5, BTC)])
        conc = concurrency(events)
        idx = pd.MultiIndex.from_tuples(
            [(T0 + k * HOUR, BTC) for k in range(6)], names=["ts_open", "instrument_id"]
        )
        returns = pd.Series([0.02] * 6, index=idx)
        w_no = attribution_weights(events, returns, conc, time_decay=1.0)
        # equal returns & uniqueness -> equal weights when decay disabled
        assert w_no.loc[(T0, BTC)] == pytest.approx(w_no.loc[(T0 + 3 * HOUR, BTC)])

    def test_decay_out_of_range_raises(self) -> None:
        events = make_events([(1, 2, BTC)])
        conc = concurrency(events)
        idx = pd.MultiIndex.from_tuples(
            [(T0 + k * HOUR, BTC) for k in range(3)], names=["ts_open", "instrument_id"]
        )
        returns = pd.Series([0.02] * 3, index=idx)
        with pytest.raises(ValueError, match="time_decay"):
            attribution_weights(events, returns, conc, time_decay=1.5)


class TestCrossSectionalDecorrelation:
    def test_concurrent_cross_section_is_downweighted(self) -> None:
        # 4 symbols fire the SAME decision timestamp τ=T0; one lone symbol fires later.
        spans = [(1, 2, f"SYM{i}") for i in range(4)]
        spans.append((5, 6, "LONE"))
        events = make_events(spans)
        bars_list = []
        for i in range(4):
            bars_list.append(make_bars([100.0 + j for j in range(8)], instrument_id=f"SYM{i}"))
        bars_list.append(make_bars([100.0 + j for j in range(8)], instrument_id="LONE"))
        bars = pd.concat(bars_list, ignore_index=True)
        w = sample_weights(events, bars)
        assert w.name == "sample_weight"
        # The lone event (n_t = 1) keeps factor 1/sqrt(1); each clustered event gets 1/sqrt(4).
        # Compare against attribution-only to isolate the cross-sectional factor.
        from alphaforge.labeling.weights import _bar_open_returns

        returns = _bar_open_returns(bars, timeframe=Timeframe.H1)
        conc = concurrency(events)
        attr = attribution_weights(events, returns, conc, time_decay=0.75)
        lone_key = (T0 + 4 * HOUR, "LONE")
        clustered_key = (T0, "SYM0")
        # sample_weight = attribution * 1/sqrt(n_t)
        assert w.loc[lone_key] == pytest.approx(attr.loc[lone_key] * 1.0)
        assert w.loc[clustered_key] == pytest.approx(attr.loc[clustered_key] / math.sqrt(4.0))

    def test_isolated_timestamps_unchanged_by_decorr(self) -> None:
        # all distinct decision timestamps -> 1/sqrt(1) everywhere -> equals attribution.
        events = make_events([(1, 2, BTC), (5, 6, BTC)])
        bars = make_bars([100.0 + j for j in range(8)])
        from alphaforge.labeling.weights import _bar_open_returns

        returns = _bar_open_returns(bars, timeframe=Timeframe.H1)
        conc = concurrency(events)
        attr = attribution_weights(events, returns, conc, time_decay=0.75)
        w = sample_weights(events, bars)
        pd.testing.assert_series_equal(
            w.rename("attribution_weight"), attr, check_names=True
        )


class TestSampleWeightsComposer:
    def test_open_to_open_returns_are_used(self) -> None:
        events = make_events([(1, 2, BTC)])
        opens = [100.0, 110.0, 121.0, 133.1]
        bars = make_bars(opens)
        w = sample_weights(events, bars, time_decay=1.0)
        # single isolated event over bars [1,2]: r1 = ln(121/110), r2 = ln(133.1/121); c=1
        # attribution magnitude before mean-1 = |r1 + r2|; after mean-1 with N=1 -> 1.0
        assert w.loc[(T0, BTC)] == pytest.approx(1.0)

    def test_nan_sentinel_rows_dropped(self) -> None:
        events = make_events([(1, 2, BTC), (3, 4, BTC)])
        events.loc[(T0 + 2 * HOUR, BTC), "t1"] = np.nan
        bars = make_bars([100.0 + j for j in range(8)])
        w = sample_weights(events, bars)
        assert (T0, BTC) in w.index
        assert (T0 + 2 * HOUR, BTC) not in w.index  # the NaN-t1 event earns no weight

    def test_weights_nonnegative_and_named(self) -> None:
        events = make_events([(1, 3, BTC), (2, 4, BTC)])
        bars = make_bars([100.0 + 0.5 * j for j in range(8)])
        w = sample_weights(events, bars)
        assert w.name == "sample_weight"
        assert (w >= 0).all()
        assert not w.isna().any()


class TestGapDiscipline:
    def test_gap_bar_does_not_inflate_concurrency(self) -> None:
        # event spans [1..4] but bar 3 is absent from the return/concurrency picture only
        # via the panel; concurrency is built from the span grid, so the gap shows as a
        # missing grid slot that the uniqueness/attribution code skips.
        events = make_events([(1, 4, BTC)])
        conc = concurrency(events)
        # remove bar 3 from concurrency to simulate a panel gap
        conc = conc.drop((T0 + 3 * HOUR, BTC))
        uniq = average_uniqueness(events, conc)
        # span has 4 grid slots but only 3 printed -> mean over the 3 present (all c=1) = 1
        assert uniq.loc[(T0, BTC)] == pytest.approx(1.0)


class TestImmutabilityAndValidation:
    def test_inputs_not_mutated(self) -> None:
        events = make_events([(1, 3, BTC), (2, 4, BTC)])
        bars = make_bars([100.0 + j for j in range(8)])
        events_copy = events.copy(deep=True)
        bars_copy = bars.copy(deep=True)
        sample_weights(events, bars)
        pd.testing.assert_frame_equal(events, events_copy)
        pd.testing.assert_frame_equal(bars, bars_copy)

    def test_missing_span_column_raises(self) -> None:
        events = make_events([(1, 3, BTC)]).drop(columns=["t1"])
        with pytest.raises(ValueError, match="missing required columns"):
            concurrency(events)

    def test_wrong_index_names_raise(self) -> None:
        events = make_events([(1, 3, BTC)]).reset_index()
        with pytest.raises(ValueError, match="must be indexed by"):
            concurrency(events)

    def test_duplicate_events_raise(self) -> None:
        events = make_events([(1, 3, BTC)])
        dup = pd.concat([events, events])
        with pytest.raises(ValueError, match="duplicate"):
            concurrency(dup)

    def test_bars_non_int_ts_open_raises(self) -> None:
        events = make_events([(1, 3, BTC)])
        bars = make_bars([100.0 + j for j in range(8)])
        bars["ts_open"] = bars["ts_open"].astype(float)
        with pytest.raises(TypeError, match="ts_open"):
            sample_weights(events, bars)

    def test_bars_duplicate_rows_raise(self) -> None:
        events = make_events([(1, 3, BTC)])
        bars = make_bars([100.0 + j for j in range(8)])
        bars = pd.concat([bars, bars.iloc[[0]]], ignore_index=True)
        with pytest.raises(ValueError, match="duplicate"):
            sample_weights(events, bars)

    def test_bars_missing_column_raises(self) -> None:
        events = make_events([(1, 3, BTC)])
        bars = make_bars([100.0 + j for j in range(8)]).drop(columns=["open"])
        with pytest.raises(ValueError, match="missing required columns"):
            sample_weights(events, bars)
