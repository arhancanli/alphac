#!/usr/bin/env python3
"""Bind the single preregistered earnings-narrative trial to its sealed result."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion

REPO: Final[Path] = Path(__file__).resolve().parent.parent
RESULT: Final[Path] = REPO / "artifacts" / "probe" / "earnings_narrative_change" / "result.json"
PREREG: Final[Path] = REPO / "docs" / "design" / "PREREG_EARNINGS_NARRATIVE_CHANGE.md"
OUT: Final[Path] = REPO / "artifacts" / "research" / "equity_narrative_family.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, Any]:
    found: dict[str, tuple[Any, Path]] = {}
    union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    for path in union.paths:
        if not path.exists():
            continue
        ledger = ExperimentLog(path)
        for record in ledger.all():
            if record.config.get("probe") != "earnings_narrative_change":
                continue
            key = ledger._hypothesis_key(record.config)
            prior = found.get(key)
            if prior is None or (record.now_ms, record.config_hash) < (
                prior[0].now_ms,
                prior[0].config_hash,
            ):
                found[key] = (record, path)
    if len(found) != 1:
        raise ValueError(f"expected one narrative identity, found {len(found)}")
    key, (record, ledger_path) = next(iter(found.items()))
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    metrics = result["metrics"]
    if not math.isclose(float(metrics["net_sharpe"]), record.sharpe_ann, rel_tol=0.0, abs_tol=5e-6):
        raise ValueError("result Sharpe does not reconcile to immutable ledger")
    if result["verdict"] != "KILL" or result["admission_review"]["technically_eligible"]:
        raise ValueError("narrative result no longer has the persisted fail-closed verdict")
    return {
        "schema": "canli.alphac-equity-narrative-family.v1",
        "evidence_date": "2026-08-22",
        "author": "Arhan Canli",
        "family_key": "equity_narrative_change",
        "claim_boundary": (
            "This packet binds one preregistered historical trial and its kill verdict. It does "
            "not establish forward performance, capacity, live execution, or future return."
        ),
        "summary": {
            "distinct_hypothesis_identities": 1,
            "verdict": result["verdict"],
            "research_gates_passed": result["admission_review"]["research_subset_passed"],
            "research_gates_required": result["admission_review"]["research_subset_checks"],
            "technically_eligible": result["admission_review"]["technically_eligible"],
            "admission_status": result["admission_review"]["status"],
            "broker_reconciled_forward_status": "NOT_ESTABLISHED",
        },
        "identity": {
            "hypothesis_key": key,
            "config_hash": record.config_hash,
            "configuration": record.config,
            "ledger_source_path": str(ledger_path.relative_to(REPO)),
            "observations": record.n_obs,
            "artifact_path": str(RESULT.relative_to(REPO)),
            "artifact_sha256": _sha256(RESULT),
            "result": metrics,
            "gates": result["gates"],
            "verdict": result["verdict"],
        },
        "source_provenance": {
            "preregistration_path": str(PREREG.relative_to(REPO)),
            "preregistration_sha256": _sha256(PREREG),
            "result_path": str(RESULT.relative_to(REPO)),
            "result_sha256": _sha256(RESULT),
            "result_lineage": result["lineage"],
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
