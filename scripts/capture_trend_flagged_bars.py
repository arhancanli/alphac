"""Four bounded raw Polygon daily requests to investigate retained anomalies."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-full-price-panel-20260912/polygon_review"
CASES = [("DBA", "2007-01-08"), ("UUP", "2007-06-20"), ("UUP", "2007-03-15"), ("USO", "2020-04-09")]


async def main():
    OUT.mkdir(exist_ok=False)
    (OUT / "protocol.json").write_text(
        json.dumps(
            {
                "cases": CASES,
                "max_requests": 4,
                "adjusted": False,
                "retries": 0,
                "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "purpose": "read-only anomaly evidence; no source substitution",
            },
            indent=2,
        )
        + "\n"
    )
    key = dotenv_values(Path.home() / ".config/alphaforge/polygon.env")["POLYGON_API_KEY"]
    async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:

        async def fetch(symbol, date):
            receipt = {"symbol": symbol, "date": date}
            name = f"{symbol}_{date}"
            try:
                response = await client.get(
                    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{date}/{date}",
                    params={"adjusted": "false", "sort": "asc", "limit": 10},
                    headers={"Authorization": f"Bearer {key}"},
                )
                (OUT / (name + ".bin")).write_bytes(response.content)
                receipt.update(
                    http_status=response.status_code,
                    sha256=hashlib.sha256(response.content).hexdigest(),
                )
                if response.status_code == 200:
                    payload = response.json()
                    receipt["bars"] = payload.get("results", [])
                    receipt["pagination"] = bool(payload.get("next_url"))
            except (httpx.HTTPError, ValueError) as exc:
                receipt["error_type"] = type(exc).__name__
            receipt["received_at"] = datetime.now(UTC).isoformat()
            (OUT / (name + ".json")).write_text(json.dumps(receipt, indent=2) + "\n")
            return receipt

        results = await asyncio.gather(*(fetch(*case) for case in CASES))
    (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
