from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.workspace_evidence

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "audit_pre_fomc_market_data_readiness.py"
)
SPEC = importlib.util.spec_from_file_location("audit_pre_fomc_market_data_readiness", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SCHEDULE = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "feasibility"
    / "pre_fomc_announcement_drift"
    / "annual_schedule_events.parquet"
)


def test_locked_windows_preserve_cancellation_and_controls() -> None:
    schedule = pd.read_parquet(SCHEDULE)
    windows = MODULE.build_windows(schedule)
    cancelled = windows[windows["event_date"] == pd.Timestamp("2020-03-18")]
    completed = schedule[schedule["event_status"] != MODULE.CANCELLED_STATUS]
    controls = windows[
        (windows["window_kind"] == "CONTROL") & (windows["window_status"] == "REQUIRED")
    ]

    assert len(schedule) == 80
    assert len(completed) == 79
    assert len(cancelled) == 1
    assert cancelled.iloc[0]["window_status"] == "CANCELLED_NO_ENTRY"
    assert cancelled.iloc[0][["entry_session", "exit_session"]].isna().all()
    assert controls.groupby("event_date").size().min() >= 3
    assert windows[windows["window_kind"] == "EVENT"]["event_date"].nunique() == 80


def test_required_sessions_exclude_cancelled_and_nonrequired_windows() -> None:
    schedule = pd.read_parquet(SCHEDULE)
    windows = MODULE.build_windows(schedule)
    sessions = MODULE.required_sessions(windows)

    assert date(2020, 3, 18) not in sessions
    assert date(2020, 3, 17) not in sessions
    assert min(sessions) >= date(2015, 12, 1)
    assert max(sessions) == date(2025, 12, 10)


def test_summary_passes_complete_metadata_without_opening_returns(tmp_path: Path) -> None:
    schedule = pd.read_parquet(SCHEDULE)
    windows = MODULE.build_windows(schedule)
    sessions = MODULE.required_sessions(windows)
    inventory = pd.DataFrame(
        {
            "session": pd.to_datetime(sorted(sessions)),
            "object_key": [MODULE.quote_key(session) for session in sorted(sessions)],
            "size_bytes": [1024] * len(sessions),
            "etag": ["sealed"] * len(sessions),
            "last_modified": ["2026-08-16T00:00:00+00:00"] * len(sessions),
        }
    )
    windows_path = tmp_path / "windows.parquet"
    inventory_path = tmp_path / "inventory.parquet"
    windows.to_parquet(windows_path, index=False)
    inventory.to_parquet(inventory_path, index=False)
    result = MODULE.summarize(
        schedule,
        windows,
        inventory,
        [MODULE.quote_key(min(sessions)), MODULE.quote_key(max(sessions))],
        [],
        {"authorized": True},
        windows_path,
        inventory_path,
    )

    assert result["decision"] == "PASS_TO_CONTROLLED_QUOTE_INGEST"
    assert result["required_unique_session_files"] == len(sessions)
    assert result["missing_session_files"] == []
    assert result["return_data_opened"] is False
    assert result["return_hypotheses_spent"] == 0


def test_summary_is_data_gated_when_listing_works_but_get_is_forbidden(
    tmp_path: Path,
) -> None:
    schedule = pd.read_parquet(SCHEDULE)
    windows = MODULE.build_windows(schedule)
    sessions = MODULE.required_sessions(windows)
    inventory = pd.DataFrame(
        {
            "session": pd.to_datetime(sorted(sessions)),
            "object_key": [MODULE.quote_key(session) for session in sorted(sessions)],
            "size_bytes": [1024] * len(sessions),
            "etag": ["listed"] * len(sessions),
            "last_modified": ["2026-08-16T00:00:00+00:00"] * len(sessions),
        }
    )
    windows_path = tmp_path / "windows.parquet"
    inventory_path = tmp_path / "inventory.parquet"
    windows.to_parquet(windows_path, index=False)
    inventory.to_parquet(inventory_path, index=False)
    result = MODULE.summarize(
        schedule,
        windows,
        inventory,
        [],
        [{"object_key": MODULE.quote_key(min(sessions)), "code": "403", "message": ""}],
        {"authorized": False},
        windows_path,
        inventory_path,
    )

    assert result["decision"] == "DATA_GATED"
    assert result["credential_state"] == "NO_USABLE_QUOTE_DOWNLOAD_ROUTE"
    assert result["gates"]["every_required_session_object_listed"] is True
    assert result["gates"]["practical_server_filtered_or_bounded_download_route"] is False
