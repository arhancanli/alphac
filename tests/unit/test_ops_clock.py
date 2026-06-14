"""Unit tests for :mod:`alphaforge.ops.clock` (offline, no network).

Covers: skew within / at / over threshold (the boundary is inclusive); the signed
skew convention (local ahead => positive); the fake source's fixed and sequence
modes and call counting; the CCXT source dispatch over ``fetch_time`` and the raw
``fapiPublicGetTime`` fallback; and the ``max_skew_ms < 0`` guard. Every exchange
time read comes from an injected fake -- nothing here touches the real network.
"""

from __future__ import annotations

from typing import Any

import pytest

from alphaforge.ops.clock import (
    CCXTExchangeTimeSource,
    ClockCheck,
    ClockSanity,
    ExchangeTimeSource,
    FakeExchangeTimeSource,
)

T0 = 1_700_000_000_000  # an arbitrary epoch-ms anchor


class TestClockSanity:
    def test_zero_skew_is_ok(self) -> None:
        sanity = ClockSanity(FakeExchangeTimeSource(T0), max_skew_ms=2000)
        check = sanity.check(now=T0)
        assert check == ClockCheck(local_ms=T0, exchange_ms=T0, skew_ms=0, ok=True)

    def test_local_ahead_is_positive_skew(self) -> None:
        sanity = ClockSanity(FakeExchangeTimeSource(T0), max_skew_ms=2000)
        check = sanity.check(now=T0 + 1500)
        assert check.skew_ms == 1500
        assert check.ok is True

    def test_local_behind_is_negative_skew(self) -> None:
        sanity = ClockSanity(FakeExchangeTimeSource(T0), max_skew_ms=2000)
        check = sanity.check(now=T0 - 1500)
        assert check.skew_ms == -1500
        assert check.ok is True

    def test_skew_at_threshold_is_ok_inclusive(self) -> None:
        """The boundary is INCLUSIVE: |skew| == max_skew_ms still passes."""
        sanity = ClockSanity(FakeExchangeTimeSource(T0), max_skew_ms=2000)
        assert sanity.check(now=T0 + 2000).ok is True
        assert sanity.check(now=T0 - 2000).ok is True

    def test_skew_one_over_threshold_fails(self) -> None:
        sanity = ClockSanity(FakeExchangeTimeSource(T0), max_skew_ms=2000)
        over = sanity.check(now=T0 + 2001)
        assert over.skew_ms == 2001
        assert over.ok is False
        under = sanity.check(now=T0 - 2001)
        assert under.skew_ms == -2001
        assert under.ok is False

    def test_default_threshold_is_2s(self) -> None:
        sanity = ClockSanity(FakeExchangeTimeSource(T0))
        assert sanity.max_skew_ms == 2000
        assert sanity.check(now=T0 + 2000).ok is True
        assert sanity.check(now=T0 + 2001).ok is False

    def test_negative_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_skew_ms must be >= 0"):
            ClockSanity(FakeExchangeTimeSource(T0), max_skew_ms=-1)

    def test_check_describe_strings(self) -> None:
        sanity = ClockSanity(FakeExchangeTimeSource(T0), max_skew_ms=2000)
        assert "clock ok" in sanity.check(now=T0 + 12).describe()
        assert "+12ms" in sanity.check(now=T0 + 12).describe()
        bad = sanity.check(now=T0 - 5000)
        assert "SKEW ALERT" in bad.describe()
        assert "-5000ms" in bad.describe()

    def test_source_exception_propagates(self) -> None:
        class _Boom:
            def server_time_ms(self) -> int:
                raise RuntimeError("exchange time fetch failed")

        sanity = ClockSanity(_Boom(), max_skew_ms=2000)
        with pytest.raises(RuntimeError, match="exchange time fetch failed"):
            sanity.check(now=T0)


class TestFakeExchangeTimeSource:
    def test_fixed_reading_is_sticky(self) -> None:
        src = FakeExchangeTimeSource(T0)
        assert src.server_time_ms() == T0
        assert src.server_time_ms() == T0
        assert src.call_count == 2

    def test_sequence_advances_then_sticks_on_last(self) -> None:
        src = FakeExchangeTimeSource(sequence=[T0, T0 + 100, T0 + 250])
        assert src.server_time_ms() == T0
        assert src.server_time_ms() == T0 + 100
        assert src.server_time_ms() == T0 + 250
        assert src.server_time_ms() == T0 + 250  # sticky on exhaustion
        assert src.call_count == 4

    def test_requires_exactly_one_mode(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            FakeExchangeTimeSource()
        with pytest.raises(ValueError, match="exactly one"):
            FakeExchangeTimeSource(T0, sequence=[T0])

    def test_empty_sequence_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            FakeExchangeTimeSource(sequence=[])

    def test_satisfies_protocol(self) -> None:
        src: ExchangeTimeSource = FakeExchangeTimeSource(T0)
        assert isinstance(src, ExchangeTimeSource)
        assert src.server_time_ms() == T0


class _FetchTimeClient:
    """ccxt-shaped fake exposing unified ``fetch_time``."""

    def __init__(self, value: int) -> None:
        self._value = value
        self.calls = 0

    def fetch_time(self) -> int:
        self.calls += 1
        return self._value


class _RawTimeClient:
    """ccxt-shaped fake exposing only the raw ``fapiPublicGetTime`` endpoint."""

    def __init__(self, value: int) -> None:
        self._value = value

    def fapiPublicGetTime(self) -> dict[str, Any]:
        return {"serverTime": self._value}


class _NoTimeClient:
    """ccxt-shaped fake exposing neither time endpoint."""


class TestCCXTExchangeTimeSource:
    def test_prefers_fetch_time(self) -> None:
        client = _FetchTimeClient(T0 + 7)
        src = CCXTExchangeTimeSource(client)
        assert src.server_time_ms() == T0 + 7
        assert client.calls == 1

    def test_falls_back_to_raw_endpoint(self) -> None:
        src = CCXTExchangeTimeSource(_RawTimeClient(T0 + 9))
        assert src.server_time_ms() == T0 + 9

    def test_wired_into_clock_sanity(self) -> None:
        sanity = ClockSanity(CCXTExchangeTimeSource(_FetchTimeClient(T0)), max_skew_ms=2000)
        assert sanity.check(now=T0 + 500).ok is True
        assert sanity.check(now=T0 + 5000).ok is False

    def test_no_time_endpoint_raises(self) -> None:
        src = CCXTExchangeTimeSource(_NoTimeClient())
        with pytest.raises(AttributeError, match="neither fetch_time nor fapiPublicGetTime"):
            src.server_time_ms()
