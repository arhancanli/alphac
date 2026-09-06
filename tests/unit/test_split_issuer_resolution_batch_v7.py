from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_split_issuer_resolution_batch_v7.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_issuer_batch_v7_test", SCRIPT)
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


def test_six_exact_mutations_bind_issuer_dates() -> None:
    module = _module()
    payload = module.build(_sources(module), retrieved_at="2026-08-23T00:00:00+00:00")
    rows = {row["ticker"]: row for row in payload["verified_events"]}
    assert rows["BNI"]["ex_date_ms"] == 904694400000
    assert rows["BNI"]["market_date_binding"]["prior_date"] == "1998-09-01"
    assert rows["EPAC"]["ex_date_ms"] == 886464000000
    assert rows["EPAC"]["market_date_binding"]["event_date"] == "1998-02-03"
    assert rows["GDW"]["ex_date_ms"] == 945043200000
    assert rows["GDW"]["market_date_binding"]["prior_date"] == "1999-12-10"
    assert (rows["JAKK"]["ex_date_ms"], rows["JAKK"]["stored_ratio"]) == (
        941760000000,
        1.5,
    )
    assert rows["JAKK"]["market_date_binding"]["prior_date"] == "1999-11-04"
    assert rows["HAFC"]["ex_date_ms"] == 1001289600000
    assert rows["HAFC"]["market_date_binding"]["prior_date"] == "2001-09-21"
    assert rows["LNG"]["ex_date_ms"] == 971827200000
    assert rows["LNG"]["market_date_binding"]["event_date"] == "2000-10-18"
    assert payload["return_data_opened"] is False


def test_missing_source_fails_closed() -> None:
    module = _module()
    with pytest.raises(ValueError, match="exactly the six sealed issuer sources"):
        module.build(_sources(module)[:1], retrieved_at="2026-08-23T00:00:00+00:00")
