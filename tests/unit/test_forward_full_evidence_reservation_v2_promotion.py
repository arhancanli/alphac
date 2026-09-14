"""Promotion of the v2 template is one recorded decision that binds what it checked.

WHY. "IN_FORCE" must never be a word somebody typed. The receipt binds the template bytes, the
protocol bytes, the evidence-classes companion, the validator and every guard; the template
records the receipt and the effective ordinal; the template audit refuses IN_FORCE without a
receipt that binds the bytes on disk; and the public projection derives the promotion from the
audited receipt, never from a typed status. These tests exercise the promotion in a temporary
copy of the governed files and pin the promoted state of the repository itself.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from alphaforge.validation.experiments import ExperimentLog

REPO = Path(__file__).resolve().parents[2]


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROMOTE = _module(
    "v2_promotion_under_test", "scripts/promote_forward_full_evidence_reservation_v2.py"
)
TEMPLATE_AUDIT = _module(
    "v2_template_audit_under_test", "scripts/audit_forward_full_evidence_reservation_v2_template.py"
)
OWNER_WORDS = (
    "i want you to focus on adding sleeves improving each sleeves sharpe ratio returs cagr max dd "
    "and everything go agead make sure everything is perfect and i give you full permision for "
    "the activiations so you can go ahead"
)


def _governed_copy(tmp_path: Path, *, promoted: bool = False) -> Path:
    """Copy exactly the files the promotion reads and writes into a temporary repository."""
    for relative in (
        "config/forward_full_evidence_reservation_v2_template.json",
        "config/trial_accounting_evidence_classes.json",
        "config/trial_accounting.json",
        "config/sleeve_admission_contract.json",
        "docs/design/FORWARD_FULL_EVIDENCE_RESERVATION_V2.md",
        "scripts/audit_forward_full_evidence_reservation_v2_template.py",
        "scripts/audit_forward_full_evidence_reservation.py",
        "scripts/research_export.py",
        "src/alphaforge/validation/trial_reservation.py",
        "artifacts/research/trial_packet_manifest.json",
        *PROMOTE.GUARDS,
    ):
        source = REPO / relative
        if not source.is_file():
            pytest.skip(f"governed file lives in the working tree only: {relative}")
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # Two forward-epoch identities in a ledger, so the next governed ordinal is 231 (228 legacy
    # identities in the copied manifest + 2 + 1), the way the validator counts it.
    ledger = ExperimentLog(tmp_path / "artifacts" / "forward" / "experiments.jsonl")
    for index, name in enumerate(("forward_edge_a", "forward_edge_b"), start=1):
        ledger.record(
            {"alpha_names": [name], "allocator": "rank", "start": 1, "end": 2},
            sharpe_ann=0.0,
            sharpe_per_period=0.0,
            n_obs=10,
            skew=0.0,
            kurtosis=3.0,
            now_ms=index,
        )
    if promoted:
        return tmp_path
    template_path = tmp_path / "config" / "forward_full_evidence_reservation_v2_template.json"
    template = json.loads(template_path.read_text())
    template["status"] = "TEMPLATE_NOT_IN_FORCE_NO_RETURN_AUTHORIZATION"
    template["scope"]["earliest_possible_reservation_ordinal"] = 230
    template.pop("promotion", None)
    template_path.write_text(json.dumps(template, indent=2) + "\n")
    receipt = tmp_path / "config" / "forward_full_evidence_reservation_v2_promotion.json"
    if receipt.exists():
        receipt.unlink()
    return tmp_path


def _point(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    for name in (
        "ROOT",
        "TEMPLATE",
        "RECEIPT",
        "PROTOCOL",
        "EVIDENCE_CLASSES",
        "TRIAL_POLICY",
        "CONTRACT",
        "PACKET_MANIFEST",
        "TEMPLATE_AUDIT",
        "FILLED_AUDIT",
        "VALIDATOR",
    ):
        original = getattr(PROMOTE, name)
        monkeypatch.setattr(PROMOTE, name, repo / original.relative_to(REPO))


def test_promotion_writes_a_receipt_that_binds_the_template_and_flips_it_into_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _governed_copy(tmp_path)
    _point(monkeypatch, repo)
    receipt = PROMOTE.promote(authorized_by=OWNER_WORDS, promoted_at="2026-09-14", repo=repo)
    template = json.loads(
        (repo / "config/forward_full_evidence_reservation_v2_template.json").read_text()
    )
    assert template["status"] == "IN_FORCE"
    assert (
        template["promotion"]["effective_on_or_after_reservation_ordinal"]
        == receipt["effective_on_or_after_reservation_ordinal"]
    )
    assert receipt["effective_on_or_after_reservation_ordinal"] == 231
    assert receipt["effective_on_or_after_reservation_ordinal"] == PROMOTE.next_governed_ordinal(
        repo
    )
    assert receipt["promoted_template_sha256"] == PROMOTE._sha256(
        repo / "config/forward_full_evidence_reservation_v2_template.json"
    )
    assert set(receipt["gates"]) == set(PROMOTE.GATES)
    assert receipt["gates"]["OWNER_PROMOTION_RECORDED"]["authorized_by"] == OWNER_WORDS
    assert receipt["applies_to_known_results"] is False
    assert PROMOTE.verify_current(repo)["passes"] is True
    audited = TEMPLATE_AUDIT.build(repo)
    assert (
        audited["status"] == "PASS_TEMPLATE_PROMOTED_IN_FORCE_RETURN_BY_VALIDATED_RESERVATION_ONLY"
    )
    assert audited["remaining_before_promotion"] == []
    assert audited["promotion_receipt"]["content_hash"] == receipt["content_hash"]


def test_promotion_refuses_to_run_twice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _governed_copy(tmp_path)
    _point(monkeypatch, repo)
    PROMOTE.promote(authorized_by=OWNER_WORDS, promoted_at="2026-09-14", repo=repo)
    with pytest.raises(PROMOTE.PromotionError, match="already promoted"):
        PROMOTE.promote(authorized_by=OWNER_WORDS, promoted_at="2026-09-14", repo=repo)


def test_promotion_refuses_a_missing_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _governed_copy(tmp_path)
    _point(monkeypatch, repo)
    (repo / "config" / "trial_accounting_evidence_classes.json").write_text(
        json.dumps({"schema": "canli.alphac-trial-evidence-classes.v0"})
    )
    with pytest.raises(PROMOTE.PromotionError, match="evidence classes"):
        PROMOTE.promote(authorized_by=OWNER_WORDS, promoted_at="2026-09-14", repo=repo)


def test_in_force_without_a_receipt_fails_the_template_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _governed_copy(tmp_path)
    template_path = repo / "config/forward_full_evidence_reservation_v2_template.json"
    template = json.loads(template_path.read_text())
    template["status"] = "IN_FORCE"
    template_path.write_text(json.dumps(template))
    with pytest.raises(TEMPLATE_AUDIT.TemplateAuditError, match="no promotion receipt"):
        TEMPLATE_AUDIT.build(repo)


def test_a_receipt_that_no_longer_binds_the_template_fails_the_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _governed_copy(tmp_path)
    _point(monkeypatch, repo)
    PROMOTE.promote(authorized_by=OWNER_WORDS, promoted_at="2026-09-14", repo=repo)
    template_path = repo / "config/forward_full_evidence_reservation_v2_template.json"
    template = json.loads(template_path.read_text())
    template["pbo_matrix"]["minimum_identity_columns"] = 1  # weakened after promotion
    template_path.write_text(json.dumps(template))
    with pytest.raises(TEMPLATE_AUDIT.TemplateAuditError, match="does not bind the template"):
        TEMPLATE_AUDIT.build(repo)
    assert PROMOTE.verify_current(repo)["passes"] is False


def test_the_repository_template_is_promoted_and_its_receipt_binds_it() -> None:
    receipt_path = REPO / "config" / "forward_full_evidence_reservation_v2_promotion.json"
    assert receipt_path.is_file(), "the template has not been promoted in this repository"
    verdict = PROMOTE.verify_current(REPO)
    assert verdict["passes"] is True, verdict["problems"]
    receipt = json.loads(receipt_path.read_text())
    assert receipt["authorized_by"] == OWNER_WORDS
    audited = TEMPLATE_AUDIT.build(REPO)
    assert (
        audited["status"] == "PASS_TEMPLATE_PROMOTED_IN_FORCE_RETURN_BY_VALIDATED_RESERVATION_ONLY"
    )
