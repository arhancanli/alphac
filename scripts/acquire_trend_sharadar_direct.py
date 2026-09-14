"""Bounded full-prefix ETF capture; separate current-vintage vendor dataset."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-sharadar-direct-20260912"


def write(name, value):
    with (OUT / name).open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


async def main():
    symbols = json.loads(
        (ROOT / "evidence/alphatrend-history-bridge-20260912/protocol.json").read_text()
    )["symbols"]
    write(
        "protocol.json",
        {
            "start": "2003-01-01",
            "end_inclusive": "2026-09-11",
            "symbols": symbols,
            "tables": ["funds", "actions"],
            "max_requests": 34,
            "concurrency": 3,
            "retries": 0,
            "limit_per_request": 10000,
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "mode": "CURRENT_VINTAGE_ACQUISITION_NOT_HISTORICAL_PIT_PROOF",
            "new_hypotheses": 0,
            "union_hypotheses": 238,
        },
    )
    key = dotenv_values(Path.home() / ".config/alphaforge/sharadar_direct.env")[
        "SHARADAR_API_KEY"
    ].strip()
    semaphore = asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=40, trust_env=False, follow_redirects=False) as client:

        async def fetch(symbol, table):
            stem = table + "_" + symbol
            params = {
                "ticker": symbol,
                "from": "2003-01-01",
                "to": "2026-09-11",
                "format": "csv",
                "sort": "date.asc",
                "limit": 10000,
            }
            async with semaphore:
                receipt = {
                    "symbol": symbol,
                    "table": table,
                    "params": params,
                    "requested_at": datetime.now(UTC).isoformat(),
                }
                try:
                    response = await client.get(
                        "https://api.sharadar.com/v1.0/data/" + table,
                        params={**params, "api_key": key},
                    )
                    (OUT / (stem + ".csv")).write_bytes(response.content)
                    receipt.update(
                        status=response.status_code,
                        received_at=datetime.now(UTC).isoformat(),
                        sha256=hashlib.sha256(response.content).hexdigest(),
                    )
                    if response.status_code != 200:
                        raise ValueError("Non-200 response")
                    frame = pd.read_csv(io.BytesIO(response.content))
                    if not {"ticker", "date"}.issubset(frame.columns):
                        raise ValueError("Missing key columns")
                    if len(frame) >= 10000 or not frame.ticker.eq(symbol).all():
                        raise ValueError("Truncated or wrong-symbol response")
                    dates = pd.to_datetime(frame.date, format="%Y-%m-%d", errors="raise")
                    if not dates.between("2003-01-01", "2026-09-11").all():
                        raise ValueError("Out-of-range dates")
                    if table == "funds" and (
                        frame.empty or frame.duplicated(["ticker", "date"]).any()
                    ):
                        raise ValueError("Missing or duplicate prices")
                    receipt.update(rows=len(frame), complete_response=True)
                    frame.to_parquet(OUT / (stem + ".parquet"), index=False)
                except (httpx.HTTPError, ValueError):
                    receipt["complete_response"] = False
                    receipt["error"] = "REQUEST_OR_VALIDATION_FAILURE"
                write(stem + "_receipt.json", receipt)
                return receipt

        results = await asyncio.gather(
            *(fetch(s, t) for s in symbols for t in ["funds", "actions"])
        )
    result = {
        "responses": results,
        "all_requests_complete": all(r["complete_response"] for r in results),
        "price_rows": sum(r.get("rows", 0) for r in results if r["table"] == "funds"),
        "action_rows": sum(r.get("rows", 0) for r in results if r["table"] == "actions"),
        "runtime_ready": False,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
    }
    write("acquisition.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "responses"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
