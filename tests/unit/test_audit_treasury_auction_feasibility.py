from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_treasury_auction_feasibility.py"
SPEC = spec_from_file_location("audit_treasury_auction_feasibility", SCRIPT)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def record(**overrides: str) -> dict[str, str]:
    base = {
        "record_date": "2020-01-10",
        "cusip": "91282TEST",
        "security_type": "Note",
        "security_term": "10-Year",
        "floating_rate": "No",
        "auction_date": "2020-01-08",
        "issue_date": "2020-01-15",
        "maturity_date": "2030-01-15",
        "announcemt_date": "2020-01-02",
        "announcemtd_cusip": "91282TEST",
        "auction_format": "Single-Price",
        "closing_time_comp": "01:00 PM",
        "offering_amt": "24000000000",
        "original_cusip": "null",
        "original_issue_date": "2020-01-15",
        "original_security_term": "10-Year",
        "pdf_filenm_announcemt": "A_20200102_1.pdf",
        "reopening": "No",
    }
    return {**base, **overrides}


def test_manifest_keeps_only_coupon_auctions_and_safe_fields() -> None:
    frame = MODULE.build_manifest(
        [record(), record(cusip="BILL", security_type="Bill", security_term="13-Week")]
    )

    assert len(frame) == 1
    assert list(frame.columns) == MODULE.SAFE_EVENT_FIELDS
    assert frame.iloc[0]["event_identity"] == "2020-01-08|91282TEST"
    assert frame.iloc[0]["offering_amount_usd"] == 24_000_000_000
    assert frame.iloc[0]["floating_rate"] == "No"
    assert "high_yield" not in frame.columns
    assert "bid_to_cover_ratio" not in frame.columns


def test_summary_fails_when_notice_is_after_auction() -> None:
    frame = MODULE.build_manifest([record(announcemt_date="2020-01-09")])
    result = MODULE.summarize(frame, "abc", 1)

    assert result["announcement_not_after_auction_rate"] == 0.0
    assert result["decision"] == "FAIL_FEASIBILITY"
    assert result["return_hypotheses_spent"] == 0


def test_summary_passes_complete_synthetic_panel(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "MIN_EVENTS", 2)
    monkeypatch.setattr(MODULE, "MIN_POST_PUBLICATION_EVENTS", 2)
    rows = [
        record(cusip="CUSIP0001", auction_date="2020-01-08"),
        record(cusip="CUSIP0002", auction_date="2020-02-08", issue_date="2020-02-15"),
    ]
    frame = MODULE.build_manifest(rows)
    result = MODULE.summarize(frame, "abc", 2)

    assert result["decision"] == "PASS_TO_RETURN_PREREGISTRATION"
    assert result["unique_event_identity_rate"] == 1.0
    assert result["post_2013_events"] == 2
    assert all(result["gates"].values())


def test_dates_are_typed_for_lead_time_checks() -> None:
    frame = MODULE.build_manifest([record()])

    assert pd.api.types.is_datetime64_any_dtype(frame["announcement_date"])
    assert pd.api.types.is_datetime64_any_dtype(frame["auction_date"])
