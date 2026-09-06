from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_sharadar_dividend_basis_resolution.py"


def _module():
    spec = importlib.util.spec_from_file_location("dividend_basis_resolution_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_issuer_anchor_authorizes_validation_only() -> None:
    documents = {
        "apple_history": b"$.82 Regular Cash 4-for-1 Stock Split",
        "apple_sec_filing": b"cash dividend of $0.82 per share",
        "sharadar_stocks_docs": b"Close Price - Split Adjusted",
        "sharadar_actions_docs": b"Value value numeric",
    }
    payload = _module().build(documents, retrieved_at="2026-08-23T00:00:00+00:00")
    assert payload["decision"] == (
        "VERSIONED_DIVIDEND_BASIS_REPAIR_AUTHORIZED_FOR_DATA_VALIDATION"
    )
    assert payload["status"] == "REPAIR_CONTRACT_SEALED_REPLAY_NOT_AUTHORIZED"
    assert payload["ordinary_event_anchor"]["exact_equality"] is True
    assert payload["repair_contract"]["amount_imputation_permitted"] is False
    assert payload["mandatory_post_build_gates"][
        "replay_permitted_before_all_gates_pass"
    ] is False
    assert payload["hypotheses_spent"] == 0
    assert payload["return_data_opened"] is False
