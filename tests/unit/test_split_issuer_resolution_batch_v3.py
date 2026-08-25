from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_split_issuer_resolution_batch_v3.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_issuer_batch_v3_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(module):
    return {
        **module.SOURCE,
        "retrieved_sha256": "0" * 64,
        "required_fragments_verified": module.SOURCE["required_fragments"],
    }


def test_orig_binds_exact_rounded_reverse_split_and_market_date() -> None:
    module = _module()
    payload = module.build(_source(module), retrieved_at="2026-08-23T00:00:00+00:00")
    row = payload["verified_events"][0]
    assert (row["instrument_id"], row["ex_date_ms"], row["ratio"]) == (
        "XUSE:CASH:ORIGUSD",
        1506038400000,
        0.00011,
    )
    assert row["market_date_binding"]["prior_date"] == "2017-09-21"
    assert row["market_date_binding"]["event_date"] == "2017-09-22"
    assert payload["return_data_opened"] is False


def test_orig_rejects_nonmatching_issuer_ratio() -> None:
    module = _module()
    source = _source(module)
    source["issuer_ratio"] = 1 / 9000
    with pytest.raises(ValueError, match="does not match the sealed source specification"):
        module.build(source, retrieved_at="2026-08-23T00:00:00+00:00")
