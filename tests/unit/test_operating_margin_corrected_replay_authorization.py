from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts/seal_operating_margin_corrected_replay_authorization.py"
    spec = importlib.util.spec_from_file_location("corrected_replay_authorization_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authorization_is_narrow_and_fail_closed() -> None:
    payload = _module().build(sealed_at="2026-08-23T00:00:00+00:00")
    assert payload["decision"] == "OPERATING_MARGIN_CORRECTED_REPLAY_AUTHORIZED_FAIL_CLOSED"
    assert payload["run_name"] == "single_operating_margin"
    assert payload["hypotheses_spent"] == 0
    assert payload["return_data_opened"] is False
    assert payload["accounting"]["global_split_gate_passed"] is False
    assert payload["accounting"]["historically_exposed_events"] == 2
    assert len(payload["verified_split_events"]) == 2
    assert payload["content_hash"].startswith("sha256:")
