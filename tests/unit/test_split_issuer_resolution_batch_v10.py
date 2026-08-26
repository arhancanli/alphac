from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_split_issuer_resolution_batch_v10.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_issuer_batch_v10_test", SCRIPT)
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


def test_three_exact_mutations_bind_issuer_dates() -> None:
    module = _module()
    payload = module.build(_sources(module), retrieved_at="2026-08-23T00:00:00+00:00")
    rows = {row["event_id"]: row for row in payload["verified_events"]}
    assert rows["MCLDQ_1999"]["market_date_binding"]["prior_date"] == "1999-07-26"
    assert rows["MCLDQ_2000"]["market_date_binding"]["prior_date"] == "2000-04-24"
    assert rows["NCI1_1998"]["market_date_binding"]["event_date"] == "1998-04-01"
    assert len(rows) == 3
    assert payload["return_data_opened"] is False


def test_missing_source_fails_closed() -> None:
    module = _module()
    with pytest.raises(ValueError, match="exactly the three sealed issuer-event sources"):
        module.build(_sources(module)[:1], retrieved_at="2026-08-23T00:00:00+00:00")
