"""Current-vintage Sharadar action normalization; not historical availability proof."""

from __future__ import annotations

import math

import pandas as pd

from alphaforge.validation.trend_observation import ObservationError, fingerprint, session_window

NORMALIZATION = "sharadar_split_adjusted_dividend_to_raw_v1"


def normalize_actions(actions: pd.DataFrame, *, observed_ms: int) -> pd.DataFrame:
    """Convert source dividend units using all later splits in a complete vintage.

    Caller must establish full subsequent-split coverage through the source price
    vintage. No declaration/available_at timestamp is invented. Lifecycle rows
    remain outside this arithmetic-only output and must be resolved separately.
    """
    if type(observed_ms) is not int or observed_ms <= 0:
        raise ObservationError("Actual observation timestamp required")
    if not {"ticker", "date", "action", "value"}.issubset(actions.columns):
        raise ObservationError("Required source fields absent")
    frame = actions[actions.action.isin(["split", "dividend"])].copy()
    if frame.duplicated(["ticker", "date", "action"]).any():
        raise ObservationError("Ambiguous duplicate action key")
    frame["session_ms"] = (
        pd.to_datetime(frame.date, format="%Y-%m-%d", errors="raise")
        .dt.as_unit("ms")
        .astype("int64")
    )
    for stamp in frame.session_ms.unique():
        session_window(int(stamp))
    if any(not math.isfinite(float(v)) or float(v) <= 0 for v in frame.value):
        raise ObservationError("Positive finite action value required")
    if (frame.groupby(["ticker", "session_ms"]).action.nunique() > 1).any():
        raise ObservationError("Same-session split/dividend basis is ambiguous")
    output = []
    for row in frame.itertuples():
        value = float(row.value)
        later = frame[
            (frame.ticker == row.ticker)
            & (frame.action == "split")
            & (frame.session_ms > row.session_ms)
        ]
        product = math.prod(float(v) for v in later.value) if row.action == "dividend" else 1.0
        raw = value * product
        if not math.isfinite(raw) or raw <= 0:
            raise ObservationError("Invalid normalized amount")
        payload = {
            "symbol": row.ticker,
            "session_ms": int(row.session_ms),
            "kind": row.action,
            "source_value": value,
            "later_split_product": product,
            "raw_value": raw,
            "observed_ms": observed_ms,
            "normalization": NORMALIZATION,
        }
        output.append({**payload, "event_id": fingerprint(payload)})
    return pd.DataFrame(output)
