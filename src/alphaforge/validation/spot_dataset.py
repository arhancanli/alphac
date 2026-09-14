"""Source-bound close/quote normalization. Never computes signals or returns."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alphaforge.portfolio.spot_restart import DAY_MS, SYMBOLS


def utc_ns(value: str) -> int:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("UTC timestamp required")
    whole, _, fraction = value[:-1].partition(".")
    if len(whole) != 19 or len(fraction) > 9 or (fraction and not fraction.isdigit()):
        raise ValueError("invalid source timestamp")
    stamp = datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    return int(stamp.timestamp()) * 1_000_000_000 + int(fraction.ljust(9, "0") or "0")


def decimal_string(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("exact decimal input required")
    number = Decimal(value)
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValueError("invalid numeric range")
    return str(number)


def bound_response(repo: Path, binding: dict) -> dict:
    path = (repo / binding["raw"]).resolve()
    path.relative_to(repo.resolve())
    if path.stat().st_size > 9_000_000:
        raise ValueError("cache envelope exceeds size limit")
    envelope = json.loads(path.read_text())
    raw = bytes.fromhex(envelope["body_hex"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != envelope["sha256"] or digest != binding["sha256"]:
        raise ValueError("source response hash mismatch")
    if not envelope["query"]["url"].startswith("https://data.alpaca.markets/v1beta3/crypto/us/"):
        raise ValueError("source venue mismatch")
    return {"query": envelope["query"], "data": json.loads(raw, parse_float=Decimal)}


def normalize(repo: Path, coverage: dict) -> dict:
    """Normalize only after the fixed collection is complete.

    Complete intraday OHLC is NOT claimed: a daily close needs an observed
    final hourly interval. Alpaca bars include quote midpoints even at zero
    volume; these are bar prices, not necessarily executed trade prices.
    Unknown historical metadata and receive delays remain explicit assumptions
    for a future registered diagnostic, never admission-quality lineage.
    """
    if coverage.get("status") != "COVERAGE_ONLY_NOT_RETURN_EVALUATION":
        raise ValueError("completed coverage report required")
    start = utc_ns(coverage["start"] + "T00:00:00Z") // 1_000_000
    end = utc_ns(coverage["end"] + "T00:00:00Z") // 1_000_000
    if start > end or (end - start) // DAY_MS > 2000:
        raise ValueError("invalid or oversized evaluation window")
    hourly = {s: {} for s in SYMBOLS}
    for binding in coverage["bar_coverage"]["bindings"]:
        response = bound_response(repo, binding)
        if (
            not response["query"]["url"].endswith("/bars")
            or response["query"]["params"].get("timeframe") != "1Hour"
        ):
            raise ValueError("hourly source query required")
        for symbol, bars in response["data"]["bars"].items():
            if symbol not in hourly:
                raise ValueError("foreign bar symbol")
            for bar in bars:
                ns = utc_ns(bar["t"])
                if ns % 3_600_000_000_000:
                    raise ValueError("hourly bar timestamp misaligned")
                timestamp = ns // 1_000_000
                if timestamp in hourly[symbol]:
                    raise ValueError("duplicate hourly observation")
                hourly[symbol][timestamp] = bar
    closes = {s: [] for s in SYMBOLS}
    missing_final = []
    for day_end in range(start - 199 * DAY_MS, end + 1, DAY_MS):
        for symbol in SYMBOLS:
            bar = hourly[symbol].get(day_end - 3_600_000)
            if bar is None:
                missing_final.append({"symbol": symbol, "end_ms": day_end})
                continue
            volume = decimal_string(bar["v"])
            closes[symbol].append(
                {
                    "end_ms": day_end,
                    "close": decimal_string(bar["c"], positive=True),
                    "volume": volume,
                    "price_semantics": "alpaca_trade_and_quote_midpoint_bar",
                }
            )
    if missing_final:
        raise ValueError(f"missing final-hour close observations: {len(missing_final)}")
    observations = {}
    unavailable = []
    for item in coverage["quotes"]:
        symbol = item["symbol"]
        day_start = utc_ns(item["date"] + "T00:00:00Z") // 1_000_000
        if symbol not in SYMBOLS or not start <= day_start <= end:
            raise ValueError("foreign quote symbol or date")
        key = (day_start, symbol)
        if key in observations:
            raise ValueError("duplicate daily quote")
        observations[key] = None
        if "binding" not in item:
            unavailable.append(
                {"date": item["date"], "symbol": symbol, "reason": "request_unverified"}
            )
            continue
        response = bound_response(repo, item["binding"])
        params = response["query"]["params"]
        if (
            not response["query"]["url"].endswith("/quotes")
            or params.get("symbols") != symbol
            or params.get("sort") != "desc"
            or params.get("limit") != 1
            or params.get("end") != item["date"] + "T00:05:00Z"
            or params.get("start") != item["date"] + "T00:04:00Z"
        ):
            raise ValueError("quote selection differs from fixed query policy")
        rows = response["data"].get("quotes", {}).get(symbol, [])
        if not rows:
            unavailable.append(
                {"date": item["date"], "symbol": symbol, "reason": "no_valuation_quote"}
            )
            continue
        if len(rows) != 1:
            raise ValueError("ambiguous quote selection")
        raw = rows[0]
        decision_ms = day_start + 300_000
        source_ns = utc_ns(raw["t"])
        age_ns = decision_ms * 1_000_000 - source_ns
        if not 0 <= age_ns <= 60_000_000_000:
            raise ValueError("quote outside valuation interval")
        bid, ask = (
            decimal_string(raw["bp"], positive=True),
            decimal_string(raw["ap"], positive=True),
        )
        if Decimal(bid) > Decimal(ask):
            raise ValueError("crossed quote")
        observations[key] = {
            "bid": bid,
            "ask": ask,
            "source_ns": source_ns,
            # Floor is conservative for quote freshness; nanoseconds retained.
            "source_ms": source_ns // 1_000_000,
            "bid_size": decimal_string(raw["bs"]),
            "ask_size": decimal_string(raw["as"]),
        }
    expected = {(day, s) for day in range(start, end + 1, DAY_MS) for s in SYMBOLS}
    if set(observations) != expected:
        raise ValueError("incomplete quote collection grid")
    days = [
        {"decision_ms": day + 300_000, "quotes": {s: observations[(day, s)] for s in SYMBOLS}}
        for day in range(start, end + 1, DAY_MS)
    ]
    return {
        "status": "NORMALIZED_WITH_UNRESOLVED_LINEAGE"
        if not unavailable
        else "VALUATION_DATA_GATED",
        "daily_closes": closes,
        "days": days,
        "unavailable_quotes": unavailable,
        "intraday_gaps": coverage["bar_coverage"]["symbols"],
        "historical_asset_metadata_verified": False,
        "local_receipts_measured": False,
        "returns_computed": False,
        "admission_ready": False,
    }
