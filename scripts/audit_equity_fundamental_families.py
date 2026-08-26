#!/usr/bin/env python3
"""Build deterministic ledger evidence for equity quality and value/investment families."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion
from alphaforge.validation.legacy_epoch import (
    LEGACY_CLOSURE,
    validate_legacy_packet_bound_file,
)

REPO: Final[Path] = Path(__file__).resolve().parent.parent
OUT_DIR: Final[Path] = REPO / "artifacts" / "research"
QUALITY = {
    "eq_operating_margin",
    "eq_gross_profitability",
    "eq_quality_composite",
    "eq_roe",
    "eq_qual_gpe",
}
VALUE = {
    "eq_accruals",
    "eq_asset_growth",
    "eq_book_to_price",
    "eq_earnings_yield",
    "eq_ilrev",
    "eq_net_issuance",
    "eq_sales_to_price",
    "eq_value_composite",
    "eq_52whigh_252",
}
SPECS: Final[dict[str, dict[str, Any]]] = {
    "equity_fundamental_quality": {
        "expected": 11,
        "signals": QUALITY,
        "schema": "canli.alphac-equity-quality-family.v1",
        "output": "equity_quality_family.json",
        "preregistrations": ["docs/design/PREREG_FUNDAMENTAL_SINGLES.md"],
    },
    "equity_fundamental_value_investment": {
        "expected": 13,
        "signals": VALUE,
        "schema": "canli.alphac-equity-value-investment-family.v1",
        "output": "equity_value_investment_family.json",
        "preregistrations": [
            "docs/design/PREREG_FUNDAMENTAL_SINGLES.md",
            "docs/design/PREREG_SLEEVE4_INVESTMENT.md",
            "docs/design/LITERATURE_REPURCHASE_ISSUANCE_FLOW.md",
        ],
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def _classified_family(alphas: set[str]) -> str | None:
    # Mirror the manifest's precedence: mixed momentum/reversal and BAB configurations belong to
    # their price and low-beta families before fundamental labels are considered.
    if any(alpha.startswith("eq_mom_") for alpha in alphas) or "eq_rev_resid_21" in alphas:
        return None
    if "eq_bab_252" in alphas:
        return None
    if alphas.intersection(QUALITY):
        return "equity_fundamental_quality"
    if alphas.intersection(VALUE):
        return "equity_fundamental_value_investment"
    return None


def _records(family_key: str) -> dict[str, tuple[Any, Path]]:
    first: dict[str, tuple[Any, Path]] = {}
    union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    for path in union.paths:
        if not path.exists():
            continue
        ledger = ExperimentLog(path)
        for record in ledger.all():
            raw = record.config.get("alpha_names")
            alphas = {str(value) for value in raw} if isinstance(raw, list) else set()
            if _classified_family(alphas) != family_key:
                continue
            key = ledger._hypothesis_key(record.config)
            current = first.get(key)
            if current is None or (record.now_ms, record.config_hash) < (
                current[0].now_ms,
                current[0].config_hash,
            ):
                first[key] = (record, path)
    return first


def build_family(family_key: str) -> dict[str, Any]:
    spec = SPECS[family_key]
    if (REPO / LEGACY_CLOSURE).is_file():
        path = OUT_DIR / spec["output"]
        validate_legacy_packet_bound_file(REPO, str(path.relative_to(REPO)))
        return json.loads(path.read_text(encoding="utf-8"))
    records = _records(family_key)
    if len(records) != spec["expected"]:
        raise ValueError(
            f"{family_key}: expected {spec['expected']} identities, found {len(records)}"
        )
    identities = []
    for key, (record, ledger_path) in sorted(records.items()):
        identities.append(
            {
                "hypothesis_key": key,
                "config_hash": record.config_hash,
                "configuration": record.config,
                "ledger_source_path": str(ledger_path.relative_to(REPO)),
                "ledger_source_sha256": _sha256(ledger_path),
                "evidence_grade": "immutable_ledger_summary_only",
                "result": {
                    "annualized_sharpe": _finite(record.sharpe_ann),
                    "observations": record.n_obs,
                    "skew": _finite(record.skew),
                    "kurtosis": _finite(record.kurtosis),
                    "maximum_drawdown": None,
                    "artifact_era_dsr": None,
                },
            }
        )
    sharpes = [row["result"]["annualized_sharpe"] for row in identities]
    finite = [float(value) for value in sharpes if value is not None]
    prereg = {relative: _sha256(REPO / relative) for relative in spec["preregistrations"]}
    return {
        "schema": spec["schema"],
        "evidence_date": "2026-08-22",
        "author": "Arhan Canli",
        "family_key": family_key,
        "claim_boundary": (
            "This packet reconciles immutable historical summary measurements. Missing curves, "
            "drawdowns, DSR, capacity, and forward evidence remain missing and are not "
            "reconstructed."
        ),
        "summary": {
            "distinct_hypothesis_identities": len(identities),
            "finite_sharpe_identities": len(finite),
            "nonfinite_sharpe_identities": len(identities) - len(finite),
            "positive_sharpe_identities": sum(value > 0 for value in finite),
            "minimum_annualized_sharpe": min(finite),
            "maximum_annualized_sharpe": max(finite),
            "complete_walkforward_artifacts": 0,
            "capacity_status": "UNMEASURED_NO_FAMILY_CAPACITY_SWEEP",
            "admission_status": "NOT_ESTABLISHED_RESEARCH_ONLY",
            "broker_reconciled_forward_status": "NOT_ESTABLISHED",
        },
        "source_provenance": {"reference_sha256": prereg},
        "identities": identities,
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for family_key, spec in SPECS.items():
        payload = build_family(family_key)
        (OUT_DIR / spec["output"]).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"{family_key}: {json.dumps(payload['summary'], sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
