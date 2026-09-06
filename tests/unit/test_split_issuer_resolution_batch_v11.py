from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_split_issuer_resolution_batch_v11.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_issuer_batch_v11_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sources(module):
    return [
        {
            "event_id": event_id,
            **source,
            "retrieved_sha256": "0" * 64,
            "required_fragments_verified": source["required_fragments"],
        }
        for event_id, source in module.SOURCES.items()
    ]


def test_five_exact_mutations_bind_issuer_dates() -> None:
    module = _module()
    payload = module.build(_sources(module), retrieved_at="2026-08-23T00:00:00+00:00")
    rows = {row["event_id"]: row for row in payload["verified_events"]}
    assert rows["BYNDQ_2001"]["market_date_binding"]["event_date"] == "2001-07-02"
    assert rows["NWKC_2001"]["market_date_binding"]["event_date"] == "2001-06-18"
    assert rows["XCEDQ_2001"]["market_date_binding"]["event_date"] == "2001-03-21"
    assert rows["CB_1998"]["market_date_binding"]["prior_date"] == "1998-03-02"
    assert rows["CCIL_1998"]["market_date_binding"]["prior_date"] == "1998-04-14"
    assert payload["return_data_opened"] is False


def test_missing_source_fails_closed() -> None:
    module = _module()
    with pytest.raises(ValueError, match="exactly the five sealed issuer-event sources"):
        module.build(_sources(module)[:1], retrieved_at="2026-08-23T00:00:00+00:00")
