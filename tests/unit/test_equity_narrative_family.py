from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_narrative_packet_binds_the_single_preregistered_kill() -> None:
    script = REPO / "scripts" / "audit_equity_narrative_family.py"
    spec = importlib.util.spec_from_file_location("audit_equity_narrative_family_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    packet = module.build()
    assert packet["summary"]["distinct_hypothesis_identities"] == 1
    assert packet["summary"]["verdict"] == "KILL"
    assert packet["summary"]["technically_eligible"] is False
    assert packet["identity"]["hypothesis_key"] == "e2b76a7604131f00"
    assert len(packet["identity"]["artifact_sha256"]) == 64
