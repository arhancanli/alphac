"""Capture SIP daily inputs for audit; no history splice or producer activation."""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import pandas as pd

from alphaforge.validation.trend_observation import ObservationError, canonical, session_window

ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"


def normalize_daily(body: dict, *, session_ms: int, symbols: list[str]) -> list[dict]:
    """Require one complete raw SIP bar per expected symbol at NY midnight."""
    session_window(session_ms)
    if not symbols or len(set(symbols)) != len(symbols):
        raise ObservationError("Nonempty unique symbol universe required")
    if not isinstance(body, dict) or body.get("next_page_token") is not None:
        raise ObservationError("Incomplete or paginated daily response")
    bars = body.get("bars")
    if not isinstance(bars, dict) or set(bars) != set(symbols):
        raise ObservationError("Daily universe mismatch")
    date = pd.Timestamp(session_ms, unit="ms").date()
    rows = []
    for symbol in sorted(symbols):
        values = bars[symbol]
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
            raise ObservationError("Exactly one bar per symbol required")
        bar = values[0]
        try:
            stamp = pd.Timestamp(bar["t"])
            if stamp.tzinfo is None:
                raise ValueError("Timezone required")
            local = stamp.tz_convert("America/New_York")
            if local.date() != date or local != local.normalize():
                raise ValueError("Session timestamp mismatch")
            o, h, low, c, v = (bar[k] for k in ("o", "h", "l", "c", "v"))
            if not all(type(x) in (float, int) and math.isfinite(x) for x in (o, h, low, c, v)):
                raise ValueError("Nonfinite bar")
            if not (0 < low <= min(o, c) <= max(o, c) <= h and v > 0):
                raise ValueError("Invalid OHLCV")
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise ObservationError("Invalid daily bar") from exc
        rows.append(
            {
                "symbol": symbol,
                "session_ms": session_ms,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": v,
                "vendor_timestamp": bar["t"],
            }
        )
    return rows


async def capture_daily(
    client, directory: Path, *, session_ms: int, symbols: list[str], clock=None
) -> dict:
    """One GET with no redirects/retries; persist bytes before parsing or validation.

    Caller supplies an authenticated httpx client with a bounded timeout and no
    environment proxies. Local times and hashes do not authenticate vendor time.
    Failures remain in the exclusive capture directory. This is acquisition only.
    """
    clock = clock or (lambda: time.time_ns() // 1_000_000)
    close, next_open = session_window(session_ms)
    if (
        not symbols
        or len(set(symbols)) != len(symbols)
        or any(not isinstance(s, str) or not s.isascii() or not s.isalpha() for s in symbols)
    ):
        raise ObservationError("Unique alphabetic symbols required")
    requested = clock()
    if requested < close:
        raise ObservationError("Session has not closed")
    date = pd.Timestamp(session_ms, unit="ms")
    params = {
        "symbols": ",".join(sorted(symbols)),
        "timeframe": "1Day",
        "start": date.strftime("%Y-%m-%dT00:00:00Z"),
        "end": (date + pd.Timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),
        "feed": "sip",
        "adjustment": "raw",
        "limit": 1000,
    }
    directory.mkdir(parents=True, exist_ok=False)

    def save(name, value):
        with (directory / name).open("x") as stream:
            stream.write(canonical(value) + "\n")

    save(
        "request.json",
        {
            "method": "GET",
            "url": ENDPOINT,
            "params": params,
            "requested_ms": requested,
            "session_ms": session_ms,
        },
    )
    try:
        response = await client.get(ENDPOINT, params=params, follow_redirects=False, timeout=8)
        received = clock()
        raw = response.content
        with (directory / "response.bin").open("xb") as stream:
            stream.write(raw)
        save(
            "receipt.json",
            {
                "status": response.status_code,
                "received_ms": received,
                "server_date": response.headers.get("date"),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
        )
        if response.status_code != 200:
            raise ObservationError("Daily endpoint did not return HTTP 200")
        if received < requested:
            raise ObservationError("Local clock moved backwards")
        rows = normalize_daily(json.loads(raw), session_ms=session_ms, symbols=symbols)
        result = {
            "rows": rows,
            "received_ms": received,
            "within_observation_window": close <= requested <= received < next_open,
            "runtime_ready": False,
            "blockers": [
                "HOST_CLOCK_NOT_ATTESTED",
                "HISTORY_CONTINUITY_NOT_VERIFIED",
                "ADJUSTMENT_PARITY_NOT_VERIFIED",
                "PRODUCER_BINDING_PENDING",
            ],
        }
        save("normalized.json", result)
        return result
    except Exception as exc:
        save("failure.json", {"error_type": type(exc).__name__, "runtime_ready": False})
        raise
