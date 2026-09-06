from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build_fresh_context_reader_packets.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fresh_context_reader_packets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_manuscript_gets_a_blank_reader_packet(tmp_path: Path) -> None:
    module = _module()
    root = tmp_path / "reader_packets"
    document = module.generate(root)

    assert document["status"] == "PASS_BLANK_PACKETS_ZERO_READERS_ZERO_REVIEWS"
    assert document["papers"] == 16
    assert document["questions"] == 144
    assert document["answers_completed"] == 0
    assert document["readers_assigned"] == 0
    assert document["reviews_completed"] == 0
    assert document["content_hash"] == module._content_hash(document)
    for record in document["records"]:
        packet = json.loads((root / record["packet"]).read_text())
        assert packet["reader"]["identity"] is None
        assert packet["reader"]["assigned"] is False
        assert packet["fresh_context_review_claimed"] is False
        assert all(question["answer"] is None for question in packet["questions"])
        assert packet["decision"]["value"] is None
        assert packet["content_hash"] == module._content_hash(packet)


def test_persisted_reader_manifest_is_self_hashing_and_unreviewed() -> None:
    module = _module()
    persisted = json.loads(module.OUTPUT.read_text())
    assert persisted["content_hash"] == module._content_hash(persisted)
    assert persisted["readers_assigned"] == 0
    assert persisted["reviews_completed"] == 0

