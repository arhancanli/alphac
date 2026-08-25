from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_final_six_family_packets_bind_exactly_sixteen_identities() -> None:
    script = REPO / "scripts" / "audit_remaining_research_families.py"
    spec = importlib.util.spec_from_file_location("remaining_family_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    packets = module.build_all()
    assert set(packets) == set(module.SPECS)
    assert sum(len(packet["identities"]) for packet in packets.values()) == 16
    assert (
        len({row["hypothesis_key"] for packet in packets.values() for row in packet["identities"]})
        == 16
    )
    assert all(
        packet["summary"]["admission_status"].startswith("NOT_ESTABLISHED")
        for packet in packets.values()
    )
