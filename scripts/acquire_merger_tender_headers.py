"""Bounded acquisition of header-only SEC files for the immutable merger sample."""

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/merger-tender-headers-20260913"
SAMPLE = ROOT / "evidence/merger-tender-linkage-20260913/queue.json"


async def main():
    frozen = json.loads((SAMPLE.parent / "closure.json").read_text())
    assert hashlib.sha256(SAMPLE.read_bytes()).hexdigest() == frozen["files"][str(SAMPLE.relative_to(ROOT))]
    frame = pd.DataFrame(json.loads(SAMPLE.read_text()))
    assert len(frame) == 205 and not frame.accession.duplicated().any()
    unique = frame
    OUT.mkdir(exist_ok=False)
    (OUT / "headers").mkdir()
    receipts = OUT / "receipts.jsonl"
    if receipts.exists():
        raise FileExistsError("Inspect existing acquisition before any resume")
    (OUT / "scope.json").write_text(
        json.dumps(
            {
                "sample_sha256": hashlib.sha256(SAMPLE.read_bytes()).hexdigest(),
                "scope": "205 frozen matched tender headers only; no filing bodies, labels or returns",
                "concurrency": 2,
                "minimum_start_gap_seconds": 0.35,
                "byte_cap": 3000000,
                "timeout_seconds": 20,
                "retry_count": 0,
                "stop_on": "403 or429 stop remaining queued requests; in-flight requests finish",
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(2)
    stopped = asyncio.Event()
    previous = 0.0
    counts = {"success": 0, "failed": 0, "skipped": 0}

    async def acquire(row, client):
        nonlocal previous
        async with semaphore:
            if stopped.is_set():
                counts["skipped"] += 1
                return
            record = {"accession": row.accession, "index_cik": int(row.cik)}
            path = OUT / "headers" / f"{row.accession}.sgml"
            record["url"] = (
                f"https://www.sec.gov/Archives/edgar/data/{row.cik}/"
                f"{row.accession.replace('-', '')}/{row.accession}.hdr.sgml"
            )
            try:
                assert not path.exists()
                expected = f"https://www.sec.gov/Archives/edgar/data/{row.cik}/{row.accession.replace('-', '')}/{row.accession}.hdr.sgml"
                assert row.header_url == record["url"] == expected
                async with lock:
                    await asyncio.sleep(max(0, 0.35 - (time.monotonic() - previous)))
                    previous = time.monotonic()
                if stopped.is_set():
                    counts["skipped"] += 1
                    return
                async with client.stream("GET", record["url"]) as response:
                    record["status"] = response.status_code
                    if response.status_code in (403, 429):
                        stopped.set()
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > 3000000:
                            raise ValueError("Header size cap exceeded")
                        chunks.append(part)
                data = b"".join(chunks)
                if b"<SEC-HEADER>" not in data or row.accession.encode() not in data:
                    raise ValueError("Header/accession identity absent")
                with path.open("xb") as stream:
                    stream.write(data)
                record.update(
                    success=True, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
                )
                counts["success"] += 1
            except Exception as exc:
                record.update(success=False, error_type=type(exc).__name__)
                counts["failed"] += 1
            record["received_at_utc"] = datetime.now(UTC).isoformat()
            with receipts.open("a") as stream:
                stream.write(json.dumps(record) + "\n")
            if (counts["success"] + counts["failed"]) % 25 == 0:
                print(counts, flush=True)

    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": "Canli Capital research research@canlicapital.com"},
    ) as client:
        await asyncio.gather(*(acquire(row, client) for row in unique.itertuples()))
    (OUT / "acquisition_result.json").write_text(json.dumps(counts, indent=2) + "\n")
    print("Terminal acquisition:", counts, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
