from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path

import pandas as pd
import pytest

REPO = Path(__file__).parents[2]
MODULE = run_path(str(REPO / "scripts" / "audit_treasury_schedule_state_machine.py"))


def test_revised_dates_cancel_or_skip_without_chasing() -> None:
    entered = MODULE["classify_unresolved_case"](
        {
            "auction_date": "2013-12-17",
            "announcement_date": "2013-12-12",
            "classification": "TENTATIVE_DATE_CHANGED",
            "alternate_tentative_dates": [
                {
                    "tentative_auction_date": "2013-12-16",
                    "maximum_capture_lead_sessions_to_actual": 83,
                }
            ],
        }
    )
    not_entered = MODULE["classify_unresolved_case"](
        {
            "auction_date": "2015-11-04",
            "announcement_date": "2015-10-30",
            "classification": "TENTATIVE_DATE_CHANGED",
            "alternate_tentative_dates": [
                {
                    "tentative_auction_date": "2015-11-23",
                    "maximum_capture_lead_sessions_to_actual": 41,
                }
            ],
        }
    )

    assert entered["path"] == "PRE_ENTERED_THEN_CANCELLED_ON_REVISION"
    assert entered["pre_entry_date"] == "2013-12-02"
    assert entered["pre_exit_date"] == "2013-12-13"
    assert not_entered["path"] == "REVISION_BEFORE_ENTRY_POST_ONLY"
    assert not_entered["pre_entry_date"] is None
    assert not_entered["stale_entry_cancelled"] == "2015-11-09"


@pytest.mark.workspace_evidence
def test_current_sealed_panel_has_one_fail_closed_path_per_event(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result = MODULE["run"](
        REPO / "artifacts/feasibility/treasury_auction_concession/events.parquet",
        REPO
        / "artifacts/feasibility/treasury_auction_concession/tentative_schedule_audit.json",
        REPO
        / "artifacts/feasibility/treasury_auction_concession/calendar_revision_audit.json",
        REPO / "docs/design/FEASIBILITY_TREASURY_AUCTION_STATE_MACHINE.md",
        result_path,
    )

    assert result["summary"] == {
        "eligible_events": 156,
        "exact_schedule_pre_and_post": 145,
        "pre_entered_then_cancelled_on_revision": 4,
        "revision_before_entry_post_only": 1,
        "late_post_event_or_missing_post_only": 6,
        "events_with_pre_leg": 149,
        "events_post_only": 7,
        "known_tentative_date_changes": 5,
        "adjacent_event_windows_with_overlap": 83,
    }
    assert result["summary"]["adjacent_event_windows_with_overlap"] > 0
    assert all(
        value is True
        for key, value in result["gates"].items()
        if key != "author_technical_approval_recorded"
    )
    assert result["gates"]["author_technical_approval_recorded"] is False
    assert result["technical_decision"] == "PASS_NO_RETURN_STATE_MACHINE_AUDIT"
    assert result["governance_decision"] == "AUTHOR_APPROVAL_REQUIRED"
    assert result["return_preregistration_authorized"] is False
    assert result["return_data_opened"] is False
    assert result["return_hypotheses_spent"] == 0
    assert result["content_hash"] == MODULE["content_hash"](result)
    assert json.loads(result_path.read_text()) == result


def test_market_columns_fail_closed() -> None:
    frame = pd.DataFrame(
        {
            "event_identity": ["2020-01-01|TEST"],
            "security_type": ["Note"],
            "security_term": ["2-Year"],
            "floating_rate": ["No"],
            "auction_date": pd.to_datetime(["2020-01-02"]),
            "announcement_date": pd.to_datetime(["2019-12-30"]),
            "price": [100.0],
        }
    )

    try:
        MODULE["_eligible_events"](frame)
    except ValueError as error:
        assert "market or return columns are prohibited" in str(error)
    else:
        raise AssertionError("market columns must fail closed")
