#!/usr/bin/env python3
"""Select the next sleeve feasibility candidate without opening returns."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]
DISCOVERY: Final[Path] = REPO / "config/sleeve_discovery.json"
REACHABILITY: Final[Path] = REPO / "artifacts/analysis/atlas_reachability_screen/result.json"
ACTIVE_FEASIBILITY: Final[Path] = (
    REPO / "artifacts/feasibility/active_ownership_13d_item4_v3/result.json"
)
ACTIVE_PACKET: Final[Path] = (
    REPO / "artifacts/labeling/active_ownership_13d_item4_v3_blind/manifest.json"
)
REPURCHASE_PACKET: Final[Path] = (
    REPO / "artifacts/labeling/repurchase_item703_blind/manifest.json"
)
OUTPUT: Final[Path] = REPO / "artifacts/analysis/next_sleeve_selection.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _load_sealed(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    declared = payload.pop("content_hash", None)
    actual = _content_hash(payload)
    payload["content_hash"] = declared
    if declared != actual:
        raise ValueError(f"content hash mismatch: {path.relative_to(REPO)}")
    return payload


def build() -> dict[str, Any]:
    discovery = json.loads(DISCOVERY.read_text(encoding="utf-8"))
    reachability = json.loads(REACHABILITY.read_text(encoding="utf-8"))
    feasibility = _load_sealed(ACTIVE_FEASIBILITY)
    active_packet = _load_sealed(ACTIVE_PACKET)
    repurchase_packet = _load_sealed(REPURCHASE_PACKET)
    candidates = {row["id"]: row for row in discovery["candidates"]}
    active_reach = next(
        row for row in reachability["families"] if row["family"] == "active_ownership_escalation"
    )
    if (
        active_reach["verdict"] != "HELD_MACHINE_GATES_PASS_HUMAN_ACCURACY_REQUIRED"
        or active_reach["history_years"] < 3.0
        or feasibility["decision"] != "HUMAN_AUDIT_REQUIRED"
        or not all(feasibility["gates"].values())
        or active_packet["rows"] != 48
        or not active_packet["prediction_blind"]
    ):
        raise ValueError("active-ownership selection evidence changed")
    if candidates["repurchase_issuance_flow"]["counts_toward_ten_new_independent_sleeves"]:
        raise ValueError("repurchase family independence classification changed")
    if repurchase_packet["rows"] != 60 or not repurchase_packet["prediction_blind"]:
        raise ValueError("repurchase comparison packet changed")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-next-sleeve-selection.v1",
        "author": "Arhan Canli",
        "decision": "ACTIVE_OWNERSHIP_SELECTED_PENDING_GENUINE_INDEPENDENT_BLIND_AUDIT",
        "selected_candidate": {
            "id": "active_ownership_escalation",
            "mechanism": candidates["active_ownership_escalation"]["mechanism"],
            "asset_class": candidates["active_ownership_escalation"]["asset_class"],
            "history_years": active_reach["history_years"],
            "machine_gates_passed": True,
            "blind_labels_completed": 0,
            "blind_labels_required": active_packet["rows"],
            "return_trial_authorized": False,
        },
        "selection_rule": [
            "Must represent a distinct economic mechanism from the four current sleeves.",
            "Must be eligible to count toward the ten-new-sleeve objective.",
            "Must have at least three years of point-in-time source history already held.",
            "Must have passed its frozen machine extraction gates before any return access.",
            "The smallest remaining evidence gap wins; no return statistic may enter ranking.",
        ],
        "comparisons": {
            "active_ownership_escalation": (
                "Selected: 15.75 years held, all machine gates pass, 48 independent blind labels "
                "remain."
            ),
            "tender_offer_spread": (
                "Not selected: held history, but its frozen human ceiling is unmeasured and parser "
                "repair is not authorized."
            ),
            "repurchase_issuance_flow": (
                "Not selected: 60 blind labels remain and the identity is explicitly classified "
                "as same-family/distinct-measurement, so it does not count toward ten new sleeves."
            ),
            "untouched_atlas": (
                "Not selected: the reachability screen finds no untouched family currently "
                "unlocked by engineering."
            ),
        },
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "lineage": {
            str(path.relative_to(REPO)): _sha256(path)
            for path in (
                DISCOVERY,
                REACHABILITY,
                ACTIVE_FEASIBILITY,
                ACTIVE_PACKET,
                REPURCHASE_PACKET,
            )
        },
        "required_next_action": (
            "Give the frozen 48-document packet to a reviewer independent of parser development. "
            "Do not run classifier scoring, returns, correlation, or capacity until the completed "
            "labels and signed independence attestation pass the existing importer."
        ),
        "claim_boundary": (
            "This selects the next feasibility candidate using source reachability and mechanism "
            "criteria only. It makes no edge, sign, Sharpe, drawdown, correlation, capacity, or "
            "sleeve-admission claim and spends zero return hypotheses."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
