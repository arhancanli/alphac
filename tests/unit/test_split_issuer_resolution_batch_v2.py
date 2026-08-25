from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_split_issuer_resolution_batch_v2.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_issuer_batch_v2_test", SCRIPT)
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


def test_batch_binds_only_two_exact_frozen_events() -> None:
    module = _module()
    payload = module.build(_sources(module), retrieved_at="2026-08-23T00:00:00+00:00")
    assert payload["decision"] == "TWO_EXACT_QUARANTINED_EVENTS_ISSUER_VERIFIED"
    assert payload["return_data_opened"] is False
    assert {
        (row["instrument_id"], row["ex_date_ms"], row["ratio"])
        for row in payload["verified_events"]
    } == {
        ("XUSE:CASH:AMPEUSD", 1669075200000, 0.06667),
        ("XUSE:CASH:EVHCUSD", 1480636800000, 0.334),
    }


def test_batch_rejects_a_nonmatching_frozen_ratio() -> None:
    module = _module()
    sources = _sources(module)
    sources[0]["ratio"] = 0.06666
    with pytest.raises(ValueError, match="does not bind an unresolved frozen event"):
        module.build(sources, retrieved_at="2026-08-23T00:00:00+00:00")


def test_source_verification_requires_every_anchor() -> None:
    verify = _module().verify_source
    verify(
        "A fifteen-to-one reverse stock split became effective November 9, 2022.",
        ["fifteen-to-one reverse stock split", "became effective November 9, 2022"],
    )
    with pytest.raises(ValueError, match="missing required fragments"):
        verify("fifteen-to-one reverse stock split", ["began trading December 2, 2016"])
