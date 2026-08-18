#!/usr/bin/env python3
"""Check whether formal auction announcements support the published 10-day identity."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

MANIFEST: Final = Path("artifacts/feasibility/treasury_auction_concession/events.parquet")
RESULT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/identity_timing.json"
)
PUBLISHED_PRE_AUCTION_SESSIONS: Final = 10
MIN_TWO_YEAR_EVENTS: Final = 300


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(frame: pd.DataFrame, manifest_sha256: str) -> dict[str, Any]:
    eligible = frame[
        frame["security_type"].eq("Note")
        & frame["security_term"].eq("2-Year")
        & frame["floating_rate"].eq("No")
    ].copy()
    lead_days = (eligible["auction_date"] - eligible["announcement_date"]).dt.days
    events = len(eligible)
    at_least_ten_calendar_days = int(lead_days.ge(PUBLISHED_PRE_AUCTION_SESSIONS).sum())
    rates = {
        f"at_least_{days}_calendar_days": float(lead_days.ge(days).mean()) if events else 0.0
        for days in [2, 5, 7, 10]
    }
    gates = {
        "minimum_two_year_events": events >= MIN_TWO_YEAR_EVENTS,
        "formal_notice_supports_published_ten_session_entry": (
            at_least_ten_calendar_days == events and events > 0
        ),
        "point_in_time_tentative_schedule_archive_sealed": False,
    }
    return {
        "schema": "canli.feasibility.treasury-auction-identity-timing.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "announcement_timing_only_no_prices_no_returns",
        "source_manifest_sha256": manifest_sha256,
        "published_pre_auction_sessions": PUBLISHED_PRE_AUCTION_SESSIONS,
        "two_year_note_auctions": events,
        "announcement_lead_calendar_days": {
            "minimum": int(lead_days.min()) if events else None,
            "median": float(lead_days.median()) if events else None,
            "maximum": int(lead_days.max()) if events else None,
            **rates,
        },
        "formal_announcements_with_at_least_ten_calendar_days": at_least_ten_calendar_days,
        "gates": gates,
        "decision": "CALENDAR_LINEAGE_REQUIRED",
        "next_required_artifact": (
            "Point-in-time archive of six-month tentative auction schedules released at "
            "each Treasury quarterly refunding."
        ),
        "return_hypotheses_spent": 0,
    }


def run(manifest_path: Path, result_path: Path) -> dict[str, Any]:
    frame = pd.read_parquet(manifest_path)
    result = summarize(frame, sha256_file(manifest_path))
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--result", type=Path, default=RESULT)
    args = parser.parse_args()
    print(json.dumps(run(args.manifest, args.result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
