from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/seal_walkforward_input_snapshot_protocol.py"


def _module():
    spec = importlib.util.spec_from_file_location("walkforward_input_snapshot_protocol", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_protocol_is_structurally_enforced_before_execution(tmp_path: Path) -> None:
    module = _module()
    document = module.run(tmp_path / "receipt.json")
    assert document["status"] == "PASS_PROSPECTIVE_PRIVATE_INPUT_SNAPSHOT_ENFORCED"
    enforcement = document["enforcement"]
    assert enforcement["automatic_for_every_persisted_walkforward"] is True
    assert enforcement["sealed_before_first_execution_leg"] is True
    assert enforcement["manifest_bound_into_walkforward_config"] is True
    assert enforcement["validator_rehashes_every_payload"] is True
    assert enforcement["private_data_rights_default"] is True
    assert document["retroactivity"]["repairs_historical_missing_snapshot"] is False
    assert document["trial_accounting"]["new_trials"] == 0
    assert document["content_hash"] == module._content_hash(document)
