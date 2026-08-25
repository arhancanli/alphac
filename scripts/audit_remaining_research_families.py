#!/usr/bin/env python3
"""Build deterministic evidence packets for the final six uncovered research families."""

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
OUT: Final[Path] = REPO / "artifacts" / "research"
SPECS: Final[dict[str, dict[str, Any]]] = {
    "crypto_defensive": {
        "count": 2,
        "output": "crypto_defensive_family.json",
        "artifact": "artifacts/analysis/lowvol720_reopen/result.json",
    },
    "crypto_short_horizon_reversal": {"count": 2, "output": "crypto_reversal_family.json"},
    "energy_inventory": {
        "count": 1,
        "output": "energy_inventory_family.json",
        "artifact": "artifacts/probe/eia_petroleum_inventory/result.json",
    },
    "equity_insider_activity": {
        "count": 2,
        "output": "equity_insider_family.json",
        "artifact": "artifacts/probe/insider_purchase_clusters/result.json",
    },
    "equity_low_beta": {"count": 2, "output": "equity_low_beta_family.json"},
    "macro_economic_trend": {
        "count": 7,
        "output": "macro_economic_trend_family.json",
        "artifact": "artifacts/probe/macro_vintage_family/result.json",
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def _family(config: dict[str, Any]) -> str | None:
    probe = config.get("probe")
    if probe in {"macro_vintage_family", "econtrend", "cpi_surprise_size"}:
        return "macro_economic_trend"
    if probe == "eia_petroleum_inventory":
        return "energy_inventory"
    if probe == "insider_purchase_clusters":
        return "equity_insider_activity"
    raw = config.get("alpha_names")
    alphas = {str(value) for value in raw} if isinstance(raw, list) else set()
    if "eq_bab_252" in alphas:
        return "equity_low_beta"
    if any(alpha.startswith("carry_") for alpha in alphas):
        return None
    if any(alpha.startswith(("mom_ts_", "mom_xs_")) for alpha in alphas):
        return None
    if any(alpha.startswith("mr_res_") for alpha in alphas):
        return "crypto_short_horizon_reversal"
    if alphas.intersection({"lowvol_720", "beta_lowbeta_720"}):
        return "crypto_defensive"
    return None


def _all_records() -> dict[str, dict[str, tuple[Any, Path]]]:
    found: dict[str, dict[str, tuple[Any, Path]]] = {key: {} for key in SPECS}
    union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    for path in union.paths:
        if not path.exists():
            continue
        ledger = ExperimentLog(path)
        for record in ledger.all():
            family = _family(record.config)
            if family not in found:
                continue
            key = ledger._hypothesis_key(record.config)
            prior = found[family].get(key)
            if prior is None or (record.now_ms, record.config_hash) < (
                prior[0].now_ms,
                prior[0].config_hash,
            ):
                found[family][key] = (record, path)
    return found


def build_all() -> dict[str, dict[str, Any]]:
    if (REPO / LEGACY_CLOSURE).is_file():
        sealed: dict[str, dict[str, Any]] = {}
        for family, spec in SPECS.items():
            path = OUT / spec["output"]
            validate_legacy_packet_bound_file(REPO, str(path.relative_to(REPO)))
            sealed[family] = json.loads(path.read_text(encoding="utf-8"))
        return sealed
    records = _all_records()
    packets: dict[str, dict[str, Any]] = {}
    for family, spec in SPECS.items():
        family_records = records[family]
        if len(family_records) != spec["count"]:
            raise ValueError(f"{family}: expected {spec['count']}, found {len(family_records)}")
        identities = []
        for key, (record, ledger_path) in sorted(family_records.items()):
            identities.append(
                {
                    "hypothesis_key": key,
                    "config_hash": record.config_hash,
                    "configuration": record.config,
                    "ledger_source_path": str(ledger_path.relative_to(REPO)),
                    "ledger_source_sha256": _sha256(ledger_path),
                    "evidence_grade": "immutable_ledger_summary_with_optional_family_artifact",
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
        sharpes = [
            float(row["result"]["annualized_sharpe"])
            for row in identities
            if row["result"]["annualized_sharpe"] is not None
        ]
        artifact_rel = spec.get("artifact")
        artifact = REPO / artifact_rel if artifact_rel else None
        packets[family] = {
            "schema": f"canli.alphac-{family.replace('_', '-')}-family.v1",
            "evidence_date": "2026-08-22",
            "author": "Arhan Canli",
            "family_key": family,
            "claim_boundary": (
                "Immutable historical evidence only; no forward performance, admitted sleeve, "
                "live execution, or future-return claim."
            ),
            "summary": {
                "distinct_hypothesis_identities": len(identities),
                "finite_sharpe_identities": len(sharpes),
                "positive_sharpe_identities": sum(value > 0 for value in sharpes),
                "minimum_annualized_sharpe": min(sharpes),
                "maximum_annualized_sharpe": max(sharpes),
                "capacity_status": "UNMEASURED_OR_NOT_FAMILY_WIDE",
                "admission_status": "NOT_ESTABLISHED_RESEARCH_ONLY",
                "broker_reconciled_forward_status": "NOT_ESTABLISHED",
            },
            "related_family_artifact": (
                {"path": artifact_rel, "sha256": _sha256(artifact)}
                if artifact is not None and artifact.exists()
                else None
            ),
            "identities": identities,
        }
    return packets


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for family, packet in build_all().items():
        (OUT / SPECS[family]["output"]).write_text(
            json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"{family}: {json.dumps(packet['summary'], sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
