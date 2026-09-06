#!/usr/bin/env python3
"""Seal the crypto-carry non-reproduction as a publication correction incident."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE: Final = ROOT / "artifacts/walkforward/crypto_carry_wk/walkforward.json"
REPLAY: Final = ROOT / "artifacts/probe/crypto_carry_frozen_current_code_replay/walkforward.json"
RECEIPT: Final = (
    ROOT / "artifacts/probe/crypto_carry_frozen_current_code_replay/replay_receipt.json"
)
FIRST_ATTRIBUTION: Final = (
    ROOT / "artifacts/probe/crypto_carry_replay_drift/first_rebalance_attribution.json"
)
FULL_PATH_ATTRIBUTION: Final = (
    ROOT / "artifacts/probe/crypto_carry_replay_drift/full_path_attribution.json"
)
SNAPSHOT_PROTOCOL: Final = ROOT / "artifacts/audit/walkforward_input_snapshot_protocol.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _verified(path: Path) -> dict[str, Any]:
    document = cast(dict[str, Any], json.loads(path.read_text()))
    if document.get("content_hash") != _content_hash(document):
        raise RuntimeError(f"invalid content hash: {path}")
    return document


def build() -> dict[str, Any]:
    source = json.loads(SOURCE.read_text())
    replay = json.loads(REPLAY.read_text())
    receipt = _verified(RECEIPT)
    first = _verified(FIRST_ATTRIBUTION)
    full_path = _verified(FULL_PATH_ATTRIBUTION)
    snapshot_protocol = _verified(SNAPSHOT_PROTOCOL)
    if receipt["exact_replay"] is not False:
        raise RuntimeError("correction incident requires a non-exact replay")
    if first["status"] != "PASS_FIRST_REBALANCE_CAUSE_EXACTLY_REPRODUCED":
        raise RuntimeError("first-rebalance attribution is not sealed")
    if not (
        first["reconstruction"]["source_quantities_exact"]
        and first["reconstruction"]["replay_quantities_exact"]
    ):
        raise RuntimeError("first-rebalance attribution is not exact")
    if full_path["status"] != (
        "PASS_SURVIVING_EVIDENCE_EXHAUSTED_EXACT_ADDITIVE_CAUSAL_SPLIT_NOT_IDENTIFIABLE"
    ):
        raise RuntimeError("full-path identifiability audit is not sealed")
    if snapshot_protocol["status"] != "PASS_PROSPECTIVE_PRIVATE_INPUT_SNAPSHOT_ENFORCED":
        raise RuntimeError("prospective input-snapshot protocol is not sealed")

    keys = ("final_equity", "sharpe", "max_dd", "cagr", "funding_net", "fees_paid")
    source_summary = {key: float(source["summary"][key]) for key in keys}
    replay_summary = {key: float(replay["summary"][key]) for key in keys}
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-replay-correction.v1",
        "author": "Arhan Canli",
        "incident_date": "2026-08-23",
        "status": "OPEN_CORRECTION_EXTERNAL_SUBMISSION_BLOCKED",
        "severity": "MATERIAL_RESEARCH_REPRODUCIBILITY_FAILURE",
        "historical_artifact_policy": "PRESERVE_DO_NOT_OVERWRITE_OR_DELETE",
        "bindings": {
            "selected_historical_artifact": {
                "path": str(SOURCE.relative_to(ROOT)),
                "sha256": _sha256(SOURCE),
            },
            "current_state_replay": {
                "path": str(REPLAY.relative_to(ROOT)),
                "sha256": _sha256(REPLAY),
            },
            "truthful_replay_receipt": {
                "path": str(RECEIPT.relative_to(ROOT)),
                "sha256": _sha256(RECEIPT),
                "content_hash": receipt["content_hash"],
            },
            "first_rebalance_attribution": {
                "path": str(FIRST_ATTRIBUTION.relative_to(ROOT)),
                "sha256": _sha256(FIRST_ATTRIBUTION),
                "content_hash": first["content_hash"],
            },
            "full_path_attribution": {
                "path": str(FULL_PATH_ATTRIBUTION.relative_to(ROOT)),
                "sha256": _sha256(FULL_PATH_ATTRIBUTION),
                "content_hash": full_path["content_hash"],
            },
            "prospective_input_snapshot_protocol": {
                "path": str(SNAPSHOT_PROTOCOL.relative_to(ROOT)),
                "sha256": _sha256(SNAPSHOT_PROTOCOL),
                "content_hash": snapshot_protocol["content_hash"],
            },
        },
        "material_difference": {
            "selected_historical_summary": source_summary,
            "current_state_replay_summary": replay_summary,
            "delta_replay_minus_historical": {
                key: replay_summary[key] - source_summary[key] for key in keys
            },
            "maximum_absolute_equity_difference": receipt["comparison"][
                "max_absolute_equity_difference"
            ],
            "first_equity_divergence": receipt["comparison"]["first_divergence"],
        },
        "causal_findings": {
            "first_rebalance": {
                "status": "EXACTLY_ATTRIBUTED",
                "cause": (
                    "The historical decision cross-section contained EOS while the current "
                    "derived-universe snapshot did not. Restoring EOS exactly reproduces all "
                    "ten historical discretized quantities."
                ),
                "source_cross_section_size": first["cross_section_difference"]["source_size"],
                "replay_cross_section_size": first["cross_section_difference"]["replay_size"],
                "source_only": first["cross_section_difference"]["source_only"],
            },
            "full_path": {
                "status": ("SURVIVING_EVIDENCE_EXHAUSTED_EXACT_ADDITIVE_SPLIT_NOT_IDENTIFIABLE"),
                "confirmed_contributors": [
                    "MUTABLE_DERIVED_UNIVERSE_NOT_BOUND_BY_HISTORICAL_ARTIFACT",
                    "CURRENT_REALIZED_VOL_OVERLAY_DIFFERS_FROM_HISTORICAL_IMPLEMENTATION",
                ],
                "software_correction_commit": "dd35711497d0e551d61d3593f7fd395a33b0c7b4",
                "observed_current_realized_leg_bound_rebalances": replay["config"][
                    "risk_counters"
                ].get("realized_leg_bound"),
                "claim_boundary": (
                    "The complete surviving output path has been compared. Overlapping decision "
                    "prices, position marks, funding marks and funding rates are exact; holdings "
                    "and state paths are not. Because the historical run omitted its exact code "
                    "and derived-input snapshots, no unique additive dollar or Sharpe split among "
                    "causes exists from the surviving two paths."
                ),
            },
        },
        "root_governance_failure": (
            "The 2026-06-20 artifact sealed outputs and strategy parameters but did not seal "
            "the exact derived universe-membership and instrument-metadata snapshots consumed. "
            "A later run therefore could not isolate code drift from mutable-input drift."
        ),
        "publication_decision": {
            "external_submission_allowed": False,
            "website_may_present_historical_numbers": True,
            "required_label": (
                "HISTORICAL ARTIFACT; NOT CURRENTLY EXACTLY REPRODUCIBLE; OPEN CORRECTION"
            ),
            "superseding_current_numbers_may_be_called_replication": False,
            "selected_historical_artifact_may_be_called_validated": False,
        },
        "required_remediation": [
            (
                "Keep this correction and full-path identifiability audit beside every "
                "historical table."
            ),
            (
                "Keep the enforced prospective snapshot control mandatory for every persisted "
                "walk-forward result; never treat it as retroactive historical evidence."
            ),
            (
                "Build a portable fresh-data lake and run the preregistered current implementation "
                "only after its exact pre-run snapshot is sealed."
            ),
            (
                "Keep the family NO-DEPLOY and external-submission blocked until the corrected "
                "paper and release bundle are rebuilt and independently reviewed."
            ),
        ],
        "remediation_progress": {
            "first_decision_exactly_attributed": True,
            "surviving_full_path_evidence_exhausted": True,
            "exact_additive_split_structurally_identifiable": False,
            "prospective_private_input_snapshot_enforced": True,
            "fresh_preregistered_snapshot_bound_run_completed": False,
            "independent_review_completed": False,
        },
        "trial_accounting": {
            "new_return_hypotheses": 0,
            "new_trials": 0,
            "classification": "REPRODUCIBILITY_CORRECTION_AND_CAUSAL_DIAGNOSTIC_ONLY",
        },
        "claim_boundary": (
            "This incident proves a material non-reproduction, exactly attributes the first "
            "sizing difference, exhausts the surviving full-path evidence, and proves why an "
            "additive causal split is not identifiable. It does not prove that either performance "
            "record will persist, repair the omitted historical snapshots, or constitute an "
            "independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def run(output: Path) -> dict[str, Any]:
    document = build()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/publication/crypto_carry_replay_correction.json",
    )
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.output.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
