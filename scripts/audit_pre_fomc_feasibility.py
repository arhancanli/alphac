#!/usr/bin/env python3
"""No-return feasibility audit for the pre-FOMC announcement-drift candidate.

Only official Federal Reserve calendar/statement metadata are opened.  No market prices, returns,
signals, position weights, or performance statistics are read.  The audit separates exact event
and release-clock coverage from the harder point-in-time question: when a tentative meeting date
or revision first became knowable.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "pre_fomc_announcement_drift"
OUT = ROOT / "artifacts" / "feasibility" / "pre_fomc_announcement_drift"
CURRENT_CALENDAR = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
HISTORICAL = {
    year: f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
    for year in range(2016, 2021)
}
YEAR_MIN = 2016
YEAR_MAX = 2025
USER_AGENT = "CanliCapital-Research/1.0 research@canlicapital.com"

_STATEMENT = re.compile(
    r'href=["\'](?P<href>/newsevents/pressreleases/monetary(?P<date>20\d{6})a\.htm)["\']',
    re.I,
)
_HISTORICAL_SECTION = re.compile(
    r'<h5[^>]*panel-heading--shaded[^>]*>(?P<head>.*?)</h5>(?P<body>.*?)(?=<h5[^>]*panel-heading--shaded|\Z)',
    re.I | re.S,
)
_RELEASE_TIME = re.compile(
    r'<p[^>]*class=["\'][^"\']*releaseTime[^"\']*["\'][^>]*>(?P<text>.*?)</p>',
    re.I | re.S,
)


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _clean(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _date_from_compact(value: str) -> dt.date:
    return dt.date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")


def parse_historical_scheduled(page: str, source_url: str) -> list[dict[str, str]]:
    """Extract regular meeting statement links; exclude conference calls/emergency actions."""
    rows: list[dict[str, str]] = []
    for section in _HISTORICAL_SECTION.finditer(page):
        heading = _clean(section.group("head"))
        heading_lower = heading.lower()
        if (
            "meeting" not in heading_lower
            or "conference call" in heading_lower
            or "(unscheduled)" in heading_lower
        ):
            continue
        links = list(_STATEMENT.finditer(section.group("body")))
        if not links:
            continue
        link = links[0]
        rows.append(
            {
                "decision_date": _date_from_compact(link.group("date")).isoformat(),
                "statement_url": "https://www.federalreserve.gov" + link.group("href"),
                "source_url": source_url,
                "source_heading": heading,
            }
        )
    return rows


def parse_current_completed(page: str, source_url: str) -> list[dict[str, str]]:
    """Extract completed regular statements from the 2021+ calendar page."""
    rows: dict[str, dict[str, str]] = {}
    for link in _STATEMENT.finditer(page):
        date = _date_from_compact(link.group("date"))
        if not (2021 <= date.year <= YEAR_MAX):
            continue
        # The calendar also publishes notation votes and strategy statements inside meeting-like
        # rows.  They are policy communications, not scheduled decision announcements.
        if "notation vote" in page[max(0, link.start() - 400) : link.start()].lower():
            continue
        url = "https://www.federalreserve.gov" + link.group("href")
        rows[url] = {
            "decision_date": date.isoformat(),
            "statement_url": url,
            "source_url": source_url,
            "source_heading": f"{date.year} regular meeting calendar",
        }
    return list(rows.values())


def parse_release_time(page: str) -> str | None:
    match = _RELEASE_TIME.search(page)
    return _clean(match.group("text")) if match else None


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    retrieved_at = dt.datetime.now(dt.UTC).isoformat()

    source_bytes = {CURRENT_CALENDAR: _fetch(CURRENT_CALENDAR)}
    for _, url in HISTORICAL.items():
        source_bytes[url] = _fetch(url)
    rows = parse_current_completed(source_bytes[CURRENT_CALENDAR].decode("utf-8"), CURRENT_CALENDAR)
    for _, url in HISTORICAL.items():
        rows.extend(parse_historical_scheduled(source_bytes[url].decode("utf-8"), url))
    rows = sorted(
        {row["statement_url"]: row for row in rows}.values(),
        key=lambda row: row["decision_date"],
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        statement_bytes = dict(zip(
            (row["statement_url"] for row in rows),
            pool.map(_fetch, (row["statement_url"] for row in rows)),
            strict=True,
        ))

    events: list[dict[str, Any]] = []
    for row in rows:
        raw = statement_bytes[row["statement_url"]]
        release_text = parse_release_time(raw.decode("utf-8"))
        events.append(
            {
                **row,
                "release_time_text": release_text,
                "release_at_2pm_et": bool(
                    release_text and re.search(r"\b2:00\s+p\.m\.\s+E[DS]T\b", release_text, re.I)
                ),
                "statement_sha256": hashlib.sha256(raw).hexdigest(),
                "retrieved_at": retrieved_at,
            }
        )

    frame = pd.DataFrame(events).sort_values("decision_date")
    frame.to_parquet(OUT / "events.parquet", index=False)
    source_manifest = {
        "retrieved_at": retrieved_at,
        "sources": [
            {"url": url, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            for url, raw in sorted(source_bytes.items())
        ],
        "statement_sources": [
            {"url": url, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            for url, raw in sorted(statement_bytes.items())
        ],
    }
    (RAW / "source_manifest.json").write_text(json.dumps(source_manifest, indent=2) + "\n")

    year_counts = {
        str(year): int((pd.to_datetime(frame["decision_date"]).dt.year == year).sum())
        for year in range(YEAR_MIN, YEAR_MAX + 1)
    }
    release_coverage = float(frame["release_time_text"].notna().mean()) if len(frame) else 0.0
    two_pm_rate = float(frame["release_at_2pm_et"].mean()) if len(frame) else 0.0
    result = {
        "schema": "canli.feasibility.pre-fomc-announcement-drift.v1",
        "candidate": "pre_fomc_announcement_drift",
        "generated_at": retrieved_at,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "scheduled_events": len(frame),
        "period_start": str(frame["decision_date"].min()),
        "period_end": str(frame["decision_date"].max()),
        "year_counts": year_counts,
        "years_with_eight_regular_decisions": sum(count == 8 for count in year_counts.values()),
        "documented_2020_regular_decisions": year_counts["2020"],
        "release_time_coverage_rate": release_coverage,
        "release_at_2pm_et_rate": two_pm_rate,
        "point_in_time_schedule_revision_lineage_rate": 0.0,
        "decision": "CALENDAR_LINEAGE_REQUIRED",
        "blockers": ["point_in_time_schedule_revision_lineage"],
        "reason": (
            "Official archives identify regular decision dates and release clocks, but the live "
            "calendar says future meetings are tentative until confirmed at the preceding meeting. "
            "The ex-post pages do not provide a complete first-known/revision history. "
            "Returns remain locked."
        ),
        "source_manifest_sha256": _canonical_hash(source_manifest),
        "events_sha256": _canonical_hash(events),
        "method": {
            "official_sources_only": True,
            "regular_meetings_only": True,
            "conference_calls_excluded": True,
            "prices_or_returns_read": False,
        },
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
