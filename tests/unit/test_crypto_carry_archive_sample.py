from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/seal_crypto_carry_archive_sample.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_archive_sample", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_crypto_carry_sample_is_exact_and_bounded() -> None:
    receipt = _module().validate_published()
    assert receipt["status"] == "PASS_EXACT_SINGLE_SYMBOL_MONTH_ARCHIVE_EQUIVALENCE"
    assert receipt["comparisons"]["ohlcv_rows"] == 744
    assert receipt["comparisons"]["funding_rows"] == 93
    assert receipt["comparisons"]["ohlcv_timestamps_exact"] is True
    assert all(receipt["comparisons"]["ohlcv_fields_exact"].values())
    assert receipt["comparisons"]["funding_timestamps_exact"] is True
    assert receipt["comparisons"]["funding_rates_exact"] is True
    assert receipt["fresh_full_universe_download_completed"] is False
    assert receipt["full_walkforward_replayed"] is False
    assert receipt["independent_replication"] is False
