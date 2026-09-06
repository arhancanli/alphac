from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_split_lifecycle_discontinuity_resolution.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_lifecycle_break_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence(module):
    return [
        {
            "ticker": ticker,
            **source,
            "retrieved_sha256": "0" * 64,
            "required_fragments_verified": source["required_fragments"],
        }
        for ticker, event in module.EVENTS.items()
        for source in event["sources"]
    ]


def test_six_bankruptcy_relistings_are_resolved_but_never_executable() -> None:
    module = _module()
    payload = module.build(_evidence(module), retrieved_at="2026-08-23T00:00:00+00:00")
    rows = payload["resolved_events"]
    assert {row["ticker"] for row in rows} == {
        "BASXQ",
        "CIVI",
        "CQB",
        "EGLE2",
        "KEGX",
        "TDW",
    }
    assert all(row["execution_authorized"] is False for row in rows)
    assert all(row["ratio_repair_authorized"] is False for row in rows)
    assert all(
        row["governance_route"]
        == "NON_EXECUTABLE_ISSUER_VERIFIED_LIFECYCLE_DISCONTINUITY"
        for row in rows
    )
    assert all(
        row["market_date_binding"]["binding"]
        == "EVENT_DATE_IS_FIRST_FROZEN_PRICE_BAR_AFTER_ISSUER_EFFECTIVE_DATE"
        for row in rows
    )


def test_every_event_requires_all_of_its_evidence_roles() -> None:
    module = _module()
    evidence = [row for row in _evidence(module) if row["ticker"] != "TDW"]
    with pytest.raises(ValueError, match="all issuer-evidence roles are required for TDW"):
        module.build(evidence, retrieved_at="2026-08-23T00:00:00+00:00")
