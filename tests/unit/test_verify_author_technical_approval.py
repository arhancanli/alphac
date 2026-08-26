from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_author_technical_approval.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_author_approval", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed_response(module: ModuleType) -> dict[str, object]:
    response = module.prepare("alphavintage_macro_surprise")
    for question in response["author_questions"]:
        question["answer"] = (
            "This test fixture supplies a sufficiently detailed author answer without claiming "
            "that a real human approval occurred."
        )
        question["answered_by"] = "Arhan Canli"
        question["approved_by_author"] = True
    source = ROOT / "publication" / "alphavintage" / "v1.0.0" / "trial_accounting.json"
    response["claim_trace"] = [
        {
            "id": "A1",
            "claim": "The corrected historical verdict is killed.",
            "manuscript_location": "Abstract",
            "capital_kind": "HISTORICAL_RESEARCH_SIMULATION",
            "source_artifact": str(source.relative_to(ROOT)),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "selector": "$.verdict",
            "recomputed_value": "KILLED",
            "matches_manuscript": True,
        }
    ]
    for check in response["research_integrity_checks"]:
        check["passes"] = True
        check["evidence"] = "Test-only evidence binding; no real approval is claimed."
    response["ai_assistance"] = {
        "used": True,
        "systems": ["TEST_AI_SYSTEM"],
        "scope": "Test fixture generation and mechanical validation only.",
        "venue_disclosure_text": (
            "This test fixture used a named AI system and does not represent a real manuscript."
        ),
        "author_reviewed_every_retained_claim": True,
        "disclosure_approved_by_author": True,
    }
    response["approval"] = {
        "decision": "APPROVED_FOR_FRESH_READER",
        "blocking_issues": [],
        "author_statement": module.APPROVAL_STATEMENT,
        "explicit_authorization_reference": "TEST_FIXTURE_NOT_REAL_AUTHORIZATION",
        "approval_date": "2026-08-26",
        "approved_manuscript_sha256": response["manuscript_binding"]["sha256"],
        "approved_pdf_sha256": response["paper_pdf_binding"]["sha256"],
        "self_attested_by_author": True,
    }
    return response


def test_prepare_is_blank_and_bound_to_current_worksheet() -> None:
    module = _module()
    response = module.prepare("alphavintage_macro_surprise")
    assert response["schema"] == module.RESPONSE_SCHEMA
    assert response["author"] == "Arhan Canli"
    assert len(response["author_questions"]) == 5
    assert all(item["answer"] is None for item in response["author_questions"])
    assert response["claim_trace"] == []
    assert response["ai_assistance"]["used"] is None
    assert response["approval"]["decision"] is None


def test_complete_response_produces_bounded_self_attestation_receipt() -> None:
    module = _module()
    receipt = module.verify(_completed_response(module))
    assert receipt["status"] == "PASS_SELF_ATTESTED_AUTHOR_TECHNICAL_APPROVAL"
    assert receipt["questions_answered"] == 5
    assert receipt["claim_trace_rows"] == 1
    assert receipt["integrity_checks_passed"] == 11
    assert receipt["identity_proof"].endswith("NOT_INDEPENDENTLY_VERIFIED_BY_SOFTWARE")
    assert receipt["external_review_claimed"] is False
    assert receipt["publication_claimed"] is False
    assert receipt["content_hash"] == module._content_hash(receipt)


def test_stale_evidence_hash_fails_closed() -> None:
    module = _module()
    response = _completed_response(module)
    response["claim_trace"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source hash does not verify"):
        module.verify(response)


@pytest.mark.parametrize("binding", ["manuscript_binding", "paper_pdf_binding"])
def test_stale_manuscript_or_pdf_binding_fails_closed(binding: str) -> None:
    module = _module()
    response = _completed_response(module)
    response[binding]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="authoritative worksheet binding"):
        module.verify(response)


def test_changed_worksheet_generator_binding_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    response = _completed_response(module)
    real_sha256 = module._sha256

    def changed_generator_hash(path: Path) -> str:
        if path == module.GENERATOR:
            return "0" * 64
        return real_sha256(path)

    monkeypatch.setattr(module, "_sha256", changed_generator_hash)
    with pytest.raises(ValueError, match="current immutable worksheet"):
        module.verify(response)


def test_duplicate_question_row_fails_closed() -> None:
    module = _module()
    response = _completed_response(module)
    response["author_questions"].append(copy.deepcopy(response["author_questions"][0]))
    with pytest.raises(ValueError, match="all and only the governed author questions"):
        module.verify(response)


def test_missing_claim_trace_fails_closed() -> None:
    module = _module()
    response = _completed_response(module)
    response["claim_trace"] = []
    with pytest.raises(ValueError, match="at least one result-bearing claim trace"):
        module.verify(response)


def test_future_approval_date_fails_closed() -> None:
    module = _module()
    response = _completed_response(module)
    response["approval"]["approval_date"] = "2999-01-01"
    with pytest.raises(ValueError, match="cannot be in the future"):
        module.verify(response)


def test_missing_ai_disclosure_fails_closed() -> None:
    module = _module()
    response = copy.deepcopy(_completed_response(module))
    response["ai_assistance"]["venue_disclosure_text"] = None
    with pytest.raises(ValueError, match="venue AI disclosure text"):
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
        json.dumps(module.prepare("alphavintage_macro_surprise")),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "verify_author_technical_approval.py",
            "verify",
            "--input",
            str(response_path),
        ],
    )

    assert module.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("FAIL: answer WHY_TEST must contain at least 40")
    assert "Traceback" not in captured.err
