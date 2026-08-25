from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_split_issuer_resolution_batch_v4.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_issuer_batch_v4_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sources(module):
    return [
        {
            "ticker": ticker,
            **source,
            "retrieved_sha256": "0" * 64,
            "required_fragments_verified": source["required_fragments"],
        }
        for ticker, source in module.SOURCES.items()
    ]


def test_twelve_composite_mutations_are_bound_but_nonexecutable() -> None:
    module = _module()
    payload = module.build(_sources(module), retrieved_at="2026-08-23T00:00:00+00:00")
    assert {
        (row["ticker"], row["instrument_id"], row["ex_date_ms"], row["ratio"])
        for row in payload["resolved_events"]
    } == {
        ("ATNI", "XUSE:CASH:ATNIUSD", 883526400000, 0.4),
        ("CMO", "XUSE:CASH:CMOUSD", 994032000000, 0.5),
        ("ITT", "XUSE:CASH:ITTUSD", 1320105600000, 0.5),
        ("IHG", "XUSE:CASH:IHGUSD", 1119916800000, 0.73333),
        ("KMI1", "XUSE:CASH:KMI1USD", 915408000000, 1.5),
        ("KSU", "XUSE:CASH:KSUUSD", 963446400000, 0.5),
        ("NRF", "XUSE:CASH:NRFUSD", 1404086400000, 0.5),
        ("SBRA", "XUSE:CASH:SBRAUSD", 1289865600000, 0.33333),
        ("TYC", "XUSE:CASH:TYCUSD", 1183334400000, 0.25),
        ("T1", "XUSE:CASH:T1USD", 1037664000000, 0.2),
        ("RBAK", "XUSE:CASH:RBAKUSD", 1073260800000, 0.01363),
        ("SDH1", "XUSE:CASH:SDH1USD", 890611200000, 0.25),
    }
    assert all(row["share_mutation_verified"] is True for row in payload["resolved_events"])
    atni = next(row for row in payload["resolved_events"] if row["ticker"] == "ATNI")
    assert atni["market_date_binding"]["prior_date"] is None
    assert all(row["execution_authorized"] is False for row in payload["resolved_events"])
    assert all(
        row["governance_route"] == "HARD_QUARANTINE_ISSUER_VERIFIED_COMPOSITE_ACTION"
        for row in payload["resolved_events"]
    )
    assert payload["return_data_opened"] is False


def test_missing_source_fails_closed() -> None:
    module = _module()
    with pytest.raises(ValueError, match="exactly the twelve sealed composite-action sources"):
        module.build(_sources(module)[:2], retrieved_at="2026-08-23T00:00:00+00:00")
