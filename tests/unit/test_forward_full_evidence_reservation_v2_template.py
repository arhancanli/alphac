from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts/audit_forward_full_evidence_reservation_v2_template.py"
    spec = importlib.util.spec_from_file_location("forward_full_evidence_template_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_template_is_fail_closed_and_return_blind() -> None:
    module = _module()
    document = module.build(ROOT)
    assert document["status"] == "PASS_TEMPLATE_FAIL_CLOSED_NOT_ACTIVE_ZERO_RETURN"
    checks = document["fail_closed_checks"]
    assert checks["known_results_excluded"] is True
    assert checks["return_artifacts_read"] == 0
    assert checks["returns_computed"] is False
    assert checks["hypotheses_spent"] == 0
    assert checks["active_policy_changed"] is False
    assert checks["return_authorized"] is False
    assert len(document["remaining_before_promotion"]) == 5
    assert document["content_hash"] == module._content_hash(document)


def test_template_rejects_a_known_result_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    original = module._load

    def mutate(path: Path):
        value = original(path)
        if path.name == "forward_full_evidence_reservation_v2_template.json":
            value = json.loads(json.dumps(value))
            value["scope"]["applies_to_known_results"] = True
        return value

    monkeypatch.setattr(module, "_load", mutate)
    with pytest.raises(module.TemplateAuditError, match="prospective scope"):
        module.build(ROOT)


def test_template_rejects_outcome_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    original = module._load

    def mutate(path: Path):
        value = original(path)
        if path.name == "forward_full_evidence_reservation_v2_template.json":
            value = json.loads(json.dumps(value))
            value["sharpe"] = 9.9
        return value

    monkeypatch.setattr(module, "_load", mutate)
    with pytest.raises(module.TemplateAuditError, match="forbidden outcome keys"):
        module.build(ROOT)
