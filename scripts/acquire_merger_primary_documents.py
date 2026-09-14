"""Bounded acquisition of primary SEC filing documents for the immutable merger sample."""

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/merger-primary-documents-20260913"
SAMPLE = ROOT / "evidence/merger-confirmation-metadata-20260913/selected_anchors.parquet"


async def main():
    manifest_path = ROOT / "evidence/merger-document-manifests-20260913/primary_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert len(manifest) == 395
    unique = pd.DataFrame([row for row in manifest if row["success"]])
    assert unique.accession.is_unique
    OUT.mkdir(exist_ok=False)
    (OUT / "documents").mkdir()
    receipts = OUT / "receipts.jsonl"
    if receipts.exists():
        raise FileExistsError("Inspect existing acquisition before any resume")
    (OUT / "scope.json").write_text(
        json.dumps(
            {
                "sample_sha256": hashlib.sha256(SAMPLE.read_bytes()).hexdigest(),
                "primary_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "resolved_requested": len(unique),
                "unresolved_manifest_rows": 395 - len(unique),
                "scope": "Primary source documents only; no eligibility labels or returns",
                "concurrency": 2,
                "minimum_start_gap_seconds": 0.35,
                "byte_cap": 25000000,
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
            record = {"accession": row.accession, "index_cik": int(row.index_cik)}
            path = OUT / "documents" / f"{row.accession}.bin"
            record["url"] = row.primary_url
            try:
                async with lock:
                    await asyncio.sleep(max(0, 0.35 - (time.monotonic() - previous)))
                    previous = time.monotonic()
                async with client.stream("GET", record["url"]) as response:
                    record["status"] = response.status_code
                    if response.status_code in (403, 429):
                        stopped.set()
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > 25000000:
                            raise ValueError("Index size cap exceeded")
                        chunks.append(part)
                data = b"".join(chunks)
                if not data or b"Your Request Originates from an Undeclared Automated Tool" in data:
                    raise ValueError("Empty or access-denied document")
                path.write_bytes(data)
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
