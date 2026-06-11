"""Unit tests for alphaforge.core.calendar — merged calendar, funding schedule, registry."""

from __future__ import annotations

import pytest

from alphaforge.core import time as core_time
from alphaforge.core.calendar import Always24x7Calendar, TradingCalendar, calendar_for
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass

H1 = Timeframe.H1
H4 = Timeframe.H4
D1 = Timeframe.D1

HOUR_MS = 3_600_000
DAY_MS = 86_400_000

# 2024-01-02T00:00:00Z — a UTC midnight, aligned to every funding interval.
T0 = 1_704_153_600_000

CAL = Always24x7Calendar()


class TestPeriodsPerYear:
    def test_h1_is_8760(self) -> None:
        assert CAL.periods_per_year(H1) == 8760.0

    def test_h4_is_2190(self) -> None:
        assert CAL.periods_per_year(H4) == 2190.0

    def test_d1_is_365(self) -> None:
        assert CAL.periods_per_year(D1) == 365.0

    def test_matches_timeframe_bars_per_year(self) -> None:
        for tf in Timeframe:
            assert CAL.periods_per_year(tf) == tf.bars_per_year


class TestIsSession:
    def test_always_true(self) -> None:
        # Epoch, a weekday midnight, a Saturday (2024-01-06), an unaligned instant.
        for ts in (0, T0, T0 + 4 * DAY_MS, T0 + 12_345_678):
            assert CAL.is_session(ts) is True


class TestBarArithmeticDelegation:
    def test_floor_bar_matches_core_time(self) -> None:
        ts = T0 + 5 * HOUR_MS + 17
        assert CAL.floor_bar(ts, H1) == core_time.floor_bar(ts, H1) == T0 + 5 * HOUR_MS
        assert CAL.floor_bar(ts, H4) == core_time.floor_bar(ts, H4) == T0 + 4 * HOUR_MS
        assert CAL.floor_bar(ts, D1) == core_time.floor_bar(ts, D1) == T0

    def test_next_bar_open_matches_core_time(self) -> None:
        ts = T0 + 5 * HOUR_MS + 17
        assert CAL.next_bar_open(ts, H1) == core_time.next_bar_open(ts, H1) == T0 + 6 * HOUR_MS
        assert CAL.next_bar_open(T0, D1) == T0 + DAY_MS

    def test_expected_bar_opens_matches_core_time(self) -> None:
        start, end = T0 - 2 * HOUR_MS, T0 + 3 * HOUR_MS
        opens = CAL.expected_bar_opens(start, end, H1)
        assert opens == core_time.expected_bar_opens(start, end, H1)
        assert opens == [T0 + k * HOUR_MS for k in range(-2, 3)]

    def test_expected_bar_opens_empty_range(self) -> None:
        assert CAL.expected_bar_opens(T0, T0, H1) == []


class TestFundingEvents:
    def test_8h_across_day_boundary(self) -> None:
        # [2024-01-01T20:00Z, 2024-01-02T10:00Z) -> settlements at 00:00 and 08:00.
        events = CAL.funding_events_in(T0 - 4 * HOUR_MS, T0 + 10 * HOUR_MS, 8)
        assert events == [T0, T0 + 8 * HOUR_MS]

    def test_4h_across_day_boundary(self) -> None:
        # Same window -> 20:00 (Jan 1), 00:00, 04:00, 08:00 (Jan 2).
        events = CAL.funding_events_in(T0 - 4 * HOUR_MS, T0 + 10 * HOUR_MS, 4)
        assert events == [T0 - 4 * HOUR_MS, T0, T0 + 4 * HOUR_MS, T0 + 8 * HOUR_MS]

    def test_1h_is_hourly(self) -> None:
        events = CAL.funding_events_in(T0 - 4 * HOUR_MS, T0 + 10 * HOUR_MS, 1)
        assert events == [T0 + k * HOUR_MS for k in range(-4, 10)]

    def test_8h_full_day_pattern(self) -> None:
        # One UTC day of 8h funding -> exactly 00:00, 08:00, 16:00.
        events = CAL.funding_events_in(T0, T0 + DAY_MS, 8)
        assert events == [T0, T0 + 8 * HOUR_MS, T0 + 16 * HOUR_MS]

    def test_start_inclusive(self) -> None:
        assert CAL.funding_events_in(T0, T0 + 1, 8) == [T0]

    def test_end_exclusive(self) -> None:
        assert CAL.funding_events_in(T0 - 8 * HOUR_MS, T0, 8) == [T0 - 8 * HOUR_MS]

    def test_unaligned_start_skips_just_passed_event(self) -> None:
        assert CAL.funding_events_in(T0 + 1, T0 + 8 * HOUR_MS + 1, 8) == [T0 + 8 * HOUR_MS]

    def test_empty_when_no_event_in_range(self) -> None:
        assert CAL.funding_events_in(T0, T0, 8) == []
        assert CAL.funding_events_in(T0 + 1, T0 + 2, 8) == []

    def test_interval_24h_is_daily(self) -> None:
        assert CAL.funding_events_in(T0, T0 + 2 * DAY_MS, 24) == [T0, T0 + DAY_MS]

    @pytest.mark.parametrize("bad_hours", [0, -8, 5, 7, 9, 48])
    def test_invalid_interval_raises(self, bad_hours: int) -> None:
        with pytest.raises(ValueError, match="divisor of 24"):
            CAL.funding_events_in(T0, T0 + DAY_MS, bad_hours)


class TestCalendarFor:
    def test_crypto_perp_is_24x7(self) -> None:
        cal = calendar_for(AssetClass.CRYPTO_PERP)
        assert isinstance(cal, Always24x7Calendar)
        assert isinstance(cal, TradingCalendar)

    def test_crypto_spot_is_24x7(self) -> None:
        assert isinstance(calendar_for(AssetClass.CRYPTO_SPOT), Always24x7Calendar)

    def test_shared_singleton(self) -> None:
        assert calendar_for(AssetClass.CRYPTO_PERP) is calendar_for(AssetClass.CRYPTO_SPOT)

    def test_equity_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="equity"):
            calendar_for(AssetClass.EQUITY)
