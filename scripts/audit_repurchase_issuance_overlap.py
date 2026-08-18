#!/usr/bin/env python3
"""Reconcile the proposed completed-flow identity with prior net-issuance research.

This audit opens no returns. It inventories already-persisted results and prevents a cleaner
measurement of corporate equity supply from being presented as a new economic family or from
receiving a fresh trial budget that ignores the prior net-issuance campaign.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parent.parent
OUT: Final = ROOT / "artifacts/feasibility/repurchase_issuance_flow/identity_overlap_audit.json"
FEATURE_SOURCE: Final = ROOT / "src/alphaforge/features/library/equity_fundamental.py"
PROPOSAL: Final = ROOT / "docs/design/FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md"
RERUN_RESULT: Final = ROOT / "artifacts/analysis/null_fundamentals_rerun/result.json"
SWEEP_RESULT: Final = ROOT / "artifacts/sweep/gauntlet_eq_net_issuance/walkforward.json"
SWEEP_SUMMARY: Final = ROOT / "artifacts/sweep/gauntlet_eq_net_issuance/summary.txt"
SWEEP_LEGS: Final = ROOT / "artifacts/sweep/gauntlet_eq_net_issuance/legs"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def issuance_records(ledger_paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(ledger_paths):
        if not path.exists():
            continue
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            config = row.get("config", {})
            if "eq_net_issuance" not in (config.get("alpha_names") or []):
                continue
            hypothesis = {
                key: value for key, value in config.items() if key not in {"start", "end"}
            }
            records.append(
                {
                    "ledger": display_path(path),
                    "line": line_number,
                    "config_hash": row["config_hash"],
                    "hypothesis_key_excluding_window": canonical_sha256(hypothesis)[:16],
                    "sharpe_ann": row.get("sharpe_ann"),
                    "n_obs": row.get("n_obs"),
                    "start": config.get("start"),
                    "end": config.get("end"),
                    "instrument_count": len(config.get("instrument_ids", [])),
                    "allocator": config.get("allocator"),
                    "rebalance_bars": config.get("rebalance_bars"),
                }
            )
    return records


def audit_overlap(ledger_paths: list[Path]) -> dict[str, Any]:
    required = [FEATURE_SOURCE, PROPOSAL, RERUN_RESULT, SWEEP_RESULT, SWEEP_SUMMARY]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"required overlap evidence is missing: {missing}")
    records = issuance_records(ledger_paths)
    if not records:
        raise RuntimeError("no prior eq_net_issuance ledger records found")
    rerun = json.loads(RERUN_RESULT.read_text())["eq_net_issuance"]
    sweep = json.loads(SWEEP_RESULT.read_text())
    summary = SWEEP_SUMMARY.read_text()
    folds = len([path for path in SWEEP_LEGS.iterdir() if path.is_dir()])
    result: dict[str, Any] = {
        "schema": "canli.alphac-repurchase-issuance-overlap-audit.v1",
        "stage": "identity_governance_no_new_returns",
        "return_data_opened_by_this_audit": False,
        "return_hypotheses_spent_by_this_audit": 0,
        "classification": "SAME_ECONOMIC_FAMILY_DISTINCT_MEASUREMENT",
        "economic_family": "corporate_equity_supply",
        "prior_identity": {
            "id": "eq_net_issuance",
            "measurement": "year-over-year log change in split-adjusted basic shares",
            "direction": "long net repurchasers, short net issuers",
            "source_sha256": file_sha256(FEATURE_SOURCE),
        },
        "proposed_identity": {
            "id": "repurchase_issuance_flow",
            "measurement": (
                "filing-known completed cash repurchases versus contamination-resolved "
                "completed issuance"
            ),
            "proposal_sha256": file_sha256(PROPOSAL),
        },
        "prior_trial_account": {
            "ledger_records": records,
            "distinct_config_hashes": len({row["config_hash"] for row in records}),
            "distinct_hypothesis_keys_excluding_window": len(
                {row["hypothesis_key_excluding_window"] for row in records}
            ),
            "walkforward_folds_not_independent_trials": folds,
        },
        "prior_outcomes": {
            "source_correct_full_window_rerun": rerun,
            "latest_sealed_sweep": {
                "sharpe": sweep["validation"]["sr_ann"],
                "dsr": sweep["validation"]["dsr"],
                "n_trials_at_run": sweep["validation"]["n_trials"],
                "clears_dsr_gate": sweep["validation"]["clears_dsr_gate"],
                "max_drawdown": float(
                    next(
                        line.split()[1]
                        for line in summary.splitlines()
                        if line.startswith("max_dd            ")
                    )
                ),
                "artifact_sha256": file_sha256(SWEEP_RESULT),
            },
        },
        "governance": {
            "may_count_as_new_economic_family": False,
            "may_count_toward_ten_new_independent_sleeves": False,
            "feasibility_audit_may_continue_without_returns": True,
            "fresh_standalone_trial_budget": False,
            "required_family_trial_floor": len({row["config_hash"] for row in records}) + 1,
            "required_future_controls": [
                "include every prior corporate-equity-supply trial in union DSR accounting",
                "residualize against the frozen broad eq_net_issuance signal",
                "prove positive mean-zero marginal book contribution",
                "use an untouched post-declaration holdout and publish a null",
                "admit only as a replacement or same-family refinement, never as "
                "independent breadth",
            ],
        },
        "decision": "CONTINUE_DATA_FEASIBILITY_SAME_FAMILY",
        "claim_boundary": (
            "Completed flows may be a cleaner measurement, but cleanliness is not economic "
            "independence. No return sign, Sharpe, correlation, admission, or new-sleeve claim "
            "is authorized by this audit."
        ),
        "lineage": {
            "rerun_result_sha256": file_sha256(RERUN_RESULT),
            "sweep_summary_sha256": file_sha256(SWEEP_SUMMARY),
        },
    }
    result["content_hash"] = "sha256:" + canonical_sha256(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    result = audit_overlap(list(ROOT.glob("var*/experiments.jsonl")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), **result}, indent=2))


if __name__ == "__main__":
    main()
