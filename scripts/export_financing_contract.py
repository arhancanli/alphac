"""Emit deterministic cash-financing replay capability evidence."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "execution" / "financing.py"
ENGINE: Final[Path] = REPO / "src" / "alphaforge" / "backtest" / "engine.py"
LEDGER: Final[Path] = REPO / "src" / "alphaforge" / "backtest" / "ledger.py"
RESULT: Final[Path] = REPO / "src" / "alphaforge" / "backtest" / "result.py"
UNIT_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_financing.py"
LEDGER_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_ledger.py"
ENGINE_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_backtest_engine.py"
OUTPUT: Final[Path] = REPO / "artifacts" / "engineering" / "financing_contract.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_contract() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "alphaforge.financing-contract.v1",
        "classification": "engineering capability; not return or admission evidence",
        "status": "EVENT_DRIVEN_BACKTEST_INTEGRATED_NO_HISTORICAL_COVERAGE",
        "trial_accounting": {
            "market_data_opened": False,
            "returns_evaluated": False,
            "hypotheses_spent": 0,
        },
        "implemented": [
            "PIT financing schedules with observed, available, and validity timestamps",
            "ACT/360 and ACT/365 interval accrual",
            "separate positive-cash credit, margin-debit, and short-proceeds rates",
            "short-sale proceeds segregated up to current short market value",
            "complete-interval coverage requirement with missing-rate failure",
            "single-ledger-currency guard for enabled financing replay",
            "event-driven accrual before each bar's fills and cashflow events",
            "persisted financing.parquet bases, rates, lineage, and signed payments",
        ],
        "not_implemented": [
            "historical broker financing schedules and account-tier ingestion",
            "multi-currency cash ledgers and FX translation",
            "security-specific collateral haircuts and rehypothecation",
            "intraday margin calls, forced liquidation, and default waterfalls",
            "futures initial and maintenance margin integration",
            "options margin, collateral optimization, and portfolio margin",
            "live broker interest accrual and statement reconciliation",
        ],
        "claim_boundary": (
            "The event-driven engine can replay fully covered financing schedules and "
            "persist their cash effects. No historical rate coverage is bundled, and this "
            "does not prove broker-specific margin, collateral, or live statement parity."
        ),
        "source_sha256": {
            "financing_domain": sha256(SOURCE),
            "event_driven_engine": sha256(ENGINE),
            "ledger": sha256(LEDGER),
            "result_artifact": sha256(RESULT),
            "domain_tests": sha256(UNIT_TESTS),
            "ledger_tests": sha256(LEDGER_TESTS),
            "engine_tests": sha256(ENGINE_TESTS),
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
