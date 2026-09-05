from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/audit_crypto_carry_first_rebalance_drift.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_first_drift", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_first_rebalance_drift_is_exactly_reproduced(tmp_path: Path) -> None:
    document = _module().run(tmp_path / "result.json")
    assert document["status"] == "PASS_FIRST_REBALANCE_CAUSE_EXACTLY_REPRODUCED"
    assert document["cross_section_difference"]["source_only"] == [
        "BINANCE:PERP:EOSUSDT"
    ]
    assert document["cross_section_difference"]["replay_only"] == []
    reconstruction = document["reconstruction"]
    assert reconstruction["source_quantities_exact"] is True
    assert reconstruction["replay_quantities_exact"] is True
    assert reconstruction["current_21_name_cross_section"]["cross_section_size"] == 21
    assert reconstruction["source_22_name_cross_section_with_eos"]["cross_section_size"] == 22
    assert document["new_trials"] == 0
