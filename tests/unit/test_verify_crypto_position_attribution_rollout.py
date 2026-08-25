from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_crypto_position_attribution_rollout.py"


def _module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    verifier = _module("rollout_verifier_test", SCRIPT)
    deploy = verifier._load_module("rollout_deploy_test", verifier.DEPLOY_SCRIPT)
    attribution = verifier._load_module("rollout_attribution_test", verifier.ATTRIBUTION_SCRIPT)
    return verifier, deploy, attribution


def _contract(verifier: ModuleType) -> dict[str, object]:
    return json.loads(verifier.CONTRACT_PATH.read_text(encoding="utf-8"))


def _receipt(
    deploy: ModuleType, contract: dict[str, object], *, baseline: int = 1_000
) -> dict[str, object]:
    files = contract["required_files"]
    assert isinstance(files, list)
    return deploy.build_receipt(
        before={"latest_equity_cycle_ts": baseline},
        after={
            "files": {item["path"]: item["desired_sha256"] for item in files},
            "position_snapshot_columns": ["cycle_ts", *deploy.REQUIRED_COLUMNS],
        },
        stamp="20260823T143500Z",
        contract_path=deploy.DEFAULT_CONTRACT,
    )


def _payload(
    deploy: ModuleType,
    *,
    cycle_ts: int = 2_000,
    source: str = "order_book_mid",
    unrealized_pnl: float = 40.0,
) -> dict[str, object]:
    return {
        "timer_state": "active",
        "service_state": "inactive",
        "position_snapshot_columns": ["cycle_ts", *deploy.REQUIRED_COLUMNS],
        "equity": {
            "cycle_ts": cycle_ts,
            "equity_quote": 1_100.0,
            "cash_quote": 900.0,
            "n_pos": 1,
            "ts": cycle_ts,
        },
        "positions": [
            {
                "cycle_ts": cycle_ts,
                "instrument_id": "BINANCE:PERP:BTCUSDT",
                "qty": 2.0,
                "avg_entry_price": 80.0,
                "opened_ts": 500,
                "mark_price": 100.0,
                "mark_source": source,
                "market_value_quote": 200.0,
                "unrealized_pnl_quote": unrealized_pnl,
            }
        ],
    }


def _document(
    modules: tuple[ModuleType, ModuleType, ModuleType],
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    verifier, deploy, attribution = modules
    contract = _contract(verifier)
    return verifier.build_document(
        receipt=_receipt(deploy, contract),
        contract=contract,
        payload=_payload(deploy) if payload is None else payload,
        receipt_sha256="a" * 64,
        deploy=deploy,
        attribution=attribution,
    )


def test_first_nonempty_natural_cycle_verifies(modules) -> None:
    verifier, _, _ = modules
    document = _document(modules)

    assert document["status"] == "VERIFIED_FIRST_NATURAL_MARKED_CYCLE"
    assert document["passes"] is True
    assert document["attribution"]["status"] == "COMPLETE"
    assert document["content_hash"] == verifier._content_hash(document)


def test_same_cycle_is_not_mislabeled_as_post_deployment(modules) -> None:
    _, deploy, _ = modules
    document = _document(modules, payload=_payload(deploy, cycle_ts=1_000))

    assert document["status"] == "WAITING_FOR_FIRST_NATURAL_CYCLE"
    assert document["passes"] is False


@pytest.mark.parametrize(
    ("payload_change", "expected"),
    [
        ({"source": "entry_fallback_missing_book"}, "ATTRIBUTION_FALLBACK_MARKS_PRESENT"),
        ({"unrealized_pnl": 41.0}, "ATTRIBUTION_POSITION_ARITHMETIC_FAILED"),
    ],
)
def test_bad_mark_provenance_or_arithmetic_fails_closed(modules, payload_change, expected) -> None:
    _, deploy, _ = modules
    document = _document(modules, payload=_payload(deploy, **payload_change))

    assert document["status"] == expected
    assert document["passes"] is False


def test_receipt_must_bind_exact_deployed_sources(modules) -> None:
    verifier, deploy, _ = modules
    contract = _contract(verifier)
    receipt = _receipt(deploy, contract)
    receipt["after"]["files"][deploy.EXPECTED_PATHS[0]] = "f" * 64
    receipt["content_hash"] = deploy._content_hash(receipt)

    with pytest.raises(verifier.VerificationError, match="desired source hashes"):
        verifier.validate_receipt(receipt, contract, deploy)


def test_receipt_binds_the_deployment_and_verification_code(modules) -> None:
    verifier, deploy, _ = modules
    contract = _contract(verifier)
    receipt = _receipt(deploy, contract)
    receipt["source_bindings"]["deployment_tool_sha256"] = "f" * 64
    receipt["content_hash"] = deploy._content_hash(receipt)

    with pytest.raises(verifier.VerificationError, match="source bindings"):
        verifier.validate_receipt(receipt, contract, deploy)


def test_no_receipt_is_deterministic_fail_closed_without_remote_query(modules) -> None:
    verifier, _, _ = modules
    first = verifier.no_deployment_receipt_document()
    second = verifier.no_deployment_receipt_document()

    assert first == second
    assert first["status"] == "NO_DEPLOYMENT_RECEIPT"
    assert first["passes"] is False
    assert first["remote_query_performed"] is False
    assert first["content_hash"] == verifier._content_hash(first)


def test_first_success_freezes_only_for_the_same_deployment_receipt(modules) -> None:
    verifier, _, _ = modules
    document = _document(modules)

    assert verifier.is_frozen_success(document, receipt_sha256="a" * 64)
    assert not verifier.is_frozen_success(document, receipt_sha256="b" * 64)
    document["attribution"]["latest_cycle"]["equity_quote"] = 999.0
    assert not verifier.is_frozen_success(document, receipt_sha256="a" * 64)
