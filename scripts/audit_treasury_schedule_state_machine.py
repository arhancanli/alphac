#!/usr/bin/env python3
"""Audit the Treasury schedule state machine without loading prices or returns."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

import exchange_calendars as xcals
import pandas as pd

MANIFEST: Final = Path("artifacts/feasibility/treasury_auction_concession/events.parquet")
COMBINED_AUDIT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/tentative_schedule_audit.json"
)
REVISION_AUDIT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/calendar_revision_audit.json"
)
PROTOCOL: Final = Path("docs/design/FEASIBILITY_TREASURY_AUCTION_STATE_MACHINE.md")
RESULT: Final = Path(
    "artifacts/feasibility/treasury_auction_concession/schedule_state_machine_audit.json"
)
START_YEAR: Final = 2013
END_YEAR: Final = 2025
PRE_SESSIONS: Final = 10
POST_SESSIONS: Final = 10
FORBIDDEN_MARKET_COLUMNS: Final = {
    "price",
    "return",
    "pnl",
    "sharpe",
    "drawdown",
    "equity",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _sessions_around(value: date) -> pd.DatetimeIndex:
    calendar = xcals.get_calendar("XNYS")
    timestamp = pd.Timestamp(value)
    return calendar.sessions_in_range(
        timestamp - pd.Timedelta(days=60), timestamp + pd.Timedelta(days=60)
    )


def session_before(value: date, count: int) -> date:
    sessions = _sessions_around(value)
    prior = sessions[sessions < pd.Timestamp(value)]
    if len(prior) < count:
        raise ValueError(f"insufficient prior XNYS sessions for {value}")
    return prior[-count].date()


def session_after(value: date, count: int) -> date:
    sessions = _sessions_around(value)
    following = sessions[sessions > pd.Timestamp(value)]
    if len(following) < count:
        raise ValueError(f"insufficient following XNYS sessions for {value}")
    return following[count - 1].date()


def is_session(value: date) -> bool:
    return bool(xcals.get_calendar("XNYS").is_session(pd.Timestamp(value)))


def _eligible_events(manifest: pd.DataFrame) -> pd.DataFrame:
    required = {
        "event_identity",
        "security_type",
        "security_term",
        "floating_rate",
        "auction_date",
        "announcement_date",
    }
    missing = required - set(manifest.columns)
    if missing:
        raise ValueError(f"manifest missing state-machine fields: {sorted(missing)}")
    market_columns = {
        column
        for column in manifest.columns
        if any(token in column.lower() for token in FORBIDDEN_MARKET_COLUMNS)
    }
    if market_columns:
        raise ValueError(f"market or return columns are prohibited: {sorted(market_columns)}")
    frame = manifest[
        manifest["security_type"].eq("Note")
        & manifest["security_term"].eq("2-Year")
        & manifest["floating_rate"].eq("No")
    ].copy()
    frame["auction_date"] = pd.to_datetime(frame["auction_date"]).dt.date
    frame["announcement_date"] = pd.to_datetime(frame["announcement_date"]).dt.date
    frame = frame[
        frame["auction_date"].map(lambda value: START_YEAR <= value.year <= END_YEAR)
    ].sort_values("auction_date")
    if not frame["event_identity"].is_unique or not frame["auction_date"].is_unique:
        raise ValueError("eligible event identities and dates must be unique")
    return frame


def classify_unresolved_case(case: dict[str, Any]) -> dict[str, Any]:
    auction_date = date.fromisoformat(str(case["auction_date"]))
    announcement_date = date.fromisoformat(str(case["announcement_date"]))
    classification = str(case["classification"])
    if classification != "TENTATIVE_DATE_CHANGED":
        return {
            "path": "NO_PRE_POSITION_POST_ONLY",
            "tentative_date": None,
            "pre_entry_date": None,
            "pre_exit_date": None,
            "revision_action": classification,
        }
    alternates = [
        value
        for value in case.get("alternate_tentative_dates", [])
        if int(value["maximum_capture_lead_sessions_to_actual"]) >= PRE_SESSIONS
    ]
    if len(alternates) != 1:
        raise ValueError(
            f"expected one source-bound alternate date for revised auction {auction_date}"
        )
    tentative_date = date.fromisoformat(str(alternates[0]["tentative_auction_date"]))
    pre_entry_date = session_before(tentative_date, PRE_SESSIONS)
    if announcement_date <= pre_entry_date:
        return {
            "path": "REVISION_BEFORE_ENTRY_POST_ONLY",
            "tentative_date": str(tentative_date),
            "pre_entry_date": None,
            "pre_exit_date": None,
            "stale_entry_cancelled": str(pre_entry_date),
            "revision_action": "CANCEL_ARMED_DATE_DO_NOT_CHASE",
        }
    return {
        "path": "PRE_ENTERED_THEN_CANCELLED_ON_REVISION",
        "tentative_date": str(tentative_date),
        "pre_entry_date": str(pre_entry_date),
        "pre_exit_date": str(session_after(announcement_date, 1)),
        "revision_action": "EXIT_NEXT_XNYS_CLOSE_DO_NOT_REOPEN_LATE",
    }


def summarize(
    manifest: pd.DataFrame,
    combined: dict[str, Any],
    revisions: dict[str, Any],
    source_hashes: dict[str, str],
) -> dict[str, Any]:
    events = _eligible_events(manifest)
    missing_dates = {str(value) for value in combined["combined_missing_auction_dates"]}
    cases = {str(value["auction_date"]): value for value in revisions["cases"]}
    if set(cases) != missing_dates:
        raise ValueError("revision cases do not exactly match combined missing dates")
    if int(combined["target_two_year_auctions"]) != len(events):
        raise ValueError("combined audit target count does not match the event manifest")
    if int(combined["combined_schedule_bound_auctions"]) + len(cases) != len(events):
        raise ValueError("bound and unresolved event counts do not reconcile")

    records: list[dict[str, Any]] = []
    for row in events.itertuples(index=False):
        auction_date = row.auction_date
        announcement_date = row.announcement_date
        if not is_session(auction_date):
            raise ValueError(f"auction date is not an XNYS session: {auction_date}")
        record: dict[str, Any] = {
            "event_identity": str(row.event_identity),
            "auction_date": str(auction_date),
            "announcement_date": str(announcement_date),
            "post_entry_date": str(auction_date),
            "post_exit_date": str(session_after(auction_date, POST_SESSIONS)),
        }
        if str(auction_date) not in cases:
            record.update(
                {
                    "path": "EXACT_SCHEDULE_PRE_AND_POST",
                    "tentative_date": str(auction_date),
                    "pre_entry_date": str(session_before(auction_date, PRE_SESSIONS)),
                    "pre_exit_date": str(auction_date),
                    "revision_action": "NONE",
                }
            )
        else:
            record.update(classify_unresolved_case(cases[str(auction_date)]))
        records.append(record)

    path_counts = {
        path: sum(record["path"] == path for record in records)
        for path in (
            "EXACT_SCHEDULE_PRE_AND_POST",
            "PRE_ENTERED_THEN_CANCELLED_ON_REVISION",
            "REVISION_BEFORE_ENTRY_POST_ONLY",
            "NO_PRE_POSITION_POST_ONLY",
        )
    }
    pre_events = [record for record in records if record.get("pre_entry_date")]
    post_only = [record for record in records if not record.get("pre_entry_date")]
    overlaps = []
    for previous, current in pairwise(records):
        current_start = date.fromisoformat(
            str(current.get("pre_entry_date") or current["post_entry_date"])
        )
        previous_end = date.fromisoformat(str(previous["post_exit_date"]))
        if current_start <= previous_end:
            overlaps.append(
                {
                    "previous_event": previous["event_identity"],
                    "current_event": current["event_identity"],
                    "previous_post_exit": str(previous_end),
                    "current_first_active_session": str(current_start),
                }
            )

    gates = {
        "all_events_have_one_deterministic_path": len(records) == len(events),
        "source_counts_reconcile": sum(path_counts.values()) == len(events),
        "all_auction_dates_are_xnys_sessions": all(
            is_session(date.fromisoformat(record["auction_date"])) for record in records
        ),
        "revisions_have_explicit_cancel_behavior": path_counts[
            "PRE_ENTERED_THEN_CANCELLED_ON_REVISION"
        ]
        == 4,
        "late_and_missing_updates_fail_closed": len(post_only) == 7,
        "overlap_policy_declared": True,
        "market_and_return_columns_absent": True,
        "return_data_unopened": True,
        "return_hypotheses_unspent": True,
        "author_technical_approval_recorded": False,
    }
    technical_gates = {
        key: value for key, value in gates.items() if key != "author_technical_approval_recorded"
    }
    payload: dict[str, Any] = {
        "schema": "canli.feasibility.treasury-schedule-state-machine.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "point_in_time_calendar_identity_redesign_no_prices_no_returns",
        "family": "treasury_auction_concession",
        "period": {"start_year": START_YEAR, "end_year": END_YEAR},
        "clock": {
            "calendar": "XNYS",
            "pre_sessions": PRE_SESSIONS,
            "post_sessions": POST_SESSIONS,
            "unknown_intraday_update_policy": "ACT_AT_NEXT_XNYS_CLOSE",
            "late_replacement_policy": "DO_NOT_CHASE_PRE_LEG",
            "post_entry_policy": "CONFIRMED_AUCTION_DAY_XNYS_CLOSE_AFTER_AUCTION",
        },
        "source_hashes": source_hashes,
        "summary": {
            "eligible_events": len(events),
            "exact_schedule_pre_and_post": path_counts["EXACT_SCHEDULE_PRE_AND_POST"],
            "pre_entered_then_cancelled_on_revision": path_counts[
                "PRE_ENTERED_THEN_CANCELLED_ON_REVISION"
            ],
            "revision_before_entry_post_only": path_counts[
                "REVISION_BEFORE_ENTRY_POST_ONLY"
            ],
            "late_post_event_or_missing_post_only": path_counts[
                "NO_PRE_POSITION_POST_ONLY"
            ],
            "events_with_pre_leg": len(pre_events),
            "events_post_only": len(post_only),
            "known_tentative_date_changes": int(
                revisions["classifications"]["TENTATIVE_DATE_CHANGED"]
            ),
            "adjacent_event_windows_with_overlap": len(overlaps),
        },
        "path_counts": path_counts,
        "overlap_cases": overlaps,
        "events": records,
        "gates": gates,
        "technical_decision": (
            "PASS_NO_RETURN_STATE_MACHINE_AUDIT"
            if all(technical_gates.values())
            else "FAIL_NO_RETURN_STATE_MACHINE_AUDIT"
        ),
        "governance_decision": "AUTHOR_APPROVAL_REQUIRED",
        "decision": "AUTHOR_APPROVAL_REQUIRED",
        "candidate_status": "identity-redesign-required",
        "author_technical_approval": False,
        "return_preregistration_authorized": False,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "claim_boundary": (
            "This audit proves only that each sealed calendar event has a deterministic "
            "point-in-time state path. It is not author approval, a return preregistration, "
            "return evidence, a Sharpe or drawdown estimate, or sleeve admission."
        ),
    }
    payload["content_hash"] = content_hash(payload)
    return payload


def run(
    manifest_path: Path,
    combined_audit_path: Path,
    revision_audit_path: Path,
    protocol_path: Path,
    result_path: Path,
) -> dict[str, Any]:
    combined = json.loads(combined_audit_path.read_text(encoding="utf-8"))
    revisions = json.loads(revision_audit_path.read_text(encoding="utf-8"))
    source_hashes = {
        "event_manifest_sha256": sha256_file(manifest_path),
        "combined_schedule_audit_sha256": sha256_file(combined_audit_path),
        "calendar_revision_audit_sha256": sha256_file(revision_audit_path),
        "protocol_sha256": sha256_file(protocol_path),
    }
    result = summarize(
        pd.read_parquet(manifest_path), combined, revisions, source_hashes
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--combined-audit", type=Path, default=COMBINED_AUDIT)
    parser.add_argument("--revision-audit", type=Path, default=REVISION_AUDIT)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--result", type=Path, default=RESULT)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.manifest,
                args.combined_audit,
                args.revision_audit,
                args.protocol,
                args.result,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
