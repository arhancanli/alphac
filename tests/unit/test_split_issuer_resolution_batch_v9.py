from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_split_issuer_resolution_batch_v9.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_issuer_batch_v9_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uti1_exact_mutation_binds_issuer_date() -> None:
    module = _module()
    source = {
        **module.SOURCE,
        "retrieved_sha256": "0" * 64,
        "required_fragments_verified": module.SOURCE["required_fragments"],
    }
    payload = module.build(source, retrieved_at="2026-08-23T00:00:00+00:00")
    row = payload["verified_events"][0]
    assert (row["instrument_id"], row["ex_date_ms"], row["ratio"]) == (
        "XUSE:CASH:UTI1USD",
        970531200000,
        2.0,
    )
    assert row["market_date_binding"]["event_date"] == "2000-10-03"
    assert payload["return_data_opened"] is False


def test_changed_source_fails_closed() -> None:
    module = _module()
    with pytest.raises(ValueError, match="source changed"):
        module.build(
            {**module.SOURCE, "issuer_ratio": 3.0},
            retrieved_at="2026-08-23T00:00:00+00:00",
        )
