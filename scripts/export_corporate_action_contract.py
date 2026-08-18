"""Emit deterministic corporate-action and delisting replay evidence."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "execution" / "corporate_actions.py"
ENGINE: Final[Path] = REPO / "src" / "alphaforge" / "backtest" / "engine.py"
LEDGER: Final[Path] = REPO / "src" / "alphaforge" / "backtest" / "ledger.py"
RESULT: Final[Path] = REPO / "src" / "alphaforge" / "backtest" / "result.py"
UNIT_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_corporate_actions.py"
ENGINE_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_backtest_engine.py"
INTEGRATION_TESTS: Final[Path] = (
    REPO / "tests" / "integration" / "test_split_marking_running_path.py"
)
NAN_BOUNDARY_TESTS: Final[Path] = (
    REPO / "tests" / "unit" / "test_corporate_action_nan_cash.py"
)
OUTPUT: Final[Path] = (
    REPO / "artifacts" / "engineering" / "corporate_action_contract.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_contract() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "alphaforge.corporate-action-contract.v2",
        "classification": "engineering capability; not return or admission evidence",
        "status": "EVENT_DRIVEN_BACKTEST_INTEGRATED",
        "trial_accounting": {
            "market_data_opened": False,
            "returns_evaluated": False,
            "hypotheses_spent": 0,
        },
        "implemented": [
            "PIT split and cash-dividend events with explicit availability lineage",
            "late event rejection when replay at the ex boundary would require future data",
            "split conversion of held quantities, average entry prices, and queued orders",
            "split price-discontinuity sanity checking before conversion",
            "signed cash-dividend accrual for long and short ex-date holdings",
            "persisted corporate_actions.parquet cashflow and transformation ledger",
            "delisting liquidation only with explicit SCD2 delisted_ts support",
            "fail-closed terminal price history for instruments still marked active",
            (
                "lake NaN split-cash normalization to null at the engine boundary while "
                "non-finite cash-dividend amounts still fail closed"
            ),
        ],
        "not_implemented": [
            "payable-date cash settlement and withholding-tax conventions",
            "fractional-share cash-in-lieu after reverse splits",
            "mergers, tender consideration, spin-offs, rights, and symbol changes",
            "bankruptcy recovery values and delisting-auction price formation",
            "cross-vendor corporate-action reconciliation and correction versioning",
            "live broker corporate-action polling and position reconciliation",
        ],
        "claim_boundary": (
            "The event-driven engine now accounts for source-bound splits, cash dividends, "
            "and metadata-confirmed delistings. It does not establish historical coverage "
            "completeness, model complex reorganizations, or prove live broker handling."
        ),
        "source_sha256": {
            "corporate_action_domain": sha256(SOURCE),
            "event_driven_engine": sha256(ENGINE),
            "ledger": sha256(LEDGER),
            "result_artifact": sha256(RESULT),
            "domain_tests": sha256(UNIT_TESTS),
            "engine_tests": sha256(ENGINE_TESTS),
            "integration_tests": sha256(INTEGRATION_TESTS),
            "nan_boundary_tests": sha256(NAN_BOUNDARY_TESTS),
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
