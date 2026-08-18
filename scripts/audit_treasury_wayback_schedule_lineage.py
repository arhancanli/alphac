#!/usr/bin/env python3
"""Audit timestamped Internet Archive captures of Treasury's mutable auction XML.

This stage opens no prices or returns. A capture proves an auction date only from the archive
timestamp onward; events without ten prior XNYS sessions remain unbound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import exchange_calendars as xcals
import httpx
import pandas as pd

CDX: Final = "https://web.archive.org/cdx/search/cdx"
ORIGINAL: Final = (
    "https://www.treasury.gov/resource-center/data-chart-center/"
    "quarterly-refunding/Documents/auctions.xml"
)
MANIFEST: Final = Path("artifacts/feasibility/treasury_auction_concession/events.parquet")
RAW_DIR: Final = Path(
    "data/raw/treasury_auction_concession/wayback_tentative_schedule_archive"
)
EVENTS_OUT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/wayback_schedule_events.parquet"
)
RESULT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/wayback_schedule_audit.json"
)
START: Final = date(2013, 1, 1)
END: Final = date(2020, 4, 30)
MIN_PRIOR_SESSIONS: Final = 10
UA: Final = "Canli Capital quantitative research research@canlicapital.com"


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


def parse_schedule(raw: bytes) -> tuple[date, date, list[date]]:
    root = ET.fromstring(raw)
    start = date.fromisoformat(str(root.findtext("StartDate")))
    end = date.fromisoformat(str(root.findtext("EndDate")))
    events = []
    for node in root.findall("AuctionCalendarDate"):
        if (
            (node.findtext("SecurityTermWeekYear") or "").strip() == "2-Year"
            and (node.findtext("SecurityType") or "").strip() == "NOTE"
            and (node.findtext("TIPS") or "N").strip() == "N"
            and (node.findtext("FloatingRate") or "N").strip() == "N"
        ):
            events.append(date.fromisoformat(str(node.findtext("AuctionDate"))))
    return start, end, events


def prior_sessions(capture_date: date, auction_date: date) -> int:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(capture_date), pd.Timestamp(auction_date)
    )
    return int((sessions < pd.Timestamp(auction_date)).sum())


def summarize(
    manifest: pd.DataFrame,
    captures: list[dict[str, Any]],
    manifest_sha256: str,
    cdx_sha256: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    target = manifest[
        manifest["security_type"].eq("Note")
        & manifest["security_term"].eq("2-Year")
        & manifest["floating_rate"].eq("No")
    ].copy()
    target["auction_date"] = pd.to_datetime(target["auction_date"]).dt.date
    target = target[target["auction_date"].between(START, END)].copy()

    evidence = []
    capture_range_checks = []
    for capture in captures:
        capture_date = datetime.strptime(
            capture["timestamp"], "%Y%m%d%H%M%S"
        ).replace(tzinfo=UTC).date()
        capture_range_checks.append(
            capture["schedule_start_date"]
            <= capture_date
            <= capture["schedule_end_date"]
        )
        for auction_date in capture["events"]:
            sessions = prior_sessions(capture_date, auction_date)
            evidence.append(
                {
                    "auction_date": auction_date,
                    "capture_timestamp": capture["timestamp"],
                    "capture_date": capture_date,
                    "published_pre_auction_sessions": sessions,
                    "eligible_ten_session_proof": sessions >= MIN_PRIOR_SESSIONS,
                    "schedule_start_date": capture["schedule_start_date"],
                    "schedule_end_date": capture["schedule_end_date"],
                    "archive_url": capture["archive_url"],
                    "archive_sha256": capture["archive_sha256"],
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
    capture_ranges_valid = all(capture_range_checks)
    gates = {
        "cdx_capture_index_nonempty": bool(captures),
        "all_capture_payloads_hash_bound": all(row["archive_sha256"] for row in captures),
        "capture_timestamps_inside_schedule_ranges": capture_ranges_valid,
        "every_2013_through_2020q1_auction_has_ten_session_proof": bool(len(joined))
        and bool(bound.all()),
        "manifest_auction_dates_unique": bool(target["auction_date"].is_unique),
        "return_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    missing = sorted(str(value) for value in joined.loc[~bound, "auction_date"])
    result = {
        "schema": "canli.feasibility.treasury-wayback-schedule-lineage.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "authenticated_archive_schedule_lineage_no_prices_no_returns",
        "cdx_url": CDX,
        "original_treasury_schedule_url": ORIGINAL,
        "cdx_sha256": cdx_sha256,
        "source_manifest_sha256": manifest_sha256,
        "target_period": [str(START), str(END)],
        "archive_captures": len(captures),
        "target_fixed_rate_two_year_auctions": len(joined),
        "ten_session_schedule_bound_auctions": int(bound.sum()),
        "ten_session_schedule_coverage_rate": float(bound.mean()) if len(joined) else 0.0,
        "missing_auction_dates": missing,
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
    cdx_path = raw_dir / "auctions_xml_cdx.json"
    if cdx_path.exists():
        cdx_raw = cdx_path.read_bytes()
    else:
        cdx_raw = request_bytes(
            CDX,
            {
                "url": ORIGINAL,
                "output": "json",
                "filter": ["statuscode:200", "mimetype:text/xml"],
                "from": "2013",
                "to": "2020",
                "fl": "timestamp,original,digest,statuscode,mimetype",
                "collapse": "digest",
            },
        )
        atomic_write(cdx_path, cdx_raw)
    captures = []
    for row in parse_cdx(cdx_raw):
        path = raw_dir / f"{row['timestamp']}-auctions.xml"
        archive_url = (
            f"https://web.archive.org/web/{row['timestamp']}id_/"
            f"{row['original']}"
        )
        if path.exists():
            raw = path.read_bytes()
        else:
            raw = request_bytes(archive_url)
            atomic_write(path, raw)
        start, end, events = parse_schedule(raw)
        captures.append(
            {
                **row,
                "schedule_start_date": start,
                "schedule_end_date": end,
                "events": events,
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
    events.to_parquet(events_path, index=False, compression="zstd")
    result["events_file"] = str(events_path)
    result["events_sha256"] = sha256_bytes(events_path.read_bytes())
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n")
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
