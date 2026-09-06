from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_split_issuer_conflict_resolution_batch_v5.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_issuer_conflict_v5_test", SCRIPT)
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


def test_sixteen_conflicts_are_resolved_but_remain_nonexecutable() -> None:
    module = _module()
    payload = module.build(_sources(module), retrieved_at="2026-08-23T00:00:00+00:00")
    rows = payload["resolved_events"]
    assert {row["ticker"] for row in rows} == {
        "CDR",
        "DIAL1",
        "GEVA",
        "IPAR",
        "MHGVY",
        "NCI1",
        "NVEC",
        "PRTK",
        "USB",
        "PRGN1",
        "ABEV",
        "E",
        "EXMCQ",
        "AAWW",
        "ACL",
        "AZAA",
    }
    assert all(row["execution_authorized"] is False for row in rows)
    assert all(row["ratio_repair_authorized"] is False for row in rows)
    assert all(
        row["governance_route"] == "HARD_QUARANTINE_ISSUER_CONFLICT_OR_DATE_MISMATCH"
        for row in rows
    )


def test_missing_conflict_source_fails_closed() -> None:
    module = _module()
    with pytest.raises(ValueError, match="exactly the sixteen sealed issuer-conflict sources"):
        module.build(_sources(module)[:1], retrieved_at="2026-08-23T00:00:00+00:00")
