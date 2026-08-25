from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/compare_crypto_carry_fresh_inputs.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_compare", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_crypto_carry_comparison_quantifies_without_overclaiming() -> None:
    receipt = _module().validate_published()
    assert receipt["status"] == "INCOMPLETE_PORTABLE_INPUT_EQUIVALENCE_GAPS_QUANTIFIED"
    assert receipt["comparison_executed"] is True
    assert receipt["portable_input_equivalence_complete"] is False
    assert len(receipt["records"]) == 58
    assert receipt["totals"]["ohlcv_overlap_rows"] > 2_000_000
    assert receipt["totals"]["daily_fallback_objects_required"] >= 0
    assert receipt["totals"]["funding_local_only_rows"] > 0
    assert receipt["totals"]["funding_fresh_only_at_or_after_delisting"] == 271
    assert receipt["totals"]["funding_fresh_only_before_listing"] == 2
    assert receipt["totals"]["funding_fresh_only_inside_lifecycle"] == 0
    assert receipt["totals"]["ohlcv_fresh_only_before_listing"] == 1
    assert receipt["totals"]["ohlcv_fresh_only_inside_lifecycle"] == 0
    icp = next(row for row in receipt["records"] if row["symbol"] == "ICPUSDT")
    assert icp["funding"]["local_only_range"]["first_timestamp"] == (
        "2021-07-30T08:00:00+00:00"
    )
    assert icp["funding"]["local_only_range"]["last_timestamp"] == (
        "2022-08-31T16:00:00.013000+00:00"
    )
    assert receipt["full_walkforward_replayed"] is False
    assert receipt["independent_replication"] is False
