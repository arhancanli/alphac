from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build_author_technical_audit_worksheets.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("author_audit_worksheets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_manuscript_gets_a_blank_non_invented_author_audit(tmp_path: Path) -> None:
    module = _module()
    root = tmp_path / "author_audits"
    document = module.generate(root)

    assert document["status"] == "PASS_BLANK_WORKSHEETS_ZERO_AUTHOR_APPROVALS"
    assert document["worksheets"] == 16
    assert document["questions"] == 80
    assert document["answers_completed"] == 0
    assert document["author_audits_completed"] == 0
    assert document["author_approvals"] == 0
    assert document["content_hash"] == module._content_hash(document)
    for record in document["records"]:
        worksheet = json.loads((root / record["worksheet"]).read_text())
        assert worksheet["author"] == "Arhan Canli"
        assert worksheet["author_audit_claimed"] is False
        assert worksheet["ai_detector_used"] is False
        assert worksheet["ai_detector_evasion_claimed"] is False
        assert worksheet["claim_trace"] == []
        assert all(question["answer"] is None for question in worksheet["author_questions"])
        assert worksheet["approval"]["decision"] is None
        assert worksheet["content_hash"] == module._content_hash(worksheet)


def test_persisted_author_audit_manifest_is_self_hashing_and_unapproved() -> None:
    module = _module()
    persisted = json.loads(module.OUTPUT.read_text())
    assert persisted["content_hash"] == module._content_hash(persisted)
    assert persisted["author_audits_completed"] == 0
    assert persisted["author_approvals"] == 0
