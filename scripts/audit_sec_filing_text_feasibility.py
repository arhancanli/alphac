#!/usr/bin/env python3
"""Audit whether official SEC filing text supports a PIT narrative-change probe.

This script deliberately reads no prices or returns. It creates a deterministic, sector-stratified
filing sample, preserves source lineage, extracts fixed sections, and emits corpus-quality gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from itertools import pairwise
from pathlib import Path
from typing import Final

import httpx
import pandas as pd

TICKERS_ZIP: Final = Path("data/sharadar_raw/TICKERS.zip")
OUT_DIR: Final = Path("artifacts/feasibility/earnings_narrative_change")
RAW_DIR: Final = Path("data/raw/sec_filing_text_feasibility")
UA: Final = "Canli Capital quantitative research arhancanli@icloud.com"
PARSER_VERSION: Final = "sec-filing-sections-v2"
MIN_INTERVAL: Final = 0.12
BLOCK_TAGS: Final = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "caption",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
}
SKIP_TAGS: Final = {"script", "style", "noscript", "svg"}


@dataclass(frozen=True)
class Filing:
    ticker: str
    sector: str
    cik: int
    accession: str
    form: str
    report_date: str
    filing_date: str
    acceptance_datetime: str
    primary_document: str
    source_url: str


class FilingTextParser(HTMLParser):
    """Small deterministic HTML-to-text parser with hidden-XBRL suppression."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {k.lower(): (v or "").lower() for k, v in attrs}
        hidden = (
            "hidden" in attr
            or attr.get("aria-hidden") == "true"
            or "display:none" in attr.get("style", "").replace(" ", "")
        )
        should_skip = (
            tag in SKIP_TAGS or hidden or (tag.startswith("ix:") and tag.endswith("hidden"))
        )
        if self.skip_depth or should_skip:
            self.skip_depth += 1
        if not self.skip_depth and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if not self.skip_depth and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        value = unicodedata.normalize("NFKC", "".join(self.parts)).replace("\xa0", " ")
        lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
        return "\n".join(line for line in lines if line)


def html_to_text(raw: bytes) -> str:
    parser = FilingTextParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    return parser.text()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def _span(
    text: str,
    starts: Iterable[re.Pattern[str]],
    ends: Iterable[re.Pattern[str]],
    minimum_words: int = 350,
) -> str | None:
    normalized = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    start_positions = sorted(
        {match.start() for pattern in starts for match in pattern.finditer(normalized)}
    )
    end_positions = sorted(
        {match.start() for pattern in ends for match in pattern.finditer(normalized)}
    )
    candidates: list[str] = []
    for start in start_positions:
        # Use the nearest heading. A TOC span then fails the length gate instead of jumping over
        # its own end marker and swallowing the real section later in the document.
        end = next((position for position in end_positions if position > start + 10), None)
        if end is None:
            continue
        candidate = re.sub(r"\s+", " ", normalized[start:end]).strip()
        words = candidate.split()
        if minimum_words <= len(words) <= 80_000:
            candidates.append(candidate)
    # A prose cross-reference can share the actual section's end. The later real heading creates
    # the shortest valid span, which is selected without reading a return label.
    return min(candidates, key=lambda value: (len(value.split()), len(value)), default=None)


PREFIX = r"^[ \t]*(?:part[ \t]+[ivx]+[ \t]*[.\-:]?[ \t]*)?"
FLAGS = re.IGNORECASE | re.MULTILINE
ITEM_1A_START = (
    re.compile(PREFIX + r"item\s+1\s*a\s*[.\-:\u2013\u2014]*\s*risk\s+factors\b", FLAGS),
)
ITEM_1A_END = (
    re.compile(
        PREFIX + r"item\s+1\s*b\s*[.\-:\u2013\u2014]*\s*(?:unresolved\s+staff\s+comments)?\b",
        FLAGS,
    ),
    re.compile(PREFIX + r"item\s+1\s*c\s*[.\-:\u2013\u2014]*\s*cybersecurity\b", FLAGS),
    re.compile(PREFIX + r"item\s+2\s*[.\-:\u2013\u2014]+\s*properties\b", FLAGS),
    re.compile(PREFIX + r"item\s+2\s*[.\-:\u2013\u2014]+\s*unregistered\s+sales\b", FLAGS),
)
K_MDA_START = (
    re.compile(
        PREFIX
        + r"item\s+7\s*[.\-:\u2013\u2014]*\s*management[^\n]{0,80}?discussion\s+and\s+analysis\b",
        FLAGS,
    ),
)
K_MDA_END = (
    re.compile(
        PREFIX + r"item\s+7\s*a\s*[.\-:\u2013\u2014]*\s*quantitative\s+and\s+qualitative\b",
        FLAGS,
    ),
    re.compile(PREFIX + r"item\s+8\s*[.\-:\u2013\u2014]*\s*financial\s+statements\b", FLAGS),
)
Q_MDA_START = (
    re.compile(
        PREFIX
        + r"item\s+2\s*[.\-:\u2013\u2014]*\s*management[^\n]{0,80}?discussion\s+and\s+analysis\b",
        FLAGS,
    ),
)
Q_MDA_END = (
    re.compile(
        PREFIX + r"item\s+3\s*[.\-:\u2013\u2014]*\s*quantitative\s+and\s+qualitative\b",
        FLAGS,
    ),
    re.compile(
        PREFIX + r"item\s+4\s*[.\-:\u2013\u2014]*\s*controls\s+and\s+procedures\b",
        FLAGS,
    ),
)


def extract_sections(text: str, form: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    risk = _span(text, ITEM_1A_START, ITEM_1A_END)
    if risk:
        sections["risk_factors"] = risk
    if form == "10-K":
        mda = _span(text, K_MDA_START, K_MDA_END)
    elif form == "10-Q":
        mda = _span(text, Q_MDA_START, Q_MDA_END)
    else:
        mda = None
    if mda:
        sections["mda"] = mda
    return sections


def shingles(text: str, width: int = 5) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(tokens[i : i + width]) for i in range(max(0, len(tokens) - width + 1))}


def jaccard(left: str, right: str) -> float:
    a, b = shingles(left), shingles(right)
    return len(a & b) / len(a | b) if a or b else 1.0


def read_ticker_reference() -> pd.DataFrame:
    frame = pd.read_csv(TICKERS_ZIP, compression="zip", low_memory=False)
    cik = frame["secfilings"].fillna("").str.extract(r"CIK=(\d+)", expand=False)
    frame = frame.assign(cik=pd.to_numeric(cik, errors="coerce"))
    eligible = frame[
        frame["table"].eq("SF1")
        & frame["isdelisted"].eq("N")
        & frame["category"].eq("Domestic Common Stock")
        & pd.to_datetime(frame["firstpricedate"], errors="coerce").le(pd.Timestamp("2010-01-01"))
        & frame["sector"].notna()
        & frame["cik"].notna()
    ].copy()
    eligible["cik"] = eligible["cik"].astype(int)
    eligible = eligible.sort_values(["cik", "ticker"]).drop_duplicates("cik", keep="first")
    return eligible


def locked_sample(frame: pd.DataFrame, companies_per_sector: int) -> pd.DataFrame:
    frame = frame.copy()
    frame["sample_rank"] = frame.apply(
        lambda row: sha256_text(f"{row['sector']}|{int(row['cik'])}"), axis=1
    )
    return (
        frame.sort_values(["sector", "sample_rank", "cik"])
        .groupby("sector", sort=True, group_keys=False)
        .head(companies_per_sector)
        .sort_values(["sector", "cik"])
        .reset_index(drop=True)
    )


class SecClient:
    def __init__(self) -> None:
        self.client = httpx.Client(
            headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"},
            follow_redirects=True,
            timeout=45.0,
        )
        self.last_request = 0.0

    def close(self) -> None:
        self.client.close()

    def get(self, url: str) -> httpx.Response:
        wait = MIN_INTERVAL - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(1, 4):
            response = self.client.get(url)
            self.last_request = time.monotonic()
            if response.status_code not in {429, 503}:
                response.raise_for_status()
                return response
            time.sleep(attempt * 2.0)
        response.raise_for_status()
        return response


def filings_for_company(
    row: pd.Series, payload: dict, start_year: int, end_year: int
) -> list[Filing]:
    recent = payload["filings"]["recent"]
    records = pd.DataFrame(recent)
    records = records[
        records["form"].isin(["10-K", "10-Q"])
        & pd.to_datetime(records["filingDate"], errors="coerce").dt.year.between(
            start_year, end_year
        )
    ].copy()
    records = records.sort_values(["form", "acceptanceDateTime"], ascending=[True, False])
    records = pd.concat(
        [
            records[records["form"].eq("10-K")].head(3),
            records[records["form"].eq("10-Q")].head(8),
        ]
    ).sort_values("acceptanceDateTime")
    out: list[Filing] = []
    for record in records.to_dict("records"):
        accession = str(record["accessionNumber"])
        accession_dir = accession.replace("-", "")
        document = str(record["primaryDocument"])
        url = f"https://www.sec.gov/Archives/edgar/data/{int(row.cik)}/{accession_dir}/{document}"
        out.append(
            Filing(
                ticker=str(row.ticker),
                sector=str(row.sector),
                cik=int(row.cik),
                accession=accession,
                form=str(record["form"]),
                report_date=str(record["reportDate"]),
                filing_date=str(record["filingDate"]),
                acceptance_datetime=str(record["acceptanceDateTime"]),
                primary_document=document,
                source_url=url,
            )
        )
    return out


def audit(args: argparse.Namespace) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    sample = locked_sample(read_ticker_reference(), args.companies_per_sector)
    sample[["ticker", "name", "sector", "cik", "sample_rank"]].to_csv(
        OUT_DIR / "locked_sample.csv", index=False
    )

    client = SecClient()
    filings: list[Filing] = []
    metadata_failures: list[dict] = []
    try:
        for row in sample.itertuples(index=False):
            try:
                payload = client.get(
                    f"https://data.sec.gov/submissions/CIK{int(row.cik):010d}.json"
                ).json()
                filings.extend(
                    filings_for_company(
                        pd.Series(row._asdict()), payload, args.start_year, args.end_year
                    )
                )
            except Exception as error:
                metadata_failures.append(
                    {"ticker": row.ticker, "cik": int(row.cik), "error": str(error)}
                )

        rows: list[dict] = []
        document_failures: list[dict] = []
        for index, filing in enumerate(filings, 1):
            raw_path = RAW_DIR / f"{filing.accession.replace('-', '')}_{filing.primary_document}"
            try:
                raw = (
                    raw_path.read_bytes()
                    if raw_path.exists()
                    else client.get(filing.source_url).content
                )
                if not raw_path.exists():
                    raw_path.write_bytes(raw)
                text = html_to_text(raw)
                sections = extract_sections(text, filing.form)
                for section_name in ("risk_factors", "mda"):
                    section = sections.get(section_name)
                    rows.append(
                        {
                            **asdict(filing),
                            "parser_version": PARSER_VERSION,
                            "raw_sha256": sha256_bytes(raw),
                            "raw_bytes": len(raw),
                            "document_words": len(text.split()),
                            "section": section_name,
                            "extracted": section is not None,
                            "section_words": len(section.split()) if section else 0,
                            "section_sha256": sha256_text(section) if section else None,
                            "section_text": section,
                        }
                    )
            except Exception as error:
                document_failures.append({**asdict(filing), "error": str(error)})
            if index % 50 == 0:
                print(f"documents {index}/{len(filings)}", flush=True)
    finally:
        client.close()

    sections = pd.DataFrame(rows)
    if sections.empty:
        raise RuntimeError("no filing sections were processed")
    sections.to_parquet(OUT_DIR / "sections.parquet", index=False)

    extracted = sections[sections["extracted"]].sort_values(
        ["cik", "form", "section", "acceptance_datetime"]
    )
    pair_rows: list[dict] = []
    for keys, group in extracted.groupby(["cik", "ticker", "form", "section"], sort=True):
        records = group.to_dict("records")
        for previous, current in pairwise(records):
            pair_rows.append(
                {
                    "cik": keys[0],
                    "ticker": keys[1],
                    "form": keys[2],
                    "section": keys[3],
                    "previous_accession": previous["accession"],
                    "current_accession": current["accession"],
                    "previous_acceptance": previous["acceptance_datetime"],
                    "current_acceptance": current["acceptance_datetime"],
                    "previous_sha256": previous["section_sha256"],
                    "current_sha256": current["section_sha256"],
                    "exact_duplicate": previous["section_sha256"] == current["section_sha256"],
                    "fivegram_jaccard": jaccard(previous["section_text"], current["section_text"]),
                }
            )
    pairs = pd.DataFrame(pair_rows)
    pairs.to_parquet(OUT_DIR / "pairs.parquet", index=False)

    selected_documents = len(filings)
    downloaded_documents = selected_documents - len(document_failures)
    company_count = int(sample["cik"].nunique())
    rates: dict[str, float | None] = {}
    for form, section in (("10-K", "risk_factors"), ("10-K", "mda"), ("10-Q", "mda")):
        subset = sections[(sections["form"] == form) & (sections["section"] == section)]
        rates[f"{form}_{section}"] = float(subset["extracted"].mean()) if len(subset) else None

    pair_coverage: dict[str, float] = {}
    for form in ("10-K", "10-Q"):
        eligible = set(
            extracted[extracted["form"].eq(form)].groupby("cik").size().loc[lambda x: x >= 2].index
        )
        pair_coverage[form] = len(eligible) / company_count if company_count else 0.0

    section_word_median = float(extracted["section_words"].median()) if len(extracted) else 0.0
    exact_duplicate_rate = float(pairs["exact_duplicate"].mean()) if len(pairs) else 1.0
    gates = {
        "download_rate_gte_0_95": downloaded_documents / selected_documents >= 0.95
        if selected_documents
        else False,
        "10k_risk_extraction_gte_0_80": (rates["10-K_risk_factors"] or 0.0) >= 0.80,
        "10k_mda_extraction_gte_0_80": (rates["10-K_mda"] or 0.0) >= 0.80,
        "10q_mda_extraction_gte_0_80": (rates["10-Q_mda"] or 0.0) >= 0.80,
        "10k_pair_coverage_gte_0_70": pair_coverage["10-K"] >= 0.70,
        "10q_pair_coverage_gte_0_70": pair_coverage["10-Q"] >= 0.70,
        "median_section_words_gte_500": section_word_median >= 500,
        "exact_duplicate_rate_lt_0_05": exact_duplicate_rate < 0.05,
        "lineage_complete": not extracted[
            [
                "cik",
                "accession",
                "form",
                "report_date",
                "filing_date",
                "acceptance_datetime",
                "source_url",
                "raw_sha256",
                "section_sha256",
                "parser_version",
            ]
        ]
        .isna()
        .any()
        .any(),
    }
    result = {
        "schema": "canli.feasibility.earnings-narrative-change.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "corpus_feasibility_no_returns",
        "hypothesis_identities_spent": 0,
        "parser_version": PARSER_VERSION,
        "sample": {
            "companies": company_count,
            "sectors": int(sample["sector"].nunique()),
            "companies_per_sector": args.companies_per_sector,
            "start_year": args.start_year,
            "end_year": args.end_year,
        },
        "documents": {
            "selected": selected_documents,
            "downloaded": downloaded_documents,
            "download_rate": downloaded_documents / selected_documents
            if selected_documents
            else 0.0,
            "metadata_failures": metadata_failures,
            "document_failures": document_failures,
            "forms": Counter(filing.form for filing in filings),
        },
        "extraction_rates": rates,
        "pair_coverage_by_form": pair_coverage,
        "extracted_sections": len(extracted),
        "comparable_pairs": len(pairs),
        "median_section_words": section_word_median,
        "exact_duplicate_rate": exact_duplicate_rate,
        "jaccard": {
            "p05": float(pairs["fivegram_jaccard"].quantile(0.05)) if len(pairs) else None,
            "median": float(pairs["fivegram_jaccard"].median()) if len(pairs) else None,
            "p95": float(pairs["fivegram_jaccard"].quantile(0.95)) if len(pairs) else None,
        },
        "gates": gates,
        "decision": "PASS_TO_RETURN_PREREGISTRATION" if all(gates.values()) else "DATA_GATED",
        "sources": {
            "sec_api": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
            "sec_archives": "https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data",
            "research_prior": "https://www.nber.org/papers/w25084",
        },
    }
    (OUT_DIR / "result.json").write_text(json.dumps(result, indent=2, default=list) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--companies-per-sector", type=int, default=3)
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()
    result = audit(args)
    print(json.dumps(result, indent=2, default=list))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
