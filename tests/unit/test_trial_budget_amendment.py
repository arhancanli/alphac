"""A budget raise is an owner amendment beside the policy, never an edit of the policy.

config/trial_accounting.json is embedded byte-for-byte in the v7 promotion receipt and hash-bound
by every sealed reservation, so its 400 ceiling cannot move without drifting all of them. The
owner's decision of 2026-09-23 (raise in steps: 500, then 700 only after a measured review) lives
in config/trial_accounting_budget_amendments.json. These tests pin that reservations at or below
400 validate exactly as before, that nothing above 400 exists without the amendment's hash, and
that a tampered or mis-bound amendment raises instead of quietly raising the ceiling.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from alphaforge.validation.trial_budget import (
    AMENDMENTS,
    BudgetAmendmentError,
    content_hash,
    effective_budget,
    governance_epoch_fields,
)
from alphaforge.validation.trial_reservation import ReservationError, _validate_governance_epoch

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = Path("config/sleeve_admission_contract.json")
POLICY = Path("config/trial_accounting.json")
RECEIPT = Path("config/admission_v7_promotion.json")


def _repo(tmp_path: Path, *, amendments: bool = True) -> Path:
    for relative in (CONTRACT, POLICY, RECEIPT, *((AMENDMENTS,) if amendments else ())):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    return tmp_path


def _effective_hash(repo: Path) -> str:
    contract = json.loads((repo / CONTRACT).read_text())
    return str(contract["prospective_scope"]["effective_contract_content_hash"])


def _epoch(repo: Path, ordinal: int) -> dict[str, object]:
    return governance_epoch_fields(
        repo,
        admission_contract=CONTRACT,
        trial_policy=POLICY,
        promotion_receipt=RECEIPT,
        effective_contract_hash=_effective_hash(repo),
        ordinal=ordinal,
    )


def _validate(repo: Path, epoch: dict[str, object]) -> dict[str, object]:
    ordinal = int(epoch["reservation_ordinal"])  # type: ignore[call-overload]
    return _validate_governance_epoch(
        {"governance_epoch": epoch},
        repo=repo,
        historical_identities=ordinal - 1,
        forward_identities_already_logged=0,
    )


def _rewrite(repo: Path, mutate: object) -> None:
    path = repo / AMENDMENTS
    doc = json.loads(path.read_text())
    mutate(doc)  # type: ignore[operator]
    doc["content_hash"] = content_hash(doc)
    path.write_text(json.dumps(doc))


def test_the_recorded_amendment_raises_the_ceiling_to_500_with_reviews_at_450_and_500() -> None:
    budget = effective_budget(ROOT, ROOT / POLICY)
    assert budget.policy_budget == 400
    assert budget.ceiling == 500
    assert {450, 500} <= set(budget.staged_hard_reviews)
    assert {360, 400} <= set(budget.staged_hard_reviews)


def test_the_policy_bytes_the_sealed_records_bind_are_the_ones_the_amendment_names() -> None:
    doc = json.loads((ROOT / AMENDMENTS).read_text())
    policy_sha = "sha256:" + hashlib.sha256((ROOT / POLICY).read_bytes()).hexdigest()
    assert [a["policy_sha256"] for a in doc["amendments"]] == [policy_sha]
    assert doc["content_hash"] == content_hash(doc)


def test_ordinals_at_or_below_400_validate_exactly_as_before(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    epoch = _epoch(repo, 400)
    assert "budget_amendment_sha256" not in epoch
    out = _validate(repo, epoch)
    assert out["hypothesis_identity_budget"] == 400
    assert "budget_amendment_sha256" not in out


def test_an_ordinal_at_or_below_400_may_not_bind_an_amendment(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    epoch = _epoch(repo, 400)
    epoch["budget_amendment_sha256"] = _epoch(repo, 401)["budget_amendment_sha256"]
    with pytest.raises(ReservationError, match="does not need"):
        _validate(repo, epoch)


def test_ordinal_401_binds_the_amendment_and_validates(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = _validate(repo, _epoch(repo, 401))
    assert out["hypothesis_identity_ceiling"] == 500
    assert out["budget_amendment_sha256"] is not None


def test_ordinal_401_without_the_amendment_hash_is_exhausted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    epoch = _epoch(repo, 401)
    del epoch["budget_amendment_sha256"]
    with pytest.raises(ReservationError, match="exhausted"):
        _validate(repo, epoch)


def test_ordinal_401_without_an_amendment_file_is_exhausted(tmp_path: Path) -> None:
    repo = _repo(tmp_path, amendments=False)
    with pytest.raises(BudgetAmendmentError, match="no budget amendment"):
        _epoch(repo, 401)
    epoch = _epoch(_repo(tmp_path / "with", amendments=True), 401)
    with pytest.raises(ReservationError, match="exhausted"):
        _validate(repo, epoch)


def test_ordinal_501_is_exhausted_until_a_further_amendment(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(ReservationError, match="exhausted"):
        _validate(repo, _epoch(repo, 501))


def test_a_stale_amendment_hash_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    epoch = _epoch(repo, 401)
    _rewrite(repo, lambda d: d["amendments"][0].update({"queue_rule": "changed after binding"}))
    with pytest.raises(ReservationError, match="amendment hash mismatch"):
        _validate(repo, epoch)


def test_a_hand_edited_amendment_raises_rather_than_raising_the_ceiling(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    path = repo / AMENDMENTS
    doc = json.loads(path.read_text())
    doc["amendments"][0]["hypothesis_identity_ceiling"] = 5000
    path.write_text(json.dumps(doc))  # content hash NOT recomputed
    with pytest.raises(BudgetAmendmentError, match="content hash"):
        effective_budget(repo, repo / POLICY)


def test_an_amendment_bound_to_other_policy_bytes_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    policy = repo / POLICY
    policy.write_bytes(policy.read_bytes() + b"\n")
    with pytest.raises(BudgetAmendmentError, match="different policy"):
        effective_budget(repo, policy)


@pytest.mark.parametrize(
    ("ceiling", "reviews", "message"),
    [
        (400, [400], "must rise"),
        (500, [350, 500], "staged reviews"),
        (500, [450], "staged reviews"),
    ],
)
def test_malformed_steps_are_refused(
    tmp_path: Path, ceiling: int, reviews: list[int], message: str
) -> None:
    repo = _repo(tmp_path)

    def mutate(doc: dict[str, object]) -> None:
        amendment = copy.deepcopy(doc["amendments"][0])  # type: ignore[index]
        amendment["hypothesis_identity_ceiling"] = ceiling
        amendment["staged_hard_reviews"] = reviews
        doc["amendments"] = [amendment]

    _rewrite(repo, mutate)
    with pytest.raises(BudgetAmendmentError, match=message):
        effective_budget(repo, repo / POLICY)


def test_the_recorded_prices_come_from_the_pricing_script_as_it_is_now() -> None:
    """Edit the pricing script and this fails until the amendment is re-priced and re-recorded."""
    doc = json.loads((ROOT / AMENDMENTS).read_text())
    for amendment in doc["amendments"]:
        priced = amendment["priced_by"]
        script = ROOT / priced["script"]
        assert (
            priced["script_sha256"] == "sha256:" + hashlib.sha256(script.read_bytes()).hexdigest()
        )
