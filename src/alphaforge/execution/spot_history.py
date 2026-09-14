"""Bounded authenticated daily-close collection; no signals, returns or activation."""

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from decimal import Decimal

from alphaforge.portfolio.spot_restart import DAY_MS, SYMBOLS, DailyClose
from alphaforge.validation.spot_dataset import decimal_string, utc_ns

ORIGIN = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
HOUR_MS = 3_600_000


def stamp(ms):
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat().replace("+00:00", "Z")


async def collect_daily_history(reader, *, day_end_ms: int):
    """Fetch 200 completed UTC final-hour closes and retain decoded-page receipts.

    Hashes cover canonical decoded JSON, not the original HTTP bytes. Receipts
    establish what this reader observed now, not historical availability times or
    matching execution-account routing. Intraday gaps are disclosed; a missing
    final hourly observation blocks the whole history.
    """
    began_ns, began_mono = time.time_ns(), time.monotonic_ns()
    if (
        type(day_end_ms) is not int
        or day_end_ms % DAY_MS
        or day_end_ms < 200 * DAY_MS
        or day_end_ms > began_ns // 1_000_000
    ):
        raise ValueError("completed UTC day boundary required")
    start = day_end_ms - 200 * DAY_MS
    params = {
        "symbols": ",".join(SYMBOLS),
        "timeframe": "1Hour",
        "start": stamp(start),
        "end": stamp(day_end_ms - 1),
        "sort": "asc",
        "limit": 1000,
    }
    rows = {s: {} for s in SYMBOLS}
    receipts, tokens = [], set()
    async with asyncio.timeout(45):
        for _ in range(64):
            page = await reader._read(ORIGIN, params=dict(params))
            received = time.time_ns()
            if not isinstance(page, dict) or not isinstance(page.get("bars"), dict):
                raise ValueError("invalid historical bar page")
            canonical = json.dumps(
                page, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
            )
            receipts.append(
                {
                    "url": ORIGIN,
                    "params": dict(params),
                    "received_ns": received,
                    "decoded_json": canonical,
                    "decoded_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
                }
            )
            count = 0
            for symbol, bars in page["bars"].items():
                if symbol not in SYMBOLS or not isinstance(bars, list):
                    raise ValueError("foreign or malformed bar series")
                for bar in bars:
                    count += 1
                    ns = utc_ns(bar["t"])
                    ms = ns // 1_000_000
                    if ns % (HOUR_MS * 1_000_000) or not start <= ms < day_end_ms:
                        raise ValueError("bar outside requested completed hourly window")
                    if ms in rows[symbol]:
                        raise ValueError("duplicate bar across pages")
                    close = decimal_string(bar["c"], positive=True)
                    decimal_string(bar["v"])
                    rows[symbol][ms] = close
            if count > 1000 or sum(map(len, rows.values())) > 9600:
                raise ValueError("historical data exceeds query budget")
            token = page.get("next_page_token")
            if token is None:
                break
            if not isinstance(token, str) or not token or len(token) > 4096 or token in tokens:
                raise ValueError("invalid or repeating history pagination token")
            tokens.add(token)
            params["page_token"] = token
        else:
            raise ValueError("history pagination did not exhaust")
    ended_ns, ended_mono = time.time_ns(), time.monotonic_ns()
    if abs((ended_ns - began_ns) - (ended_mono - began_mono)) > 10_000_000:
        raise ValueError("clock discontinuity during history collection")
    histories = {}
    for symbol in SYMBOLS:
        history = []
        for end in range(start + DAY_MS, day_end_ms + 1, DAY_MS):
            close = rows[symbol].get(end - HOUR_MS)
            if close is None:
                raise ValueError("missing completed final-hour close")
            history.append(DailyClose(end, Decimal(close)))
        histories[symbol] = tuple(history)
    packet = {
        "schema": "alphaforge.spot-history-receipt.v1",
        "day_end_ms": day_end_ms,
        "pages": receipts,
        "observed_at_ns": ended_ns,
        "daily_closes": {
            s: [{"end_ms": b.end_ms, "close": str(b.close)} for b in bars]
            for s, bars in histories.items()
        },
        "missing_intraday_hours": {s: 4800 - len(bars) for s, bars in rows.items()},
        "price_semantics": "alpaca_trade_and_quote_midpoint_bar",
        "historical_known_at_verified": False,
        "execution_account_routing_verified": False,
        "clock_accuracy_verified": False,
        "returns_computed": False,
    }
    return histories, packet
