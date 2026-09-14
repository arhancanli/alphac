"""Freeze public timing/lifecycle sources without converting metadata into availability."""

import hashlib
import io
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "evidence/wasde-timing-lifecycle"
SOURCES = {
    "cme-december-2018.pdf": "https://www.cmegroup.com/notices/clearing/2018/11/Chadv18-462.pdf",
    "cme-november-2018.pdf": "https://www.cmegroup.com/notices/clearing/2018/10/Chadv18-053.pdf",
    "cme-november-2025.pdf": "https://www.cmegroup.com/content/dam/cmegroup/notices/clearing/2025/10/chadv25-328.pdf",
    "usda-2025-bulletin.html": "https://content.govdelivery.com/accounts/USDAOC/bulletins/3ed883b",
}


def collect(item):
    name, url = item
    result = {"file": name, "url": url, "historical_availability_verified": False}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ALPHAC-source-audit/1.0"})
        with urllib.request.urlopen(request, timeout=25) as response:
            body = response.read(8_000_001)
            result["http_last_modified"] = response.headers.get("Last-Modified")
            result["response_url"] = response.url
        if len(body) > 8_000_000:
            raise ValueError("source size exceeds bound")
        if name.endswith(".pdf") and not body.startswith(b"%PDF"):
            raise ValueError("expected PDF")
        (DEST / name).write_bytes(body)
        result.update(
            status="RETRIEVED",
            sha256=hashlib.sha256(body).hexdigest(),
            bytes=len(body),
            observed_at=datetime.now(UTC).isoformat(),
        )
        if name.endswith(".pdf"):
            pdf = PdfReader(io.BytesIO(body))
            result["pdf_metadata"] = {str(k): str(v) for k, v in (pdf.metadata or {}).items()}
            (DEST / (name + ".txt")).write_text(
                "\n".join(p.extract_text() or "" for p in pdf.pages)
            )
        else:
            text = body.decode("utf-8", errors="replace")
            result["time_elements"] = re.findall(r"<time\b[^>]*>.*?</time>", text, flags=re.S)
            result["meta_elements"] = re.findall(r"<meta\b[^>]*>", text)
    except Exception as error:
        result.update(status="FAILED", error_type=type(error).__name__)
    return result


def main():
    DEST.mkdir(exist_ok=False)
    index = json.loads(
        (ROOT / "evidence/breadth-source-audit/wasde-release-index.json").read_text()
    )
    dates = {"2018-07-12", "2018-08-10", "2025-07-11", "2025-08-12"}
    for row in index["release_dates"]:
        date = row["release_date_label"]
        if date in dates:
            pdfs = [url for url in row["files"] if url.endswith(".pdf")]
            if len(pdfs) != 1:
                raise ValueError(f"ambiguous PDF for {date}")
            SOURCES[f"wasde-{date}.pdf"] = pdfs[0]
            SOURCES[f"release-{date}.html"] = (
                "https://esmis.nal.usda.gov/publication/world-agricultural-supply-and-demand-estimates/"
                + date
            )
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(collect, SOURCES.items()))
    report = {
        "files": results,
        "return_trials": 0,
        "policy": (
            "Creation, modification, scheduled and date-only stamps "
            "do not prove first public availability"
        ),
    }
    (DEST / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
