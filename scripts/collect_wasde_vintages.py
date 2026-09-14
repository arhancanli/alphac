"""Collect text vintages from a frozen archive index; never infer report URLs."""

import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "evidence/breadth-source-audit/wasde-release-index.json"
DEST = ROOT / "evidence/wasde-vintages"


def collect(row):
    label = row["release_date_label"]
    urls = [url for url in row["files"] if url.endswith(".txt")]
    result = {"release_date_label": label, "intraday_publication_time_verified": False}
    if len(urls) != 1:
        return {**result, "status": "AMBIGUOUS_OR_MISSING_TEXT", "urls": urls}
    result["url"] = urls[0]
    try:
        with urllib.request.urlopen(urls[0], timeout=20) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000 or b"WASDE" not in raw[:2000]:
            raise ValueError("unexpected report body")
        name = f"{label}.txt"
        (DEST / name).write_bytes(raw)
        result.update(
            status="RETRIEVED",
            file=name,
            bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            retrieved_at=datetime.now(UTC).isoformat(),
        )
    except Exception as error:
        result.update(status="FAILED", error_type=type(error).__name__)
    return result


def main():
    # Exclusive directory prevents silently replacing an earlier observation.
    DEST.mkdir(parents=True, exist_ok=False)
    raw = INDEX.read_bytes()
    rows = json.loads(raw)["release_dates"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(collect, rows))
    report = {
        "schema": "alphac.wasde-text-vintages.v1",
        "index_sha256": hashlib.sha256(raw).hexdigest(),
        "scope": "2015-01 through 2025-12; every indexed date retained",
        "files": results,
        "retrieved": sum(row["status"] == "RETRIEVED" for row in results),
        "requested": len(rows),
        "historical_publication_times_verified": False,
        "return_trials_run": 0,
    }
    (DEST / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "files"}))


if __name__ == "__main__":
    main()
