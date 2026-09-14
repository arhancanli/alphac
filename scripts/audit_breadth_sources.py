"""Fixed-scope WASDE archive metadata audit. No market prices or return trials."""

import hashlib
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1] / "evidence/breadth-source-audit"
BASE = "https://esmis.nal.usda.gov/publication/world-agricultural-supply-and-demand-estimates"


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current = {"text": [], "links": []}
        if tag == "a" and self.current is not None:
            href = dict(attrs).get("href", "")
            if "/release-files/" in href:
                self.current["links"].append(urljoin(BASE, href))

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "tr" and self.current is not None:
            self.rows.append(self.current)
            self.current = None


def fetch(page):
    url = BASE + f"?page={page}"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("response size budget")
        name = f"archive-page-{page:02}.html"
        (ROOT / name).write_bytes(raw)
        parser = Rows()
        parser.feed(raw.decode())
        rows = []
        for row in parser.rows:
            text = " ".join(" ".join(row["text"]).split())
            match = re.search(r"\b([A-Z][a-z]{2} \d{2} 20\d{2})\b", text)
            if not match or not row["links"]:
                continue
            month, day, year = match[1].split()
            months = (
                "Jan",
                "Feb",
                "Mar",
                "Apr",
                "May",
                "Jun",
                "Jul",
                "Aug",
                "Sep",
                "Oct",
                "Nov",
                "Dec",
            )
            month_number = months.index(month) + 1
            label = date(int(year), month_number, int(day)).isoformat()
            rows.append({"release_date_label": label, "files": sorted(set(row["links"]))})
        if not rows:
            raise ValueError("no archive rows parsed")
        return {
            "page": page,
            "url": url,
            "file": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "status": "RETRIEVED",
            "rows": rows,
        }
    except Exception as error:
        return {"page": page, "url": url, "status": "FAILED", "error_type": type(error).__name__}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pages = list(pool.map(fetch, range(15)))
    dates = {}
    for page in pages:
        for row in page.get("rows", []):
            date = row["release_date_label"]
            if not "2015-01-01" <= date <= "2025-12-31":
                continue
            item = dates.setdefault(
                date,
                {
                    "release_date_label": date,
                    "files": [],
                    "source_pages": [],
                    "intraday_publication_time_verified": False,
                },
            )
            item["files"] = sorted(set(item["files"]) | set(row["files"]))
            item["source_pages"].append(page["page"])
    expected = [f"{year}-{month:02}" for year in range(2015, 2026) for month in range(1, 13)]
    observed = {d[:7] for d in dates}
    report = {
        "schema": "alphac.wasde-release-index-audit.v1",
        "observed_at": datetime.now(UTC).isoformat(),
        "fixed_scope": "2015-01 through 2025-12",
        "pages": pages,
        "release_dates": [dates[d] for d in sorted(dates)],
        "status": "SOURCE_INDEX_OBSERVED_NOT_POINT_IN_TIME_VERIFIED"
        if all(p["status"] == "RETRIEVED" for p in pages)
        else "SOURCE_COLLECTION_INCOMPLETE",
        "distinct_release_dates": len(dates),
        "expected_calendar_months": len(expected),
        "months_without_indexed_release": [m for m in expected if m not in observed],
        "duplicate_month_release_counts": {
            m: sum(d.startswith(m) for d in dates)
            for m in expected
            if sum(d.startswith(m) for d in dates) > 1
        },
        "prices_opened": False,
        "return_trials_run": 0,
    }
    (ROOT / "wasde-release-index.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "distinct_release_dates",
                    "expected_calendar_months",
                    "months_without_indexed_release",
                    "duplicate_month_release_counts",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
