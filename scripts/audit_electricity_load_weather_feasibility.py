#!/usr/bin/env python3
"""Audit EIA-930 load/forecast lineage without opening prices or returns."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx

API: Final = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
RESPONDENTS: Final = ("PJM", "ERCO", "MISO", "ISNE")
TYPES: Final = ("D", "DF")
START: Final = "2019-01-01T00"
END: Final = "2025-12-31T23"
RAW: Final = Path("data/raw/electricity_load_weather/eia930_schema_audit.json")
RESULT: Final = Path("artifacts/feasibility/electricity_load_weather/result.json")
REQUIRED_FIELDS: Final = {
    "period",
    "respondent",
    "respondent-name",
    "type",
    "type-name",
    "value",
    "value-units",
}
MAX_RETRIES: Final = 4


def canonical_json(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch_panel(api_key: str) -> dict[str, Any]:
    params = [
        ("api_key", api_key),
        ("frequency", "hourly"),
        ("data[0]", "value"),
        *(("facets[respondent][]", value) for value in RESPONDENTS),
        *(("facets[type][]", value) for value in TYPES),
        ("start", START),
        ("end", END),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "asc"),
        ("length", "100"),
    ]
    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Canli Capital research research@canlicapital.com"},
    ) as client:
        for attempt in range(MAX_RETRIES):
            response = client.get(API, params=params)
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            retry_after = response.headers.get("Retry-After")
            delay = min(float(retry_after), 16) if retry_after else min(2**attempt, 16)
            time.sleep(delay)
    raise RuntimeError(
        "EIA rate limit persisted for the locked load/forecast panel"
    )


def summarize(payload: dict[str, Any], raw_sha256: str) -> dict[str, Any]:
    response = payload["response"]
    rows = response.get("data", [])
    series: list[dict[str, Any]] = []
    schema_complete = True
    for respondent in RESPONDENTS:
        for series_type in TYPES:
            selected = [
                row
                for row in rows
                if row.get("respondent") == respondent
                and row.get("type") == series_type
            ]
            first_row = selected[0] if selected else {}
            last_row = selected[-1] if selected else {}
            fields = set.intersection(*(set(row) for row in selected)) if selected else set()
            schema_complete = schema_complete and REQUIRED_FIELDS.issubset(fields)
            series.append(
                {
                    "respondent": respondent,
                    "type": series_type,
                    "sample_rows": len(selected),
                    "first_period": first_row.get("period"),
                    "last_sample_period": last_row.get("period"),
                    "units": first_row.get("value-units"),
                    "fields": sorted(fields),
                }
            )

    all_available = all(row["sample_rows"] > 0 for row in series)
    starts_at_locked_boundary = all(row["first_period"] == START for row in series)
    gates = {
        "four_locked_balancing_authorities_both_series_available": all_available,
        "locked_window_start_present": starts_at_locked_boundary,
        "core_schema_complete": schema_complete,
        "full_historical_missingness_and_revision_audit_complete": False,
        "explicit_forecast_issue_or_vintage_timestamp": False,
        "delivery_period_timezone_and_dst_fold_explicit": False,
        "noaa_operational_forecast_vintage_corpus_sealed": False,
        "return_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    decision = "PASS_TO_RETURN_PREREGISTRATION" if all(gates.values()) else "DATA_GATED"
    return {
        "schema": "canli.feasibility.electricity-load-weather.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_load_forecast_schema_no_weather_no_prices_no_returns",
        "source_url": API,
        "locked_respondents": list(RESPONDENTS),
        "locked_series_types": {"D": "actual_demand", "DF": "day_ahead_demand_forecast"},
        "locked_period": {"start": START, "end": END},
        "api_total_rows_locked_panel": int(response.get("total", 0)),
        "schema_sample_rows": len(rows),
        "series": series,
        "gates": gates,
        "decision": decision,
        "blocking_reasons": [name for name, passed in gates.items() if not passed],
        "raw_sha256": raw_sha256,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
    }


def run(raw_path: Path, result_path: Path, api_key: str) -> dict[str, Any]:
    payload = fetch_panel(api_key)
    raw_bytes = canonical_json(payload)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw_bytes)
    result = summarize(payload, sha256_bytes(raw_bytes))
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--result", type=Path, default=RESULT)
    args = parser.parse_args()
    api_key = os.environ.get("EIA_API_KEY", "DEMO_KEY")
    try:
        result = run(args.raw, args.result, api_key)
    except (httpx.HTTPError, RuntimeError) as exc:
        result = {
            "schema": "canli.feasibility.electricity-load-weather.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "stage": "official_load_forecast_collection_no_prices_no_returns",
            "source_url": API,
            "source_collection_complete": False,
            "decision": "DATA_GATED",
            "blocking_reasons": ["official_eia_collection_rate_limited_or_unavailable"],
            "collection_error_type": type(exc).__name__,
            "return_data_opened": False,
            "return_hypotheses_spent": 0,
        }
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "PASS_TO_RETURN_PREREGISTRATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
