#!/usr/bin/env python3
"""Build the preregistered SEC 10-K manifest without reading prices or returns.

The job is intentionally resumable. Official submissions JSON is cached by CIK and historical
page, while the emitted manifest contains immutable accession URLs for the filing index and
primary document. This stage spends no return hypothesis: it does not open SEP or any curve.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import httpx
import pandas as pd

TICKERS_ZIP: Final = Path("data/sharadar_raw/TICKERS.zip")
RAW_DIR: Final = Path("data/raw/sec_10k_narrative/submissions")
OUT_DIR: Final = Path("artifacts/ingest/earnings_narrative_change")
UA: Final = "Canli Capital quantitative research arhancanli@icloud.com"
MIN_INTERVAL: Final = 0.12
START_DATE: Final = "2005-01-01"
END_DATE: Final = "2025-12-31"
REQUIRED_FIELDS: Final = (
    "accessionNumber",
    "filingDate",
    "reportDate",
    "acceptanceDateTime",
    "form",
    "primaryDocument",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_issuer_universe(path: Path = TICKERS_ZIP) -> pd.DataFrame:
    """Return every domestic common-stock CIK with price coverage overlapping the contract."""
    usecols = [
        "table",
        "permaticker",
        "ticker",
        "name",
        "exchange",
        "isdelisted",
        "category",
        "firstpricedate",
        "lastpricedate",
        "secfilings",
    ]
    frame = pd.read_csv(path, compression="zip", usecols=usecols, low_memory=False)
    frame["cik"] = pd.to_numeric(
        frame["secfilings"].fillna("").str.extract(r"CIK=(\d+)", expand=False),
        errors="coerce",
    )
    frame["firstpricedate"] = pd.to_datetime(frame["firstpricedate"], errors="coerce")
    frame["lastpricedate"] = pd.to_datetime(frame["lastpricedate"], errors="coerce")
    eligible = frame[
        frame["table"].eq("SF1")
        & frame["category"].eq("Domestic Common Stock")
        & frame["cik"].notna()
        & frame["firstpricedate"].le(pd.Timestamp(END_DATE))
        & frame["lastpricedate"].ge(pd.Timestamp(START_DATE))
    ].copy()
    eligible["cik"] = eligible["cik"].astype("int64")
    eligible["firstpricedate"] = eligible["firstpricedate"].dt.strftime("%Y-%m-%d")
    eligible["lastpricedate"] = eligible["lastpricedate"].dt.strftime("%Y-%m-%d")
    return eligible.drop(columns=["table", "category", "secfilings"]).sort_values(
        ["cik", "firstpricedate", "ticker"]
    ).reset_index(drop=True)


def filing_frame(payload: dict) -> pd.DataFrame:
    """Normalize either a current submissions object or one historical submissions page."""
    records = payload.get("filings", {}).get("recent", payload)
    if not records or any(field not in records for field in REQUIRED_FIELDS):
        return pd.DataFrame(columns=REQUIRED_FIELDS)
    lengths = {len(records[field]) for field in REQUIRED_FIELDS}
    if len(lengths) != 1:
        raise ValueError(f"SEC submissions columns have inconsistent lengths: {lengths}")
    return pd.DataFrame({field: records[field] for field in REQUIRED_FIELDS})


def accession_urls(cik: int, accession: str, primary_document: str) -> tuple[str, str]:
    accession_dir = accession.replace("-", "")
    root = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_dir}"
    return f"{root}/{accession}-index.html", f"{root}/{primary_document}"


class SecClient:
    def __init__(self, raw_dir: Path = RAW_DIR) -> None:
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(
            headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"},
            follow_redirects=True,
            timeout=45.0,
            limits=httpx.Limits(max_connections=12, max_keepalive_connections=8),
        )
        self.last_request = 0.0
        self.rate_lock = threading.Lock()

    def close(self) -> None:
        self.client.close()

    def _get(self, url: str) -> bytes:
        response: httpx.Response | None = None
        for attempt in range(1, 5):
            with self.rate_lock:
                wait = MIN_INTERVAL - (time.monotonic() - self.last_request)
                if wait > 0:
                    time.sleep(wait)
                self.last_request = time.monotonic()
            try:
                response = self.client.get(url)
            except httpx.TransportError:
                if attempt == 4:
                    raise
                time.sleep(float(attempt * 2))
                continue
            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                return response.content
            time.sleep(float(attempt * 2))
        assert response is not None
        response.raise_for_status()
        raise AssertionError("unreachable")

    def get_bytes(self, url: str) -> bytes:
        return self._get(url)

    def json(self, name: str) -> dict:
        cache = self.raw_dir / name
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        raw = self.get_bytes(f"https://data.sec.gov/submissions/{name}")
        payload = json.loads(raw)
        cache.write_bytes(raw)
        return payload


def company_filings(client: SecClient, cik: int) -> tuple[pd.DataFrame, int]:
    """Read current and referenced historical submissions pages for one issuer."""
    name = f"CIK{cik:010d}.json"
    current = client.json(name)
    frames = [filing_frame(current)]
    historical = current.get("filings", {}).get("files", [])
    for item in historical:
        page_name = str(item.get("name", ""))
        filing_from = str(item.get("filingFrom", ""))
        filing_to = str(item.get("filingTo", ""))
        if not page_name or (filing_to and filing_to < START_DATE) or (
            filing_from and filing_from > END_DATE
        ):
            continue
        frames.append(filing_frame(client.json(page_name)))
    combined = pd.concat(frames, ignore_index=True)
    if combined.empty:
        return combined, len(frames) - 1
    filing_dates = pd.to_datetime(combined["filingDate"], errors="coerce")
    combined = combined[
        combined["form"].eq("10-K")
        & filing_dates.between(pd.Timestamp(START_DATE), pd.Timestamp(END_DATE))
        & combined["accessionNumber"].astype(str).str.fullmatch(r"\d{10}-\d{2}-\d{6}")
        & combined["primaryDocument"].fillna("").ne("")
    ].copy()
    return combined.drop_duplicates("accessionNumber").sort_values("acceptanceDateTime"), len(
        frames
    ) - 1


def build(args: argparse.Namespace) -> dict:
    out_dir = Path(args.out_dir)
    raw_dir = Path(args.raw_dir)
    tickers_zip = Path(args.tickers_zip)
    out_dir.mkdir(parents=True, exist_ok=True)
    universe = read_issuer_universe(tickers_zip)
    ciks = sorted(universe["cik"].unique().tolist())
    if args.max_issuers is not None:
        ciks = ciks[: args.max_issuers]
        universe = universe[universe["cik"].isin(ciks)].copy()
    universe.to_parquet(out_dir / "issuer_ticker_history.parquet", index=False)

    client = SecClient(raw_dir)
    rows: list[dict] = []
    failures: list[dict] = []
    historical_pages = 0

    def load_company(cik: int) -> tuple[int, pd.DataFrame | None, int, str | None]:
        try:
            filings, page_count = company_filings(client, cik)
            return cik, filings, page_count, None
        except Exception as error:
            return cik, None, 0, str(error)

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = pool.map(load_company, ciks)
            for number, (cik, filings, page_count, error) in enumerate(results, 1):
                if error is None and filings is not None:
                    historical_pages += page_count
                    for filing in filings.to_dict("records"):
                        accession = str(filing["accessionNumber"])
                        document = str(filing["primaryDocument"])
                        index_url, document_url = accession_urls(cik, accession, document)
                        rows.append(
                            {
                                "filing_identity": f"{cik}|{accession}",
                                "cik": cik,
                                "accession": accession,
                                "form": "10-K",
                                "report_date": str(filing["reportDate"]),
                                "filing_date": str(filing["filingDate"]),
                                "acceptance_datetime": str(filing["acceptanceDateTime"]),
                                "primary_document": document,
                                "index_url": index_url,
                                "document_url": document_url,
                            }
                        )
                else:
                    failures.append({"cik": cik, "error": error})
                if number % 100 == 0 or number == len(ciks):
                    print(
                        f"issuers {number}/{len(ciks)} | filings {len(rows)} | "
                        f"failures {len(failures)}",
                        flush=True,
                    )
    finally:
        client.close()

    manifest = pd.DataFrame(rows)
    if manifest.empty:
        manifest = pd.DataFrame(
            columns=[
                "cik",
                "filing_identity",
                "accession",
                "form",
                "report_date",
                "filing_date",
                "acceptance_datetime",
                "primary_document",
                "index_url",
                "document_url",
            ]
        )
    manifest = manifest.sort_values(["acceptance_datetime", "cik", "accession"])
    manifest.to_parquet(out_dir / "filings_manifest.parquet", index=False)

    result = {
        "schema": "canli.ingest.sec-10k-narrative-manifest.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "manifest_no_prices_no_returns",
        "hypothesis_identities_spent": 0,
        "preregistration": "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "date_contract": {"start": START_DATE, "end": END_DATE},
        "ticker_reference_sha256": sha256_file(tickers_zip),
        "issuer_ticker_rows": len(universe),
        "unique_ciks": len(ciks),
        "historical_submission_pages": historical_pages,
        "filings": len(manifest),
        "duplicate_accessions_across_issuers": int(manifest["accession"].duplicated().sum()),
        "duplicate_filing_identities": int(manifest["filing_identity"].duplicated().sum()),
        "issuers_with_filings": int(manifest["cik"].nunique()) if len(manifest) else 0,
        "metadata_failures": failures,
        "metadata_failure_rate": len(failures) / len(ciks) if ciks else 0.0,
        "complete_required_lineage": bool(
            len(manifest)
            and not manifest[
                [
                    "cik",
                    "accession",
                    "report_date",
                    "filing_date",
                    "acceptance_datetime",
                    "primary_document",
                    "index_url",
                    "document_url",
                ]
            ]
            .isna()
            .any()
            .any()
        ),
    }
    (out_dir / "manifest_result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-issuers",
        type=int,
        help="Deterministic CIK-prefix smoke run; omit for the locked full universe.",
    )
    parser.add_argument("--tickers-zip", default=str(TICKERS_ZIP))
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    print(json.dumps(build(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
