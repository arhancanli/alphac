"""Emit the deterministic options engineering capability contract.

This architecture artifact opens no market data, evaluates no returns, and spends no
research hypothesis.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "execution" / "options.py"
TESTS: Final[Path] = REPO / "tests" / "unit" / "test_options_execution.py"
DELIVERABLE_SOURCE: Final[Path] = (
    REPO / "src" / "alphaforge" / "execution" / "options_deliverables.py"
)
DELIVERABLE_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_options_deliverables.py"
ADJUSTMENT_INGEST_SOURCE: Final[Path] = (
    REPO / "src" / "alphaforge" / "data" / "ingest" / "option_adjustments.py"
)
ADJUSTMENT_INGEST_TESTS: Final[Path] = (
    REPO / "tests" / "unit" / "test_option_adjustment_ingest.py"
)
OCC_ARCHIVE_SOURCE: Final[Path] = (
    REPO / "src" / "alphaforge" / "data" / "ingest" / "occ_memo_archive.py"
)
OCC_ARCHIVE_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_occ_memo_archive.py"
PACKAGE_SOURCE: Final[Path] = (
    REPO / "src" / "alphaforge" / "execution" / "options_packages.py"
)
PACKAGE_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_options_packages.py"
FEE_SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "execution" / "options_fees.py"
FEE_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_options_fees.py"
MARGIN_SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "execution" / "options_margin.py"
MARGIN_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_options_margin.py"
OUTPUT: Final[Path] = REPO / "artifacts" / "engineering" / "options_execution_contract.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_contract() -> dict[str, object]:
    """Build the deterministic, source-bound capability statement."""
    payload: dict[str, object] = {
        "schema": "alphaforge.options-execution-contract.v9",
        "classification": "engineering capability; not return or admission evidence",
        "status": "DOMAIN_PRIMITIVES_ONLY",
        "trial_accounting": {
            "market_data_opened": False,
            "returns_evaluated": False,
            "hypotheses_spent": 0,
        },
        "implemented": [
            "canonical OPTION asset and market identities",
            "point-in-time contract-term and quote availability",
            "crossed-market and stale-quote rejection without strike interpolation",
            "single-underlying active-lifecycle surfaces with unique economic terms",
            "positive-size bid/ask-bound call/put monotonicity checks by homogeneous series",
            "nonuniform-strike convexity checks from displayed bid/ask bounds",
            "official settlement observations distinct from last trades and midpoints",
            "cash and physical expiry delivery for signed call and put positions",
            "automatic-exercise threshold with explicit lapse",
            "authoritative early-assignment notices for American physical options",
            "source-bound contiguous point-in-time adjusted-deliverable revisions",
            "signed multi-asset and multi-currency adjusted baskets for expiry and assignment",
            "strict exact-decimal reviewed OCC adjustment extraction manifests",
            "content-addressed point-in-time memo revisions with unresolved and delayed blockers",
            (
                "allowlisted bounded no-redirect OCC memo transport and immutable "
                "content-addressed source archive"
            ),
            "reviewed OCC extractions bound to exact archived bytes available by review time",
            "exact OCC-versus-vendor adjusted-deliverable economic reconciliation",
            (
                "ratio-defined multi-leg IOC/FOK package replay crossing side-specific displayed "
                "bid/ask prices with explicit homogeneous premium currency and whole-package-unit "
                "size caps"
            ),
            (
                "net debit or minimum-credit package limits, ratio-preserving IOC partial fills, "
                "and atomic FOK rejection"
            ),
            (
                "optional point-in-time per-leg OPEN/HALTED/OUTAGE/AUCTION_ONLY/CLOSE_ONLY package "
                "status replay with fail-closed missing coverage"
            ),
            (
                "close-only package execution only after integer-contract position evidence proves "
                "every requested leg reduces without increasing or flipping exposure"
            ),
            (
                "exact-decimal point-in-time option fee schedule revisions keyed by venue, "
                "account class, product group, and premium currency"
            ),
            (
                "side-, liquidity-, and event-scoped per-contract and premium-rate fees, minima, "
                "caps, rebates, explicit component rounding, exercise fees, and assignment fees"
            ),
            (
                "complete-matrix exact-decimal internal option scenario margin with cross-leg P&L "
                "netting and locked model/input artifact hashes"
            ),
            (
                "point-in-time initial/maintenance margin policies with scenario-loss multipliers, "
                "short-contract floors, gross-short-mark and concentration add-ons"
            ),
            "hard rejection of generic crypto routing and fee fallbacks",
        ],
        "invariants": {
            "future_data": "future-known terms, quotes, settlements, or notices fail closed",
            "surface_missingness": "unquoted strikes remain absent; no interpolation is invented",
            "surface_identity": (
                "each snapshot has one underlying; duplicate terms and post-last-trade contracts "
                "fail closed"
            ),
            "cross_strike_integrity": (
                "monotonicity and convexity use only same-series, same-premium-currency, "
                "positive-size bid/ask bounds"
            ),
            "settlement": "expiry cashflow uses an official post-expiry available observation",
            "physical_delivery": (
                "underlying and strike-cash deltas preserve call/put and long/short signs"
            ),
            "assignment": "only an observed notice can create early-assignment delivery",
            "adjusted_deliverables": (
                "only the latest revision both effective and available at the decision may create "
                "a deterministic signed asset/cash basket"
            ),
            "adjustment_ingest": (
                "unknown manifest fields, unreviewed or unresolved terms, delayed settlement, "
                "reused source content, and cross-vendor economic disagreement fail closed"
            ),
            "occ_source_archive": (
                "memo URL identities are allowlisted; immutable manifests bind observation time, "
                "HTTP metadata, exact SHA-256 bytes, and a reverified content-addressed blob"
            ),
            "displayed_package_execution": (
                "positive ratios cross asks, negative ratios cross strictly positive bids, the "
                "smallest whole-number displayed leg capacity controls every leg, and execution "
                "records require one premium currency and reconcile premium cash to net package "
                "debit"
            ),
            "option_market_status": (
                "when status replay is required, every executable leg must have an effective, "
                "known status; halts, outages, and continuous fills in auction-only state block, "
                "while close-only permits only pre-validated reduce-only packages"
            ),
            "option_fee_assessment": (
                "only a schedule revision both effective and available at assessment may apply; "
                "trade fees consume accepted leg executions and exact fee lines must reconcile "
                "to their Decimal total after declared component rounding, minima, and caps"
            ),
            "internal_scenario_margin": (
                "every scenario must price every position exactly once in one premium currency; "
                "future, stale, incomplete, or malformed matrices fail closed and every reported "
                "requirement component reconciles to its recorded policy parameters; the snapshot "
                "model id must equal the policy risk method"
            ),
        },
        "not_implemented": [
            "historical OPRA/OptionMetrics quote and terms ingestion",
            (
                "operational unattended OCC acquisition (the live endpoint returned a Cloudflare "
                "HTTP 403 managed challenge to direct and headless-browser clients on 2026-08-18), "
                "automated PDF text extraction, a reviewed historical memo corpus, and a "
                "production vendor-terms adapter"
            ),
            (
                "implied-volatility fitting, put-call parity/rate-dividend checks, arbitrage "
                "repair, and surface interpolation"
            ),
            "dividend, rates, borrow, early-exercise, and assignment-probability models",
            (
                "a content-verified historical venue/account/product fee corpus and production "
                "fee adapter; beyond-displayed-size impact, queue position, complex-order-"
                "book price improvement, and complex-order auction execution; historical option "
                "status ingestion and live outage polling/failover"
            ),
            (
                "broker/OCC/regulatory margin equivalence, a validated option stress repricer and "
                "calibrated scenario corpus, opening-premium collateral integration, margin calls, "
                "forced liquidation, and live broker margin reconciliation"
            ),
            "end-to-end options backtest ledger integration",
            "options broker routing, exercise instructions, or live reconciliation",
        ],
        "claim_boundary": (
            "These primitives make option quote, cross-strike integrity, adjusted-deliverable "
            "normalization/reconciliation, source-byte archival, displayed-size package crossing, "
            "exact fee-assessment semantics, internal scenario-margin arithmetic, and lifecycle "
            "assumptions explicit. Internal scenario margin is not broker, clearinghouse, "
            "exchange, or regulatory margin and does not include opening premium cash. No "
            "historical "
            "fee schedule corpus or calibrated venue rates are bundled. The package replay is an "
            "atomic crossing "
            "assumption over independently displayed legs, not evidence of simultaneous market "
            "fillability. Status replay consumes supplied PIT events but has no historical option "
            "status corpus or live venue polling. The archive accepts an injectable transport, "
            "but current live OCC access "
            "is challenge-blocked. These primitives do not constitute a historical OCC corpus, "
            "prove adjustment coverage, actual package fillability, fill probability, or price "
            "improvement; create a fitted surface, an executable options strategy, or a "
            "sleeve-admission case."
        ),
        "source_sha256": {
            "implementation": sha256(SOURCE),
            "tests": sha256(TESTS),
            "adjusted_deliverable_implementation": sha256(DELIVERABLE_SOURCE),
            "adjusted_deliverable_tests": sha256(DELIVERABLE_TESTS),
            "adjustment_ingest_implementation": sha256(ADJUSTMENT_INGEST_SOURCE),
            "adjustment_ingest_tests": sha256(ADJUSTMENT_INGEST_TESTS),
            "occ_archive_implementation": sha256(OCC_ARCHIVE_SOURCE),
            "occ_archive_tests": sha256(OCC_ARCHIVE_TESTS),
            "package_execution_implementation": sha256(PACKAGE_SOURCE),
            "package_execution_tests": sha256(PACKAGE_TESTS),
            "fee_assessment_implementation": sha256(FEE_SOURCE),
            "fee_assessment_tests": sha256(FEE_TESTS),
            "scenario_margin_implementation": sha256(MARGIN_SOURCE),
            "scenario_margin_tests": sha256(MARGIN_TESTS),
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
