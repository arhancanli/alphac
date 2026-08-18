from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "audit_cftc_hedging_pressure_feasibility.py"
)
SPEC = spec_from_file_location("audit_cftc_hedging_pressure_feasibility", SCRIPT)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def record(**overrides: str) -> dict[str, str]:
    base = {
        "id": "200107067651F",
        "market_and_exchange_names": "CRUDE OIL - NEW YORK MERCANTILE EXCHANGE",
        "report_date_as_yyyy_mm_dd": "2020-01-07T00:00:00.000",
        "yyyy_report_week_ww": "2020 Report Week 01",
        "contract_market_name": "CRUDE OIL",
        "cftc_contract_market_code": "067651",
        "cftc_market_code": "NYM",
        "cftc_region_code": "NYC",
        "cftc_commodity_code": "067",
        "commodity_name": "CRUDE OIL",
        "contract_units": "CONTRACTS OF 1,000 BARRELS",
        "cftc_subgroup_code": "N10",
        "commodity_subgroup_name": "PETROLEUM AND PRODUCTS",
        "commodity_group_name": "NATURAL RESOURCES",
    }
    return {**base, **overrides}


def test_manifest_contains_metadata_only() -> None:
    frame = MODULE.build_manifest([record()])

    assert list(frame.columns) == MODULE.SAFE_EVENT_FIELDS
    assert frame.iloc[0]["event_identity"] == "200107067651F"
    assert frame.iloc[0]["conservative_default_available_date"] == pd.Timestamp("2020-01-13")
    assert not bool(frame.iloc[0]["release_timestamp_verified"])
    assert "prod_merc_positions_long" not in frame.columns
    assert "open_interest_all" not in frame.columns


def test_summary_fails_closed_without_release_lineage_and_mapping(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "MIN_ROWS", 1)
    monkeypatch.setattr(MODULE, "MIN_YEARS", 1)
    frame = MODULE.build_manifest([record()])
    result = MODULE.summarize(frame, "abc")

    assert result["decision"] == "DATA_GATED"
    assert result["gates"]["exact_historical_release_lineage"] is False
    assert result["gates"]["fixed_tradable_contract_mapping"] is False
    assert result["return_hypotheses_spent"] == 0


def test_duplicate_dataset_ids_fail_identity_gate(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "MIN_ROWS", 2)
    monkeypatch.setattr(MODULE, "MIN_YEARS", 1)
    frame = MODULE.build_manifest([record(), record()])
    result = MODULE.summarize(frame, "abc")

    assert result["unique_event_identity_rate"] == 0.5
    assert result["gates"]["unique_event_identity"] is False


def test_non_tuesday_report_dates_fail_calendar_gate(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "MIN_ROWS", 1)
    monkeypatch.setattr(MODULE, "MIN_YEARS", 1)
    frame = MODULE.build_manifest([record(report_date_as_yyyy_mm_dd="2020-01-08")])
    result = MODULE.summarize(frame, "abc")

    assert result["tuesday_report_date_rate"] == 0.0
    assert result["gates"]["report_date_is_tuesday"] is False
