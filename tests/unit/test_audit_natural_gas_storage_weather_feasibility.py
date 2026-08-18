from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd

SCRIPT = (
    Path(__file__).parents[2]
    / "scripts"
    / "audit_natural_gas_storage_weather_feasibility.py"
)
SPEC = importlib.util.spec_from_file_location(
    "audit_natural_gas_storage_weather_feasibility", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_parse_wngsr_csv_binds_release_and_first_report_values() -> None:
    raw = b'''Energy Information Administration
"Working Gas in Underground Storage, Lower 48"
"Released: January 12, 2023 at 10:30 a.m. (eastern time) for the Week Ending January 6, 2023"
Region,stocks
Total,"2,902","","","2,891","",,"11",""
'''
    parsed = MODULE.parse_wngsr_csv(raw)
    assert parsed["release_date"] == date(2023, 1, 12)
    assert parsed["period_end"] == date(2023, 1, 6)
    assert parsed["reported_total_bcf"] == 2902
    assert parsed["reported_prior_total_bcf"] == 2891
    assert parsed["reported_net_change_bcf"] == 11


def test_gefs_keys_preserve_model_upgrade_lineage() -> None:
    legacy = MODULE.gefs_keys(date(2019, 1, 5))
    modern = MODULE.gefs_keys(date(2021, 1, 2))
    assert legacy[0].endswith("gec00.t00z.pgrb2af24")
    assert legacy[1].endswith("gep20.t00z.pgrb2af168")
    assert "/pgrb2a/" in legacy[0]
    assert modern[0].endswith("gec00.t00z.pgrb2a.0p50.f024")
    assert modern[1].endswith("gep30.t00z.pgrb2a.0p50.f168")


def test_summary_fails_closed_when_first_release_archive_is_sparse() -> None:
    periods = pd.date_range("2017-01-06", periods=469, freq="7D")
    expected = pd.DataFrame({"period_end": periods, "current_total_bcf": 1000})
    original = pd.DataFrame(
        {
            "period_end": periods,
            "original_total_bcf": 999,
            "original_explanation": None,
        }
    )
    captures = pd.DataFrame(
        {
            "period_end": periods[:93].date,
            "error": [None] * 93,
        }
    )
    noaa = pd.DataFrame(
        {
            "period_end": [day.date() for day in periods for _ in range(2)],
            "available": [True] * (len(periods) * 2),
        }
    )
    cme = {
        "metadata_access": True,
        "range": {"start": "2010-01-01T00:00:00Z"},
        "schemas": ["ohlcv-1d", "mbp-1"],
        "market_records_requested": 0,
    }
    result = MODULE.summarize(
        expected,
        original,
        captures,
        noaa,
        cme,
        {"ngshistory_xls": "a" * 64},
    )
    assert result["decision"] == "DATA_GATED"
    assert result["first_release_capture_coverage"] < 0.20
    assert result["official_original_data_coverage"] == 1
    assert result["return_hypotheses_spent"] == 0
