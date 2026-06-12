"""Unit tests for alphaforge.labeling.forward_returns (alphaDesign.md §5.1).

Covers: the exact entry/exit arithmetic (entry = open(τ+Δ), exit = open(τ+(1+h)Δ)),
NaN at the panel tail, the gap rule (missing entry OR exit bar → NaN, neighbours
unaffected, never positionally bridged), the price-scale-invariance property
(Hypothesis), vol scaling against an explicit sigma and against the internal EWMA
estimator, input immutability, and the fail-loud validations.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from alphaforge.core.time import Timeframe
from alphaforge.labeling import forward_returns

HOUR = 3_600_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z
BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"


def make_bars(
    opens: list[float],
    *,
    instrument_id: str = BTC,
    skip: set[int] = frozenset(),
    closes: list[float] | None = None,
) -> pd.DataFrame:
    """1h bar panel with ts_open = T0 + i·HOUR; rows in ``skip`` are gaps."""
    rows = [
        {
            "instrument_id": instrument_id,
            "ts_open": T0 + i * HOUR,
            "open": opens[i],
            "close": closes[i] if closes is not None else opens[i],
        }
        for i in range(len(opens))
        if i not in skip
    ]
    return pd.DataFrame(rows)


class TestEntryExitArithmetic:
    def test_exact_hand_computed_values(self) -> None:
        opens = [100.0 + i for i in range(10)]
        out = forward_returns(make_bars(opens), 2)
        assert out.name == "fwd_ret_2"
        # τ = T0 (bar 0): entry = open(bar 1) = 101, exit = open(bar 3) = 103
        assert out.loc[(T0, BTC)] == pytest.approx(math.log(103.0 / 101.0), abs=1e-15)
        # τ = bar 6: entry = open(7) = 107, exit = open(9) = 109 — last computable label
        assert out.loc[(T0 + 6 * HOUR, BTC)] == pytest.approx(math.log(109.0 / 107.0), abs=1e-15)

    def test_tail_bars_without_exit_are_nan(self) -> None:
        out = forward_returns(make_bars([100.0 + i for i in range(10)]), 2)
        # bars 7, 8, 9 need exit bars 10, 11, 12 which never printed
        for i in (7, 8, 9):
            assert math.isnan(out.loc[(T0 + i * HOUR, BTC)])

    def test_one_label_per_input_bar_row_and_sorted_index(self) -> None:
        bars = pd.concat(
            [
                make_bars([100.0 + i for i in range(6)]),
                make_bars([50.0 + i for i in range(6)], instrument_id=ETH),
            ]
        )
        out = forward_returns(bars, 1)
        assert len(out) == 12
        assert out.index.names == ["ts_open", "instrument_id"]
        assert out.index.is_monotonic_increasing
        # per-instrument independence: ETH label uses ETH opens only
        assert out.loc[(T0, ETH)] == pytest.approx(math.log(52.0 / 51.0), abs=1e-15)

    def test_4h_timeframe_uses_4h_bar_arithmetic(self) -> None:
        rows = [
            {
                "instrument_id": BTC,
                "ts_open": T0 + i * 4 * HOUR,
                "open": 100.0 + i,
                "close": 100.0 + i,
            }
            for i in range(5)
        ]
        out = forward_returns(pd.DataFrame(rows), 1, timeframe=Timeframe.H4)
        assert out.loc[(T0, BTC)] == pytest.approx(math.log(102.0 / 101.0), abs=1e-15)


class TestGapDiscipline:
    def test_gap_at_entry_bar_is_nan_neighbours_unaffected(self) -> None:
        opens = [100.0 + i for i in range(10)]
        out = forward_returns(make_bars(opens, skip={4}), 2)
        # τ = bar 3: entry bar 4 missing → NaN (a live system could not have entered)
        assert math.isnan(out.loc[(T0 + 3 * HOUR, BTC)])
        # neighbours that need neither bar 4 as entry nor exit are exact
        assert out.loc[(T0, BTC)] == pytest.approx(math.log(103.0 / 101.0), abs=1e-15)
        assert out.loc[(T0 + 2 * HOUR, BTC)] == pytest.approx(math.log(105.0 / 103.0), abs=1e-15)

    def test_gap_at_exit_bar_is_nan(self) -> None:
        opens = [100.0 + i for i in range(10)]
        out = forward_returns(make_bars(opens, skip={4}), 2)
        # τ = bar 1: exit bar 1+1+2 = 4 missing → NaN
        assert math.isnan(out.loc[(T0 + HOUR, BTC)])

    def test_gaps_are_never_positionally_bridged(self) -> None:
        # If implementation shifted by ROW position instead of ts arithmetic,
        # τ = bar 3 would silently use bar 5 as entry. It must be NaN instead.
        opens = [100.0, 101.0, 102.0, 103.0, 104.0, 999.0, 106.0, 107.0]
        out = forward_returns(make_bars(opens, skip={4}), 1)
        assert math.isnan(out.loc[(T0 + 3 * HOUR, BTC)])
        # and the gap bar itself emits no label row at all
        assert (T0 + 4 * HOUR, BTC) not in out.index


class TestScaleInvarianceProperty:
    @settings(max_examples=50, derandomize=True, deadline=None)
    @given(scale=st.floats(min_value=1e-3, max_value=1e3, allow_nan=False))
    def test_constant_price_rescaling_leaves_log_returns_unchanged(self, scale: float) -> None:
        opens = [100.0, 103.0, 99.0, 105.0, 102.0, 108.0, 101.0, 110.0]
        base = forward_returns(make_bars(opens, skip={5}), 2)
        scaled = forward_returns(make_bars([p * scale for p in opens], skip={5}), 2)
        np.testing.assert_allclose(base.to_numpy(), scaled.to_numpy(), atol=1e-12, equal_nan=True)


class TestVolScaling:
    def test_explicit_vol_divides_by_sigma_sqrt_h(self) -> None:
        opens = [100.0 + i for i in range(10)]
        bars = make_bars(opens)
        raw = forward_returns(bars, 4)
        sigma = pd.Series(0.02, index=raw.index)
        scaled = forward_returns(bars, 4, vol_scaled=True, vol=sigma)
        assert scaled.name == "fwd_ret_4_volscaled"
        np.testing.assert_allclose(
            scaled.to_numpy(),
            raw.to_numpy() / (0.02 * math.sqrt(4.0)),
            atol=1e-12,
            equal_nan=True,
        )

    def test_zero_or_missing_sigma_yields_nan(self) -> None:
        opens = [100.0 + i for i in range(6)]
        bars = make_bars(opens)
        raw = forward_returns(bars, 1)
        sigma = pd.Series(0.02, index=raw.index)
        sigma.iloc[0] = 0.0
        sigma.iloc[1] = np.nan
        scaled = forward_returns(bars, 1, vol_scaled=True, vol=sigma)
        assert math.isnan(scaled.iloc[0])
        assert math.isnan(scaled.iloc[1])
        assert not math.isnan(scaled.iloc[2])

    def test_internal_ewma_sigma_on_constant_drift_panel(self) -> None:
        # closes/opens grow by exactly 1% per bar → every log return is 0.01,
        # so after the 168-bar warmup sigma = 0.01 and y~_h = (0.01·h)/(0.01·√h) = √h.
        n, h = 200, 4
        prices = [100.0 * math.exp(0.01 * i) for i in range(n)]
        bars = make_bars(prices, closes=prices)
        out = forward_returns(bars, h, vol_scaled=True)
        warm = out.iloc[168 : n - (1 + h)]
        np.testing.assert_allclose(warm.to_numpy(), math.sqrt(float(h)), atol=1e-9)
        # before warmup (sigma undefined, min_periods=168) the label is NaN
        assert out.iloc[:168].isna().all()

    def test_vol_scaled_without_close_or_vol_raises(self) -> None:
        bars = make_bars([100.0, 101.0, 102.0]).drop(columns=["close"])
        with pytest.raises(ValueError, match="close"):
            forward_returns(bars, 1, vol_scaled=True)


class TestValidationAndImmutability:
    def test_input_frame_is_not_mutated(self) -> None:
        bars = make_bars([100.0 + i for i in range(8)])
        before = bars.copy(deep=True)
        forward_returns(bars, 2, vol_scaled=True)
        pd.testing.assert_frame_equal(bars, before)

    def test_rejects_bad_horizon(self) -> None:
        with pytest.raises(ValueError, match="horizon_bars"):
            forward_returns(make_bars([100.0, 101.0]), 0)

    def test_rejects_missing_columns(self) -> None:
        with pytest.raises(ValueError, match="missing required columns"):
            forward_returns(pd.DataFrame({"ts_open": [T0]}), 1)

    def test_rejects_non_integer_ts_open(self) -> None:
        bars = make_bars([100.0, 101.0])
        bars = bars.assign(ts_open=pd.to_datetime(bars["ts_open"], unit="ms", utc=True))
        with pytest.raises(TypeError, match="epoch-ms"):
            forward_returns(bars, 1)

    def test_rejects_duplicate_bar_rows(self) -> None:
        bars = pd.concat([make_bars([100.0, 101.0]), make_bars([100.0, 101.0])])
        with pytest.raises(ValueError, match="duplicate"):
            forward_returns(bars, 1)

    def test_rejects_non_positive_prices(self) -> None:
        with pytest.raises(ValueError, match="non-positive"):
            forward_returns(make_bars([100.0, -1.0, 102.0]), 1)
