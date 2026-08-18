"""Emit the deterministic PIT market-status replay capability contract."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
STATUS_SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "execution" / "market_status.py"
STATUS_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_market_status.py"
ENGINE_SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "backtest" / "engine.py"
ENGINE_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_backtest_engine.py"
OUTPUT: Final[Path] = REPO / "artifacts" / "engineering" / "market_status_contract.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_contract() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "alphaforge.market-status-contract.v1",
        "classification": "engineering capability; not return or admission evidence",
        "status": "EVENT_DRIVEN_BACKTEST_INTEGRATED",
        "trial_accounting": {
            "market_data_opened": False,
            "returns_evaluated": False,
            "hypotheses_spent": 0,
        },
        "implemented": [
            "PIT venue-wide and instrument-specific status intervals",
            "explicit OPEN, HALTED, OUTAGE, AUCTION_ONLY, and CLOSE_ONLY states",
            "future-known status rejection and per-scope overlap rejection",
            "instrument status precedence over venue status",
            "coverage-complete fill-time enforcement in the event-driven backtester",
            "halt, outage, and auction-only execution blocking even when a bar exists",
            "close-only risk-increase blocking with reduce-only permission",
            "no-provider compatibility path preserved",
        ],
        "not_implemented": [
            "historical exchange-status feed ingestion and cross-source reconciliation",
            "auction imbalance, queue position, and auction-price formation",
            "cancel/replace state for resting orders across outage boundaries",
            "cross-venue smart routing and venue-specific failover",
            "live broker/exchange status polling and reconciliation",
            "restart persistence for outage-blocked strategy intents",
        ],
        "claim_boundary": (
            "Explicit status replay can block impossible fills; it does not create historical "
            "status coverage, model auction prices, or prove live venue failover."
        ),
        "source_sha256": {
            "status_implementation": sha256(STATUS_SOURCE),
            "status_tests": sha256(STATUS_TESTS),
            "event_driven_engine": sha256(ENGINE_SOURCE),
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
