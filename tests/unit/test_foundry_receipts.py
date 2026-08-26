from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from alphaforge.foundry.contract import canonical_sha256
from alphaforge.foundry.receipts import (
    ReceiptContractError,
    expected_receipt_bindings,
    load_receipt_contract,
    verify_acceptance_receipts,
)

ROOT = Path(__file__).resolve().parents[2]


def _write_receipts(directory: Path) -> dict[str, dict[str, Any]]:
    contract = load_receipt_contract()
    bindings = {
        **expected_receipt_bindings(contract, ROOT),
        "source_commit": "a" * 40,
        "infrastructure_fingerprint": "sha256:" + "b" * 64,
        "worker_image_digest": "registry.invalid/foundry@sha256:" + "c" * 64,
    }
    base_time = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)
    documents: dict[str, dict[str, Any]] = {}
    for index, (receipt_id, raw_rule) in enumerate(contract["receipts"].items()):
        rule = dict(raw_rule)
        document: dict[str, Any] = {
            "schema": "canli.foundry-acceptance-receipt.v1",
            "receipt_id": receipt_id,
            "result": "PASS",
            "claim_boundary": "Synthetic unit-test receipt. It is not deployment evidence.",
            "generated_at": (base_time + dt.timedelta(seconds=index)).isoformat().replace(
                "+00:00", "Z"
            ),
            "bindings": bindings,
            "assertions": dict.fromkeys(rule["required_assertions"], True),
            "measurements": dict.fromkeys(rule["required_measurements"], 1),
            "evidence": [
                {
                    "name": "synthetic-test-evidence",
                    "sha256": "sha256:" + "d" * 64,
                    "classification": "PUBLIC",
                }
            ],
        }
        document["content_hash"] = canonical_sha256(document)
        (directory / f"{receipt_id}.json").write_text(json.dumps(document))
        documents[receipt_id] = document
    return documents


def test_absent_receipts_are_explicitly_not_operational(tmp_path: Path) -> None:
    report = verify_acceptance_receipts(tmp_path, repository_root=ROOT)
    assert report["status"] == "INCOMPLETE_NOT_OPERATIONAL"
    assert report["valid_receipts_present"] == 0
    assert report["required_receipts"] == 11


def test_complete_consistent_receipts_can_earn_acceptance(tmp_path: Path) -> None:
    _write_receipts(tmp_path)
    report = verify_acceptance_receipts(tmp_path, repository_root=ROOT)
    assert report["status"] == "ACCEPTED_OPERATIONAL"
    assert report["valid_receipts_present"] == 11
    assert report["missing_receipts"] == []


def test_passing_receipt_cannot_hide_a_false_assertion(tmp_path: Path) -> None:
    documents = _write_receipts(tmp_path)
    receipt_id = "negative_network_probe"
    document = documents[receipt_id]
    first_assertion = next(iter(document["assertions"]))
    document["assertions"][first_assertion] = False
    document["content_hash"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "content_hash"}
    )
    (tmp_path / f"{receipt_id}.json").write_text(json.dumps(document))
    with pytest.raises(ReceiptContractError, match="false assertion"):
        verify_acceptance_receipts(tmp_path, repository_root=ROOT)


def test_public_status_receipt_must_be_last(tmp_path: Path) -> None:
    documents = _write_receipts(tmp_path)
    receipt_id = "honest_public_status"
    document = documents[receipt_id]
    document["generated_at"] = "2026-08-26T11:59:00Z"
    document["content_hash"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "content_hash"}
    )
    (tmp_path / f"{receipt_id}.json").write_text(json.dumps(document))
    with pytest.raises(ReceiptContractError, match="predates"):
        verify_acceptance_receipts(tmp_path, repository_root=ROOT)
