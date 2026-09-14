"""Extract filing document lineage without labeling deal eligibility."""

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/merger-document-manifests-20260913"
SAMPLE = ROOT / "evidence/merger-confirmation-metadata-20260913/selected_anchors.parquet"


class DocumentTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.cell = None
        self.cells = []
        self.links = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and attrs.get("summary") == "Document Format Files":
            self.active = True
        if not self.active:
            return
        if tag == "tr":
            self.cells, self.links = [], []
        elif tag == "td":
            self.cell = []
        elif tag == "a" and self.cell is not None:
            self.links.append(attrs.get("href", ""))

    def handle_data(self, data):
        if self.active and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag == "td" and self.cell is not None:
            self.cells.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.cells:
            self.rows.append((self.cells, self.links))
        elif tag == "table":
            self.active = False


def primary_link(html, *, accession, form):
    parser = DocumentTable()
    parser.feed(html)
    matching = [
        (cells, links)
        for cells, links in parser.rows
        if len(cells) == 5 and cells[0] == "1" and cells[3] == form
    ]
    if len(matching) != 1:
        raise ValueError("Require exactly one sequence1 exact-form document")
    cells, links = matching[0]
    if len(links) != 1:
        raise ValueError("Ambiguous document link")
    url = urljoin("https://www.sec.gov", links[0])
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.sec.gov"
        or not parsed.path.startswith("/Archives/edgar/data/")
        or f"/{accession.replace('-', '')}/" not in parsed.path
        or parsed.query
        or parsed.fragment
        or ".." in parsed.path.split("/")
    ):
        raise ValueError("Document link outside exact SEC accession")
    return {
        "primary_url": url,
        "filename": cells[2],
        "sequence": 1,
        "form": cells[3],
        "listed_size": cells[4],
    }


def main():
    sample = pd.read_parquet(SAMPLE).drop_duplicates("accession", keep="first")
    scope = json.loads((OUT / "scope.json").read_text())
    assert hashlib.sha256(SAMPLE.read_bytes()).hexdigest() == scope["sample_sha256"]
    receipts = {
        r["accession"]: r
        for r in map(json.loads, (OUT / "receipts.jsonl").read_text().splitlines())
    }
    old = ROOT / "evidence/merger-header-acquisition-20260913"
    clocks = {
        r["accession"]: r["acceptance_raw"]
        for r in json.loads((old / "header_mapping.json").read_text())
    }
    rows = []
    for row in sample.itertuples():
        result = {"accession": row.accession, "index_cik": int(row.cik)}
        try:
            receipt = receipts[row.accession]
            assert receipt["success"]
            data = (OUT / "manifests" / f"{row.accession}.html").read_bytes()
            assert hashlib.sha256(data).hexdigest() == receipt["sha256"]
            html = data.decode("utf-8")
            primary = primary_link(html, accession=row.accession, form=row.form)
            accepted = re.findall(r'Accepted</div>\s*<div class="info">([^<]+)</div>', html)
            assert len(accepted) == 1
            clock = re.sub(r"\D", "", accepted[0])
            assert clock == clocks[row.accession]
            result.update(
                primary,
                success=True,
                raw_clock_matches_header=True,
                manifest_sha256=receipt["sha256"],
            )
        except Exception as exc:
            result.update(success=False, error_type=type(exc).__name__)
        rows.append(result)
    (OUT / "primary_manifest.json").write_text(json.dumps(rows, indent=2) + "\n")
    summary = {
        "filings": len(rows),
        "resolved_primary": sum(r["success"] for r in rows),
        "unresolved": sum(not r["success"] for r in rows),
        "utc_clock_verified": False,
        "deal_eligibility_verified": False,
        "return_hypotheses_spent": 0,
    }
    (OUT / "audit_result.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
