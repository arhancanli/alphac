"""Causal daily wealth-coordinate mapping; separate from vendor-adjusted OHLC.

The open coordinate uses the previous close state and effective actions, never
this session's closing price. These are synthetic signal coordinates, not tradable
quotes. Cash distributions are included at ex-session, with reinvestment at close.
"""

from __future__ import annotations

from dataclasses import dataclass

from alphaforge.validation.trend_observation import ObservationError
from alphaforge.validation.trend_price_bridge import (
    ActionSnapshot,
    PriceState,
    advance_close,
    positive,
)

VERSION = "forward_wealth_ohlc_v1"


@dataclass(frozen=True)
class SignalBar:
    state: PriceState
    open: float
    high: float
    low: float
    close: float


def advance_bar(
    previous: PriceState,
    *,
    session_ms: int,
    raw_open: float,
    raw_high: float,
    raw_low: float,
    raw_close: float,
    snapshot: ActionSnapshot,
    decision_ms: int,
    mode: str = "PROSPECTIVE",
) -> SignalBar:
    """Affine wealth mapping for each print, with common pre-session state.

    X(p) = previous_index * (new_shares_per_old * p + cash_per_old) / previous_raw.
    It is intentionally not Yahoo's multiplicative back-adjustment. A new candidate
    identity is required before strategy-return testing with this convention.
    """
    values = [raw_open, raw_high, raw_low, raw_close]
    if not all(positive(v) for v in values) or not (
        raw_low <= min(raw_open, raw_close) <= max(raw_open, raw_close) <= raw_high
    ):
        raise ObservationError("Invalid raw OHLC")
    state = advance_close(
        previous,
        session_ms=session_ms,
        raw_close=raw_close,
        snapshot=snapshot,
        decision_ms=decision_ms,
        mode=mode,
    )
    events = [a for a in snapshot.actions if a.session_ms == session_ms]
    splits = [a for a in events if a.kind == "split"]
    ratio = splits[0].value if splits else 1.0
    cash = sum(a.value for a in events if a.kind == "dividend")

    def transform(price):
        value = previous.signal_close * (ratio * price + cash) / previous.raw_close
        if not positive(value):
            raise ObservationError("Nonfinite synthetic price")
        return value

    return SignalBar(
        state, transform(raw_open), transform(raw_high), transform(raw_low), state.signal_close
    )
