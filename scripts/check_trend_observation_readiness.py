"""Bounded GET-only 17-ETF readiness observations; no orders or epoch activation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import exchange_calendars as xcals
import httpx
import pandas as pd
from dotenv import dotenv_values

from alphaforge.execution.spot_clock import ClockBlocked, check_host_clock

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-observation-readiness-20260912"
BASE = ROOT / "artifacts/analysis/alphatrend_causal_continuous_20260912"


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_bar(bar, session):
    try:
        if pd.Timestamp(bar["t"]).date() != pd.Timestamp(session).date():
            return False
        o, h, low, c, v = (bar[k] for k in ("o", "h", "l", "c", "v"))
        return all(type(x) in (int, float) and math.isfinite(x) for x in (o, h, low, c, v)) and (
            0 < low <= min(o, c) <= max(o, c) <= h and v > 0
        )
    except (ValueError, TypeError, KeyError):
        return False


async def main():
    OUT.mkdir(exist_ok=False)
    config = json.loads((BASE / "candidate/reservation.json").read_text())["trial_config"]
    symbols = [iid.split(":")[-1].removesuffix("USD") for iid in config["instrument_ids"]]
    now = pd.Timestamp.now(tz="UTC")
    cal = xcals.get_calendar("XNYS", start="2000-01-01", end="2030-12-31")
    recent = cal.sessions_in_range((now - pd.Timedelta(days=10)).date(), now.date())
    session = next(s for s in reversed(recent) if cal.session_close(s) < now)
    write(
        OUT / "protocol.json",
        {
            "scope": "BOUNDED_READ_ONLY_OBSERVATION_FEASIBILITY",
            "candidate_id": "59901461092dd7a6",
            "symbols": symbols,
            "latest_completed_session": str(session.date()),
            "started_at": now.isoformat(),
            "methods": ["GET"],
            "max_http_requests": 20,
            "retries": 0,
            "feeds": ["sip"],
            "feed_substitution": False,
            "clock": "One bounded read-only SNTP sample; no clock adjustment",
            "orders": 0,
            "epoch_activation": False,
            "bindings": {
                str(p.relative_to(ROOT)): sha(p)
                for p in [
                    Path(__file__),
                    BASE / "candidate/reservation.json",
                    ROOT / "src/alphaforge/execution/spot_clock.py",
                ]
            },
        },
    )
    try:
        clock = await check_host_clock()
    except ClockBlocked as e:
        clock = {"status": "CLOCK_NOT_VERIFIED", "reason": str(e), "clock_adjusted": False}
    clock["received_at_local"] = datetime.now(UTC).isoformat()
    write(OUT / "clock.json", clock)
    values = dotenv_values(Path.home() / ".config/alphaforge/alpaca_equity.env")
    if (
        values.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
        != "https://paper-api.alpaca.markets"
    ):
        raise ValueError("Paper origin required")
    headers = {
        "APCA-API-KEY-ID": values["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": values["APCA_API_SECRET_KEY"],
    }
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(
        headers=headers, timeout=8, follow_redirects=False, trust_env=False
    ) as client:

        async def get(name, url, params=None):
            async with sem:
                row = {"method": "GET", "requested_at_local": datetime.now(UTC).isoformat()}
                started = time.monotonic()
                try:
                    response = await client.get(url, params=params)
                    row.update(
                        http_status=response.status_code,
                        received_at_local=datetime.now(UTC).isoformat(),
                        elapsed_ms=(time.monotonic() - started) * 1000,
                        server_date=response.headers.get("date"),
                        response_sha256=hashlib.sha256(response.content).hexdigest(),
                    )
                    if response.status_code == 200:
                        body = response.json()
                        if name.startswith("asset_"):
                            keys = [
                                "symbol",
                                "class",
                                "exchange",
                                "status",
                                "tradable",
                                "marginable",
                                "shortable",
                                "easy_to_borrow",
                                "borrow_status",
                            ]
                            body = {k: body.get(k) for k in keys}
                        row["body"] = body
                    else:
                        row["error"] = "HTTP_ERROR_BODY_WITHHELD"
                except (httpx.HTTPError, ValueError):
                    row["error"] = "REQUEST_FAILED_OR_INVALID_JSON"
                write(OUT / f"{name}.json", row)
                return row

        requests = [
            (f"asset_{s}", f"https://paper-api.alpaca.markets/v2/assets/{s}", None) for s in symbols
        ]
        requests += [
            ("market_clock", "https://paper-api.alpaca.markets/v2/clock", None),
            (
                "sip_daily_bars",
                "https://data.alpaca.markets/v2/stocks/bars",
                {
                    "symbols": ",".join(symbols),
                    "timeframe": "1Day",
                    "start": session.strftime("%Y-%m-%dT00:00:00Z"),
                    "end": (session + pd.Timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),
                    "feed": "sip",
                    "adjustment": "raw",
                    "limit": 1000,
                },
            ),
            (
                "sip_latest_quotes",
                "https://data.alpaca.markets/v2/stocks/quotes/latest",
                {"symbols": ",".join(symbols), "feed": "sip"},
            ),
        ]
        rows = await asyncio.gather(*(get(*r) for r in requests))
    byname = dict(zip([r[0] for r in requests], rows, strict=True))
    assets = {}
    for s in symbols:
        row = byname[f"asset_{s}"]
        body = row.get("body", {})
        assets[s] = {
            "http_status": row.get("http_status"),
            "identity_verified": body.get("symbol") == s and body.get("class") == "us_equity",
            "tradable": body.get("tradable"),
            "status": body.get("status"),
            "shortable": body.get("shortable"),
            "easy_to_borrow": body.get("easy_to_borrow"),
            "borrow_status": body.get("borrow_status"),
            "dated_locate_or_availability_proof": False,
        }
    bars = byname["sip_daily_bars"].get("body", {})
    coverage = {
        s: len(bars.get("bars", {}).get(s, [])) == 1 and valid_bar(bars["bars"][s][0], session)
        for s in symbols
    }
    write(
        OUT / "result.json",
        {
            "candidate_id": "59901461092dd7a6",
            "clock": clock,
            "http_status_counts": {
                str(code): sum(r.get("http_status") == code for r in rows)
                for code in sorted({r.get("http_status", 0) for r in rows})
            },
            "assets": assets,
            "daily_bar_valid": coverage,
            "daily_bar_pagination_complete": not bars.get("next_page_token"),
            "sip_daily_status": byname["sip_daily_bars"].get("http_status"),
            "sip_latest_quote_status": byname["sip_latest_quotes"].get("http_status"),
            "market_clock": byname["market_clock"].get("body"),
            "runtime_ready": False,
            "orders": 0,
            "requests_sent": len(requests),
            "unresolved": [
                "Provider-history adjustment parity and full causal prefix are not verified",
                "Corrected journal binding missing; legacy recorder pins old candidate",
                "No producer, continuous runtime state recovery or independent timestamp evidence",
                "Asset flags lack dated borrow capacity; latest quotes are not fills",
            ],
            "new_return_trials": 0,
        },
    )
    print(
        json.dumps(
            {
                "clock": clock["status"],
                "bar_coverage": sum(coverage.values()),
                "asset_identities": sum(a["identity_verified"] for a in assets.values()),
                "sip_daily": byname["sip_daily_bars"].get("http_status"),
                "sip_quotes": byname["sip_latest_quotes"].get("http_status"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
