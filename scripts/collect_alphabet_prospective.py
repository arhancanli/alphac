"""Bounded GET-only quote/borrow observations; explicit feed, no execution clearance."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

SYMBOLS = ("GOOG", "GOOGL")


def quote_diagnostic(quotes, received_at):
    """Age/skew diagnostics only: host clock is not independently calibrated."""
    result = {"execution_eligible": False, "clock_calibrated": False, "valid_pair": False}
    try:
        timestamps = []
        for symbol in SYMBOLS:
            q = quotes[symbol]
            if (
                not all(
                    type(q[k]) in (int, float) and math.isfinite(q[k]) and q[k] > 0
                    for k in ("bp", "ap", "bs", "as")
                )
                or q["bp"] > q["ap"]
            ):
                raise ValueError("Invalid two-sided quote")
            timestamp = datetime.fromisoformat(q["t"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("Naive timestamp")
            timestamps.append(timestamp)
        ages = [(received_at - t).total_seconds() * 1000 for t in timestamps]
        skew = abs((timestamps[0] - timestamps[1]).total_seconds() * 1000)
        result.update(
            quote_age_ms_local=ages,
            pair_source_skew_ms=skew,
            valid_pair=all(0 <= age <= 1000 for age in ages) and skew <= 100,
        )
    except (KeyError, ValueError, TypeError, AttributeError):
        result["reason"] = "MISSING_OR_INVALID_QUOTES"
    return result


def get_evidence(client, url, params=None):
    row = {"requested_at_local": datetime.now(UTC).isoformat(), "method": "GET"}
    started = time.monotonic()
    try:
        response = client.get(url, params=params)
        row.update(
            received_at_local=datetime.now(UTC).isoformat(),
            elapsed_ms=(time.monotonic() - started) * 1000,
            http_status=response.status_code,
            server_date=response.headers.get("date"),
        )
        if response.status_code == 200:
            row["body"] = response.json()
            row["response_sha256"] = hashlib.sha256(response.content).hexdigest()
        else:
            row["error"] = "HTTP_ERROR_BODY_NOT_LOGGED"
    except (httpx.HTTPError, ValueError):
        row["error"] = "REQUEST_FAILED"
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--feed", choices=["sip", "iex"], required=True)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 6:
        raise ValueError("One to six bounded rounds required")
    values = dotenv_values(args.credentials)
    if (
        values.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
        != "https://paper-api.alpaca.markets"
    ):
        raise ValueError("Paper origin required")
    headers = {
        "APCA-API-KEY-ID": values["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": values["APCA_API_SECRET_KEY"],
    }
    args.output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "feed_requested": args.feed,
        "status": "STARTED",
        "orders": 0,
        "locates": 0,
        "max_requests": args.rounds * 3,
        "retries": 0,
        "samples": [],
        "continuous_monitoring": False,
        "purpose": "prospective feasibility only",
    }
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    with httpx.Client(
        headers=headers, timeout=5, follow_redirects=False, trust_env=False
    ) as client:
        for i in range(args.rounds):
            assets = {}
            for symbol in SYMBOLS:
                obs = get_evidence(client, f"https://paper-api.alpaca.markets/v2/assets/{symbol}")
                body = obs.pop("body", {})
                fields = (
                    "symbol",
                    "class",
                    "status",
                    "tradable",
                    "marginable",
                    "shortable",
                    "borrow_status",
                )
                obs["asset"] = {k: body.get(k) for k in fields} if isinstance(body, dict) else {}
                obs["identity_verified"] = (
                    obs["asset"].get("symbol") == symbol
                    and obs["asset"].get("class") == "us_equity"
                )
                assets[symbol] = obs
            quote = get_evidence(
                client,
                "https://data.alpaca.markets/v2/stocks/quotes/latest",
                {"symbols": ",".join(SYMBOLS), "feed": args.feed, "currency": "USD"},
            )
            body = quote.pop("body", {})
            quotes = body.get("quotes", {}) if isinstance(body, dict) else {}
            sample = {
                "assets": assets,
                "quote_request": quote,
                "feed_requested": args.feed,
                "quotes": quotes,
                "diagnostic": quote_diagnostic(quotes, datetime.now(UTC)),
                "execution_eligible": False,
                "limitations": [
                    "asset requests are sequential, not an atomic snapshot",
                    "borrow event timestamps and host clock calibration unavailable",
                    "no trade decision, SSR verification or fill simulation",
                ],
            }
            raw = json.dumps(sample, indent=2, allow_nan=False).encode()
            name = f"sample-{i:02d}.json"
            (args.output / name).write_bytes(raw)
            receipt["samples"].append(
                {
                    "path": name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "quote_http_status": quote.get("http_status"),
                    "quote_diagnostic_pass": sample["diagnostic"]["valid_pair"],
                }
            )
            (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            # Do not repeat denied requests or silently substitute a different feed.
            if quote.get("http_status") in (401, 403, 429):
                receipt["status"] = "STOPPED_FEED_ACCESS_OR_RATE_LIMIT"
                break
            if i + 1 < args.rounds:
                time.sleep(2)
        else:
            receipt["status"] = "BOUNDED_COLLECTION_COMPLETE"
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
