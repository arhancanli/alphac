#!/usr/bin/env python3
"""Measure whether the CFTC feasibility protocol's release-lineage gate is reachable."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent
FEASIBILITY: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "cftc_hedging_pressure" / "result.json"
)
EVENTS: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "cftc_hedging_pressure" / "events.parquet"
)
LINEAGE: Final[Path] = REPO / "config" / "sleeve_family_lineage.json"
OUT: Final[Path] = (
    REPO / "artifacts" / "analysis" / "cftc_release_reachability" / "result.json"
)
CFTC_COT_PAGE: Final[str] = (
    "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"
)
CFTC_SPECIAL_ANNOUNCEMENTS: Final[str] = (
    "https://www.cftc.gov/MarketReports/CommitmentsofTraders/"
    "HistoricalSpecialAnnouncements/index.htm"
)
AVAILABLE_RELEASE_MONTHS: Final[int] = 13


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def build() -> dict[str, Any]:
    feasibility = json.loads(FEASIBILITY.read_text(encoding="utf-8"))
    lineage = json.loads(LINEAGE.read_text(encoding="utf-8"))["families"][
        "cftc_hedging_pressure"
    ]
    frame = pd.read_parquet(EVENTS, columns=["report_date", "event_identity"])
    report_dates = pd.to_datetime(frame["report_date"], errors="raise")
    last = report_dates.max()
    first = report_dates.min()
    cutoff = last - pd.DateOffset(months=AVAILABLE_RELEASE_MONTHS)
    recent = frame.loc[report_dates >= cutoff]
    total_dates = int(report_dates.nunique())
    recent_dates = int(pd.to_datetime(recent["report_date"]).nunique())
    row_ceiling = len(recent) / len(frame)
    date_ceiling = recent_dates / total_dates
    required = 0.95
    if feasibility["gates"]["exact_historical_release_lineage"] is not False:
        raise RuntimeError("the preregistered exact-release gate no longer fails")
    if feasibility["exact_release_timestamp_lineage_rate"] != 0.0:
        raise RuntimeError("the observed release-lineage rate changed")
    if lineage["classification"] != "RETIRED_KILLED" or lineage["aliases"] != [
        "cot_positioning"
    ]:
        raise RuntimeError("CFTC family lineage no longer binds the killed COT campaign")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-cftc-release-reachability.v1",
        "author": "Arhan Canli",
        "family": "cftc_hedging_pressure",
        "decision": "UNREACHABLE_AS_PREREGISTERED",
        "verdict": "HISTORICAL_RELEASE_LINEAGE_CEILING_BELOW_GATE",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "protocol_gate": {
            "name": "exact_historical_release_lineage",
            "required_rate": required,
            "observed_verified_rate": 0.0,
        },
        "official_record_constraint": {
            "source": CFTC_COT_PAGE,
            "retrieved_on": "2026-08-22",
            "historical_release_date_list_exists": False,
            "available_release_history_months": AVAILABLE_RELEASE_MONTHS,
            "normal_release_rule": "Friday 15:30 US Eastern for prior Tuesday data",
            "holiday_and_disruption_exceptions_exist": True,
            "special_announcement_source": CFTC_SPECIAL_ANNOUNCEMENTS,
        },
        "measured_ceiling": {
            "first_report_date": first.date().isoformat(),
            "last_report_date": last.date().isoformat(),
            "available_window_cutoff": cutoff.date().isoformat(),
            "total_rows": len(frame),
            "rows_in_best_case_available_window": len(recent),
            "row_weighted_exact_lineage_ceiling": row_ceiling,
            "total_distinct_report_dates": total_dates,
            "dates_in_best_case_available_window": recent_dates,
            "date_weighted_exact_lineage_ceiling": date_ceiling,
            "shortfall_to_required_rate": required - row_ceiling,
            "ceiling_assumption": (
                "Best case: every observation in the most recent 13 months can be matched to an "
                "exact release timestamp; no older observation can."
            ),
        },
        "lineage": {
            "classification": lineage["classification"],
            "aliases": lineage["aliases"],
            "evidence": lineage["evidence"],
            "feasibility_sha256": _sha256(FEASIBILITY),
            "events_sha256": _sha256(EVENTS),
            "lineage_registry_sha256": _sha256(LINEAGE),
        },
        "work_authorization": {
            "build_fixed_contract_mapping_now": False,
            "reason": (
                "A contract map cannot rescue an independently unreachable release-lineage gate, "
                "and the mechanism is already classified as a retired killed lineage."
            ),
            "permitted_future_branch": (
                "Only a preregistered identity redesign with a conservative availability rule "
                "and a documented distinction from the killed COT campaign. It would be a new "
                "trial family, not completion of this protocol."
            ),
        },
        "claim_boundary": (
            "This is a reachability audit over metadata only. It assumes the best possible exact "
            "coverage for the 13 months CFTC says are available, opens no position columns, prices "
            "or returns, and makes no claim about sign, edge, Sharpe, drawdown or diversification."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    print(payload["content_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
