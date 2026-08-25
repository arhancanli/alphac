#!/usr/bin/env python3
"""Classify whether engineering can close the locked bond-ETF NAV source gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SOURCE: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "bond_etf_nav_dislocation" / "result.json"
)
OUT: Final[Path] = (
    REPO / "artifacts" / "analysis" / "bond_etf_nav_reachability" / "result.json"
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def build() -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    coverage = source["premium_discount_coverage"]
    holdings = source["historical_holdings_snapshots"]
    required_holdings = int(source["required_historical_holdings_snapshots_each"])
    if source["market_records_opened"] != 0 or source["return_hypotheses_spent"] != 0:
        raise RuntimeError("bond-ETF source audit unexpectedly opened market or return data")
    if any(float(coverage[fund]["coverage"]) >= 0.98 for fund in ("HYG", "LQD")):
        raise RuntimeError("issuer history gate no longer fails")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-bond-etf-nav-reachability.v1",
        "author": "Arhan Canli",
        "family": "bond_etf_nav_dislocation",
        "decision": "PUBLIC_ENGINEERING_CANNOT_CLOSE_LOCKED_GATES",
        "verdict": "PAID_ARCHIVAL_AND_EXECUTABLE_DATA_REQUIRED",
        "hypotheses_spent": 0,
        "market_records_opened": 0,
        "return_data_opened": False,
        "measured_public_record": {
            "required_issuer_session_coverage": 0.98,
            "funds": {
                fund: {
                    "observed_coverage": float(coverage[fund]["coverage"]),
                    "coverage_shortfall": 0.98 - float(coverage[fund]["coverage"]),
                    "first_available": coverage[fund]["first_available"],
                    "historical_holdings_snapshots": int(holdings[fund]),
                    "required_historical_holdings_snapshots": required_holdings,
                    "holdings_shortfall": required_holdings - int(holdings[fund]),
                }
                for fund in ("HYG", "LQD")
            },
        },
        "locked_gate_owners": {
            "issuer_premium_discount_history": "issuer_or_archival_vendor",
            "monthly_point_in_time_holdings": "issuer_or_archival_vendor",
            "constituent_valuation_timestamps": "evaluated_price_vendor",
            "synchronized_etf_and_bond_execution": "ETF_and_TRACE_market_data_vendors",
        },
        "engineering_reachability": {
            "parser_or_crawler_can_create_missing_history": False,
            "public_pages_can_retroactively_supply_point_in_time_snapshots": False,
            "public_metadata_can_replace_executable_quotes_and_trades": False,
            "next_action": (
                "Owner spending/contract decision for archival issuer holdings, evaluated bond "
                "prices, TRACE transactions, and synchronized ETF quote/trade history. Collection "
                "still does not authorize returns."
            ),
        },
        "lineage": {
            "source_path": str(SOURCE.relative_to(REPO)),
            "source_sha256": _sha256(SOURCE),
            "protocol_sha256": source["protocol_sha256"],
            "issuer_manifest_sha256": source["artifacts"][
                "issuer_premium_discount_manifest"
            ]["sha256"],
            "source_probe_manifest_sha256": source["artifacts"]["source_probe_manifest"][
                "sha256"
            ],
        },
        "claim_boundary": (
            "This classifies ownership of four failed source gates. It does not claim that paid "
            "data will pass them, opens no market records or returns, and makes no signal, Sharpe, "
            "drawdown, diversification, capacity, or admission claim."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    print(payload["content_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
