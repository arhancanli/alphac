#!/usr/bin/env python3
"""Seal Treasury tentative schedules and audit the published ten-session identity.

This stage downloads only official Treasury release pages and schedule XML. It never opens prices,
returns, positions, or curves. Missing historical schedules remain explicit lineage failures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final
from urllib.parse import urljoin

import exchange_calendars as xcals
import httpx
import pandas as pd

ARCHIVE_URL: Final = (
    "https://home.treasury.gov/policy-issues/financing-the-government/"
    "quarterly-refunding/quarterly-refunding-archives/"
    "official-remarks-on-quarterly-refunding-by-calendar-year"
)
SCHEDULE_URL: Final = (
    "https://home.treasury.gov/system/files/221/"
    "TentativeAuctionScheduleQ{quarter}{year}.xml"
)
UA: Final = "Canli Capital quantitative research arhancanli@icloud.com"
MANIFEST: Final = Path("artifacts/feasibility/treasury_auction_concession/events.parquet")
RAW_DIR: Final = Path("data/raw/treasury_auction_concession/tentative_schedule_archive")
EVENTS_OUT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/tentative_schedule_events.parquet"
)
RESULT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/tentative_schedule_audit.json"
)
WAYBACK_EVENTS: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/wayback_schedule_events.parquet"
)
WAYBACK_RESULT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/wayback_schedule_audit.json"
)
WAYBACK_PDF_EVENTS: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/wayback_pdf_schedule_events.parquet"
)
WAYBACK_PDF_RESULT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/wayback_pdf_schedule_audit.json"
)
START_YEAR: Final = 2013
END_YEAR: Final = 2025
PUBLISHED_PRE_AUCTION_SESSIONS: Final = 10
QUARTER_MONTHS: Final = {1: {1, 2}, 2: {4, 5}, 3: {7, 8}, 4: {10, 11}}


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


class TreasuryHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tokens: list[tuple[str, str | None]] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        self.times: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a":
            self._href = attributes.get("href")
            self._link_text = []
        elif tag == "time" and attributes.get("datetime"):
            self.times.append(str(attributes["datetime"]))

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._href is not None:
            self._link_text.append(text)
        else:
            self.tokens.append((text, None))

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = " ".join(" ".join(self._link_text).split())
            self.tokens.append((text, self._href))
            self._href = None
            self._link_text = []


def parse_archive_links(raw: bytes, base_url: str = ARCHIVE_URL) -> dict[tuple[int, int], str]:
    parser = TreasuryHtmlParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    started = False
    year: int | None = None
    links: dict[tuple[int, int], str] = {}
    quarter_pattern = re.compile(r"^([1-4])(?:st|nd|rd|th) Quarter")
    for text, href in parser.tokens:
        if "Official Remarks on Quarterly Refunding by Calendar Year" in text:
            started = True
        if not started:
            continue
        if href is None and re.fullmatch(r"20\d{2}", text):
            year = int(text)
            continue
        match = quarter_pattern.match(text)
        if year is None or href is None or match is None:
            continue
        key = (year, int(match.group(1)))
        resolved = urljoin(base_url, href)
        if (
            key in links
            and links[key] != resolved
            and START_YEAR <= year <= END_YEAR
        ):
            raise ValueError(f"duplicate Treasury archive quarter link: {key}")
        links.setdefault(key, resolved)
    return links


def parse_release_date(raw: bytes, year: int, quarter: int) -> date:
    parser = TreasuryHtmlParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    candidates = []
    for value in parser.times:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if parsed.year == year and parsed.month in QUARTER_MONTHS[quarter]:
            candidates.append(parsed)
    unique = sorted(set(candidates))
    if len(unique) != 1:
        raise ValueError(
            f"expected one {year} Q{quarter} release date, found {unique}"
        )
    return unique[0]


def parse_schedule(raw: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = ET.fromstring(raw)
    calendar_name = (root.findtext("AuctionCalendarName") or "").strip()
    start_date = date.fromisoformat(str(root.findtext("StartDate")))
    end_date = date.fromisoformat(str(root.findtext("EndDate")))
    events = []
    for node in root.findall("AuctionCalendarDate"):
        term = (node.findtext("SecurityTermWeekYear") or "").strip()
        security_type = (node.findtext("SecurityType") or "").strip()
        tips = (node.findtext("TIPS") or "N").strip()
        floating = (node.findtext("FloatingRate") or "N").strip()
        auction = node.findtext("AuctionDate")
        if term != "2-Year" or security_type != "NOTE" or tips != "N" or floating != "N":
            continue
        events.append(
            {
                "security_term": term,
                "security_type": security_type,
                "auction_date": date.fromisoformat(str(auction)),
                "announcement_date": date.fromisoformat(
                    str(node.findtext("AnnouncementDate"))
                ),
                "settlement_date": date.fromisoformat(
                    str(node.findtext("SettlementDate"))
                ),
            }
        )
    return (
        {
            "calendar_name": calendar_name,
            "start_date": start_date,
            "end_date": end_date,
        },
        events,
    )


def prior_sessions(release_date: date, auction_date: date) -> int:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(release_date), pd.Timestamp(auction_date)
    )
    return int((sessions < pd.Timestamp(auction_date)).sum())


def summarize(
    manifest: pd.DataFrame,
    documents: list[dict[str, Any]],
    manifest_sha256: str,
    archive_sha256: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    target = manifest[
        manifest["security_type"].eq("Note")
        & manifest["security_term"].eq("2-Year")
        & manifest["floating_rate"].eq("No")
    ].copy()
    target["auction_date"] = pd.to_datetime(target["auction_date"]).dt.date
    target = target[
        target["auction_date"].map(lambda value: START_YEAR <= value.year <= END_YEAR)
    ]

    schedule_rows = []
    for document in documents:
        if document["status"] != "available":
            continue
        for event in document["events"]:
            schedule_rows.append(
                {
                    **event,
                    "schedule_year": document["year"],
                    "schedule_quarter": document["quarter"],
                    "schedule_release_date": document["release_date"],
                    "schedule_url": document["schedule_url"],
                    "schedule_sha256": document["schedule_sha256"],
                    "release_page_url": document["release_page_url"],
                    "release_page_sha256": document["release_page_sha256"],
                }
            )
    schedule = pd.DataFrame(schedule_rows)
    if len(schedule):
        schedule = schedule.sort_values(
            ["auction_date", "schedule_release_date", "schedule_year", "schedule_quarter"]
        ).drop_duplicates("auction_date", keep="first")
        schedule["published_pre_auction_sessions"] = schedule.apply(
            lambda row: prior_sessions(
                row["schedule_release_date"], row["auction_date"]
            ),
            axis=1,
        )
    joined = target.merge(
        schedule,
        on="auction_date",
        how="left",
        suffixes=("_manifest", "_schedule"),
        validate="many_to_one",
    )
    matched = joined["schedule_sha256"].notna() if len(joined) else pd.Series(dtype=bool)
    enough_notice = (
        joined.loc[matched, "published_pre_auction_sessions"]
        .ge(PUBLISHED_PRE_AUCTION_SESSIONS)
        .all()
        if matched.any()
        else False
    )
    expected_quarters = {
        (year, quarter)
        for year in range(START_YEAR, END_YEAR + 1)
        for quarter in range(1, 5)
    }
    available_quarters = {
        (int(document["year"]), int(document["quarter"]))
        for document in documents
        if document["status"] == "available"
    }
    missing_quarters = sorted(expected_quarters - available_quarters)
    gates = {
        "official_archive_release_pages_bound": all(
            document.get("release_page_sha256")
            for document in documents
            if document["status"] == "available"
        ),
        "schedule_start_matches_release_date": all(
            document.get("schedule_start_date") == document.get("release_date")
            for document in documents
            if document["status"] == "available"
        ),
        "every_2013_2025_two_year_auction_schedule_bound": bool(len(joined))
        and bool(matched.all()),
        "manifest_two_year_auction_dates_unique": bool(
            target["auction_date"].is_unique
        ),
        "every_matched_event_supports_ten_prior_sessions": bool(enough_notice),
        "return_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    decision = (
        "PASS_TO_RETURN_PREREGISTRATION"
        if all(gates.values())
        else "CALENDAR_LINEAGE_REQUIRED"
    )
    result = {
        "schema": "canli.feasibility.treasury-tentative-schedule-archive.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_tentative_schedule_lineage_no_prices_no_returns",
        "source_manifest_sha256": manifest_sha256,
        "official_archive_url": ARCHIVE_URL,
        "official_archive_sha256": archive_sha256,
        "target_years": [START_YEAR, END_YEAR],
        "expected_quarters": len(expected_quarters),
        "available_schedule_quarters": len(available_quarters),
        "missing_schedule_quarters": [f"{year}Q{quarter}" for year, quarter in missing_quarters],
        "target_two_year_auctions": len(joined),
        "target_unique_auction_dates": int(target["auction_date"].nunique()),
        "ambiguous_manifest_auction_dates": sorted(
            str(value)
            for value in target.loc[
                target["auction_date"].duplicated(keep=False), "auction_date"
            ].unique()
        ),
        "schedule_bound_auctions": int(matched.sum()) if len(joined) else 0,
        "schedule_coverage_rate": float(matched.mean()) if len(joined) else 0.0,
        "first_schedule_bound_auction": (
            str(joined.loc[matched, "auction_date"].min()) if matched.any() else None
        ),
        "last_schedule_bound_auction": (
            str(joined.loc[matched, "auction_date"].max()) if matched.any() else None
        ),
        "minimum_prior_sessions_matched": (
            int(joined.loc[matched, "published_pre_auction_sessions"].min())
            if matched.any()
            else None
        ),
        "gates": gates,
        "decision": decision,
        "next_required_artifact": (
            "Contemporaneous official or authenticated web-archive copies of the missing "
            "2013Q1-2020Q1 tentative schedules; do not shorten the return window silently."
        ),
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
    }
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["content_hash"] = f"sha256:{sha256_bytes(canonical)}"
    return result, joined


def augment_with_wayback(
    result: dict[str, Any],
    joined: pd.DataFrame,
    wayback_events: pd.DataFrame,
    wayback_result: dict[str, Any],
    manifest_sha256: str,
    wayback_events_sha256: str,
    wayback_result_sha256: str,
    wayback_pdf_events: pd.DataFrame | None = None,
    wayback_pdf_result: dict[str, Any] | None = None,
    wayback_pdf_events_sha256: str | None = None,
    wayback_pdf_result_sha256: str | None = None,
) -> dict[str, Any]:
    if wayback_result.get("source_manifest_sha256") != manifest_sha256:
        raise ValueError("Wayback audit source manifest does not match current Treasury manifest")
    if wayback_result.get("events_sha256") != wayback_events_sha256:
        raise ValueError("Wayback event artifact hash does not match its audit")
    wayback = wayback_events.copy()
    wayback["auction_date"] = pd.to_datetime(wayback["auction_date"]).dt.date
    wayback_bound_dates = set(
        wayback.loc[wayback["archive_sha256"].notna(), "auction_date"]
    )
    pdf_arguments = (
        wayback_pdf_events,
        wayback_pdf_result,
        wayback_pdf_events_sha256,
        wayback_pdf_result_sha256,
    )
    if any(value is not None for value in pdf_arguments) and not all(
        value is not None for value in pdf_arguments
    ):
        raise ValueError("Wayback PDF audit requires events, result, and both hashes")
    wayback_pdf_bound_dates: set[date] = set()
    if wayback_pdf_result is not None:
        assert wayback_pdf_events is not None
        assert wayback_pdf_events_sha256 is not None
        assert wayback_pdf_result_sha256 is not None
        if wayback_pdf_result.get("source_manifest_sha256") != manifest_sha256:
            raise ValueError(
                "Wayback PDF audit source manifest does not match current Treasury manifest"
            )
        if wayback_pdf_result.get("events_sha256") != wayback_pdf_events_sha256:
            raise ValueError("Wayback PDF event artifact hash does not match its audit")
        pdf_events = wayback_pdf_events.copy()
        pdf_events["auction_date"] = pd.to_datetime(pdf_events["auction_date"]).dt.date
        wayback_pdf_bound_dates = set(
            pdf_events.loc[pdf_events["archive_sha256"].notna(), "auction_date"]
        )
    official_bound = joined["schedule_sha256"].notna()
    combined_archive_dates = wayback_bound_dates | wayback_pdf_bound_dates
    combined_bound = official_bound | joined["auction_date"].isin(combined_archive_dates)
    missing = sorted(str(value) for value in joined.loc[~combined_bound, "auction_date"])
    result["official_xml_schedule_bound_auctions"] = int(official_bound.sum())
    result["wayback_ten_session_schedule_bound_auctions"] = len(wayback_bound_dates)
    result["wayback_pdf_ten_session_schedule_bound_auctions"] = len(
        wayback_pdf_bound_dates
    )
    result["wayback_archive_union_bound_auctions"] = len(combined_archive_dates)
    result["combined_schedule_bound_auctions"] = int(combined_bound.sum())
    result["combined_schedule_coverage_rate"] = (
        float(combined_bound.mean()) if len(joined) else 0.0
    )
    result["combined_missing_auction_dates"] = missing
    result["wayback_events_file"] = str(WAYBACK_EVENTS)
    result["wayback_events_sha256"] = wayback_events_sha256
    result["wayback_result_file"] = str(WAYBACK_RESULT)
    result["wayback_result_sha256"] = wayback_result_sha256
    result["wayback_cdx_sha256"] = wayback_result["cdx_sha256"]
    if wayback_pdf_result is not None:
        result["wayback_pdf_events_file"] = str(WAYBACK_PDF_EVENTS)
        result["wayback_pdf_events_sha256"] = wayback_pdf_events_sha256
        result["wayback_pdf_result_file"] = str(WAYBACK_PDF_RESULT)
        result["wayback_pdf_result_sha256"] = wayback_pdf_result_sha256
        result["wayback_pdf_cdx_sha256"] = wayback_pdf_result["cdx_sha256"]
    result["gates"]["every_2013_2025_two_year_auction_schedule_bound"] = bool(
        len(joined)
    ) and bool(combined_bound.all())
    result["decision"] = (
        "PASS_TO_RETURN_PREREGISTRATION"
        if all(result["gates"].values())
        else "CALENDAR_LINEAGE_REQUIRED"
    )
    result["next_required_artifact"] = (
        "Contemporaneous official or authenticated archive proof at least ten XNYS sessions "
        f"before the {len(missing)} remaining auction dates; do not shorten the return window."
    )
    return result


def fetch(client: httpx.Client, url: str) -> tuple[int, bytes]:
    last: httpx.Response | None = None
    for attempt in range(1, 4):
        try:
            response = client.get(url)
        except httpx.TransportError:
            if attempt == 3:
                raise
            time.sleep(float(attempt))
            continue
        last = response
        if response.status_code not in {429, 500, 502, 503, 504}:
            return response.status_code, response.content
        time.sleep(float(attempt))
    assert last is not None
    return last.status_code, last.content


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_dir = Path(args.raw_dir)
    archive_path = raw_dir / "official-remarks-archive.html"
    with httpx.Client(
        headers={"User-Agent": UA}, follow_redirects=True, timeout=60.0
    ) as client:
        if archive_path.exists():
            archive_raw = archive_path.read_bytes()
        else:
            status, archive_raw = fetch(client, ARCHIVE_URL)
            if status != 200:
                raise RuntimeError(f"Treasury archive returned HTTP {status}")
            atomic_write(archive_path, archive_raw)
        archive_links = parse_archive_links(archive_raw)
        required_links = {
            key: archive_links[key]
            for key in sorted(archive_links)
            if START_YEAR <= key[0] <= END_YEAR
        }
        expected = (END_YEAR - START_YEAR + 1) * 4
        if len(required_links) != expected:
            raise RuntimeError(
                f"Treasury archive exposed {len(required_links)}/{expected} quarter pages"
            )

        def collect(item: tuple[tuple[int, int], str]) -> dict[str, Any]:
            (year, quarter), release_url = item
            release_path = raw_dir / f"{year}Q{quarter}-release.html"
            if release_path.exists():
                release_raw = release_path.read_bytes()
            else:
                status, release_raw = fetch(client, release_url)
                if status != 200:
                    raise RuntimeError(f"{year}Q{quarter} release returned HTTP {status}")
                atomic_write(release_path, release_raw)
            release_date = parse_release_date(release_raw, year, quarter)
            schedule_url = SCHEDULE_URL.format(year=year, quarter=quarter)
            schedule_path = raw_dir / f"{year}Q{quarter}-schedule.xml"
            if schedule_path.exists():
                schedule_raw = schedule_path.read_bytes()
                schedule_status = 200
            else:
                schedule_status, schedule_raw = fetch(client, schedule_url)
                if schedule_status == 200:
                    atomic_write(schedule_path, schedule_raw)
            base = {
                "year": year,
                "quarter": quarter,
                "release_date": release_date,
                "release_page_url": release_url,
                "release_page_sha256": sha256_bytes(release_raw),
                "schedule_url": schedule_url,
            }
            if schedule_status == 404:
                return {**base, "status": "missing_official_xml", "events": []}
            if schedule_status != 200:
                raise RuntimeError(
                    f"{year}Q{quarter} schedule returned HTTP {schedule_status}"
                )
            metadata, events = parse_schedule(schedule_raw)
            return {
                **base,
                "status": "available",
                "schedule_sha256": sha256_bytes(schedule_raw),
                "schedule_start_date": metadata["start_date"],
                "schedule_end_date": metadata["end_date"],
                "calendar_name": metadata["calendar_name"],
                "events": events,
            }

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            documents = list(pool.map(collect, sorted(required_links.items())))

    manifest_path = Path(args.manifest)
    result, events = summarize(
        pd.read_parquet(manifest_path),
        documents,
        sha256_file(manifest_path),
        sha256_bytes(archive_raw),
    )
    wayback_events_path = Path(args.wayback_events)
    wayback_result_path = Path(args.wayback_result)
    if wayback_events_path.exists() and wayback_result_path.exists():
        wayback_pdf_events_path = Path(args.wayback_pdf_events)
        wayback_pdf_result_path = Path(args.wayback_pdf_result)
        pdf_exists = (
            wayback_pdf_events_path.exists() and wayback_pdf_result_path.exists()
        )
        result = augment_with_wayback(
            result,
            events,
            pd.read_parquet(wayback_events_path),
            json.loads(wayback_result_path.read_text()),
            sha256_file(manifest_path),
            sha256_file(wayback_events_path),
            sha256_file(wayback_result_path),
            (
                pd.read_parquet(wayback_pdf_events_path)
                if pdf_exists
                else None
            ),
            (
                json.loads(wayback_pdf_result_path.read_text())
                if pdf_exists
                else None
            ),
            sha256_file(wayback_pdf_events_path) if pdf_exists else None,
            sha256_file(wayback_pdf_result_path) if pdf_exists else None,
        )
    events_out = Path(args.events_out)
    events_out.parent.mkdir(parents=True, exist_ok=True)
    temporary_events = events_out.with_suffix(events_out.suffix + ".tmp")
    events.to_parquet(temporary_events, index=False, compression="zstd")
    temporary_events.replace(events_out)
    result["events_file"] = str(events_out)
    result["events_sha256"] = sha256_file(events_out)
    body = {key: value for key, value in result.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    result["content_hash"] = f"sha256:{sha256_bytes(canonical)}"
    result_path = Path(args.result)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_result = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary_result.write_text(json.dumps(result, indent=2, default=str) + "\n")
    temporary_result.replace(result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--events-out", default=str(EVENTS_OUT))
    parser.add_argument("--result", default=str(RESULT))
    parser.add_argument("--wayback-events", default=str(WAYBACK_EVENTS))
    parser.add_argument("--wayback-result", default=str(WAYBACK_RESULT))
    parser.add_argument("--wayback-pdf-events", default=str(WAYBACK_PDF_EVENTS))
    parser.add_argument("--wayback-pdf-result", default=str(WAYBACK_PDF_RESULT))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "PASS_TO_RETURN_PREREGISTRATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
