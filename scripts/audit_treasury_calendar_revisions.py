#!/usr/bin/env python3
"""Classify unresolved Treasury auction dates without opening prices or returns.

The audit distinguishes genuine tentative-calendar changes from late/post-event archive captures
and complete capture gaps. It does not infer publication times: only archive timestamps and the
official announcement date in the sealed Treasury event manifest are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from runpy import run_path
from typing import Any, Final

import exchange_calendars as xcals
import pandas as pd

MANIFEST: Final = Path("artifacts/feasibility/treasury_auction_concession/events.parquet")
COMBINED_AUDIT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/tentative_schedule_audit.json"
)
XML_RAW_DIR: Final = Path(
    "data/raw/treasury_auction_concession/wayback_tentative_schedule_archive"
)
PDF_RAW_DIR: Final = Path(
    "data/raw/treasury_auction_concession/wayback_tentative_schedule_pdf_archive"
)
RESULT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/calendar_revision_audit.json"
)
MIN_PRIOR_SESSIONS: Final = 10


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def prior_sessions(publication_date: date, auction_date: date) -> int:
    if publication_date >= auction_date:
        return 0
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(publication_date), pd.Timestamp(auction_date)
    )
    return int((sessions < pd.Timestamp(auction_date)).sum())


def summarize(
    manifest: pd.DataFrame,
    evidence: pd.DataFrame,
    missing_dates: list[date],
) -> dict[str, Any]:
    target = manifest[
        manifest["security_type"].eq("Note")
        & manifest["security_term"].eq("2-Year")
        & manifest["floating_rate"].eq("No")
    ].copy()
    target["auction_date"] = pd.to_datetime(target["auction_date"]).dt.date
    target["announcement_date"] = pd.to_datetime(target["announcement_date"]).dt.date
    if not target["auction_date"].is_unique:
        raise ValueError("official fixed-rate 2-year auction dates are not unique")
    evidence = evidence.copy()
    evidence["capture_date"] = pd.to_datetime(evidence["capture_date"]).dt.date
    evidence["tentative_auction_date"] = pd.to_datetime(
        evidence["tentative_auction_date"]
    ).dt.date

    cases = []
    for auction_date in sorted(missing_dates):
        rows = target[target["auction_date"].eq(auction_date)]
        if len(rows) != 1:
            raise ValueError(f"missing audit date absent or ambiguous in manifest: {auction_date}")
        announcement_date = rows.iloc[0]["announcement_date"]
        exact = evidence[evidence["tentative_auction_date"].eq(auction_date)].copy()
        same_month = evidence[
            evidence["tentative_auction_date"].map(
                lambda value, target=auction_date: value.year == target.year
                and value.month == target.month
                and value != target
            )
        ].copy()
        exact_sessions = [
            prior_sessions(value, auction_date) for value in exact["capture_date"]
        ]
        alternate_rows = []
        for tentative_date, group in same_month.groupby("tentative_auction_date"):
            lead = max(
                prior_sessions(value, auction_date) for value in group["capture_date"]
            )
            alternate_rows.append(
                {
                    "tentative_auction_date": str(tentative_date),
                    "maximum_capture_lead_sessions_to_actual": lead,
                    "sources": sorted(set(group["source"])),
                }
            )
        has_prior_alternate = any(
            row["maximum_capture_lead_sessions_to_actual"] >= MIN_PRIOR_SESSIONS
            for row in alternate_rows
        )
        maximum_exact = max(exact_sessions, default=None)
        if has_prior_alternate:
            classification = "TENTATIVE_DATE_CHANGED"
        elif maximum_exact is not None and 0 < maximum_exact < MIN_PRIOR_SESSIONS:
            classification = "EXACT_DATE_ONLY_LATE_CAPTURE"
        elif maximum_exact is not None:
            classification = "EXACT_DATE_ONLY_POST_EVENT_CAPTURE"
        else:
            classification = "NO_CAPTURED_MONTH_SCHEDULE"
        cases.append(
            {
                "auction_date": str(auction_date),
                "announcement_date": str(announcement_date),
                "announcement_lead_sessions": prior_sessions(
                    announcement_date, auction_date
                ),
                "maximum_exact_archive_lead_sessions": maximum_exact,
                "alternate_tentative_dates": alternate_rows,
                "classification": classification,
            }
        )

    counts = pd.Series([case["classification"] for case in cases]).value_counts()
    classifications = {
        key: int(counts.get(key, 0))
        for key in (
            "TENTATIVE_DATE_CHANGED",
            "EXACT_DATE_ONLY_LATE_CAPTURE",
            "EXACT_DATE_ONLY_POST_EVENT_CAPTURE",
            "NO_CAPTURED_MONTH_SCHEDULE",
        )
    }
    gates = {
        "all_unresolved_dates_classified": len(cases) == len(missing_dates),
        "all_formal_announcements_below_ten_session_entry": all(
            case["announcement_lead_sessions"] < MIN_PRIOR_SESSIONS for case in cases
        ),
        "exact_ten_session_identity_observable_for_all_dates": False,
        "return_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    return {
        "schema": "canli.feasibility.treasury-calendar-revisions.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "calendar_revision_classification_no_prices_no_returns",
        "unresolved_auction_dates": len(cases),
        "classifications": classifications,
        "cases": cases,
        "gates": gates,
        "decision": "IDENTITY_NOT_OBSERVABLE_AS_PREREGISTERED",
        "required_redesign": (
            "A point-in-time schedule-revision state machine with explicit cancel, roll, and "
            "late-announcement behavior; otherwise retire the ten-session identity."
        ),
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
    }


def collect_evidence(xml_raw_dir: Path, pdf_raw_dir: Path) -> tuple[pd.DataFrame, str]:
    scripts_dir = Path(__file__).resolve().parent
    xml_module = run_path(str(scripts_dir / "audit_treasury_wayback_schedule_lineage.py"))
    pdf_module = run_path(
        str(scripts_dir / "audit_treasury_wayback_pdf_schedule_lineage.py")
    )
    rows = []
    corpus = []
    for path in sorted(xml_raw_dir.glob("*-auctions.xml")):
        timestamp = path.name[:14]
        capture_date = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=UTC
        ).date()
        raw = path.read_bytes()
        _, _, events = xml_module["parse_schedule"](raw)
        digest = sha256_bytes(raw)
        corpus.append({"path": str(path), "sha256": digest})
        rows.extend(
            {
                "source": "archived_xml",
                "capture_date": capture_date,
                "tentative_auction_date": event,
                "payload_sha256": digest,
            }
            for event in events
        )
    for path in sorted(pdf_raw_dir.glob("*-auctions.pdf")):
        timestamp = path.name[:14]
        capture_date = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=UTC
        ).date()
        raw = path.read_bytes()
        events, _, _ = pdf_module["parse_schedule_pdf"](raw)
        digest = sha256_bytes(raw)
        corpus.append({"path": str(path), "sha256": digest})
        rows.extend(
            {
                "source": "archived_pdf",
                "capture_date": capture_date,
                "tentative_auction_date": event,
                "payload_sha256": digest,
            }
            for event in events
        )
    canonical = json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode()
    return pd.DataFrame(rows), sha256_bytes(canonical)


def run(
    manifest_path: Path,
    combined_audit_path: Path,
    xml_raw_dir: Path,
    pdf_raw_dir: Path,
    result_path: Path,
) -> dict[str, Any]:
    combined = json.loads(combined_audit_path.read_text())
    missing_dates = [
        date.fromisoformat(value) for value in combined["combined_missing_auction_dates"]
    ]
    evidence, corpus_sha256 = collect_evidence(xml_raw_dir, pdf_raw_dir)
    result = summarize(pd.read_parquet(manifest_path), evidence, missing_dates)
    result["source_manifest_sha256"] = sha256_file(manifest_path)
    result["source_combined_audit_sha256"] = sha256_file(combined_audit_path)
    result["archive_corpus_sha256"] = corpus_sha256
    result["archive_evidence_rows"] = len(evidence)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--combined-audit", type=Path, default=COMBINED_AUDIT)
    parser.add_argument("--xml-raw-dir", type=Path, default=XML_RAW_DIR)
    parser.add_argument("--pdf-raw-dir", type=Path, default=PDF_RAW_DIR)
    parser.add_argument("--result", type=Path, default=RESULT)
    args = parser.parse_args()
    result = run(
        args.manifest,
        args.combined_audit,
        args.xml_raw_dir,
        args.pdf_raw_dir,
        args.result,
    )
    print(json.dumps(result, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
