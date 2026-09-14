"""Bounded reference capture; receipt time is never replaced by declaration date."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphamax-payment-source-full-20260913"


def write(name, value):
    with (OUT / name).open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


async def main():
    protocol=json.loads((OUT/'protocol.json').read_text())
    symbols=protocol['request_symbols']
    key = dotenv_values(Path.home() / ".config/alphaforge/polygon.env")["POLYGON_API_KEY"]
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False) as client:

        async def get(symbol, kind):
            field = "execution_date" if kind == "splits" else "ex_dividend_date"
            params = {
                "ticker": symbol,
                field + ".gte": "2022-01-01",
                field + ".lte": "2026-06-01",
                "limit": 1000,
            }
            name = symbol + "_" + kind
            async with sem:
                write(
                    name + "_request.json",
                    {
                        "path": "/v3/reference/" + kind,
                        "params": params,
                        "requested_at_local": datetime.now(UTC).isoformat(),
                    },
                )
                try:
                    response = await client.get(
                        "https://api.polygon.io/v3/reference/" + kind,
                        params={**params, "apiKey": key},
                    )
                    received = datetime.now(UTC).isoformat()
                    (OUT / (name + ".bin")).write_bytes(response.content)
                    receipt = {
                        "symbol": symbol,
                        "kind": kind,
                        "http_status": response.status_code,
                        "received_at_local": received,
                        "server_date": response.headers.get("date"),
                        "sha256": hashlib.sha256(response.content).hexdigest(),
                    }
                    write(name + "_receipt.json", receipt)
                    if response.status_code != 200:
                        return {**receipt, "complete": False}
                    body = response.json()
                    rows = body.get("results")
                    complete = (
                        body.get("status") == "OK"
                        and isinstance(rows, list)
                        and not body.get("next_url")
                    )
                    return {
                        **receipt,
                        "complete": complete,
                        "records": len(rows) if isinstance(rows, list) else None,
                    }
                except (httpx.HTTPError, ValueError):
                    result = {
                        "symbol": symbol,
                        "kind": kind,
                        "complete": False,
                        "error": "REQUEST_OR_PARSE_FAILURE",
                    }
                    write(name + "_failure.json", result)
                    return result

        results = await asyncio.gather(
            *(get(s, k) for s in symbols for k in ["dividends"])
        )
    write(
        "result.json",
        {"receipts": results, "runtime_ready": False, "historical_publication_time_proven": False},
    )
    print(
        json.dumps(
            {
                "requests": len(results),
                "complete": sum(r["complete"] for r in results),
                "records": sum(r.get("records") or 0 for r in results),
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
