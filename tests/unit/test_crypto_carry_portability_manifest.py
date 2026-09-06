from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build_crypto_carry_portability_manifest.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_portability", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_crypto_carry_portability_manifest_is_frozen_and_bounded() -> None:
    receipt = _module().validate_published()
    assert receipt["status"] == "PASS_FROZEN_SOURCE_INVENTORY_NOT_FRESH_ACQUISITION"
    assert receipt["frozen_run"]["instrument_count"] == 58
    assert len(receipt["records"]) == 58
    assert receipt["totals"]["ohlcv_rows"] > 1_000_000
    assert receipt["totals"]["funding_rows"] > 10_000
    assert receipt["totals"]["official_archive_objects"] > 1_000
    assert receipt["availability_time_reconstruction"]["must_be_reconstructed_and_disclosed"]
    assert receipt["fresh_archive_download_executed"] is False
    assert receipt["full_walkforward_replayed"] is False
    assert receipt["independent_replication"] is False
