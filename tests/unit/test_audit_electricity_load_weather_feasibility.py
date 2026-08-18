from __future__ import annotations

from pathlib import Path
from runpy import run_path

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "audit_electricity_load_weather_feasibility.py"
    )
)
summarize = MODULE["summarize"]
respondents = MODULE["RESPONDENTS"]
series_types = MODULE["TYPES"]


def complete_payload() -> dict:
    rows = []
    for respondent in respondents:
        for series_type in series_types:
            rows.append(
                {
                    "period": "2019-01-01T00",
                    "respondent": respondent,
                    "respondent-name": respondent,
                    "type": series_type,
                    "type-name": series_type,
                    "value": "1",
                    "value-units": "megawatthours",
                }
            )
    return {"response": {"total": "490944", "data": rows}}


def test_clean_eia_schema_still_fails_without_vintage_and_timezone() -> None:
    result = summarize(complete_payload(), "abc")

    assert result["gates"]["four_locked_balancing_authorities_both_series_available"] is True
    assert result["gates"]["locked_window_start_present"] is True
    assert result["gates"]["full_historical_missingness_and_revision_audit_complete"] is False
    assert result["gates"]["explicit_forecast_issue_or_vintage_timestamp"] is False
    assert result["gates"]["delivery_period_timezone_and_dst_fold_explicit"] is False
    assert result["decision"] == "DATA_GATED"
    assert result["return_hypotheses_spent"] == 0


def test_missing_region_series_fails_availability_gate() -> None:
    data = complete_payload()
    data["response"]["data"] = [
        row
        for row in data["response"]["data"]
        if not (row["respondent"] == "PJM" and row["type"] == "DF")
    ]

    result = summarize(data, "abc")

    assert result["gates"]["four_locked_balancing_authorities_both_series_available"] is False
    assert result["decision"] == "DATA_GATED"
