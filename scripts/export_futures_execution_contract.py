"""Emit the deterministic dated-futures engineering capability contract.

This artifact is architecture evidence only. It opens no market data, evaluates
no returns, and spends no research hypothesis.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "execution" / "futures.py"
TESTS: Final[Path] = REPO / "tests" / "unit" / "test_futures_execution.py"
OUTPUT: Final[Path] = REPO / "artifacts" / "engineering" / "futures_execution_contract.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_contract() -> dict[str, object]:
    """Build the deterministic, source-bound capability statement."""
    payload: dict[str, object] = {
        "schema": "alphaforge.futures-execution-contract.v1",
        "classification": "engineering capability; not return or admission evidence",
        "status": "DOMAIN_PRIMITIVES_ONLY",
        "trial_accounting": {
            "market_data_opened": False,
            "returns_evaluated": False,
            "hypotheses_spent": 0,
        },
        "implemented": [
            "canonical FUTURE asset and market identities",
            "point-in-time contract metadata availability",
            "first-notice and last-trade exit buffers counted in supplied exchange sessions",
            "mandatory roll to the immediate next expiry or fail-closed flatten",
            "multi-observation next-contract volume confirmation",
            "locked-limit-up and locked-limit-down execution classification",
            "linear daily variation-margin cashflow",
            "hard rejection of generic crypto fee and calendar fallbacks",
        ],
        "invariants": {
            "roll_direction": "immediate next listed expiry only; never skip a lineage gap",
            "deadline": "earliest of first-notice and last-trade session buffers",
            "future_data": "metadata or liquidity available after decision raises LookaheadError",
            "missing_successor": "mandatory exit flattens when immediate successor is unavailable",
            "missing_liquidity": "volume roll holds; limit-state execution blocks",
        },
        "not_implemented": [
            "exchange/product session calendar ingestion",
            "dated-contract settlement/quote/volume market-data ingestion",
            "venue and product fee, exchange, initial-margin and maintenance-margin schedules",
            "continuous-series construction and roll-return attribution",
            "end-to-end backtest ledger integration",
            "futures broker routing or live order reconciliation",
            "historical limit-event and exchange-outage replay",
        ],
        "claim_boundary": (
            "These primitives prevent several classes of futures lifecycle leakage and unsafe "
            "fallback. They do not make any existing ETF proxy sleeve a futures sleeve and do "
            "not qualify a strategy for admission."
        ),
        "source_sha256": {
            "implementation": sha256(SOURCE),
            "tests": sha256(TESTS),
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
