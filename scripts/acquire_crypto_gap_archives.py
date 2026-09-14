"""Bounded public archive recovery; preserve absence, never synthesize bars."""

import asyncio
import csv
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/crypto-gap-archives-20260913"
SOURCE = ROOT / "evidence/crypto-2022-input-grid-20260913"


async def main():
    OUT.mkdir(exist_ok=False)
    gaps = pd.read_csv(SOURCE / "missing_active_hours.csv")
    gaps["day"] = pd.to_datetime(gaps.missing_active_hour, unit="ms").dt.strftime("%Y-%m-%d")
    queue = []
    for (iid, day), group in gaps.groupby(["instrument", "day"]):
        symbol = iid.rsplit(":", 1)[1]
        queue.append(
            {
                "instrument": iid,
                "day": day,
                "missing_timestamps": group.missing_active_hour.tolist(),
                "url": f"https://data.binance.vision/data/futures/um/daily/klines/{symbol}/1h/{symbol}-1h-{day}.zip",
            }
        )
    (OUT / "queue.json").write_text(json.dumps(queue, indent=2) + "\n")
    (OUT / "scope.json").write_text(
        json.dumps(
            {
                "source_sha256": hashlib.sha256(
                    (SOURCE / "missing_active_hours.csv").read_bytes()
                ).hexdigest(),
                "concurrency": 2,
                "retries": 0,
                "max_body_bytes": 2000000,
                "scope": "Raw isolated source records; inspect timestamps only; "
                "no production ingestion or returns.",
            },
            indent=2,
        )
        + "\n"
    )
    sem = asyncio.Semaphore(2)
    stop = asyncio.Event()
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:

        async def one(row):
            async with sem:
                if stop.is_set():
                    return {**row, "status": "NOT_ATTEMPTED_STOP"}
                key = row["instrument"].rsplit(":", 1)[1] + "-" + row["day"]
                result = {**row, "retrieval_started_utc": datetime.now(UTC).isoformat()}
                try:
                    if key == "FTMUSDT-2022-02-26":
                        raw = (SOURCE / "archive_probe/FTMUSDT-1h-2022-02-26.zip").read_bytes()
                        checksum = (SOURCE / "archive_probe/CHECKSUM.txt").read_text()
                        result["status"] = 200
                        result["reused_verified_probe"] = True
                    else:
                        response = await client.get(row["url"])
                        result["status"] = response.status_code
                        if response.status_code in [403, 429]:
                            stop.set()
                        if response.status_code != 200:
                            return result
                        raw = response.content
                        assert len(raw) <= 2000000
                        response = await client.get(row["url"] + ".CHECKSUM")
                        response.raise_for_status()
                        checksum = response.text
                    digest = hashlib.sha256(raw).hexdigest()
                    assert checksum.split()[0] == digest
                    (OUT / (key + ".zip")).write_bytes(raw)
                    (OUT / (key + ".CHECKSUM")).write_text(checksum)
                    with zipfile.ZipFile(io.BytesIO(raw)) as z:
                        assert len(z.namelist()) == 1
                        content = z.read(z.namelist()[0]).decode()
                        timestamps = [
                            int(r[0])
                            for r in csv.reader(io.StringIO(content))
                            if r and r[0].isdigit()
                        ]
                    assert timestamps == sorted(set(timestamps))
                    available = set(timestamps)
                    result.update(
                        sha256=digest,
                        checksum_verified=True,
                        archive_rows=len(timestamps),
                        recovered_timestamps=[
                            t for t in row["missing_timestamps"] if t in available
                        ],
                        unresolved_timestamps=[
                            t for t in row["missing_timestamps"] if t not in available
                        ],
                    )
                except Exception as exc:
                    result["error"] = str(exc)
                finally:
                    (OUT / (key + ".receipt.json")).write_text(json.dumps(result, indent=2) + "\n")
                return result

        results = await asyncio.gather(*(one(row) for row in queue))
    (OUT / "result.json").write_text(json.dumps(results, indent=2) + "\n")
    print(
        json.dumps(
            {
                "days": len(queue),
                "http_200": sum(r.get("status") == 200 for r in results),
                "http_404": sum(r.get("status") == 404 for r in results),
                "recovered_hours": sum(len(r.get("recovered_timestamps", [])) for r in results),
                "errors": sum("error" in r for r in results),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
