#!/usr/bin/env python3
"""Seal the immutable primary result without overstating admission evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Final, cast

import pandas as pd

from alphaforge.analytics.metrics import DAYS_PER_YEAR, daily_returns, sharpe
from alphaforge.validation.experiments import config_hash, hypothesis_hash
from alphaforge.validation.input_snapshot import validate_input_snapshot

ROOT: Final = Path(__file__).resolve().parents[1]
RUN_CONFIG: Final = Path("config/crypto_carry_portable_v1_run.json")
RESERVATION: Final = Path(
    "artifacts/research/preregistrations/crypto_carry_portable_v1/return_identity_reservation.json"
)
RESULT_DIR: Final = Path("artifacts/prospective/crypto_carry_portable_v1")
RESULT_RECEIPT: Final = Path("artifacts/research/crypto_carry_portable_v1_result.json")
PACKET: Final = Path("artifacts/research/trial_packets/da5f5f47f99f9bd2.json")
PAPER: Final = Path("docs/research/CRYPTO_CARRY_PORTABLE_V1.md")
CLOSURE: Final = Path("artifacts/research/crypto_carry_portable_v1_admission_closure.json")
LEDGER: Final = Path("var/experiments.jsonl")
RESULT_SCHEMA: Final = "canli.alphac-crypto-carry-portable-result.v1"
PACKET_SCHEMA: Final = "canli.alphac-identity-trial-packet.v2"
IDENTITY: Final = "da5f5f47f99f9bd2"
PUBLIC_RESULT_FILES: Final = (
    "equity.parquet",
    "summary.txt",
    "tearsheet.png",
    "tearsheet.txt",
    "walkforward.json",
    "input_snapshot/manifest.json",
)
REQUIRED_SECTIONS: Final = (
    "identity_and_authorship",
    "economic_mechanism_and_falsifiable_hypothesis",
    "literature_and_overlap_decision",
    "family_and_union_trial_accounting",
    "machine_readable_packet_and_stable_public_paper",
    "preregistration_and_hashes",
    "point_in_time_data_and_survivorship_controls",
    "execution_and_cost_model",
    "result_uncertainty_stress_capacity_and_diversification",
    "admission_or_kill_decision",
    "code_environment_and_reproduction",
)


class ResultSealError(RuntimeError):
    """The immutable result cannot be represented truthfully."""


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
        raise ResultSealError(f"required JSON is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ResultSealError(f"required JSON is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise ResultSealError(f"required JSON is not an object: {path}")
    return cast(dict[str, Any], value)


def _verified_hashed_json(path: Path, schema: str | None = None) -> dict[str, Any]:
    value = _load_json(path)
    if schema is not None and value.get("schema") != schema:
        raise ResultSealError(f"unexpected schema: {path}")
    if value.get("content_hash") != _content_hash(value):
        raise ResultSealError(f"content hash mismatch: {path}")
    return value


def _binding(repo: Path, relative: str, *, content_hash: str | None = None) -> dict[str, Any]:
    path = repo / relative
    if not path.is_file():
        raise ResultSealError(f"required binding is missing: {relative}")
    row: dict[str, Any] = {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }
    if content_hash is not None:
        row["content_hash"] = content_hash
    return row


def _verify_declared_bindings(repo: Path, run: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    bindings = run.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise ResultSealError("run config bindings are missing")
    for name, claimed in bindings.items():
        if not isinstance(claimed, dict) or not isinstance(claimed.get("path"), str):
            raise ResultSealError(f"malformed run binding: {name}")
        relative = cast(str, claimed["path"])
        observed = _binding(repo, relative)
        if observed["sha256"] != claimed.get("sha256"):
            raise ResultSealError(f"frozen run binding drifted: {name}")
        if "content_hash" in claimed:
            source = _verified_hashed_json(repo / relative)
            if source["content_hash"] != claimed["content_hash"]:
                raise ResultSealError(f"frozen run content binding drifted: {name}")
            observed["content_hash"] = source["content_hash"]
        rows.append({"name": name, **observed})
    return rows


def _ledger_record(repo: Path, trial_config: dict[str, Any]) -> dict[str, Any]:
    wanted_hash = config_hash(trial_config)
    matches = []
    path = repo / LEDGER
    for line_number, raw in enumerate(path.read_bytes().splitlines(), start=1):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ResultSealError(f"ledger line {line_number} is invalid JSON") from error
        if row.get("config_hash") == wanted_hash:
            matches.append((line_number, raw, row))
    if len(matches) != 1:
        raise ResultSealError(
            f"expected one immutable ledger record for {wanted_hash}; found {len(matches)}"
        )
    line_number, raw, row = matches[0]
    if row.get("config") != trial_config:
        raise ResultSealError("ledger configuration does not equal the frozen trial")
    return {
        "source_path": str(LEDGER),
        "line_number_at_seal": line_number,
        "record_sha256": hashlib.sha256(raw).hexdigest(),
        "record": row,
    }


def _equity(repo: Path) -> tuple[pd.Series, pd.Series]:
    frame = pd.read_parquet(repo / RESULT_DIR / "equity.parquet")
    if list(frame.columns) != ["ts", "equity"] or len(frame) < 2:
        raise ResultSealError("equity artifact has an unexpected schema")
    if frame["ts"].duplicated().any() or not frame["ts"].is_monotonic_increasing:
        raise ResultSealError("equity timestamps are not unique and increasing")
    series = pd.Series(
        frame["equity"].to_numpy(dtype="float64"),
        index=pd.Index(frame["ts"].to_numpy(dtype="int64"), name="ts"),
        name="equity",
    )
    if not all(math.isfinite(float(value)) and float(value) > 0 for value in series):
        raise ResultSealError("equity contains a non-finite or non-positive value")
    return series, daily_returns(series)


def _leave_one_year_out(returns: pd.Series) -> list[dict[str, Any]]:
    dates = pd.to_datetime(returns.index.to_numpy(dtype="int64"), unit="ms", utc=True)
    years = sorted({int(year) for year in dates.year})
    rows = []
    for year in years:
        kept = returns[dates.year != year]
        rows.append(
            {
                "excluded_calendar_year_utc": year,
                "retained_daily_observations": len(kept),
                "annualized_sharpe": sharpe(kept, DAYS_PER_YEAR),
            }
        )
    return rows


def _calendar_year_returns(returns: pd.Series) -> list[dict[str, Any]]:
    dates = pd.to_datetime(returns.index.to_numpy(dtype="int64"), unit="ms", utc=True)
    rows = []
    for year in sorted({int(value) for value in dates.year}):
        selected = returns[dates.year == year]
        rows.append(
            {
                "calendar_year_utc": year,
                "daily_observations": len(selected),
                "compounded_return": math.prod(1.0 + float(value) for value in selected) - 1.0,
                "annualized_sharpe": sharpe(selected, DAYS_PER_YEAR),
                "partial_year": year in {int(dates.year.min()), int(dates.year.max())},
            }
        )
    return rows


def _result_inventory(repo: Path) -> dict[str, Any]:
    rows = []
    for relative in PUBLIC_RESULT_FILES:
        path = repo / RESULT_DIR / relative
        rows.append(_binding(repo, str(RESULT_DIR / relative)))
        if not path.is_file():  # defensive; _binding already rejects this
            raise ResultSealError(f"result artifact is missing: {relative}")
    return {
        "files": rows,
        "file_count": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "root_sha256": hashlib.sha256(_canonical(rows)).hexdigest(),
        "private_snapshot_leaves_excluded_from_public_inventory": True,
    }


def _gate_assessment(
    contract: dict[str, Any], summary: dict[str, Any], validation: dict[str, Any]
) -> dict[str, Any]:
    thresholds = contract["thresholds"]
    measured_dsr = validation.get("dsr")
    return {
        "governing_contract_schema": contract["schema"],
        "evaluated": [
            {
                "gate": "net_sharpe_min",
                "observed": summary["sharpe"],
                "threshold": thresholds["net_sharpe_min"],
                "operator": ">=",
                "status": "PASS" if summary["sharpe"] >= thresholds["net_sharpe_min"] else "FAIL",
            },
            {
                "gate": "minimum_oos_observations",
                "observed": validation["n_obs"],
                "threshold": thresholds["minimum_oos_observations"],
                "operator": ">=",
                "status": (
                    "PASS"
                    if validation["n_obs"] >= thresholds["minimum_oos_observations"]
                    else "FAIL"
                ),
            },
            {
                "requirement": "deflated_sharpe_must_be_measured",
                "observed": measured_dsr,
                "status": "PASS_MEASUREMENT_PRESENT"
                if isinstance(measured_dsr, (int, float))
                else "FAIL",
                "admission_role": "MANDATORY_MEASUREMENT_NOT_PER_SLEEVE_GATE",
                "generic_runner_dsr_at_least_0_95_indicator": validation["clears_dsr_gate"],
                "generic_runner_indicator_is_governing_v7_gate": False,
            },
        ],
        "not_evaluated": [
            "newey_west_t_min",
            "newey_west_t_ratio_min",
            "stressed_sharpe_min",
            "capacity_curve_min_points",
            "capacity_minimum_stressed_fill_ratio",
            "capacity_usd_min",
            "ordinary_pairwise_correlation_max",
            "pairwise_correlation_upper_95_max",
            "stressed_pairwise_correlation_max",
            "stressed_pairwise_correlation_upper_95_max",
            "candidate_average_correlation_to_existing_book_max",
            "book_average_pairwise_correlation_delta_max_exclusive",
            "book_sharpe_delta_min_exclusive",
            "book_sharpe_delta_lower_95_min_exclusive",
            "minimum_leave_one_period_out_book_sharpe_delta_exclusive",
            "book_expected_shortfall_delta_max",
            "book_max_drawdown_delta_max",
            "book_expected_max_drawdown_max",
            "book_deflated_sharpe_must_be_measured",
            "execution_scenario_bundle",
            "overlay_replay",
        ],
        "pbo": {
            "value": None,
            "status": "NOT_DEFINED_SINGLE_REGISTERED_IDENTITY_NO_PATH_MATRIX",
            "zero_imputation_forbidden": True,
        },
        "admission_status": "INCOMPLETE_NOT_ADMITTED",
        "technically_eligible": False,
        "reason": (
            "Required v7 evidence remains unmeasured; a positive point estimate cannot "
            "substitute for it."
        ),
    }


def build(repo: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    repo = repo.resolve()
    run = _verified_hashed_json(repo / RUN_CONFIG, "canli.alphac-crypto-carry-portable-run.v1")
    reservation = _load_json(repo / RESERVATION)
    trial_config = cast(dict[str, Any], run["trial_config"])
    if config_hash(trial_config) != run.get("config_hash"):
        raise ResultSealError("frozen config hash does not reconcile")
    if (
        hypothesis_hash(trial_config) != run.get("hypothesis_identity")
        or run.get("hypothesis_identity") != IDENTITY
    ):
        raise ResultSealError("frozen hypothesis identity does not reconcile")
    if (
        reservation.get("hypothesis_identity") != IDENTITY
        or reservation.get("trial_config") != trial_config
        or reservation.get("hypotheses_spent") != 1
        or reservation.get("status") != "RETURN_IDENTITY_RESERVED"
    ):
        raise ResultSealError("reservation does not bind exactly one frozen identity")

    declared_bindings = _verify_declared_bindings(repo, run)
    contract_path = cast(str, reservation["governance_epoch"]["admission_contract_path"])
    contract = _load_json(repo / contract_path)
    if (
        contract.get("schema") != "canli.alphac-sleeve-admission-contract.v7"
        or _sha256(repo / contract_path)
        != reservation["governance_epoch"]["admission_contract_sha256"]
    ):
        raise ResultSealError("reservation-bound v7 contract drifted")
    if contract["deflation_policy"].get("per_sleeve_is_measured_not_gated") is not True:
        raise ResultSealError("v7 per-sleeve DSR role is not the reserved measured-only policy")

    result_dir = repo / RESULT_DIR
    snapshot = validate_input_snapshot(result_dir / "input_snapshot")
    walkforward = _load_json(result_dir / "walkforward.json")
    if len(walkforward.get("legs", [])) != run.get("expected_walkforward_legs"):
        raise ResultSealError("walk-forward leg count does not match the freeze")
    if walkforward.get("validation") is None:
        raise ResultSealError("walk-forward validation block is missing")
    summary = cast(dict[str, Any], walkforward["summary"])
    validation = cast(dict[str, Any], walkforward["validation"])
    if (
        walkforward["config"].get("input_snapshot", {}).get("content_hash")
        != snapshot["content_hash"]
    ):
        raise ResultSealError("walk-forward result does not bind the verified input snapshot")

    _equity_series, returns = _equity(repo)
    if len(returns) != validation["n_obs"]:
        raise ResultSealError("daily return count does not reconcile to validation")
    observed_sharpe = sharpe(returns, DAYS_PER_YEAR)
    if not math.isclose(observed_sharpe, summary["sharpe"], rel_tol=0.0, abs_tol=1e-12):
        raise ResultSealError("equity-derived Sharpe does not reconcile to summary")
    if not math.isclose(observed_sharpe, validation["sr_ann"], rel_tol=0.0, abs_tol=1e-12):
        raise ResultSealError("equity-derived Sharpe does not reconcile to validation")

    ledger = _ledger_record(repo, trial_config)
    record = ledger["record"]
    if record["n_obs"] != validation["n_obs"] or not math.isclose(
        record["sharpe_ann"], observed_sharpe, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ResultSealError("immutable ledger measurement does not reconcile")

    legs = cast(list[dict[str, Any]], walkforward["legs"])
    leg_sharpes = [float(item["summary"]["sharpe"]) for item in legs]
    leave_out = _leave_one_year_out(returns)
    gate_assessment = _gate_assessment(contract, summary, validation)
    receipt: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "status": "SEALED_PRIMARY_RESULT_ADMISSION_INCOMPLETE",
        "author": "Arhan Canli",
        "evidence_date": "2026-08-24",
        "identity": {
            "family_trial_account": "crypto_carry",
            "return_identity_id": "crypto_carry_portable_v1",
            "hypothesis_key": IDENTITY,
            "config_hash": run["config_hash"],
            "reservation_ordinal": reservation["governance_epoch"]["reservation_ordinal"],
            "hypotheses_spent": 1,
            "primary_return_trials_executed": 1,
            "unregistered_variants_executed": 0,
        },
        "classification": {
            "evidence_type": "HISTORICAL_WALK_FORWARD_SIMULATION",
            "live_broker_result": False,
            "forward_live_result": False,
            "independent_replication": False,
            "peer_reviewed": False,
            "external_submission_completed": False,
        },
        "immutable_primary_result": {
            "summary": summary,
            "validation": validation,
            "dsr_interpretation": {
                "measured_value": validation["dsr"],
                "generic_runner_indicator_clears_0_95": validation["clears_dsr_gate"],
                "reservation_bound_v7_role": "MEASURE_AND_PUBLISH_NOT_PER_SLEEVE_GATE",
                "candidate_killed_by_dsr_alone": False,
            },
            "drawdown_interpretation": {
                "candidate_simulation_max_drawdown": summary["max_dd"],
                "book_expected_maximum_drawdown": None,
                "book_p95_maximum_drawdown": None,
                "candidate_max_drawdown_is_not_the_book_expected_drawdown_estimand": True,
            },
        },
        "stability_diagnostics_from_same_immutable_path": {
            "method": "UTC daily returns; no return-path mutation and no new hypothesis identity",
            "walkforward_legs": legs,
            "leg_summary": {
                "count": len(leg_sharpes),
                "positive_sharpe_legs": sum(value > 0 for value in leg_sharpes),
                "nonpositive_sharpe_legs": sum(value <= 0 for value in leg_sharpes),
                "minimum_sharpe": min(leg_sharpes),
                "median_sharpe": median(leg_sharpes),
                "maximum_sharpe": max(leg_sharpes),
            },
            "calendar_year_results": _calendar_year_returns(returns),
            "leave_one_calendar_year_out": leave_out,
            "minimum_leave_one_calendar_year_out_sharpe": min(
                float(row["annualized_sharpe"]) for row in leave_out
            ),
        },
        "gate_assessment": gate_assessment,
        "lineage": {
            "reservation": _binding(repo, str(RESERVATION)),
            "run_config": _binding(repo, str(RUN_CONFIG), content_hash=run["content_hash"]),
            "admission_contract": _binding(repo, contract_path),
            "declared_pre_result_bindings": declared_bindings,
            "input_snapshot": {
                "path": str(RESULT_DIR / "input_snapshot/manifest.json"),
                "manifest_sha256": _sha256(result_dir / "input_snapshot/manifest.json"),
                "content_hash": snapshot["content_hash"],
                "root_sha256": snapshot["root_sha256"],
                "file_count": snapshot["file_count"],
                "snapshot_bytes": snapshot["snapshot_bytes"],
                "all_files_rehashed_at_seal": True,
                "public_release_allowed": False,
            },
            "immutable_ledger_record": ledger,
            "result_inventory": _result_inventory(repo),
        },
        "disposition": {
            "value": "INCOMPLETE",
            "admitted": False,
            "killed": False,
            "blocking_reason": "The preregistered v7 admission evidence suite is not complete.",
            "gate_changes_after_result": 0,
            "seriality_at_primary_result_seal": {
                "next_forward_identity_blocked": True,
                "unblock_condition": "COMPLETE_HASH_VALID_IDENTITY_PACKET",
            },
        },
        "claim_boundary": (
            "This receipt seals one preregistered historical walk-forward simulation and its "
            "same-path diagnostics. It does not establish admission, live or future returns, "
            "capacity, diversification, book drawdown, independent replication, peer review, "
            "or external publication. Missing evidence is null or explicitly NOT_EVALUATED."
        ),
    }
    receipt["content_hash"] = _content_hash(receipt)
    receipt_bytes = json.dumps(receipt, indent=2, sort_keys=True).encode() + b"\n"
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()

    common_evidence = {
        "result_receipt": {
            "source_path": str(RESULT_RECEIPT),
            "public_path": "/glassbox/crypto_carry_portable_v1_result.json",
            "sha256": receipt_sha,
            "content_hash": receipt["content_hash"],
        },
        "preregistration": _binding(repo, "docs/design/PREREG_CRYPTO_CARRY_PORTABLE_V1.md"),
        "reservation": _binding(repo, str(RESERVATION)),
    }
    paper_exists = (repo / PAPER).is_file()
    closure: dict[str, Any] | None = None
    if (repo / CLOSURE).is_file():
        closure = _verified_hashed_json(
            repo / CLOSURE,
            "canli.alphac-crypto-carry-portable-admission-closure.v1",
        )
        if (
            closure.get("identity", {}).get("hypothesis_key") != IDENTITY
            or closure.get("decision", {}).get("disposition") != "INCOMPLETE"
            or closure.get("decision", {}).get("final_for_admission") is not True
            or closure.get("decision", {}).get("admitted") is not False
            or closure.get("decision", {}).get("killed") is not False
        ):
            raise ResultSealError("final admission closure overstates or misbinds the decision")
        closure_result = closure.get("lineage", {}).get("primary_result", {})
        if (
            closure_result.get("sha256") != receipt_sha
            or closure_result.get("content_hash") != receipt["content_hash"]
        ):
            raise ResultSealError("final admission closure does not bind this primary receipt")
        if not paper_exists or closure.get("lineage", {}).get("trial_paper", {}).get(
            "sha256"
        ) != _sha256(repo / PAPER):
            raise ResultSealError("final admission closure does not bind the current trial paper")
    final_closed = closure is not None
    missing_sections = (
        []
        if final_closed
        else [
            "result_uncertainty_stress_capacity_and_diversification",
            "admission_or_kill_decision",
        ]
    )
    if not paper_exists:
        missing_sections.insert(0, "machine_readable_packet_and_stable_public_paper")
    required_sections: dict[str, Any] = {
        section: {"status": "VERIFIED_IDENTITY_LEVEL_EVIDENCE", "evidence": []}
        for section in REQUIRED_SECTIONS
    }
    required_sections["identity_and_authorship"]["evidence"] = [common_evidence["reservation"]]
    required_sections["economic_mechanism_and_falsifiable_hypothesis"]["evidence"] = [
        common_evidence["preregistration"]
    ]
    required_sections["literature_and_overlap_decision"]["evidence"] = [
        _binding(repo, "docs/research/CRYPTO_CARRY_LINEAGE.md")
    ]
    required_sections["family_and_union_trial_accounting"]["evidence"] = [
        common_evidence["reservation"],
        {
            "source_path": str(LEDGER),
            "record_sha256": ledger["record_sha256"],
            "type": "immutable_ledger_record",
        },
    ]
    if paper_exists:
        required_sections["machine_readable_packet_and_stable_public_paper"]["evidence"] = [
            common_evidence["result_receipt"],
            {
                **_binding(repo, str(PAPER)),
                "public_path": "/research/crypto-carry-portable-v1",
            },
        ]
    else:
        required_sections["machine_readable_packet_and_stable_public_paper"] = {
            "status": "MISSING_STABLE_PUBLIC_PAPER",
            "evidence": [common_evidence["result_receipt"]],
        }
    required_sections["preregistration_and_hashes"]["evidence"] = [
        common_evidence["preregistration"],
        common_evidence["reservation"],
    ]
    required_sections["point_in_time_data_and_survivorship_controls"]["evidence"] = [
        receipt["lineage"]["input_snapshot"],
        _binding(repo, "artifacts/audit/crypto_carry_portable_lake_readiness.json"),
    ]
    required_sections["execution_and_cost_model"]["evidence"] = [
        common_evidence["preregistration"],
        _binding(repo, "scripts/run_crypto_carry_portable_v1.py"),
        common_evidence["result_receipt"],
    ]
    closure_evidence = (
        []
        if closure is None
        else [
            {
                **_binding(repo, str(CLOSURE), content_hash=closure["content_hash"]),
                "type": "final_incomplete_admission_closure",
            }
        ]
    )
    required_sections["result_uncertainty_stress_capacity_and_diversification"] = {
        "status": (
            "VERIFIED_FINAL_INCOMPLETE_WITH_HASH_BOUND_BLOCKERS"
            if final_closed
            else "PARTIAL_IDENTITY_LEVEL_EVIDENCE"
        ),
        "evidence": [common_evidence["result_receipt"], *closure_evidence],
        "unmeasured": gate_assessment["not_evaluated"],
        "unmeasured_values_treated_as_pass": False,
    }
    required_sections["admission_or_kill_decision"] = {
        "status": (
            "VERIFIED_FINAL_INCOMPLETE_NOT_ADMITTED"
            if final_closed
            else "PARTIAL_INCOMPLETE_DISPOSITION_NOT_FINAL_ADMISSION_OR_KILL"
        ),
        "evidence": [common_evidence["result_receipt"], *closure_evidence],
    }
    required_sections["code_environment_and_reproduction"]["evidence"] = [
        _binding(repo, "scripts/run_crypto_carry_portable_v1.py"),
        _binding(repo, "pyproject.toml"),
        _binding(repo, "uv.lock"),
        receipt["lineage"]["input_snapshot"],
    ]
    verified_sections = [
        section for section in REQUIRED_SECTIONS if section not in missing_sections
    ]
    packet: dict[str, Any] = {
        "schema": PACKET_SCHEMA,
        "author": "Arhan Canli",
        "evidence_date": "2026-08-24",
        "hypothesis_key": IDENTITY,
        "config_hash": run["config_hash"],
        "configuration": trial_config,
        "label": "crypto_carry_portable_v1",
        "research_family_key": "crypto_carry",
        "family_paper_public_path": "/research/crypto-carry-lineage.md",
        "trial_paper_public_path": "/research/crypto-carry-portable-v1",
        "complete": final_closed,
        "packet_status": (
            "COMPLETE_EVIDENCED_FINAL_INCOMPLETE_NOT_ADMITTED"
            if final_closed
            else "INCOMPLETE_FORWARD_PACKET_ADMISSION_EVIDENCE_REQUIRED"
        ),
        "missing_sections": missing_sections,
        "partial_sections": (
            []
            if final_closed
            else [
                "result_uncertainty_stress_capacity_and_diversification",
                "admission_or_kill_decision",
            ]
        ),
        "verified_sections": verified_sections,
        "required_sections": required_sections,
        "immutable_first_measurement": {
            "annualized_sharpe": record["sharpe_ann"],
            "observations": record["n_obs"],
            "skew": record["skew"],
            "kurtosis": record["kurtosis"],
            "recorded_at_unix_ms": record["now_ms"],
            "ledger_source_path": str(LEDGER),
            "ledger_record_sha256": ledger["record_sha256"],
        },
        "result_receipt": common_evidence["result_receipt"],
        "completion_assessment": (
            {
                "status": "COMPLETE_EVIDENCE_ACCOUNTING_FINAL_INCOMPLETE",
                "blockers": [],
                "disposition": "INCOMPLETE_NOT_ADMITTED",
                "candidate_evidence_complete_for_admission": False,
                "packet_evidence_accounting_complete": True,
                "next_forward_identity_blocked_by_this_packet": False,
            }
            if final_closed
            else {
                "status": "FORWARD_PACKET_BLOCKED_ON_PREREGISTERED_ADMISSION_EVIDENCE",
                "blockers": [
                    {
                        "code": "REQUIRED_V7_GATE_EVIDENCE_NOT_MEASURED",
                        "required_section": (
                            "result_uncertainty_stress_capacity_and_diversification"
                        ),
                        "missing": gate_assessment["not_evaluated"],
                    },
                    {
                        "code": "FINAL_ADMISSION_OR_KILL_DECISION_NOT_AVAILABLE",
                        "required_section": "admission_or_kill_decision",
                        "current_disposition": "INCOMPLETE_NOT_ADMITTED",
                    },
                ],
                "next_forward_identity_blocked": True,
            }
        ),
        "claim_boundary": (
            "This packet permanently accounts for the first measurement and final INCOMPLETE "
            "decision. Packet completeness means every section has measured evidence or a "
            "hash-bound blocker; it does not mean every gate was measured or passed. It is not "
            "an admission, KILL, live result, future-return claim, independent replication, "
            "external submission, DOI, or peer review."
        ),
    }
    packet["content_hash"] = _content_hash(packet)
    return receipt, packet


def _serialized(value: dict[str, Any]) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the deterministic artifacts")
    parser.add_argument("--check", action="store_true", help="require current artifacts to match")
    args = parser.parse_args()
    if args.write and args.check:
        raise SystemExit("choose either --write or --check")
    receipt, packet = build(ROOT)
    outputs = ((RESULT_RECEIPT, receipt), (PACKET, packet))
    if args.write:
        for relative, value in outputs:
            path = ROOT / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_serialized(value))
    elif args.check:
        for relative, value in outputs:
            path = ROOT / relative
            if not path.is_file() or path.read_bytes() != _serialized(value):
                raise ResultSealError(f"sealed artifact is stale or missing: {relative}")
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "disposition": receipt["disposition"]["value"],
                "admitted": receipt["disposition"]["admitted"],
                "packet_complete": packet["complete"],
                "missing_sections": packet["missing_sections"],
                "result_content_hash": receipt["content_hash"],
                "packet_content_hash": packet["content_hash"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
