#!/usr/bin/env python3
"""Run the no-return governance audit over every ALPHAC atlas cell."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from build_sleeve_atlas import build_atlas

STRUCTURAL_GATES = (
    "unique_identity",
    "known_family",
    "mechanism_declared",
    "point_in_time_requirement_declared",
    "execution_model_declared",
    "primary_friction_declared",
    "overlap_guard_declared",
    "universe_declared",
    "horizon_declared",
    "family_trial_account_bound",
    "returns_fail_closed",
    "lineage_classification_declared",
)

ELIGIBLE_LINEAGE_CLASSES = {"ACTIVE_FEASIBILITY", "NOVEL_ATLAS"}


def audit_atlas(atlas: dict[str, Any] | None = None) -> dict[str, Any]:
    atlas = atlas or build_atlas()
    cells = atlas["cells"]
    families = {family["id"]: family for family in atlas["families"]}
    identity_counts = Counter(cell["id"] for cell in cells)
    results: list[dict[str, Any]] = []

    for cell in cells:
        gates = {
            "unique_identity": identity_counts[cell["id"]] == 1,
            "known_family": cell["family_id"] in families,
            "mechanism_declared": bool(cell["mechanism"].strip()),
            "point_in_time_requirement_declared": bool(
                cell["point_in_time_data"].strip()
            ),
            "execution_model_declared": bool(cell["execution_model"].strip()),
            "primary_friction_declared": bool(cell["primary_friction"].strip()),
            "overlap_guard_declared": bool(cell["overlap_guard"].strip()),
            "universe_declared": bool(cell["universe"].strip()),
            "horizon_declared": bool(cell["horizon"].strip()),
            "family_trial_account_bound": (
                cell["family_trial_account"] == cell["family_id"]
            ),
            "returns_fail_closed": (
                cell["return_data_opened"] is False
                and cell["return_hypotheses_spent"] == 0
            ),
            "lineage_classification_declared": cell["lineage_classification"]
            in {
                "ACTIVE_FEASIBILITY",
                "DUPLICATE_OVERLAP",
                "NOVEL_ATLAS",
                "RETIRED_KILLED",
                "IDENTITY_REDESIGN_REQUIRED",
            },
        }
        structural_pass = all(gates.values())
        literature_pass = cell["literature_status"] == "SOURCE_REVIEWED"
        if not structural_pass:
            decision = "REJECT_GOVERNANCE"
        elif cell["lineage_classification"] == "RETIRED_KILLED":
            decision = (
                "FORWARD_ONLY_MONITORING"
                if cell.get("forward_experiment")
                else "RETIRED_KILLED"
            )
        elif cell["lineage_classification"] == "DUPLICATE_OVERLAP":
            decision = "OVERLAP_REVIEW_REQUIRED"
        elif cell["lineage_classification"] == "IDENTITY_REDESIGN_REQUIRED":
            decision = "IDENTITY_REDESIGN_REQUIRED"
        elif not literature_pass:
            decision = "LITERATURE_REVIEW_REQUIRED"
        else:
            decision = "READY_FOR_KEY_FREE_FEASIBILITY"
        results.append(
            {
                "id": cell["id"],
                "family_id": cell["family_id"],
                "asset_group": cell["asset_group"],
                "gates": gates,
                "structural_pass": structural_pass,
                "literature_pass": literature_pass,
                "lineage_classification": cell["lineage_classification"],
                "lineage_aliases": cell["lineage_aliases"],
                "lineage_evidence": cell["lineage_evidence"],
                "lineage_permits_feasibility": cell["lineage_classification"]
                in ELIGIBLE_LINEAGE_CLASSES,
                "decision": decision,
                "return_data_opened": False,
                "return_hypotheses_spent": 0,
            }
        )

    decisions = Counter(result["decision"] for result in results)
    family_lineage = Counter(
        family["lineage_classification"] for family in atlas["families"]
    )
    cell_lineage = Counter(result["lineage_classification"] for result in results)
    payload: dict[str, Any] = {
        "schema": "canli.alphac-sleeve-atlas-audit.v2",
        "as_of": "2026-08-16",
        "atlas_content_hash": atlas["content_hash"],
        "stage": "NO_RETURN_TAXONOMY_AND_GOVERNANCE",
        "claim_boundary": (
            "Passing this audit is not return evidence and does not create a sleeve. "
            "It only permits a separately sealed key-free feasibility review."
        ),
        "structural_gates": list(STRUCTURAL_GATES),
        "summary": {
            "cells_audited": len(results),
            "families_audited": len(families),
            "asset_groups_audited": len({result["asset_group"] for result in results}),
            "gate_evaluations": len(results) * len(STRUCTURAL_GATES),
            "governance_rejections": decisions["REJECT_GOVERNANCE"],
            "lineage_families": dict(sorted(family_lineage.items())),
            "lineage_cells": dict(sorted(cell_lineage.items())),
            "retired_killed": decisions["RETIRED_KILLED"],
            "forward_only_monitoring": decisions["FORWARD_ONLY_MONITORING"],
            "overlap_review_required": decisions["OVERLAP_REVIEW_REQUIRED"],
            "identity_redesign_required": decisions["IDENTITY_REDESIGN_REQUIRED"],
            "literature_review_required": decisions["LITERATURE_REVIEW_REQUIRED"],
            "ready_for_key_free_feasibility": decisions[
                "READY_FOR_KEY_FREE_FEASIBILITY"
            ],
            "return_data_opened": 0,
            "return_hypotheses_spent": 0,
            "family_return_data_opened": atlas["summary"].get(
                "family_return_data_opened", 0
            ),
            "family_return_hypotheses_spent": atlas["summary"].get(
                "family_return_hypotheses_spent", 0
            ),
            "new_sleeves_admitted": 0,
        },
        "results": results,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/discovery/sleeve_atlas_audit.json"),
    )
    args = parser.parse_args()
    payload = audit_atlas()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                **payload["summary"],
                "content_hash": payload["content_hash"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
