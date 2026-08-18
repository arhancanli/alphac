#!/usr/bin/env python3
"""Audit quote-file readiness for the sealed pre-FOMC identity without opening prices.

The audit expands every scheduled slot into the locked event and matched-control windows, checks
Polygon SIP flat-file object metadata, and issues one-byte range probes on the temporal endpoints.
It never decompresses or parses a quote, computes a return, or spends a hypothesis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import exchange_calendars as xcals
import httpx
import pandas as pd

SCHEDULE_EVENTS: Final = Path(
    "artifacts/feasibility/pre_fomc_announcement_drift/annual_schedule_events.parquet"
)
WINDOWS_OUT: Final = Path(
    "artifacts/feasibility/pre_fomc_announcement_drift/market_data_windows.parquet"
)
INVENTORY_OUT: Final = Path(
    "artifacts/feasibility/pre_fomc_announcement_drift/polygon_quote_inventory.parquet"
)
RESULT_OUT: Final = Path(
    "artifacts/feasibility/pre_fomc_announcement_drift/market_data_readiness.json"
)
QUOTE_PREFIX: Final = "us_stocks_sip/quotes_v1"
REST_QUOTES_URL: Final = "https://api.polygon.io/v3/quotes/SPY"
MAX_BOUNDED_FLATFILE_GIB: Final = 50.0
CANCELLED_STATUS: Final = "CANCELLED_AFTER_UNSCHEDULED_DECISION"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote_key(session: date) -> str:
    return (
        f"{QUOTE_PREFIX}/{session.year:04d}/{session.month:02d}/"
        f"{session.isoformat()}.csv.gz"
    )


def build_windows(schedule: pd.DataFrame) -> pd.DataFrame:
    """Expand the preregistered event/control windows on the XNYS session calendar."""
    calendar = xcals.get_calendar("XNYS")
    scheduled_dates = set(pd.to_datetime(schedule["scheduled_decision_date"]).dt.date)
    rows: list[dict[str, Any]] = []

    def is_session(value: date) -> bool:
        return bool(calendar.is_session(pd.Timestamp(value)))

    def previous_session(value: date) -> date:
        return calendar.previous_session(pd.Timestamp(value)).date()

    for record in schedule.sort_values("scheduled_decision_date").to_dict("records"):
        event_date = pd.Timestamp(record["scheduled_decision_date"]).date()
        event_status = str(record["event_status"])
        if event_status == CANCELLED_STATUS:
            rows.append(
                {
                    "event_date": event_date,
                    "window_kind": "EVENT",
                    "control_lag_weeks": pd.NA,
                    "window_status": "CANCELLED_NO_ENTRY",
                    "entry_session": pd.NaT,
                    "exit_session": pd.NaT,
                }
            )
            continue
        if not is_session(event_date):
            raise ValueError(f"scheduled decision is not an XNYS session: {event_date}")
        rows.append(
            {
                "event_date": event_date,
                "window_kind": "EVENT",
                "control_lag_weeks": pd.NA,
                "window_status": "REQUIRED",
                "entry_session": previous_session(event_date),
                "exit_session": event_date,
            }
        )
        for lag in range(1, 5):
            control_exit = event_date - timedelta(days=7 * lag)
            status = "REQUIRED"
            entry: date | pd.NaTType = pd.NaT
            if not is_session(control_exit):
                status = "EXCLUDED_NON_SESSION"
            else:
                entry = previous_session(control_exit)
                if scheduled_dates.intersection({entry, control_exit}):
                    status = "EXCLUDED_FOMC_OVERLAP"
            rows.append(
                {
                    "event_date": event_date,
                    "window_kind": "CONTROL",
                    "control_lag_weeks": lag,
                    "window_status": status,
                    "entry_session": entry,
                    "exit_session": control_exit if is_session(control_exit) else pd.NaT,
                }
            )

    frame = pd.DataFrame(rows)
    frame["event_date"] = pd.to_datetime(frame["event_date"])
    frame["entry_session"] = pd.to_datetime(frame["entry_session"])
    frame["exit_session"] = pd.to_datetime(frame["exit_session"])
    frame["control_lag_weeks"] = frame["control_lag_weeks"].astype("Int64")
    return frame.sort_values(
        ["event_date", "window_kind", "control_lag_weeks"], na_position="first"
    )


def required_sessions(windows: pd.DataFrame) -> set[date]:
    required = windows[windows["window_status"] == "REQUIRED"]
    values = pd.concat([required["entry_session"], required["exit_session"]]).dropna()
    return set(pd.to_datetime(values).dt.date)


def polygon_inventory(
    sessions: set[date],
) -> tuple[pd.DataFrame, list[str], list[dict[str, str]]]:
    """List exact required objects and transport-probe endpoints without parsing records."""
    import boto3
    from botocore.config import Config

    names = (
        "POLYGON_S3_ENDPOINT",
        "POLYGON_S3_ACCESS_KEY_ID",
        "POLYGON_S3_SECRET_ACCESS_KEY",
        "POLYGON_S3_BUCKET",
    )
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing Polygon flat-file environment names: {missing}")
    bucket = os.environ["POLYGON_S3_BUCKET"]
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["POLYGON_S3_ENDPOINT"],
        aws_access_key_id=os.environ["POLYGON_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["POLYGON_S3_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
    )
    required_keys = {quote_key(session): session for session in sessions}
    found: dict[str, dict[str, Any]] = {}
    months = sorted({(session.year, session.month) for session in sessions})
    paginator = client.get_paginator("list_objects_v2")
    for year, month in months:
        prefix = f"{QUOTE_PREFIX}/{year:04d}/{month:02d}/"
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = str(obj.get("Key", ""))
                if key in required_keys:
                    modified = obj.get("LastModified")
                    found[key] = {
                        "session": required_keys[key],
                        "object_key": key,
                        "size_bytes": int(obj["Size"]),
                        "etag": str(obj.get("ETag", "")).strip('"'),
                        "last_modified": modified.isoformat() if modified else None,
                    }
    endpoint_keys = [quote_key(min(sessions)), quote_key(max(sessions))]
    from botocore.exceptions import ClientError

    range_verified = []
    transport_errors = []
    for key in endpoint_keys:
        try:
            response = client.get_object(Bucket=bucket, Key=key, Range="bytes=0-0")
        except ClientError as exc:
            error = exc.response.get("Error", {})
            transport_errors.append(
                {
                    "object_key": key,
                    "code": str(error.get("Code", "UNKNOWN")),
                    "message": str(error.get("Message", "")),
                }
            )
            continue
        body = response["Body"]
        try:
            raw = body.read()
        finally:
            body.close()
        if len(raw) != 1:
            raise RuntimeError(f"expected one-byte transport probe for {key}, got {len(raw)}")
        range_verified.append(key)
    frame = pd.DataFrame(found.values())
    if not frame.empty:
        frame["session"] = pd.to_datetime(frame["session"])
        frame = frame.sort_values("session").reset_index(drop=True)
    return frame, range_verified, transport_errors


def polygon_rest_probe(first_session: date) -> dict[str, Any]:
    """Probe one server-filtered SPY record while retaining schema only, never values."""
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        return {
            "status_code": None,
            "api_status": "CREDENTIAL_MISSING",
            "message": "POLYGON_API_KEY is not configured",
            "results_count": 0,
            "result_fields": [],
            "authorized": False,
        }
    response = httpx.get(
        REST_QUOTES_URL,
        params={
            "timestamp": first_session.isoformat(),
            "limit": 1,
            "sort": "timestamp",
            "order": "asc",
            "apiKey": api_key,
        },
        timeout=30.0,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    results = payload.get("results") or []
    return {
        "status_code": response.status_code,
        "api_status": payload.get("status"),
        "message": payload.get("message"),
        "results_count": len(results),
        "result_fields": sorted(results[0]) if results else [],
        "authorized": response.status_code == 200 and bool(results),
    }


def summarize(
    schedule: pd.DataFrame,
    windows: pd.DataFrame,
    inventory: pd.DataFrame,
    range_verified: list[str],
    transport_errors: list[dict[str, str]],
    rest_probe: dict[str, Any],
    windows_path: Path,
    inventory_path: Path,
) -> dict[str, Any]:
    sessions = required_sessions(windows)
    completed = schedule[schedule["event_status"] != CANCELLED_STATUS]
    controls = windows[
        (windows["window_kind"] == "CONTROL") & (windows["window_status"] == "REQUIRED")
    ]
    control_counts = controls.groupby("event_date").size()
    inventory_sessions = inventory.get("session", pd.Series(dtype="datetime64[ns]"))
    found_sessions = set(pd.to_datetime(inventory_sessions.dropna()).dt.date)
    missing_sessions = sorted(sessions - found_sessions)
    compressed_gib = float(
        inventory.get("size_bytes", pd.Series(dtype="int64")).sum()
    ) / 1024**3
    bounded_flatfile_route = (
        len(range_verified) == 2 and compressed_gib <= MAX_BOUNDED_FLATFILE_GIB
    )
    server_filtered_route = bool(rest_probe.get("authorized"))
    gates = {
        "all_80_scheduled_slots_accounted": len(schedule) == 80,
        "79_completed_events_accounted": len(completed) == 79,
        "cancelled_slot_preserved_without_market_window": bool(
            (
                (windows["event_date"] == pd.Timestamp("2020-03-18"))
                & (windows["window_status"] == "CANCELLED_NO_ENTRY")
            ).any()
        ),
        "at_least_three_locked_controls_per_completed_event": len(control_counts) == 79
        and bool((control_counts >= 3).all()),
        "every_required_session_object_listed": not missing_sessions,
        "practical_server_filtered_or_bounded_download_route": (
            server_filtered_route or bounded_flatfile_route
        ),
        "quote_records_not_decompressed_or_parsed": True,
        "market_returns_unopened": True,
        "return_hypotheses_unspent": True,
    }
    return {
        "schema": "canli.feasibility.pre-fomc-market-data-readiness.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "polygon_sip_metadata_plus_two_one_byte_transport_probes_no_records_no_returns",
        "provider": "Polygon US Stocks SIP flat files",
        "source_prefix": QUOTE_PREFIX,
        "scheduled_slots": len(schedule),
        "completed_events": len(completed),
        "cancelled_slots": int((schedule["event_status"] == CANCELLED_STATUS).sum()),
        "required_control_windows": len(controls),
        "minimum_controls_per_completed_event": int(control_counts.min()),
        "required_unique_session_files": len(sessions),
        "listed_required_session_files": len(found_sessions),
        "missing_session_files": list(map(str, missing_sessions)),
        "compressed_bytes_if_all_required_full_day_files_downloaded": int(
            inventory.get("size_bytes", pd.Series(dtype="int64")).sum()
        ),
        "compressed_gib_if_all_required_full_day_files_downloaded": round(compressed_gib, 3),
        "maximum_bounded_flatfile_route_gib": MAX_BOUNDED_FLATFILE_GIB,
        "one_byte_range_verified_keys": range_verified,
        "transport_probe_errors": transport_errors,
        "rest_server_filtered_probe": rest_probe,
        "provider_route_diagnostics": {
            "flatfile_transport_authorized": len(range_verified) == 2,
            "flatfile_volume_bounded": compressed_gib <= MAX_BOUNDED_FLATFILE_GIB,
            "rest_server_filtered_authorized": server_filtered_route,
        },
        "credential_state": (
            "USABLE_SERVER_FILTERED_ROUTE"
            if server_filtered_route
            else "NO_USABLE_QUOTE_DOWNLOAD_ROUTE"
        ),
        "windows_file": str(windows_path),
        "windows_sha256": sha256_file(windows_path),
        "inventory_file": str(inventory_path),
        "inventory_sha256": sha256_file(inventory_path),
        "gates": gates,
        "decision": "PASS_TO_CONTROLLED_QUOTE_INGEST" if all(gates.values()) else "DATA_GATED",
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
    }


def run(
    schedule_path: Path,
    windows_path: Path,
    inventory_path: Path,
    result_path: Path,
) -> dict[str, Any]:
    schedule = pd.read_parquet(schedule_path)
    windows = build_windows(schedule)
    sessions = required_sessions(windows)
    inventory, range_verified, transport_errors = polygon_inventory(sessions)
    rest_probe = polygon_rest_probe(min(sessions))
    windows_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    windows.to_parquet(windows_path, index=False)
    inventory.to_parquet(inventory_path, index=False)
    result = summarize(
        schedule,
        windows,
        inventory,
        range_verified,
        transport_errors,
        rest_probe,
        windows_path,
        inventory_path,
    )
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", type=Path, default=SCHEDULE_EVENTS)
    parser.add_argument("--windows-out", type=Path, default=WINDOWS_OUT)
    parser.add_argument("--inventory-out", type=Path, default=INVENTORY_OUT)
    parser.add_argument("--result-out", type=Path, default=RESULT_OUT)
    args = parser.parse_args()
    result = run(args.schedule, args.windows_out, args.inventory_out, args.result_out)
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "PASS_TO_CONTROLLED_QUOTE_INGEST" else 2


if __name__ == "__main__":
    raise SystemExit(main())
