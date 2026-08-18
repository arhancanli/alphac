#!/usr/bin/env python3
"""Reconcile proven historical screen trials that bypassed the experiment ledger.

This is deliberately narrow and evidence-backed. It imports eight complete walk-forward arms
from ``alphamax_construction`` and sixteen parameter cells from ``alphamax_weighting``. Both
source scripts explicitly reported zero trials burned even though their persisted artifacts prove
that distinct return configurations were evaluated. Re-running is unnecessary and would risk
changing the historical evidence.

Default mode is read-only. ``--apply`` appends idempotent forensic records to the active ledger and
writes a reconciliation artifact. No record is deleted or rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alphaforge.analytics.metrics import daily_returns  # noqa: E402
from alphaforge.validation.experiments import (  # noqa: E402
    ExperimentLog,
    ExperimentUnion,
    config_hash,
)
from alphaforge.validation.probe_ledger import record_probe_trial  # noqa: E402

ACTIVE_LEDGER: Final[Path] = REPO / "var" / "experiments.jsonl"
CONSTRUCTION_ROOT: Final[Path] = REPO / "artifacts" / "sweep" / "alphamax_construction"
CONSTRUCTION_MANIFEST: Final[Path] = CONSTRUCTION_ROOT / "arms.json"
WEIGHTING_REPORT: Final[Path] = REPO / "artifacts" / "probe" / "alphamax_weighting" / "report.json"
OUT: Final[Path] = REPO / "artifacts" / "audit" / "trial_debt_reconciliation.json"
AUDIT_NOW_MS: Final[int] = 1_786_924_800_000  # 2026-08-17T00:00:00Z
EXPECTED_CONSTRUCTION_ARMS: Final[int] = 8
EXPECTED_WEIGHTING_CELLS: Final[int] = 16


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _construction_candidates() -> list[dict[str, Any]]:
    manifest = json.loads(CONSTRUCTION_MANIFEST.read_text())
    candidates: list[dict[str, Any]] = []
    for arm, evidence in sorted(manifest.items()):
        run_dir = CONSTRUCTION_ROOT / f"wf_{arm}"
        metadata_path = run_dir / "walkforward.json"
        equity_path = run_dir / "equity.parquet"
        metadata = json.loads(metadata_path.read_text())
        trial_config = metadata.get("trial_config") or metadata["config"]
        frame = pd.read_parquet(equity_path)
        equity = pd.Series(
            frame["equity"].to_numpy(dtype="float64"),
            index=pd.Index(frame["ts"].to_numpy(dtype="int64"), name="ts"),
        )
        returns = daily_returns(equity)
        candidates.append(
            {
                "kind": "complete_walkforward",
                "probe": "forensic_alphamax_construction",
                "variant": arm,
                "config": {
                    "variant": arm,
                    "parameters": evidence["params"],
                    "source_trial_config_hash": config_hash(trial_config),
                    "source_artifact": str(metadata_path.relative_to(REPO)),
                    "source_artifact_sha256": _sha256(metadata_path),
                    "historical_accounting_correction": True,
                },
                "returns": returns,
                "source": metadata_path,
            }
        )
    if len(candidates) != EXPECTED_CONSTRUCTION_ARMS:
        raise RuntimeError(
            f"expected {EXPECTED_CONSTRUCTION_ARMS} construction arms, found {len(candidates)}"
        )
    return candidates


def _weighting_candidates() -> list[dict[str, Any]]:
    report = json.loads(WEIGHTING_REPORT.read_text())
    construction = report["construction"]
    window = report["window"]
    candidates: list[dict[str, Any]] = []
    for variant, metrics in sorted(report["grid"].items()):
        candidates.append(
            {
                "kind": "summary_only_screen",
                "probe": "forensic_alphamax_weighting",
                "variant": variant,
                "config": {
                    "variant": variant,
                    "scheme": metrics["scheme"],
                    "rank_top_k": metrics["K"],
                    "construction": construction,
                    "window": window,
                    "source_artifact": str(WEIGHTING_REPORT.relative_to(REPO)),
                    "source_artifact_sha256": _sha256(WEIGHTING_REPORT),
                    "historical_accounting_correction": True,
                },
                "metrics": metrics,
                "source": WEIGHTING_REPORT,
            }
        )
    if len(candidates) != EXPECTED_WEIGHTING_CELLS:
        raise RuntimeError(
            f"expected {EXPECTED_WEIGHTING_CELLS} weighting cells, found {len(candidates)}"
        )
    return candidates


def _full_config(candidate: dict[str, Any]) -> dict[str, Any]:
    return {"probe": candidate["probe"], **candidate["config"]}


def _record(candidate: dict[str, Any], ordinal: int) -> None:
    now_ms = AUDIT_NOW_MS + ordinal
    if candidate["kind"] == "complete_walkforward":
        record_probe_trial(
            candidate["probe"],
            candidate["config"],
            candidate["returns"],
            now_ms=now_ms,
            periods_per_year=252,
            ledger_path=ACTIVE_LEDGER,
        )
        return

    metrics = candidate["metrics"]
    sharpe_ann = float(metrics["net_sharpe_ann365"])
    ExperimentLog(ACTIVE_LEDGER).record(
        _full_config(candidate),
        sharpe_ann=sharpe_ann,
        sharpe_per_period=sharpe_ann / math.sqrt(365.0),
        n_obs=int(metrics["n_days"]),
        skew=math.nan,
        kurtosis=math.nan,
        now_ms=now_ms,
    )


def reconcile(*, apply: bool) -> dict[str, Any]:
    candidates = _construction_candidates() + _weighting_candidates()
    union_before = ExperimentUnion.discover(ACTIVE_LEDGER, REPO)
    existing_hashes = {record.config_hash for record in union_before.all()}
    pending = [
        candidate
        for candidate in candidates
        if config_hash(_full_config(candidate)) not in existing_hashes
    ]
    n_before = union_before.n_hypotheses()

    if apply:
        for ordinal, candidate in enumerate(candidates):
            _record(candidate, ordinal)

    union_after = ExperimentUnion.discover(ACTIVE_LEDGER, REPO)
    n_after = union_after.n_hypotheses()
    if apply and n_after - n_before != len(pending):
        raise RuntimeError(
            f"identity delta {n_after - n_before} did not match pending forensic records "
            f"{len(pending)}"
        )

    payload = {
        "schema": "alphac.trial-debt-reconciliation.v1",
        "applied": apply,
        "claim_boundary": (
            "Only persisted, named return configurations are charged here. This is a lower-bound "
            "correction; other historical screen debt remains under audit."
        ),
        "selection_identities_before": n_before,
        "selection_identities_after": n_after,
        "candidate_records": len(candidates),
        "new_records_pending_before_run": len(pending),
        "sources": [
            {
                "path": str(CONSTRUCTION_MANIFEST.relative_to(REPO)),
                "sha256": _sha256(CONSTRUCTION_MANIFEST),
                "charged_identities": EXPECTED_CONSTRUCTION_ARMS,
                "evidence_grade": "complete_walkforward_curve_and_config",
            },
            {
                "path": str(WEIGHTING_REPORT.relative_to(REPO)),
                "sha256": _sha256(WEIGHTING_REPORT),
                "charged_identities": EXPECTED_WEIGHTING_CELLS,
                "evidence_grade": "persisted_summary_only_missing_higher_moments",
            },
        ],
        "records": [
            {
                "probe": candidate["probe"],
                "variant": candidate["variant"],
                "kind": candidate["kind"],
                "config_hash": config_hash(_full_config(candidate)),
                "source": str(candidate["source"].relative_to(REPO)),
            }
            for candidate in candidates
        ],
    }
    if apply:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="append idempotent forensic records")
    args = parser.parse_args()
    payload = reconcile(apply=args.apply)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
