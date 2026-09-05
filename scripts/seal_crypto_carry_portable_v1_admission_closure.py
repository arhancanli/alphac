#!/usr/bin/env python3
"""Close portable-v1 as final INCOMPLETE without retroactive scenario design."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = Path("artifacts/research/crypto_carry_portable_v1_admission_closure.json")
RESULT: Final = Path("artifacts/research/crypto_carry_portable_v1_result.json")
RUN: Final = Path("config/crypto_carry_portable_v1_run.json")
PREREG: Final = Path("docs/design/PREREG_CRYPTO_CARRY_PORTABLE_V1.md")
PAPER: Final = Path("docs/research/CRYPTO_CARRY_PORTABLE_V1.md")
RESERVATION: Final = Path(
    "artifacts/research/preregistrations/crypto_carry_portable_v1/return_identity_reservation.json"
)
SCHEMA: Final = "canli.alphac-crypto-carry-portable-admission-closure.v1"
IDENTITY: Final = "da5f5f47f99f9bd2"
UNFROZEN_SCENARIO_FIELDS: Final = (
    "stress_scenario_manifest",
    "stressed_cost_grid",
    "stressed_execution_grid",
    "capacity_capital_points",
    "capacity_fill_model",
    "existing_book_snapshot",
    "candidate_book_weight",
    "diversification_stress_mask",
    "book_drawdown_simulation_specification",
)


class AdmissionClosureError(RuntimeError):
    """The final incomplete decision is not supported by frozen evidence."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return "sha256:" + hashlib.sha256(_canonical(body)).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AdmissionClosureError(f"required JSON is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AdmissionClosureError(f"required JSON is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise AdmissionClosureError(f"required JSON is not an object: {path}")
    return cast(dict[str, Any], value)


def _verified_hashed_json(path: Path, schema: str) -> dict[str, Any]:
    value = _load_json(path)
    if value.get("schema") != schema or value.get("content_hash") != _content_hash(value):
        raise AdmissionClosureError(f"schema or content hash mismatch: {path}")
    return value


def _binding(repo: Path, relative: Path, *, content_hash: str | None = None) -> dict[str, Any]:
    path = repo / relative
    if not path.is_file():
        raise AdmissionClosureError(f"required binding is missing: {relative}")
    row: dict[str, Any] = {
        "path": str(relative),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }
    if content_hash is not None:
        row["content_hash"] = content_hash
    return row


def _assert_unfrozen(run: dict[str, Any], reservation: dict[str, Any]) -> None:
    searchable = {**run, **reservation}
    found = [field for field in UNFROZEN_SCENARIO_FIELDS if field in searchable]
    if found:
        raise AdmissionClosureError(
            "closure premise drifted; scenario fields are now present: " + ", ".join(found)
        )


def build(repo: Path = ROOT) -> dict[str, Any]:
    repo = repo.resolve()
    result = _verified_hashed_json(repo / RESULT, "canli.alphac-crypto-carry-portable-result.v1")
    run = _verified_hashed_json(repo / RUN, "canli.alphac-crypto-carry-portable-run.v1")
    reservation = _load_json(repo / RESERVATION)
    if (
        result.get("identity", {}).get("hypothesis_key") != IDENTITY
        or run.get("hypothesis_identity") != IDENTITY
        or reservation.get("hypothesis_identity") != IDENTITY
    ):
        raise AdmissionClosureError("identity lineage does not reconcile")
    if result.get("disposition", {}).get("value") != "INCOMPLETE":
        raise AdmissionClosureError("primary receipt is not INCOMPLETE")
    if (
        result["disposition"].get("admitted") is not False
        or result["disposition"].get("killed") is not False
    ):
        raise AdmissionClosureError("primary disposition was overstated")

    governance = reservation.get("governance_epoch")
    if not isinstance(governance, dict):
        raise AdmissionClosureError("reservation governance binding is missing")
    policy_relative = Path(cast(str, governance["trial_policy_path"]))
    contract_relative = Path(cast(str, governance["admission_contract_path"]))
    policy = _load_json(repo / policy_relative)
    contract = _load_json(repo / contract_relative)
    if _sha256(repo / policy_relative) != governance.get("trial_policy_sha256"):
        raise AdmissionClosureError("reservation-bound trial policy drifted")
    if _sha256(repo / contract_relative) != governance.get("admission_contract_sha256"):
        raise AdmissionClosureError("reservation-bound admission contract drifted")
    if policy.get("window_only_keys") != ["start", "end"]:
        raise AdmissionClosureError(
            "identity policy no longer has the narrow window-only exemption"
        )
    definition = policy.get("definitions", {}).get("hypothesis_identity")
    if not isinstance(definition, str) or "start and end" not in definition:
        raise AdmissionClosureError("identity definition is missing or changed")
    if contract.get("schema") != "canli.alphac-sleeve-admission-contract.v7":
        raise AdmissionClosureError("unexpected governing admission contract")
    thresholds = contract.get("thresholds", {})
    required_thresholds = {
        "stressed_sharpe_min",
        "capacity_curve_min_points",
        "capacity_usd_min",
        "candidate_average_correlation_to_existing_book_max",
        "book_sharpe_delta_lower_95_min_exclusive",
        "book_expected_max_drawdown_max",
    }
    if not required_thresholds <= set(thresholds):
        raise AdmissionClosureError("governing admission requirements are incomplete")
    diversification_policy = contract.get("diversification_evidence_policy", {})
    if (
        diversification_policy.get("candidate_weight")
        != "predeclared upstream and supplied explicitly"
        or diversification_policy.get("stress_mask")
        != "predeclared upstream and supplied explicitly"
    ):
        raise AdmissionClosureError("v7 no longer requires predeclared book-analysis inputs")

    _assert_unfrozen(run, reservation)
    prereg_text = (repo / PREREG).read_text(encoding="utf-8")
    required_prereg_phrases = (
        "baseline, stressed-cost and stressed-execution outcomes",
        "capacity at no fewer than three capital points",
        "Any code, data, universe, timing, allocator,",
        "cost or risk mutation is a new identity",
        "`INCOMPLETE`: required evidence cannot be computed",
    )
    if any(phrase not in prereg_text for phrase in required_prereg_phrases):
        raise AdmissionClosureError("preregistration decision or mutation rule drifted")

    frozen_fields = set(run) | set(reservation)
    if frozen_fields & set(UNFROZEN_SCENARIO_FIELDS):
        raise AdmissionClosureError("an allegedly unfrozen scenario field is present")
    gate_assessment = result.get("gate_assessment", {})
    not_evaluated = gate_assessment.get("not_evaluated")
    if not isinstance(not_evaluated, list) or len(not_evaluated) < 10:
        raise AdmissionClosureError("primary receipt no longer exposes the missing gate evidence")

    document: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "FINAL_INCOMPLETE_NOT_ADMITTED_EVIDENCE_ACCOUNTING_COMPLETE",
        "author": "Arhan Canli",
        "evidence_date": "2026-08-24",
        "identity": {
            "family_trial_account": "crypto_carry",
            "return_identity_id": "crypto_carry_portable_v1",
            "hypothesis_key": IDENTITY,
            "config_hash": run["config_hash"],
            "reservation_ordinal": governance["reservation_ordinal"],
            "hypotheses_spent": 1,
        },
        "decision": {
            "disposition": "INCOMPLETE",
            "final_for_admission": True,
            "admitted": False,
            "killed": False,
            "technically_eligible": False,
            "identity_may_be_regraded_later": False,
            "gate_changes_after_result": 0,
            "additional_return_paths_executed_after_primary": 0,
        },
        "governance_finding": {
            "status": "PREREGISTERED_OUTPUT_CLASSES_BUT_NOT_EXACT_SUPPLEMENTAL_SCENARIOS",
            "required_but_unfrozen_fields": list(UNFROZEN_SCENARIO_FIELDS),
            "trial_policy_window_only_exemption": policy["window_only_keys"],
            "trial_policy_identity_definition": definition,
            "contract_requires_predeclared_candidate_weight": True,
            "contract_requires_predeclared_stress_mask": True,
            "why_supplemental_return_paths_were_not_run": (
                "Selecting cost, execution, capital, fill, or risk mutations after observing the "
                "primary result would add post-result discretion. The reservation-bound policy "
                "exempts only start and end from hypothesis identity, and the preregistration "
                "states that cost or risk mutations are new identities unless the governing "
                "policy explicitly classifies them otherwise. No such classification or exact "
                "scenario manifest was frozen for this identity."
            ),
            "why_book_tests_cannot_support_admission": (
                "The existing-book snapshot, candidate weight, stress mask, and drawdown "
                "simulation specification were not hash-bound before the primary result. The v7 "
                "contract requires upstream predeclaration for the candidate weight and stress "
                "mask. Choosing them now could change the admission result."
            ),
            "seriality_interaction": (
                "A separate new return identity cannot be reserved until this identity has a "
                "complete packet. Packet completion therefore records the final INCOMPLETE "
                "decision; it does not waive missing gates or make the candidate eligible."
            ),
        },
        "evidence_accounting": {
            "primary_result_and_same_path_diagnostics": "SEALED",
            "pbo": "NOT_DEFINED_SINGLE_REGISTERED_IDENTITY_NO_PATH_MATRIX",
            "unmeasured_gate_evidence": not_evaluated,
            "unmeasured_values_are_null_or_absent": True,
            "unmeasured_values_treated_as_pass": False,
            "packet_completion_meaning": (
                "Every required section has either measured evidence or a hash-bound final "
                "blocker. "
                "It does not mean every admission gate was evaluated or passed."
            ),
        },
        "prospective_correction_required": {
            "applies_to_this_known_result": False,
            "applies_to_future_reservations_only": True,
            "requirements": [
                "Freeze the exact stress-cost and stress-execution scenario manifest.",
                "Freeze all capacity capital points, fill assumptions, and decision rule.",
                "Freeze the existing-book return snapshot and alignment rule.",
                (
                    "Freeze candidate book weight, stress mask, bootstrap seed, block length, "
                    "and samples."
                ),
                "Freeze the expected and p95 book-drawdown simulation specification.",
                "Classify prespecified diagnostic paths in the trial policy before reservation.",
                (
                    "Execute and seal all required evidence before exposing the primary result "
                    "to discretionary review."
                ),
            ],
        },
        "lineage": {
            "primary_result": _binding(repo, RESULT, content_hash=result["content_hash"]),
            "run_config": _binding(repo, RUN, content_hash=run["content_hash"]),
            "preregistration": _binding(repo, PREREG),
            "reservation": _binding(repo, RESERVATION),
            "trial_paper": _binding(repo, PAPER),
            "trial_policy": _binding(repo, policy_relative),
            "admission_contract": _binding(repo, contract_relative),
        },
        "claim_boundary": (
            "This closure proves why the registered candidate ends INCOMPLETE and not admitted. "
            "It does not assert that an unmeasured gate failed, convert null evidence into zero, "
            "authorize a post-result scenario choice, validate returns, or imply future "
            "performance."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def _serialized(document: dict[str, Any]) -> bytes:
    return json.dumps(document, indent=2, sort_keys=True).encode() + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write and args.check:
        raise SystemExit("choose either --write or --check")
    document = build(ROOT)
    path = ROOT / OUTPUT
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_serialized(document))
    elif args.check:
        if not path.is_file() or path.read_bytes() != _serialized(document):
            raise AdmissionClosureError(f"closure is stale or missing: {OUTPUT}")
    print(
        json.dumps(
            {
                "status": document["status"],
                "disposition": document["decision"]["disposition"],
                "admitted": document["decision"]["admitted"],
                "additional_return_paths": document["decision"][
                    "additional_return_paths_executed_after_primary"
                ],
                "content_hash": document["content_hash"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
