#!/usr/bin/env python3
"""Audit archived Treasury tentative-schedule PDFs without opening returns.

Internet Archive capture timestamps are treated as conservative publication times. A PDF can
prove a fixed-rate 2-year auction date only when its capture precedes the auction by at least ten
XNYS sessions and every extracted date cross-checks to the independently sealed Treasury manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Final

import exchange_calendars as xcals
import httpx
import pandas as pd
import pypdf
from pypdf import PdfReader

CDX: Final = "https://web.archive.org/cdx/search/cdx"
ORIGINAL: Final = (
    "https://www.treasury.gov/resource-center/data-chart-center/"
    "quarterly-refunding/Documents/auctions.pdf"
)
MANIFEST: Final = Path("artifacts/feasibility/treasury_auction_concession/events.parquet")
RAW_DIR: Final = Path(
    "data/raw/treasury_auction_concession/wayback_tentative_schedule_pdf_archive"
)
EVENTS_OUT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/wayback_pdf_schedule_events.parquet"
)
RESULT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/wayback_pdf_schedule_audit.json"
)
START: Final = date(2013, 1, 1)
END: Final = date(2020, 4, 30)
MIN_PRIOR_SESSIONS: Final = 10
UA: Final = "Canli Capital quantitative research research@canlicapital.com"
DATE_PATTERN: Final = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday),\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},\s+\d{4}"
)
NOTE_LINE_PATTERN: Final = re.compile(r"(?m)^\s*2-Year\s+NOTE\b(?P<body>[^\n]*)$")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def request_bytes(url: str, params: dict[str, Any] | None = None) -> bytes:
    error: Exception | None = None
    for attempt in range(5):
        try:
            with httpx.Client(
                timeout=90.0,
                follow_redirects=True,
                headers={"User-Agent": UA},
            ) as client:
                response = client.get(url, params=params)
                if response.status_code in {429, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        "retryable archive response",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.content
        except (httpx.HTTPError, OSError) as exc:
            error = exc
            time.sleep(min(2**attempt, 16))
    raise RuntimeError(f"archive request failed after retries: {url}") from error


def parse_cdx(raw: bytes) -> list[dict[str, str]]:
    rows = json.loads(raw)
    if not rows or rows[0][:3] != ["timestamp", "original", "digest"]:
        raise ValueError("unexpected CDX schema")
    captures = []
    for row in rows[1:]:
        timestamp, original, digest = row[:3]
        if not (len(timestamp) == 14 and timestamp.isdigit() and digest):
            raise ValueError(f"invalid CDX row: {row}")
        captures.append(
            {"timestamp": timestamp, "original": original, "cdx_digest": digest}
        )
    return captures


def parse_schedule_text(text: str) -> list[date]:
    """Return fixed-rate 2-year NOTE auction dates; FRNs never match this grammar."""
    events = []
    for match in NOTE_LINE_PATTERN.finditer(text):
        dates = DATE_PATTERN.findall(match.group("body"))
        if len(dates) != 3:
            raise ValueError(
                "expected announcement, auction, and settlement dates on each 2-Year NOTE line; "
                f"found {len(dates)} in {match.group(0)!r}"
            )
        events.append(
            datetime.strptime(dates[1], "%A, %B %d, %Y").replace(tzinfo=UTC).date()
        )
    if not events:
        raise ValueError("PDF contained no parseable fixed-rate 2-Year NOTE rows")
    if len(events) != len(set(events)):
        raise ValueError("PDF contained duplicate fixed-rate 2-Year NOTE auction dates")
    return events


def parse_schedule_pdf(raw: bytes) -> tuple[list[date], int, str]:
    if not raw.startswith(b"%PDF-"):
        raise ValueError("archive payload is not a PDF")
    reader = PdfReader(BytesIO(raw))
    text = "\n".join(
        page.extract_text(extraction_mode="layout") or "" for page in reader.pages
    )
    return parse_schedule_text(text), len(reader.pages), sha256_bytes(text.encode())


def prior_sessions(capture_date: date, auction_date: date) -> int:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(capture_date), pd.Timestamp(auction_date)
    )
    return int((sessions < pd.Timestamp(auction_date)).sum())


def official_two_year_dates(manifest: pd.DataFrame) -> set[date]:
    target = manifest[
        manifest["security_type"].eq("Note")
        & manifest["security_term"].eq("2-Year")
        & manifest["floating_rate"].eq("No")
    ].copy()
    return set(pd.to_datetime(target["auction_date"]).dt.date)


def unmatched_capture_dates(
    manifest: pd.DataFrame, captures: list[dict[str, Any]]
) -> list[date]:
    official = official_two_year_dates(manifest)
    return sorted(
        {
            event
            for capture in captures
            for event in capture["events"]
            if event not in official
        }
    )


def summarize(
    manifest: pd.DataFrame,
    captures: list[dict[str, Any]],
    manifest_sha256: str,
    cdx_sha256: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    unmatched_dates = unmatched_capture_dates(manifest, captures)
    target = manifest[
        manifest["security_type"].eq("Note")
        & manifest["security_term"].eq("2-Year")
        & manifest["floating_rate"].eq("No")
    ].copy()
    target["auction_date"] = pd.to_datetime(target["auction_date"]).dt.date
    target = target[target["auction_date"].between(START, END)].copy()

    evidence = []
    for capture in captures:
        capture_date = datetime.strptime(
            capture["timestamp"], "%Y%m%d%H%M%S"
        ).replace(tzinfo=UTC).date()
        for auction_date in capture["events"]:
            sessions = prior_sessions(capture_date, auction_date)
            evidence.append(
                {
                    "auction_date": auction_date,
                    "capture_timestamp": capture["timestamp"],
                    "capture_date": capture_date,
                    "published_pre_auction_sessions": sessions,
                    "eligible_ten_session_proof": sessions >= MIN_PRIOR_SESSIONS,
                    "archive_url": capture["archive_url"],
                    "archive_sha256": capture["archive_sha256"],
                    "extracted_text_sha256": capture["extracted_text_sha256"],
                    "pdf_pages": capture["pdf_pages"],
                    "cdx_digest": capture["cdx_digest"],
                }
            )
    evidence_frame = pd.DataFrame(evidence)
    eligible = evidence_frame[
        evidence_frame["eligible_ten_session_proof"]
    ].sort_values(["auction_date", "capture_timestamp"])
    proof = eligible.drop_duplicates("auction_date", keep="first")
    joined = target.merge(proof, on="auction_date", how="left", validate="one_to_one")
    bound = joined["archive_sha256"].notna()
    gates = {
        "cdx_capture_index_nonempty": bool(captures),
        "all_capture_payloads_hash_bound": all(row["archive_sha256"] for row in captures),
        "all_extracted_text_hash_bound": all(
            row["extracted_text_sha256"] for row in captures
        ),
        "unmatched_tentative_dates_excluded_from_proof": True,
        "every_2013_through_2020q1_auction_has_ten_session_proof": bool(len(joined))
        and bool(bound.all()),
        "manifest_auction_dates_unique": bool(target["auction_date"].is_unique),
        "return_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    missing = sorted(str(value) for value in joined.loc[~bound, "auction_date"])
    result = {
        "schema": "canli.feasibility.treasury-wayback-pdf-schedule-lineage.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "authenticated_archive_pdf_schedule_lineage_no_prices_no_returns",
        "cdx_url": CDX,
        "original_treasury_schedule_url": ORIGINAL,
        "cdx_sha256": cdx_sha256,
        "source_manifest_sha256": manifest_sha256,
        "pypdf_version": pypdf.__version__,
        "target_period": [str(START), str(END)],
        "archive_captures": len(captures),
        "target_fixed_rate_two_year_auctions": len(joined),
        "ten_session_schedule_bound_auctions": int(bound.sum()),
        "ten_session_schedule_coverage_rate": float(bound.mean()) if len(joined) else 0.0,
        "missing_auction_dates": missing,
        "excluded_unmatched_tentative_dates": list(map(str, unmatched_dates)),
        "minimum_prior_sessions_bound": (
            int(joined.loc[bound, "published_pre_auction_sessions"].min())
            if bound.any()
            else None
        ),
        "gates": gates,
        "decision": (
            "PASS_TO_COMBINED_CALENDAR_AUDIT"
            if all(gates.values())
            else "CALENDAR_LINEAGE_REQUIRED"
        ),
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
    }
    return result, joined


def collect(raw_dir: Path) -> tuple[bytes, list[dict[str, Any]]]:
    cdx_path = raw_dir / "auctions_pdf_cdx.json"
    if cdx_path.exists():
        cdx_raw = cdx_path.read_bytes()
    else:
        cdx_raw = request_bytes(
            CDX,
            {
                "url": ORIGINAL,
                "output": "json",
                "filter": ["statuscode:200", "mimetype:application/pdf"],
                "from": "2013",
                "to": "2020",
                "fl": "timestamp,original,digest,statuscode,mimetype",
                "collapse": "digest",
            },
        )
        atomic_write(cdx_path, cdx_raw)
    captures = []
    for row in parse_cdx(cdx_raw):
        path = raw_dir / f"{row['timestamp']}-auctions.pdf"
        archive_url = (
            f"https://web.archive.org/web/{row['timestamp']}id_/"
            f"{row['original']}"
        )
        if path.exists():
            raw = path.read_bytes()
        else:
            raw = request_bytes(archive_url)
            atomic_write(path, raw)
        events, pages, text_sha256 = parse_schedule_pdf(raw)
        captures.append(
            {
                **row,
                "events": events,
                "pdf_pages": pages,
                "extracted_text_sha256": text_sha256,
                "archive_url": archive_url,
                "archive_sha256": sha256_bytes(raw),
            }
        )
    return cdx_raw, captures


def run(
    manifest_path: Path,
    raw_dir: Path,
    events_path: Path,
    result_path: Path,
) -> dict[str, Any]:
    cdx_raw, captures = collect(raw_dir)
    manifest = pd.read_parquet(manifest_path)
    result, events = summarize(
        manifest,
        captures,
        sha256_bytes(manifest_path.read_bytes()),
        sha256_bytes(cdx_raw),
    )
    events_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_events = events_path.with_suffix(events_path.suffix + ".tmp")
    events.to_parquet(temporary_events, index=False, compression="zstd")
    temporary_events.replace(events_path)
    result["events_file"] = str(events_path)
    result["events_sha256"] = sha256_bytes(events_path.read_bytes())
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_result = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary_result.write_text(json.dumps(result, indent=2) + "\n")
    temporary_result.replace(result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--events", type=Path, default=EVENTS_OUT)
    parser.add_argument("--result", type=Path, default=RESULT)
    args = parser.parse_args()
    result = run(args.manifest, args.raw_dir, args.events, args.result)
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "PASS_TO_COMBINED_CALENDAR_AUDIT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
