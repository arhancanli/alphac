"""Emit the deterministic securities-borrow engineering capability contract."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "execution" / "borrow.py"
TESTS: Final[Path] = REPO / "tests" / "unit" / "test_borrow_execution.py"
ENGINE: Final[Path] = REPO / "src" / "alphaforge" / "backtest" / "engine.py"
ENGINE_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_backtest_engine.py"
OUTPUT: Final[Path] = REPO / "artifacts" / "engineering" / "borrow_execution_contract.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_contract() -> dict[str, object]:
    """Build a deterministic capability statement bound to implementation and tests."""
    payload: dict[str, object] = {
        "schema": "alphaforge.borrow-execution-contract.v1",
        "classification": "engineering capability; not return or admission evidence",
        "status": "EVENT_DRIVEN_BACKTEST_INTEGRATED",
        "trial_accounting": {
            "market_data_opened": False,
            "returns_evaluated": False,
            "hypotheses_spent": 0,
        },
        "implemented": [
            "point-in-time security-level borrow quote availability and validity",
            "easy, hard, and unavailable borrow states",
            "quantity-bounded granted, partial, and denied locate outcomes",
            "incremental-short locate quantity net of long inventory and existing shorts",
            "ACT/365 fee accrual over an exactly covered quote-validity interval",
            "point-in-time recall notices capped by the outstanding short",
            "forced-buy-in escalation at the explicit cover deadline",
            "optional event-driven short-entry locate denial and quantity caps",
            "optional event-driven security-level fee accrual with no-provider parity",
            "retryable recall cover orders reduced only by actual filled quantity",
            "forced-buy-in order escalation at the notice deadline",
        ],
        "invariants": {
            "future_data": "future-known borrow quotes and recall notices raise LookaheadError",
            "locate_quantity": "a grant never exceeds requested or explicitly available quantity",
            "fee_lineage": "one quote must cover the complete accrual interval",
            "recall_quantity": (
                "cover instruction never exceeds recalled or outstanding short quantity"
            ),
            "forced_buy_in": "deadline escalation is explicit; no fill is fabricated",
        },
        "not_implemented": [
            "historical security-lending feed ingestion and vendor reconciliation",
            "broker locate reservation, release, and intraday refresh",
            "fee-rebate conventions, collateral interest, and negative rebates",
            "partial recall allocation across tax lots and strategies",
            "forced-buy-in auction, spread, impact, and fill simulation",
            "restart recovery of outstanding recall obligations across process boundaries",
            "live broker recall polling, order routing, and post-trade reconciliation",
        ],
        "claim_boundary": (
            "These primitives prevent current borrow flags and general-collateral rates from being "
            "silently treated as historical security-level evidence. They do not prove that any "
            "historical short was locatable or that a forced buy-in could execute at a "
            "modeled price."
        ),
        "source_sha256": {
            "implementation": sha256(SOURCE),
            "tests": sha256(TESTS),
            "event_driven_engine": sha256(ENGINE),
            "event_driven_tests": sha256(ENGINE_TESTS),
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return payload


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_contract(), indent=2) + "\n")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
