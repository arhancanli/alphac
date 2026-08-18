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
INGEST_SOURCE: Final[Path] = (
    REPO / "src" / "alphaforge" / "data" / "ingest" / "market_status.py"
)
INGEST_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_market_status_ingest.py"
ENGINE_SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "backtest" / "engine.py"
ENGINE_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_backtest_engine.py"
OUTPUT: Final[Path] = REPO / "artifacts" / "engineering" / "market_status_contract.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_contract() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "alphaforge.market-status-contract.v4",
        "classification": "engineering capability; not return or admission evidence",
        "status": "EVENT_DRIVEN_BACKTEST_INTEGRATED",
        "coverage_status": "REVIEWED_INGEST_AND_BOUND_PREFLIGHT_NO_BUNDLED_CORPUS",
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
            (
                "coverage-complete run-level preflight for every instrument over the full "
                "backtest interval before bars are read"
            ),
            "halt, outage, and auction-only execution blocking even when a bar exists",
            "close-only risk-increase blocking with reduce-only permission",
            "no-provider compatibility path preserved",
            "strict reviewed manifests bound to the exact SHA-256 digest of supplied source bytes",
            (
                "separate source publication, event observation, historical availability, local "
                "capture, and review timestamps"
            ),
            "dual-review qualification and collision-checked source-record identities",
            (
                "exact official-exchange versus vendor reconciliation of status, scope, and "
                "effective interval"
            ),
            (
                "reconciliation-only pre-run coverage audit over explicit required instrument "
                "intervals without treating source silence as OPEN"
            ),
            (
                "instrument-over-venue precedence, future-known blocking without fallback, exact "
                "covered/gap duration reconciliation, and lineage-bearing coverage segments"
            ),
            (
                "reviewed provider construction refuses disclosed gaps and binds each requested "
                "run to a deterministic source-reconciled coverage-audit hash"
            ),
        ],
        "invariants": {
            "source_lineage": (
                "unknown manifest fields, source-byte digest mismatch, identity collisions, "
                "credential-bearing/non-HTTPS URLs, and impossible timestamp order fail closed"
            ),
            "historical_availability": (
                "replay knowledge is bounded by the source-disclosed available_at timestamp; "
                "local capture and review remain separately auditable"
            ),
            "independent_confirmation": (
                "reconciliation requires dual-reviewed official and vendor observations with "
                "distinct source identities and bytes and exact economic agreement"
            ),
            "coverage_preflight": (
                "every required millisecond must resolve to an effective reconciled event already "
                "available at that decision boundary; missing and future-known intervals are "
                "published explicitly and durations must reconcile exactly"
            ),
            "engine_binding": (
                "enabling market-status replay requires full run-interval coverage before any bar "
                "or strategy decision; reviewed runs record the exact coverage-audit hash"
            ),
        },
        "not_implemented": [
            (
                "a bundled content-verified historical exchange-status corpus, production feed "
                "adapters, automated capture, and empirical broad-market coverage evidence"
            ),
            "auction imbalance, queue position, and auction-price formation",
            "cancel/replace state for resting orders across outage boundaries",
            "cross-venue smart routing and venue-specific failover",
            "live broker/exchange status polling and reconciliation",
            "restart persistence for outage-blocked strategy intents",
        ],
        "claim_boundary": (
            "Explicit status replay can block impossible fills, and reviewed source-bound "
            "manifests can normalize and exactly reconcile supplied official/vendor records. A "
            "preflight audit proves completeness for explicitly supplied requirements and "
            "reconciliations and is bound to each reviewed run. No historical status corpus or "
            "production adapter is bundled; this "
            "does not prove broad-market coverage, model auction prices, or establish live venue "
            "failover."
        ),
        "source_sha256": {
            "status_implementation": sha256(STATUS_SOURCE),
            "status_tests": sha256(STATUS_TESTS),
            "ingest_implementation": sha256(INGEST_SOURCE),
            "ingest_tests": sha256(INGEST_TESTS),
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
