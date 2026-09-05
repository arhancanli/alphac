from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build_crypto_carry_metadata_manifest.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_metadata", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_published_crypto_carry_metadata_is_complete_and_bounded() -> None:
    receipt = _module().validate_published()
    assert receipt["status"] == "PASS_FULL_FROZEN_LOCAL_METADATA_INVENTORY"
    assert receipt["totals"]["records"] == 58
    assert receipt["totals"]["four_hour_funding_instruments"] == 2
    assert receipt["totals"]["eight_hour_funding_instruments"] == 56
    assert receipt["fresh_exchange_metadata_reacquired"] is False
    assert receipt["full_walkforward_replayed"] is False
    assert receipt["independent_replication"] is False
    assert all(row["asset_class"] == "crypto_perp" for row in receipt["records"])
    assert all(row["market_type"] == "perp" for row in receipt["records"])
