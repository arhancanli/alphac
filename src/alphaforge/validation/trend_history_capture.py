"""Strict multi-session normalization for acquisition audits, never a price splice."""

from __future__ import annotations

import pandas as pd

from alphaforge.validation.trend_daily_capture import normalize_daily
from alphaforge.validation.trend_observation import ObservationError, session_window


def normalize_history(body: dict, *, sessions: list[int], symbols: list[str]) -> list[dict]:
    if not sessions or sessions != sorted(set(sessions)):
        raise ObservationError("Ordered unique expected sessions required")
    for session in sessions:
        session_window(session)
    if not isinstance(body, dict) or body.get("next_page_token") is not None:
        raise ObservationError("Incomplete paginated history")
    bars = body.get("bars")
    if not isinstance(bars, dict) or set(bars) != set(symbols):
        raise ObservationError("History universe mismatch")
    dates = {pd.Timestamp(s, unit="ms").date(): s for s in sessions}
    grouped = {s: {symbol: [] for symbol in symbols} for s in sessions}
    for symbol, values in bars.items():
        if not isinstance(values, list):
            raise ObservationError("Bar list required")
        for bar in values:
            try:
                stamp = pd.Timestamp(bar["t"])
                if stamp.tzinfo is None:
                    raise ValueError("Timezone required")
                session = dates[stamp.tz_convert("America/New_York").date()]
            except (KeyError, ValueError, TypeError) as exc:
                raise ObservationError("Unexpected history timestamp") from exc
            grouped[session][symbol].append(bar)
    return [
        row
        for s in sessions
        for row in normalize_daily(
            {"bars": grouped[s], "next_page_token": None}, session_ms=s, symbols=symbols
        )
    ]
