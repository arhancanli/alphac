"""Classify what is actually blocking each DATA_GATED family, and what each unblock costs.

WHY THIS EXISTS. "Data-gated" reads like one problem. It includes free credentials, paid vendor
decisions, extraction engineering, incomplete human audits, and identities whose measured ceiling
proves that parser work cannot rescue them. Lumping those together misallocates the next iteration.

Reads the feasibility artifacts and greps the audit scripts for the credentials they consult.
Opens no return data, runs no backtest, registers no hypothesis: 0 trials.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FEASIBILITY = REPO / "artifacts" / "feasibility"
SCRIPTS = REPO / "scripts"
OUTPUT = REPO / "artifacts" / "analysis" / "data_gate_unblocks" / "result.json"
REACHABILITY = REPO / "artifacts" / "analysis" / "reachability_harness" / "result.json"
ATLAS_SCREEN = REPO / "artifacts" / "analysis" / "atlas_reachability_screen" / "result.json"
FAMILY_LINEAGE = REPO / "config" / "sleeve_family_lineage.json"
CFTC_RELEASE_REACHABILITY = (
    REPO / "artifacts" / "analysis" / "cftc_release_reachability" / "result.json"
)
BOND_ETF_REACHABILITY = (
    REPO / "artifacts" / "analysis" / "bond_etf_nav_reachability" / "result.json"
)
REPURCHASE_BLIND_PACKET = (
    REPO / "artifacts" / "labeling" / "repurchase_item703_blind" / "manifest.json"
)
ACTIVE_OWNERSHIP_BLIND_PACKET = (
    REPO
    / "artifacts"
    / "labeling"
    / "active_ownership_13d_item4_v3_blind"
    / "manifest.json"
)
TREASURY_STATE_MACHINE = (
    FEASIBILITY / "treasury_auction_concession" / "schedule_state_machine_audit.json"
)
MERGER_CONFIRMATORY_DESIGN = (
    FEASIBILITY / "merger_arbitrage" / "announcement_confirmatory_design.json"
)
SUPERSEDED_RESULTS = {
    "active_ownership_13d",
    "active_ownership_13d_schema_v2",
    "active_ownership_13d_item4",
    "active_ownership_13d_item4_v2",
}

# Some families advance through multiple fail-closed stages without rewriting a generic
# result.json.  Bind those families to the latest decision-bearing artifact explicitly; all
# other families must use their canonical result.json.  Never let filename ordering decide
# which research state is current.
CURRENT_STAGE_ARTIFACTS: dict[str, str] = {
    "merger_arbitrage": "announcement_confirmatory_design.json",
    "pre_fomc_announcement_drift": "market_data_readiness.json",
    "repurchase_issuance_flow": "item703/documents_result.json",
    "spin_off_dislocation": "document_schema_result.json",
    "treasury_auction_concession": "schedule_state_machine_audit.json",
}

# Credential -> what it costs to obtain. Stated so a blocker is never reported without its price.
CREDENTIALS: dict[str, dict[str, str]] = {
    "EIA_API_KEY": {
        "cost": "FREE",
        "obtain": "https://www.eia.gov/opendata/register.php",
        "effort": "instant, email only",
    },
    "DATABENTO_API_KEY": {
        "cost": "PAID",
        "obtain": "https://databento.com",
        "effort": "commercial agreement; usage-priced",
    },
    "POLYGON_API_KEY": {
        "cost": "FREE_TIER",
        "obtain": "https://polygon.io/dashboard/signup",
        "effort": "instant; free tier is rate-limited and may not cover the full history",
    },
}

_ENV = re.compile(r'os\.environ\.get\(\s*"([A-Z][A-Z0-9_]*)"')


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _scripts_for(family: str) -> list[Path]:
    stem = family.replace("-", "_")
    artifact_reference = f"artifacts/feasibility/{family}"
    matches: list[Path] = []
    for path in SCRIPTS.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if stem in path.stem or artifact_reference in source:
            matches.append(path)
    return sorted(matches)


def _artifact_for(directory: Path) -> tuple[Path, list[Path]]:
    considered = sorted(directory.rglob("*.json"))
    relative = CURRENT_STAGE_ARTIFACTS.get(directory.name, "result.json")
    selected = directory / relative
    if not selected.is_file():
        raise FileNotFoundError(
            f"current-stage artifact missing for {directory.name}: "
            f"{selected.relative_to(REPO)}"
        )
    return selected, considered


def _credentials_used(paths: list[Path]) -> list[str]:
    found: set[str] = set()
    for path in paths:
        found.update(name for name in _ENV.findall(path.read_text()) if name in CREDENTIALS)
    return sorted(found)


def main() -> int:
    lineage = json.loads(FAMILY_LINEAGE.read_text(encoding="utf-8")).get("families", {})
    cftc_reachability = (
        json.loads(CFTC_RELEASE_REACHABILITY.read_text(encoding="utf-8"))
        if CFTC_RELEASE_REACHABILITY.is_file()
        else None
    )
    bond_etf_reachability = (
        json.loads(BOND_ETF_REACHABILITY.read_text(encoding="utf-8"))
        if BOND_ETF_REACHABILITY.is_file()
        else None
    )
    reachability_rows = (
        json.loads(REACHABILITY.read_text(encoding="utf-8")).get("families", [])
        if REACHABILITY.is_file()
        else []
    )
    reachability = {str(row["family"]): str(row["verdict"]) for row in reachability_rows}
    atlas_rows = (
        json.loads(ATLAS_SCREEN.read_text(encoding="utf-8")).get("families", [])
        if ATLAS_SCREEN.is_file()
        else []
    )
    atlas_verdicts = {str(row["family"]): str(row["verdict"]) for row in atlas_rows}
    families: list[dict[str, Any]] = []
    for directory in sorted(p for p in FEASIBILITY.iterdir() if p.is_dir()):
        selected_artifact, considered_artifacts = _artifact_for(directory)
        artifact = json.loads(selected_artifact.read_text(encoding="utf-8"))
        decision = str(artifact.get("decision", "UNKNOWN"))
        gates = artifact.get("gates") or artifact.get("technical_gates") or {}
        failing = sorted(k for k, v in gates.items() if v is False)
        blocking = list(artifact.get("blocking_reasons") or [])
        paths = _scripts_for(directory.name)
        credentials = _credentials_used(paths)
        missing = [name for name in credentials if not os.environ.get(name)]
        family_lineage = lineage.get(directory.name, {})
        return_outcome = family_lineage.get("return_outcome") or None

        if return_outcome and return_outcome.get("return_data_opened") is True:
            classification = "RETURN_OUTCOME_ALREADY_RECORDED"
        elif directory.name in SUPERSEDED_RESULTS:
            classification = "SUPERSEDED_HISTORICAL_RESULT"
        elif (
            directory.name == "cftc_hedging_pressure"
            and cftc_reachability is not None
            and cftc_reachability.get("decision") == "UNREACHABLE_AS_PREREGISTERED"
        ):
            classification = "BLOCKED_ON_UNRECOVERABLE_RELEASE_LINEAGE"
        elif (
            directory.name == "bond_etf_nav_dislocation"
            and bond_etf_reachability is not None
            and bond_etf_reachability.get("verdict")
            == "PAID_ARCHIVAL_AND_EXECUTABLE_DATA_REQUIRED"
        ):
            classification = "BLOCKED_ON_PAID_ARCHIVAL_AND_EXECUTABLE_DATA"
        elif (
            directory.name == "pre_fomc_announcement_drift"
            and artifact.get("credential_state") == "NO_USABLE_QUOTE_DOWNLOAD_ROUTE"
        ):
            classification = "BLOCKED_ON_PAID_OR_BOUNDED_MARKET_DATA_ROUTE"
        elif directory.name == "repurchase_issuance_flow" and decision == (
            "READY_FOR_BLIND_LABELING"
        ):
            classification = "BLOCKED_ON_HUMAN_BLIND_LABELING"
        elif decision == "AUTHOR_APPROVAL_REQUIRED":
            classification = "BLOCKED_ON_AUTHOR_TECHNICAL_APPROVAL"
        elif reachability.get(directory.name) == "GATE_UNREACHABLE_BY_DETECTOR_REPAIR":
            classification = "BLOCKED_ON_MEASURED_REACHABILITY_CEILING"
        elif decision == "HUMAN_AUDIT_REQUIRED":
            classification = "BLOCKED_ON_HUMAN_ACCURACY_AUDIT"
        elif missing:
            free = [n for n in missing if CREDENTIALS[n]["cost"] in ("FREE", "FREE_TIER")]
            classification = "BLOCKED_ON_FREE_CREDENTIAL" if free else "BLOCKED_ON_PAID_DATA"
        elif failing or blocking:
            classification = "BLOCKED_ON_EXTRACTION_QUALITY"
        else:
            classification = "NOT_BLOCKED"

        families.append(
            {
                "family": directory.name,
                "decision": decision,
                "classification": classification,
                "source_artifact": str(selected_artifact.relative_to(REPO)),
                "artifacts_considered": [
                    str(path.relative_to(REPO)) for path in considered_artifacts
                ],
                "failing_gates": failing,
                "failing_gate_count": len(failing),
                "passing_gate_count": sum(1 for v in gates.values() if v is True),
                "blocking_reasons": blocking,
                "credentials_required": credentials,
                "credentials_missing": missing,
                "credential_cost": {
                    name: CREDENTIALS[name] for name in missing
                },
                "reachability_verdict": reachability.get(directory.name),
                "atlas_obtainability_verdict": atlas_verdicts.get(directory.name),
                "superseded": directory.name in SUPERSEDED_RESULTS,
                "return_outcome": return_outcome,
                "actionable_unblock": classification not in {
                    "RETURN_OUTCOME_ALREADY_RECORDED",
                    "SUPERSEDED_HISTORICAL_RESULT",
                },
                "release_reachability_verdict": (
                    cftc_reachability.get("verdict")
                    if directory.name == "cftc_hedging_pressure"
                    and cftc_reachability is not None
                    else None
                ),
                "source_reachability_verdict": (
                    bond_etf_reachability.get("verdict")
                    if directory.name == "bond_etf_nav_dislocation"
                    and bond_etf_reachability is not None
                    else None
                ),
                "return_hypotheses_spent": artifact.get("return_hypotheses_spent", 0),
            }
        )

    by_class: dict[str, list[str]] = {}
    for family in families:
        by_class.setdefault(family["classification"], []).append(family["family"])

    # Closest to passing: gated, needs no credential, and fails the fewest gates.
    nearest = sorted(
        (
            f
            for f in families
            if f["decision"] == "DATA_GATED"
            and f["classification"] == "BLOCKED_ON_EXTRACTION_QUALITY"
            and f["failing_gate_count"] > 0
            and not f["superseded"]
            and f["reachability_verdict"]
            not in {"GATE_UNREACHABLE_BY_DETECTOR_REPAIR", "GATE_BLENDS_TWO_POPULATIONS"}
            and f["atlas_obtainability_verdict"]
            not in {
                "HELD_BUT_REACHABILITY_CEILING_NOT_MEASURED",
                "HELD_MACHINE_GATES_PASS_HUMAN_ACCURACY_REQUIRED",
                "RECORD_HELD_BUT_IDENTITY_REDESIGN_REQUIRED",
                "VENDOR_ONLY_AN_OWNER_SPENDING_DECISION",
                "HISTORY_TOO_SHORT_FOR_THE_ADMISSION_CONTRACT",
                "RECORD_OBTAINABLE_BUT_THE_MARKS_ARE_NOT_EXECUTABLE",
                "NO_POINT_IN_TIME_RECORD_WAS_EVER_PRESERVED",
            }
        ),
        key=lambda f: (f["failing_gate_count"], -f["passing_gate_count"]),
    )

    result: dict[str, Any] = {
        "schema": "canli.alphac-data-gate-unblocks.v1",
        "claim_boundary": (
            "Classifies blockers only. Opens no return data, runs no backtest, registers no "
            "hypothesis, and claims nothing about any candidate's edge, sign or correlation. "
            "0 trials."
        ),
        "families_examined": len(families),
        "by_classification": by_class,
        "families": families,
        "nearest_to_passing": [
            {
                "family": f["family"],
                "failing_gates": f["failing_gates"],
                "passing": f["passing_gate_count"],
            }
            for f in nearest[:5]
        ],
        "owner_actions": [
            {
                "action": f"register {name} ({meta['cost']}) at {meta['obtain']}",
                "effort": meta["effort"],
                "unblocks": sorted(
                    f["family"]
                    for f in families
                    if name in f["credentials_missing"]
                    and f["classification"]
                    in {"BLOCKED_ON_FREE_CREDENTIAL", "BLOCKED_ON_PAID_DATA"}
                ),
            }
            for name, meta in CREDENTIALS.items()
            if any(
                name in f["credentials_missing"]
                and f["classification"]
                in {"BLOCKED_ON_FREE_CREDENTIAL", "BLOCKED_ON_PAID_DATA"}
                for f in families
            )
        ]
        + [
            {
                "action": (
                    "commission one independent reviewer to complete the frozen 60-document "
                    "Item 703 packet and attestation"
                ),
                "effort": "manual source review; no parser output, prices, or returns",
                "unblocks": ["repurchase_issuance_flow"],
                "packet": str(REPURCHASE_BLIND_PACKET.relative_to(REPO)),
                "packet_content_hash": json.loads(REPURCHASE_BLIND_PACKET.read_text())[
                    "content_hash"
                ],
            },
            {
                "action": (
                    "commission one independent reviewer to complete the frozen 48-document "
                    "active-ownership Item 4 packet and attestation"
                ),
                "effort": "manual source review; no parser output, prices, or returns",
                "unblocks": ["active_ownership_13d_item4_v3"],
                "packet": str(ACTIVE_OWNERSHIP_BLIND_PACKET.relative_to(REPO)),
                "packet_content_hash": json.loads(ACTIVE_OWNERSHIP_BLIND_PACKET.read_text())[
                    "content_hash"
                ],
            },
            {
                "action": (
                    "Arhan independently reviews the merger-announcement v2 confirmation design "
                    "and records approval or required changes; automation may not answer for him"
                ),
                "effort": (
                    "technical authorship review; confirmation corpus, prices and returns "
                    "remain unopened"
                ),
                "unblocks": ["merger_arbitrage"],
                "protocol": "docs/design/FEASIBILITY_MERGER_ANNOUNCEMENT_IDENTITY_V2.md",
                "source_artifact": (
                    "artifacts/feasibility/merger_arbitrage/"
                    "announcement_confirmatory_design.json"
                ),
                "artifact_content_hash": json.loads(MERGER_CONFIRMATORY_DESIGN.read_text())[
                    "content_hash"
                ],
            },
            {
                "action": (
                    "Arhan independently reviews the Treasury schedule state machine and records "
                    "approval or required changes; automation may not answer for him"
                ),
                "effort": "technical authorship review; no prices or returns",
                "unblocks": ["treasury_auction_concession"],
                "protocol": "docs/design/FEASIBILITY_TREASURY_AUCTION_STATE_MACHINE.md",
                "source_artifact": (
                    "artifacts/feasibility/treasury_auction_concession/"
                    "schedule_state_machine_audit.json"
                ),
                "artifact_content_hash": json.loads(TREASURY_STATE_MACHINE.read_text())[
                    "content_hash"
                ],
            },
        ],
        "honest_reading": (
            "A credential unblocks COLLECTION, never admission. A family whose key arrives still "
            "has to pass its remaining feasibility gates, then pre-register, then clear all "
            "eighty-five admission checks. The free keys are worth registering because they are "
            "free, not because they are close to a sleeve. A family with a recorded return "
            "outcome is historical evidence, never an actionable data unblock."
        ),
    }
    result["content_hash"] = content_hash(result)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    for name, members in sorted(by_class.items()):
        print(f"  {name}: {len(members)}")
    print("\n  owner actions:")
    for action in result["owner_actions"]:
        print(f"    - {action['action']}")
        print(f"      unblocks: {', '.join(action['unblocks']) or '(none mapped)'}")
    print("\n  nearest to passing (no credential needed):")
    for item in result["nearest_to_passing"]:
        print(f"    - {item['family']}: {item['passing']} gates pass, "
              f"{len(item['failing_gates'])} fail -> {item['failing_gates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
