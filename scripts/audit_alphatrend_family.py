#!/usr/bin/env python3
"""Build deterministic evidence for every managed-futures trend hypothesis.

The audit opens no holdout and records no experiment. It binds each first immutable union
measurement to the strongest persisted evidence available: a full walk-forward artifact, a
source-bound historical summary, or the immutable ledger row itself. Missing evidence stays
explicit instead of being reconstructed from rounded statistics.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion

REPO: Final[Path] = Path(__file__).resolve().parent.parent
OUT: Final[Path] = REPO / "artifacts" / "research" / "alphatrend_family.json"
ARP_REPORT: Final[Path] = REPO / "artifacts" / "sweep" / "alphatrend_arp" / "report.json"
BREADTH_REPORT: Final[Path] = REPO / "artifacts" / "sweep" / "alphatrend_breadth" / "report.json"

FULL_ARTIFACT_BY_CONFIG_HASH: Final[dict[str, str]] = {
    "82d9878e5289643f": "artifacts/sweep/mf_trend/walkforward.json",
    "085f558de3ae2d0f": "artifacts/sweep/mf_126/walkforward.json",
    "208db5dbfa72ec0b": "artifacts/sweep/mf_252/walkforward.json",
    "f622e8b77d246114": "artifacts/sweep/mf_rb5/walkforward.json",
    "66080ea19000763e": "artifacts/sweep/mf_rb10/walkforward.json",
    "6a3b0d615898ef14": "artifacts/sweep/fut_real2/walkforward.json",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def _is_alphatrend(config: dict[str, Any]) -> bool:
    if config.get("probe") in {"alphatrend_arp", "alphatrend_breadth"}:
        return True
    raw = config.get("alpha_names")
    alphas = [str(value) for value in raw] if isinstance(raw, list) else []
    return any(alpha.startswith("mf_trend_") for alpha in alphas)


def _first_records() -> dict[str, tuple[Any, Path]]:
    union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    first: dict[str, tuple[Any, Path]] = {}
    for path in union.paths:
        if not path.exists():
            continue
        ledger = ExperimentLog(path)
        for record in ledger.all():
            if not _is_alphatrend(record.config):
                continue
            key = ledger._hypothesis_key(record.config)
            current = first.get(key)
            if current is None or (record.now_ms, record.config_hash) < (
                current[0].now_ms,
                current[0].config_hash,
            ):
                first[key] = (record, path)
    return first


def _historical_summary(config: dict[str, Any]) -> tuple[Path, dict[str, Any]] | None:
    probe = config.get("probe")
    if probe == "alphatrend_arp":
        report = json.loads(ARP_REPORT.read_text(encoding="utf-8"))
        row = next(item for item in report["table"] if item["variant"] == config["variant"])
        return ARP_REPORT, {
            "annualized_sharpe": float(row["net_sharpe"]),
            "maximum_drawdown_vol_matched": abs(float(row["maxDD_volmatched"])),
            "annualized_volatility": float(row["vol_ann_realized"]),
            "skew": float(row["skew"]),
            "annual_turnover": float(row["turnover_ann"]),
            "artifact_era_dsr": float(row["DSR@N"]),
            "observations": int(report["n_sessions"]),
        }
    if probe == "alphatrend_breadth":
        report = json.loads(BREADTH_REPORT.read_text(encoding="utf-8"))
        basket = str(config["basket"])
        row_name = {
            "BASE_17": "BASE_17",
            "EXPANDED_33": "EXPANDED_33",
            "EXPANDED_MINUS_LARGEST_CONTRIBUTOR": "EXP_minus_SHY",
            "GREEDY_NEFF_PRUNED": "PRUNED_22",
        }[basket]
        row = next(item for item in report["table"] if item["basket"] == row_name)
        return BREADTH_REPORT, {
            "realized_basket": row_name,
            "annualized_sharpe": float(row["net_sharpe"]),
            "maximum_drawdown_vol_matched": abs(float(row["maxDD_vm"])),
            "annualized_volatility": float(row["vol_ann"]),
            "skew": float(row["skew"]),
            "annual_turnover": float(row["turn_ann"]),
            "artifact_era_dsr": float(row["DSR@N"]),
            "observations": int(report["n_sessions"]),
            "effective_breadth": float(row["N_eff"]),
            "average_pairwise_correlation": float(row["rhobar"]),
        }
    return None


def build() -> dict[str, Any]:
    records = _first_records()
    if len(records) != 21:
        raise ValueError(f"expected 21 managed-futures identities, found {len(records)}")

    identities: list[dict[str, Any]] = []
    for key, (record, ledger_path) in sorted(records.items()):
        evidence_grade = "immutable_ledger_summary_only"
        artifact_path: Path | None = None
        result: dict[str, Any] = {
            "annualized_sharpe": _finite(record.sharpe_ann),
            "observations": int(record.n_obs),
            "skew": _finite(record.skew),
            "kurtosis": _finite(record.kurtosis),
            "maximum_drawdown": None,
            "artifact_era_dsr": None,
        }

        relative = FULL_ARTIFACT_BY_CONFIG_HASH.get(record.config_hash)
        if relative is not None:
            artifact_path = REPO / relative
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            summary = artifact["summary"]
            validation = artifact["validation"]
            observed = float(summary["sharpe"])
            if not math.isclose(observed, record.sharpe_ann, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"{key}: artifact Sharpe does not match immutable ledger")
            result.update(
                {
                    "annualized_sharpe": observed,
                    "annualized_volatility": float(summary["vol_ann"]),
                    "maximum_drawdown": float(summary["max_dd"]),
                    "total_return": float(summary["total_return"]),
                    "annual_turnover": float(summary["turnover_ann"]),
                    "artifact_era_dsr": _finite(validation.get("dsr")),
                    "clears_artifact_era_dsr_gate": bool(
                        validation.get("clears_dsr_gate", False)
                    ),
                }
            )
            evidence_grade = "complete_walkforward_curve_config_and_validation"
        else:
            summary_evidence = _historical_summary(record.config)
            if summary_evidence is not None:
                artifact_path, summary = summary_evidence
                if not math.isclose(
                    float(summary["annualized_sharpe"]),
                    record.sharpe_ann,
                    rel_tol=0.0,
                    abs_tol=5e-4,
                ):
                    raise ValueError(f"{key}: historical summary Sharpe does not match ledger")
                result.update(summary)
                result["clears_artifact_era_dsr_gate"] = bool(
                    float(summary["artifact_era_dsr"]) >= 0.95
                )
                evidence_grade = "persisted_summary_missing_daily_curve_and_kurtosis"

        identities.append(
            {
                "hypothesis_key": key,
                "config_hash": record.config_hash,
                "configuration": record.config,
                "ledger_source_path": str(ledger_path.relative_to(REPO)),
                "evidence_grade": evidence_grade,
                "artifact_path": (
                    str(artifact_path.relative_to(REPO)) if artifact_path is not None else None
                ),
                "artifact_sha256": _sha256(artifact_path) if artifact_path is not None else None,
                "result": result,
            }
        )

    finite_sharpes = [
        float(row["result"]["annualized_sharpe"])
        for row in identities
        if row["result"]["annualized_sharpe"] is not None
    ]
    dsr_rows = [
        row for row in identities if row["result"].get("artifact_era_dsr") is not None
    ]
    return {
        "schema": "canli.alphac-alphatrend-family.v1",
        "evidence_date": "2026-08-22",
        "author": "Arhan Canli",
        "family_key": "managed_futures_trend",
        "claim_boundary": (
            "This packet reconciles historical simulations and summary-only screens. It does "
            "not establish forward performance, capacity, live-money execution, or admission."
        ),
        "summary": {
            "distinct_hypothesis_identities": len(identities),
            "finite_sharpe_identities": len(finite_sharpes),
            "minimum_annualized_sharpe": min(finite_sharpes),
            "maximum_annualized_sharpe": max(finite_sharpes),
            "complete_walkforward_artifacts": sum(
                row["evidence_grade"].startswith("complete_") for row in identities
            ),
            "persisted_summary_only_identities": sum(
                row["evidence_grade"].startswith("persisted_summary") for row in identities
            ),
            "immutable_ledger_only_identities": sum(
                row["evidence_grade"] == "immutable_ledger_summary_only" for row in identities
            ),
            "identities_with_artifact_era_dsr": len(dsr_rows),
            "artifact_era_dsr_gate_passes": sum(
                bool(row["result"].get("clears_artifact_era_dsr_gate")) for row in dsr_rows
            ),
            "capacity_status": "UNMEASURED_NO_PERSISTED_CAPACITY_SWEEP",
            "admission_status": "PAPER_EVIDENCE_COLLECTION_NOT_ESTABLISHED",
        },
        "source_provenance": {
            "arp_report_sha256": _sha256(ARP_REPORT),
            "breadth_report_sha256": _sha256(BREADTH_REPORT),
        },
        "identities": identities,
    }


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
