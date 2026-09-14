"""Gross raw-open holding labels with explicit shares and dividend receivables.

Dividends accrue only when held across the ex-date, stay as cash receivables and
are not reinvested. This is terminal economic wealth, not payment-date spendable
cash or a net execution return. It is a new label convention, not Yahoo parity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import exchange_calendars as xcals
import pandas as pd

from alphaforge.validation.trend_observation import ObservationError, session_window
from alphaforge.validation.trend_price_bridge import ActionSnapshot, positive

VERSION = "raw_open_cash_accrual_label_v1"


@dataclass(frozen=True)
class HoldingLabel:
    gross_return: float
    terminal_shares: float
    dividend_receivables: float
    release_ms: int
    mode: str


def holding_label(
    *,
    symbol: str,
    entry_ms: int,
    exit_ms: int,
    entry_open: float,
    exit_open: float,
    snapshot: ActionSnapshot,
    as_of_ms: int,
    mode: str = "PROSPECTIVE",
) -> HoldingLabel:
    """One share bought at entry open, sold at exit open, plus accrued dividends.

    Entry-session actions are excluded because the purchase is already ex-action.
    Exit-session actions are included because the position was held overnight.
    Use calendar t+1 / t+1+h externally; release is at the actual exit-session close.
    No intermediate quote is needed: dividends are not reinvested in this label.
    """
    if mode not in {"PROSPECTIVE", "DIAGNOSTIC_CURRENT_VINTAGE"}:
        raise ObservationError("Explicit supported mode required")
    session_window(entry_ms)
    release, _ = session_window(exit_ms)
    if entry_ms >= exit_ms or type(as_of_ms) is not int or as_of_ms < release:
        raise ObservationError("Positive holding period and matured exit-close required")
    if not positive(entry_open) or not positive(exit_open):
        raise ObservationError("Positive finite raw opens required")
    if (
        snapshot.symbol != symbol
        or snapshot.complete is not True
        or not snapshot.start_ms <= entry_ms < exit_ms < snapshot.end_ms
        or type(snapshot.observed_ms) is not int
        or snapshot.observed_ms <= 0
    ):
        raise ObservationError("Complete symbol/date coverage and receipt required")
    try:
        if len(snapshot.digest) != 64:
            raise ValueError("SHA256 required")
        int(snapshot.digest, 16)
    except (TypeError, ValueError) as exc:
        raise ObservationError("Invalid snapshot digest") from exc
    if mode == "PROSPECTIVE" and snapshot.observed_ms > as_of_ms:
        raise ObservationError("Action snapshot not yet observed")
    ids = set()
    grouped = {}
    for action in snapshot.actions:
        if (
            not action.event_id
            or action.event_id in ids
            or action.symbol != symbol
            or action.kind not in {"split", "dividend"}
            or not positive(action.value)
            or not snapshot.start_ms <= action.session_ms < snapshot.end_ms
        ):
            raise ObservationError("Malformed or duplicated action")
        session_window(action.session_ms)
        ids.add(action.event_id)
        if entry_ms < action.session_ms <= exit_ms:
            grouped.setdefault(action.session_ms, []).append(action)
    shares, receivables = 1.0, 0.0
    for _, actions in sorted(grouped.items()):
        splits = [a for a in actions if a.kind == "split"]
        dividends = [a for a in actions if a.kind == "dividend"]
        if len(splits) > 1 or (splits and dividends):
            raise ObservationError("Ambiguous simultaneous action/share basis")
        if splits:
            shares *= splits[0].value
        receivables += shares * sum(a.value for a in dividends)
    result = (shares * exit_open + receivables) / entry_open - 1
    if not all(math.isfinite(v) for v in [shares, receivables, result]):
        raise ObservationError("Nonfinite holding-period result")
    return HoldingLabel(result, shares, receivables, release, mode)


def label_sessions(decision_ms: int, horizon: int) -> tuple[int, int]:
    """Resolve decision t -> entry t+1, exit t+1+h on XNYS sessions."""
    session_window(decision_ms)
    if type(horizon) is not int or horizon < 1:
        raise ObservationError("Positive integer horizon required")
    cal = xcals.get_calendar("XNYS", start="2000-01-01", end="2030-12-31")
    entry = cal.next_session(pd.Timestamp(decision_ms, unit="ms"))
    end = entry
    for _ in range(horizon):
        end = cal.next_session(end)
    return int(entry.value // 1_000_000), int(end.value // 1_000_000)
