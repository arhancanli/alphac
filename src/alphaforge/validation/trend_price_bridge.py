"""Versioned forward wealth index for diagnostics; Yahoo parity is not assumed.

This extends only signal closes, not execution OHLC, volume, dividends in the
broker ledger, or the existing frozen candidate. Complete provider snapshots
remain caller-supplied evidence, not independent proof of historical publication.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import exchange_calendars as xcals
import pandas as pd

from alphaforge.validation.trend_observation import ObservationError, session_window

VERSION = "forward_close_reinvestment_v1"


@dataclass(frozen=True)
class PriceState:
    symbol: str
    session_ms: int
    raw_close: float
    signal_close: float


@dataclass(frozen=True)
class Action:
    event_id: str
    symbol: str
    session_ms: int
    kind: str  # split: new shares per old; dividend: USD per pre-event share
    value: float


@dataclass(frozen=True)
class ActionSnapshot:
    symbol: str
    start_ms: int
    end_ms: int  # exclusive effective-date coverage
    observed_ms: int
    digest: str
    complete: bool
    actions: tuple[Action, ...]


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def advance_close(
    previous: PriceState,
    *,
    session_ms: int,
    raw_close: float,
    snapshot: ActionSnapshot,
    decision_ms: int,
    mode: str = "PROSPECTIVE",
) -> PriceState:
    """Advance one consecutive session using no actions after the decision.

    I_t = I_prev * (split_new_per_old * P_t + USD_cash_per_old) / P_prev.
    Cash is economically reinvested at the ex-session close for this signal index;
    this is not a claim about actual payment-date cash availability. A simultaneous
    split and dividend is rejected until the vendor's share basis is reconciled.
    DIAGNOSTIC_CURRENT_VINTAGE explicitly allows late receipts; it must never be
    labeled a historical/prospective decision or used to promote the old candidate.
    """
    if mode not in {"PROSPECTIVE", "DIAGNOSTIC_CURRENT_VINTAGE"}:
        raise ObservationError("Explicit supported bridge mode required")
    if not previous.symbol or snapshot.symbol != previous.symbol:
        raise ObservationError("Snapshot symbol mismatch")
    if not all(positive(v) for v in [previous.raw_close, previous.signal_close, raw_close]):
        raise ObservationError("Positive finite raw and signal prices required")
    session_window(previous.session_ms)
    close, next_open = session_window(session_ms)
    cal = xcals.get_calendar("XNYS", start="2000-01-01", end="2030-12-31")
    expected = int(
        cal.next_session(pd.Timestamp(previous.session_ms, unit="ms")).value // 1_000_000
    )
    if session_ms != expected:
        raise ObservationError("Consecutive sessions required; no skipped or repeated action")
    if type(decision_ms) is not int or not close <= decision_ms < next_open:
        raise ObservationError("Decision must fall after close and before next open")
    if (
        snapshot.complete is not True
        or not snapshot.start_ms <= session_ms < snapshot.end_ms
        or type(snapshot.observed_ms) is not int
        or snapshot.observed_ms <= 0
    ):
        raise ObservationError("Complete effective-date coverage and receipt required")
    try:
        if len(snapshot.digest) != 64:
            raise ValueError("SHA256 required")
        int(snapshot.digest, 16)
    except (ValueError, TypeError) as exc:
        raise ObservationError("Invalid snapshot digest") from exc
    if mode == "PROSPECTIVE" and snapshot.observed_ms > decision_ms:
        raise ObservationError("Snapshot first observed after decision")
    ids = set()
    selected = []
    for action in snapshot.actions:
        if (
            not action.event_id
            or action.event_id in ids
            or action.symbol != previous.symbol
            or action.kind not in {"split", "dividend"}
            or not positive(action.value)
            or not snapshot.start_ms <= action.session_ms < snapshot.end_ms
        ):
            raise ObservationError("Malformed, duplicated or out-of-scope action")
        session_window(action.session_ms)
        ids.add(action.event_id)
        if action.session_ms == session_ms:
            selected.append(action)
    splits = [a for a in selected if a.kind == "split"]
    dividends = [a for a in selected if a.kind == "dividend"]
    if len(splits) > 1 or (splits and dividends):
        raise ObservationError("Ambiguous simultaneous action/share basis")
    ratio = splits[0].value if splits else 1.0
    cash = sum(a.value for a in dividends)
    signal = previous.signal_close * (ratio * raw_close + cash) / previous.raw_close
    if not positive(signal):
        raise ObservationError("Nonfinite adjusted result")
    return PriceState(previous.symbol, session_ms, raw_close, signal)
