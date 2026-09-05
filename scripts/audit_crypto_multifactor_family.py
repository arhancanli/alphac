#!/usr/bin/env python3
"""Bind all seven crypto multi-factor engine identities to the grand-matrix evidence."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion

REPO: Final[Path] = Path(__file__).resolve().parent.parent
RUN_DIR: Final[Path] = REPO / "artifacts" / "grand_backtest" / "20260616T143620Z"
MATRIX: Final[Path] = RUN_DIR / "matrix.json"
VERDICT: Final[Path] = RUN_DIR / "verdict.md"
OUT: Final[Path] = REPO / "artifacts" / "research" / "crypto_multifactor_family.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_family(config: dict[str, Any]) -> bool:
    return (
        config.get("alpha_names") is None
        and config.get("train_bars") == 8760
        and config.get("test_bars") == 2184
    )


def _config_id(config: dict[str, Any]) -> str:
    if config.get("allocator") == "mvo":
        return "C_mvo"
    if config.get("rebalance_bars") == 24:
        return "C_rebal24"
    if config.get("no_trade_band") == 0.001:
        return "C_band10"
    ml = bool(config.get("ml", False))
    regime = bool(config.get("regime", False))
    if ml and regime:
        return "A_ml_regime"
    if ml:
        return "A_ml"
    if regime:
        return "A_regime"
    return "A_blend"


def _first_records() -> dict[str, tuple[Any, Path]]:
    union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    first: dict[str, tuple[Any, Path]] = {}
    for path in union.paths:
        if not path.exists():
            continue
        ledger = ExperimentLog(path)
        for record in ledger.all():
            if not _is_family(record.config):
                continue
            key = ledger._hypothesis_key(record.config)
            current = first.get(key)
            if current is None or (record.now_ms, record.config_hash) < (
                current[0].now_ms,
                current[0].config_hash,
            ):
                first[key] = (record, path)
    return first


def build() -> dict[str, Any]:
    records = _first_records()
    if len(records) != 7:
        raise ValueError(f"expected seven crypto multi-factor identities, found {len(records)}")
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    matrix_rows = {
        row["config_id"]: row
        for row in matrix["configs"]
        if row["is_distinct_trial"] and row["config_id"] != "C_carry"
    }
    if len(matrix_rows) != 7:
        raise ValueError(f"expected seven family rows in grand matrix, found {len(matrix_rows)}")

    identities: list[dict[str, Any]] = []
    used: set[str] = set()
    for key, (record, ledger_path) in sorted(records.items()):
        config_id = _config_id(record.config)
        if config_id in used or config_id not in matrix_rows:
            raise ValueError(f"ambiguous or missing matrix row for {key}: {config_id}")
        used.add(config_id)
        row = matrix_rows[config_id]
        if not math.isclose(float(row["sr_ann"]), record.sharpe_ann, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"{key}: matrix Sharpe does not match immutable ledger")
        identities.append(
            {
                "hypothesis_key": key,
                "config_hash": record.config_hash,
                "config_id": config_id,
                "configuration": record.config,
                "ledger_source_path": str(ledger_path.relative_to(REPO)),
                "artifact_path": str(MATRIX.relative_to(REPO)),
                "artifact_sha256": _sha256(MATRIX),
                "result": {
                    "observations": record.n_obs,
                    "annualized_sharpe": row["sr_ann"],
                    "maximum_drawdown": row["max_dd"],
                    "annual_turnover": row["turnover"],
                    "artifact_era_psr": row["psr"],
                    "artifact_era_dsr": row["dsr"],
                    "clears_artifact_era_dsr_gate": row["clears_dsr_gate"],
                    "clears_baseline_gate": row["clears_baseline_gate"],
                    "skew": record.skew,
                    "kurtosis": record.kurtosis,
                },
            }
        )
    if used != set(matrix_rows):
        raise ValueError(f"unbound matrix rows: {sorted(set(matrix_rows) - used)}")

    sharpes = [float(row["result"]["annualized_sharpe"]) for row in identities]
    drawdowns = [float(row["result"]["maximum_drawdown"]) for row in identities]
    return {
        "schema": "canli.alphac-crypto-multifactor-family.v1",
        "evidence_date": "2026-08-22",
        "author": "Arhan Canli",
        "family_key": "crypto_multifactor_engine",
        "claim_boundary": (
            "This packet reconciles one historical robustness matrix. It does not establish "
            "forward performance, an independent economic sleeve, live execution, or future return."
        ),
        "summary": {
            "distinct_hypothesis_identities": len(identities),
            "minimum_annualized_sharpe": min(sharpes),
            "maximum_annualized_sharpe": max(sharpes),
            "minimum_maximum_drawdown": min(drawdowns),
            "maximum_maximum_drawdown": max(drawdowns),
            "artifact_era_dsr_gate_passes": sum(
                bool(row["result"]["clears_artifact_era_dsr_gate"]) for row in identities
            ),
            "matrix_pbo": matrix["matrix"]["pbo"],
            "matrix_pbo_gate_passes": matrix["matrix"]["clears_pbo_gate"],
            "deployment_verdict": matrix["matrix"]["deployment_verdict"],
            "admission_status": "FAIL_NO_DEPLOY",
            "broker_reconciled_forward_status": "NOT_ESTABLISHED",
        },
        "capacity_curve": matrix["capacity_curve"],
        "capacity_boundary": (
            "The curve varies capital for the regime-gated engine and is system-level evidence; "
            "it does not validate any separate factor sleeve."
        ),
        "matrix_validation": matrix["matrix"],
        "identities": identities,
        "source_provenance": {
            "matrix_path": str(MATRIX.relative_to(REPO)),
            "matrix_sha256": _sha256(MATRIX),
            "verdict_path": str(VERDICT.relative_to(REPO)),
            "verdict_sha256": _sha256(VERDICT),
            "git_sha_recorded_by_artifact": matrix["git_sha"],
        },
    }


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
