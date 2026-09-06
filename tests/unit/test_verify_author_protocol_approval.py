from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_author_protocol_approval.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_author_protocol", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed_test_response(module: ModuleType) -> dict[str, object]:
    response = module.prepare("merger-announcement-identity-v2")
    response["status"] = "AUTHOR_COMPLETED_RESPONSE"
    for question in response["author_questions"]:
        question["answer"] = (
            "This test-only fixture supplies a sufficiently detailed answer and does not claim "
            "that Arhan or any other human completed a real protocol review."
        )
        question["answered_by"] = "Arhan Canli"
        question["approved_by_author"] = True
    for check in response["technical_checks"]:
        check["author_confirmed"] = True
        check["evidence"] = "Test-only structural evidence; no real approval is claimed."
    response["ai_assistance"] = {
        "used": True,
        "systems": ["TEST_AI_SYSTEM"],
        "scope": "Test fixture generation and mechanical verification only.",
        "public_disclosure_text": (
            "A named test system generated this fixture; it is not a real author response."
        ),
        "author_reviewed_every_retained_claim": True,
        "disclosure_approved_by_author": True,
    }
    response["approval"] = {
        "decision": "APPROVED_FOR_DISJOINT_CONFIRMATION_CORPUS_ACQUISITION",
        "blocking_issues": [],
        "author_statement": module.AUTHOR_STATEMENT,
        "explicit_authorization_reference": "TEST_FIXTURE_NOT_REAL_AUTHORIZATION",
        "approval_date": module.datetime.now(module.UTC).date().isoformat(),
        "approved_protocol_sha256": response["protocol_binding"]["sha256"],
        "approved_evidence_sha256": response["evidence_binding"]["sha256"],
        "approved_evidence_content_hash": response["evidence_binding"]["content_hash"],
        "self_attested_by_author": True,
    }
    return response


def test_prepare_is_blank_and_bound_to_current_protocol_packet() -> None:
    module = _module()
    response = module.prepare("treasury-auction-state-machine")
    assert response["schema"] == module.RESPONSE_SCHEMA
    assert response["author"] == "Arhan Canli"
    assert len(response["author_questions"]) == 6
    assert all(item["answer"] is None for item in response["author_questions"])
    assert all(item["author_confirmed"] is None for item in response["technical_checks"])
    assert response["ai_assistance"]["used"] is None
    assert response["approval"]["decision"] is None


def test_complete_test_response_produces_bounded_self_attestation_receipt() -> None:
    module = _module()
    receipt = module.verify(_completed_test_response(module))
    assert receipt["status"] == "PASS_SELF_ATTESTED_AUTHOR_PROTOCOL_APPROVAL"
    assert receipt["approval_decision"] == (
        "APPROVED_FOR_DISJOINT_CONFIRMATION_CORPUS_ACQUISITION"
    )
    assert receipt["questions_answered"] == 6
    assert receipt["technical_checks_confirmed"] == 6
    assert receipt["identity_proof"].endswith("NOT_INDEPENDENTLY_VERIFIED_BY_SOFTWARE")
    assert receipt["external_review_claimed"] is False
    assert receipt["publication_claimed"] is False
    assert receipt["content_hash"] == module.content_hash(receipt)


def test_stale_protocol_binding_fails_closed() -> None:
    module = _module()
    response = _completed_test_response(module)
    response["protocol_binding"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="authoritative packet binding"):
        module.verify(response)


def test_missing_answer_fails_closed() -> None:
    module = _module()
    response = _completed_test_response(module)
    response["author_questions"][0]["answer"] = None
    with pytest.raises(ValueError, match="must contain at least 40"):
        module.verify(response)


def test_wrong_activation_decision_fails_closed() -> None:
    module = _module()
    response = _completed_test_response(module)
    response["approval"]["decision"] = "APPROVED_FOR_RETURN_EXECUTION"
    with pytest.raises(ValueError, match="only APPROVED_FOR_DISJOINT"):
        module.verify(response)


def test_missing_ai_disclosure_fails_closed() -> None:
    module = _module()
    response = copy.deepcopy(_completed_test_response(module))
    response["ai_assistance"]["public_disclosure_text"] = None
    with pytest.raises(ValueError, match="public AI disclosure text"):
        module.verify(response)


def test_future_approval_date_fails_closed() -> None:
    module = _module()
    response = _completed_test_response(module)
    response["approval"]["approval_date"] = "2999-01-01"
    with pytest.raises(ValueError, match="cannot be in the future"):
        module.verify(response)


def test_output_writer_never_overwrites(tmp_path: Path) -> None:
    module = _module()
    destination = tmp_path / "approval.json"
    module._write_new(destination, {"first": True})
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        module._write_new(destination, {"second": True})


def test_cli_reports_incomplete_response_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    response_path = tmp_path / "blank-response.json"
    response_path.write_text(
        json.dumps(module.prepare("merger-announcement-identity-v2")), encoding="utf-8"
    )
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "verify_author_protocol_approval.py",
            "verify",
            "--input",
            str(response_path),
        ],
    )
    assert module.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("FAIL: response status must be AUTHOR_COMPLETED_RESPONSE")
    assert "Traceback" not in captured.err
