#!/usr/bin/env python3
"""Build deterministic evidence for the single crypto VRP proxy hypothesis.

This audit opens no holdout and records no experiment. It binds the first immutable union
measurement to the persisted signal-validity report and preserves the report's explicit boundary:
DVOL minus realized variance is a proxy, not an executable option portfolio.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion

REPO: Final[Path] = Path(__file__).resolve().parent.parent
REPORT: Final[Path] = REPO / "artifacts" / "exp2" / "20260625T094710Z" / "exp2_metrics.json"
SOURCE: Final[Path] = REPO / "scripts" / "exp2_crypto_vrp.py"
OUT: Final[Path] = REPO / "artifacts" / "research" / "crypto_vrp_family.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _first_records() -> dict[str, tuple[Any, Path]]:
    union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    first: dict[str, tuple[Any, Path]] = {}
    for path in union.paths:
        if not path.exists():
            continue
        ledger = ExperimentLog(path)
        for record in ledger.all():
            if record.config.get("probe") != "crypto_vrp_proxy":
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
    if len(records) != 1:
        raise ValueError(f"expected one crypto VRP identity, found {len(records)}")
    key, (record, ledger_path) = next(iter(records.items()))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    result = report["standalone"]
    if not math.isclose(
        float(result["net_sharpe_oos"]), record.sharpe_ann, rel_tol=0.0, abs_tol=5e-4
    ):
        raise ValueError("persisted VRP report Sharpe does not match immutable ledger")
    if int(report["oos_days"]) != record.n_obs:
        raise ValueError("persisted VRP report observation count does not match immutable ledger")
    for name, observed in (("skew", record.skew), ("kurtosis_raw", record.kurtosis)):
        if not math.isclose(float(result[name]), observed, rel_tol=0.0, abs_tol=5e-3):
            raise ValueError(f"persisted VRP report {name} does not match immutable ledger")

    identity = {
        "hypothesis_key": key,
        "config_hash": record.config_hash,
        "configuration": record.config,
        "ledger_source_path": str(ledger_path.relative_to(REPO)),
        "artifact_path": str(REPORT.relative_to(REPO)),
        "artifact_sha256": _sha256(REPORT),
        "result": {
            "window": report["window"],
            "currencies": report["currencies"],
            "oos_days": report["oos_days"],
            "annualized_sharpe": result["net_sharpe_oos"],
            "artifact_era_dsr": result["deflated_sharpe"],
            "artifact_era_psr": result["psr"],
            "artifact_era_global_trials": result["n_trials_global"],
            "skew": result["skew"],
            "raw_kurtosis": result["kurtosis_raw"],
            "clears_artifact_era_dsr_gate": bool(float(result["deflated_sharpe"]) >= 0.95),
        },
    }
    return {
        "schema": "canli.alphac-crypto-vrp-family.v1",
        "evidence_date": "2026-08-22",
        "author": "Arhan Canli",
        "family_key": "crypto_volatility_risk_premium",
        "claim_boundary": (
            "This is a signal-validity proxy using DVOL and realized variance, not an executable "
            "option return, forward record, capacity study, admitted sleeve, or return promise."
        ),
        "summary": {
            "distinct_hypothesis_identities": 1,
            "artifact_era_dsr_gate_passes": int(identity["result"]["clears_artifact_era_dsr_gate"]),
            "capacity_status": "UNMEASURED_NO_OPTIONS_CAPACITY_SWEEP",
            "admission_status": "FAIL_RESEARCH_ONLY",
            "options_surface_status": "UNAVAILABLE_HISTORICAL_SURFACE_PROXY_ONLY",
            "broker_reconciled_forward_status": "NOT_ESTABLISHED",
        },
        "implementation": {
            "return_type": "variance_swap_signal_validity_proxy",
            "is_deployable_option_pnl": False,
            "source_path": str(SOURCE.relative_to(REPO)),
            "source_sha256": _sha256(SOURCE),
        },
        "diagnostics": report["boring_true_fact_diagnostics"],
        "unresolved_diversification": report["decorrelation_vs_live_sleeves"],
        "identity": identity,
        "source_provenance": {
            "report_path": str(REPORT.relative_to(REPO)),
            "report_sha256": _sha256(REPORT),
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
