"""Bounded, resumable market-data collection. Computes coverage only, never returns.

Fixed window and query policy are declared before fetching. Existing paper
credentials supply market-data read access only; no trading endpoint is called.
"""

import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from alphaforge.execution.spot_paper import PaperCredentials

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/spot-coverage"
START = date(2024, 1, 1)
END = date(2026, 9, 10)
SYMBOLS = ("BTC/USD", "ETH/USD")
ORIGIN = "https://data.alpaca.markets/v1beta3/crypto/us/"


def iso(day):
    return day.isoformat() + "T00:00:00Z"


def timestamp_ns(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("UTC source timestamp required")
    whole, _, fraction = value[:-1].partition(".")
    if len(fraction) > 9 or (fraction and not fraction.isdigit()):
        raise ValueError("invalid timestamp precision")
    dt = datetime.fromisoformat(whole).replace(tzinfo=UTC)
    return int(dt.timestamp()) * 1_000_000_000 + int(fraction.ljust(9, "0") or "0")


class Collector:
    def __init__(self, client):
        self.client = client
        self.requests = 0
        self.cache_hits = 0
        self.lock = asyncio.Lock()
        self.last_start = 0

    async def get(self, kind, params):
        query = {"url": ORIGIN + kind, "params": params}
        key = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
        path = OUT / "raw" / (key + ".json")
        if path.is_file():
            record = json.loads(path.read_text())
            raw = bytes.fromhex(record["body_hex"])
            if record["query"] != query or hashlib.sha256(raw).hexdigest() != record["sha256"]:
                raise ValueError("cached response hash mismatch")
            self.cache_hits += 1
            return json.loads(raw), {"raw": str(path.relative_to(ROOT)), "sha256": record["sha256"]}
        async with self.lock:
            loop = asyncio.get_running_loop()
            await asyncio.sleep(max(0, self.last_start + 0.35 - loop.time()))
            self.last_start = loop.time()
            self.requests += 1
            if self.requests > 2700:
                raise ValueError("request budget exhausted")
        async with asyncio.timeout(8):
            async with self.client.stream("GET", ORIGIN + kind, params=params) as response:
                if response.status_code != 200:
                    raise ValueError(f"data HTTP {response.status_code}")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 4_194_304:
                        raise ValueError("response size budget exhausted")
        data = json.loads(raw)
        record = {
            "query": query,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "body_hex": raw.hex(),
            "observed_at": datetime.now(UTC).isoformat(),
        }
        with path.open("x") as handle:
            json.dump(record, handle)
        return data, {"raw": str(path.relative_to(ROOT)), "sha256": record["sha256"]}

    async def bars(self):
        params = {
            "symbols": ",".join(SYMBOLS),
            "timeframe": "1Hour",
            "start": iso(START - timedelta(days=200)),
            "end": (
                datetime.combine(END, datetime.min.time(), UTC) - timedelta(seconds=1)
            ).isoformat(),
            "limit": 10000,
            "sort": "asc",
        }
        times = {s: set() for s in SYMBOLS}
        bindings = []
        seen = set()
        duplicates = dict.fromkeys(SYMBOLS, 0)
        for page in range(400):
            data, binding = await self.get("bars", params)
            bindings.append(binding)
            if page % 40 == 0:
                print(json.dumps({"bar_pages_read": page + 1}), flush=True)
            for symbol, rows in data["bars"].items():
                if symbol not in times:
                    raise ValueError("foreign bar symbol")
                for row in rows:
                    ts = timestamp_ns(row["t"])
                    if ts in times[symbol]:
                        duplicates[symbol] += 1
                    times[symbol].add(ts)
            token = data.get("next_page_token")
            if not token:
                break
            if token in seen:
                raise ValueError("pagination cycle")
            seen.add(token)
            params = {**params, "page_token": token}
        else:
            raise ValueError("bar pagination budget exhausted")
        first = timestamp_ns(iso(START - timedelta(days=200)))
        end = timestamp_ns(iso(END))
        expected = set(range(first, end, 3_600_000_000_000))
        return {
            "bindings": bindings,
            "expected_hourly_rows_per_symbol": len(expected),
            "symbols": {
                s: {
                    "rows": len(times[s]),
                    "missing_hours": len(expected - times[s]),
                    "unexpected_hours": len(times[s] - expected),
                    "duplicate_hours": duplicates[s],
                }
                for s in SYMBOLS
            },
        }

    async def quote(self, day, symbol):
        decision = day.isoformat() + "T00:05:00Z"
        params = {
            "symbols": symbol,
            "start": day.isoformat() + "T00:04:00Z",
            "end": decision,
            "sort": "desc",
            "limit": 1,
        }
        row = {"date": day.isoformat(), "symbol": symbol}
        try:
            data, binding = await self.get("quotes", params)
            quotes = data.get("quotes", {}).get(symbol, [])
            if len(quotes) > 1:
                raise ValueError("quote query returned too many rows")
            row["binding"] = binding
            if not quotes:
                row["status"] = "MISSING_IN_PREDECISION_MINUTE"
            else:
                age_ns = timestamp_ns(decision) - timestamp_ns(quotes[0]["t"])
                row.update(
                    age_ns=age_ns,
                    status="SOURCE_AGE_WITHIN_ONE_SECOND"
                    if 0 <= age_ns <= 1_000_000_000
                    else "SOURCE_AGE_OUTSIDE_ONE_SECOND",
                )
        except (ValueError, KeyError, TypeError, httpx.HTTPError, TimeoutError) as error:
            row.update(status="UNVERIFIED_ERROR", error_class=type(error).__name__)
        return row


async def main():
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    credentials = PaperCredentials.from_file(Path.home() / ".config/alphaforge/alpaca.env")
    async with httpx.AsyncClient(
        headers={"APCA-API-KEY-ID": credentials.key, "APCA-API-SECRET-KEY": credentials.secret},
        timeout=5,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        collector = Collector(client)
        bars = await collector.bars()
        print(json.dumps({"bar_coverage": bars["symbols"]}), flush=True)
        rows = []
        days = [START + timedelta(days=i) for i in range((END - START).days + 1)]
        for start in range(0, len(days), 2):
            batch = await asyncio.gather(
                *(
                    collector.quote(day, symbol)
                    for day in days[start : start + 2]
                    for symbol in SYMBOLS
                )
            )
            rows.extend(batch)
            if start % 40 == 0:
                print(
                    json.dumps(
                        {
                            "days_checked": min(start + 2, len(days)),
                            "total_days": len(days),
                            "requests": collector.requests,
                        }
                    ),
                    flush=True,
                )
        counts = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        report = {
            "status": "COVERAGE_ONLY_NOT_RETURN_EVALUATION",
            "start": str(START),
            "end": str(END),
            "bar_coverage": bars,
            "quote_counts": counts,
            "quotes": rows,
            "network_requests": collector.requests,
            "cache_hits": collector.cache_hits,
            "strategy_returns_computed": False,
            "historical_asset_metadata_verified": False,
            "local_receipt_timestamps_available": False,
        }
        (OUT / "coverage.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"completed": True, "quote_counts": counts}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
