#!/usr/bin/env python3
"""Publish evidence-backed reasons why audited historical packets remain incomplete."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Final

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion, config_hash
from alphaforge.validation.legacy_epoch import load_legacy_identity_keys

REPO: Final[Path] = Path(__file__).resolve().parent.parent
OUT: Final[Path] = REPO / "artifacts" / "research" / "identity_packet_recoverability.json"
LEGACY_EPOCH_CLOSURE: Final[Path] = (
    REPO / "artifacts" / "research" / "legacy_research_epoch_closure.json"
)
TRIAL_DEBT_RECONCILIATION: Final[Path] = (
    REPO / "artifacts" / "audit" / "trial_debt_reconciliation.json"
)
IDENTITY_EVIDENCE_BINDINGS: Final[Path] = REPO / "config" / "identity_trial_evidence_bindings.json"
DERIVED_CURVE_EVIDENCE_DIR: Final[Path] = (
    REPO / "artifacts" / "research" / "historical_curve_evidence"
)
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUT.name,
)
PREREG_COMMIT: Final[str] = "098deec4c283433cb2771884150f8d07e90713ee"
PREREG_CROSS_ASSET_TRIALS: Final[dict[str, str]] = {
    "4eb98b8f5dad412c": "prereg_momentum",
    "c6100630d688b4d7": "prereg_value",
    "97dec5f23e5fcf27": "prereg_quality",
    "cb54117502489bf8": "prereg_investment",
    "6c08c11a04ef43c5": "prereg_bab",
}
EXACT_REPLAY_CANDIDATES: Final[dict[str, str]] = {
    "1d2924f28fe31a9a": "single_gross_profitability",
    "a238c1a5ecc5d1e3": "single_book_to_price",
    "e86109044ab18734": "single_earnings_yield",
    "2d966892fb5db520": "single_sales_to_price",
    "e5f48adc25065ce9": "single_operating_margin",
}
FUNDAMENTAL_SINGLES_PREREG_COMMIT: Final[str] = "eefb04a10bc8e98981506667289aa66b206ec133"
OPERATING_MARGIN_IDENTITY: Final[str] = "e5f48adc25065ce9"
OPERATING_MARGIN_CORRECTED_DIR: Final[Path] = (
    REPO
    / "artifacts/probe/fundamental_single_replays"
    / OPERATING_MARGIN_IDENTITY
    / "corrected_corporate_actions_f812e1576bf430ee"
)
OPERATING_MARGIN_CORRECTED_SEAL: Final[Path] = (
    REPO / "artifacts/audit/operating_margin_corrected_reproduction.json"
)
FAMILY_AUDITS: Final[dict[str, str]] = {
    "alphatrend_family.json": "canli.alphac-alphatrend-family.v1",
    "crypto_defensive_family.json": "canli.alphac-crypto-defensive-family.v1",
    "crypto_momentum_family.json": "canli.alphac-crypto-momentum-family.v1",
    "crypto_multifactor_family.json": "canli.alphac-crypto-multifactor-family.v1",
    "crypto_reversal_family.json": "canli.alphac-crypto-short-horizon-reversal-family.v1",
    "equity_low_beta_family.json": "canli.alphac-equity-low-beta-family.v1",
    "equity_quality_family.json": "canli.alphac-equity-quality-family.v1",
    "equity_value_investment_family.json": ("canli.alphac-equity-value-investment-family.v1"),
    "macro_economic_trend_family.json": "canli.alphac-macro-economic-trend-family.v1",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _load_sealed_audit() -> dict[str, Any] | None:
    """Return the closure-bound audit once the legacy epoch has been retired."""
    if not LEGACY_EPOCH_CLOSURE.is_file():
        return None
    load_legacy_identity_keys(REPO)
    closure = json.loads(LEGACY_EPOCH_CLOSURE.read_text(encoding="utf-8"))
    binding = closure.get("source_bindings", {}).get("recoverability_audit", {})
    if binding.get("path") != str(OUT.relative_to(REPO)) or not OUT.is_file():
        raise ValueError("sealed legacy recoverability audit is missing")
    if sha256(OUT) != binding.get("sha256"):
        raise ValueError("sealed legacy recoverability audit file hash mismatch")
    payload: dict[str, Any] = json.loads(OUT.read_text(encoding="utf-8"))
    claimed = payload.pop("content_hash", None)
    observed = content_hash(payload)
    payload["content_hash"] = claimed
    if claimed != observed or claimed != binding.get("content_hash"):
        raise ValueError("sealed legacy recoverability audit content hash mismatch")
    if payload.get("summary", {}).get("union_identities_after_aborted_replay") != 228:
        raise ValueError("sealed legacy recoverability audit identity count mismatch")
    return payload


def commit_time(commit: str) -> dt.datetime:
    value = subprocess.check_output(
        ["git", "show", "-s", "--format=%cI", commit],
        cwd=REPO,
        text=True,
    ).strip()
    return dt.datetime.fromisoformat(value).astimezone(dt.UTC)


def first_records() -> dict[str, Any]:
    union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    records: dict[str, Any] = {}
    for path in union.paths:
        if not path.exists():
            continue
        ledger = ExperimentLog(path)
        for record in ledger.all():
            key = ledger._hypothesis_key(record.config)
            prior = records.get(key)
            if prior is None or (record.now_ms, record.config_hash) < (
                prior.now_ms,
                prior.config_hash,
            ):
                records[key] = record
    return records


def blocker(
    section: str,
    code: str,
    finding: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "required_section": section,
        "code": code,
        "finding": finding,
        "evidence": evidence,
    }


def build_audit() -> dict[str, Any]:
    sealed = _load_sealed_audit()
    if sealed is not None:
        return sealed
    records = first_records()
    insider_dir = REPO / "artifacts" / "probe" / "insider_purchase_clusters"
    insider_result_path = insider_dir / "result.json"
    insider_result = json.loads(insider_result_path.read_text())
    carry_path = REPO / "artifacts" / "walkforward" / "crypto_carry_wk" / "walkforward.json"
    carry = json.loads(carry_path.read_text())
    prereg_artifacts: dict[str, tuple[Path, dict[str, Any]]] = {}
    for identity, run_name in PREREG_CROSS_ASSET_TRIALS.items():
        path = REPO / "artifacts" / "walkforward" / run_name / "walkforward.json"
        prereg_artifacts[identity] = (path, json.loads(path.read_text()))
    runner_path = REPO / "src" / "alphaforge" / "analytics" / "walkforward.py"
    prereg_path = REPO / "docs" / "design" / "PRE_REGISTRATION.md"
    prereg_at = commit_time(PREREG_COMMIT)
    singles_prereg_at = commit_time(FUNDAMENTAL_SINGLES_PREREG_COMMIT)

    preliminary = records["7c522581b35475e3"]
    corrected = records["d614fdc1daa2906c"]
    carry_record = records["6d151a184bf3e743"]
    preliminary_sample = insider_result["implementation_correction"]["preliminary_net_sharpe"]
    preliminary_population = preliminary_sample * math.sqrt(
        preliminary.n_obs / (preliminary.n_obs - 1)
    )
    if not math.isclose(preliminary_population, preliminary.sharpe_ann, abs_tol=1e-12):
        raise ValueError("preliminary insider summary no longer reconciles to its ledger identity")
    reconciliation = insider_result["ledger_reconciliation"]
    if reconciliation["hypothesis_key"] != "d614fdc1daa2906c":
        raise ValueError("corrected insider replay points to the wrong ledger identity")
    if reconciliation["exact_first_measurement_reproduced"] is not False:
        raise ValueError("corrected insider replay unexpectedly claims an exact reproduction")
    if (
        carry["validation"]["n_obs"] != carry_record.n_obs
        or carry["validation"]["sr_ann"] != carry_record.sharpe_ann
    ):
        raise ValueError("crypto-carry artifact does not reconcile to its immutable measurement")
    prereg_evidence: dict[str, dict[str, Any]] = {}
    for identity, (path, artifact) in prereg_artifacts.items():
        record = records[identity]
        if config_hash(record.config) != record.config_hash:
            raise ValueError(f"{identity} ledger config hash does not reconcile")
        if any(artifact["config"].get(key) != value for key, value in record.config.items()):
            raise ValueError(f"{identity} artifact config does not reconcile to its ledger")
        if (
            artifact["validation"]["n_obs"] != record.n_obs
            or artifact["validation"]["sr_ann"] != record.sharpe_ann
        ):
            raise ValueError(f"{identity} artifact metrics do not reconcile to its ledger")
        non_equity = [
            item for item in artifact["config"]["instrument_ids"] if not item.startswith("XUSE:")
        ]
        if len(non_equity) != 60 or not all(
            item.startswith("BINANCE:PERP:") for item in non_equity
        ):
            raise ValueError(f"{identity} expected exactly 60 Binance perpetual ids")
        prereg_evidence[identity] = {
            "path": str(path.relative_to(REPO)),
            "sha256": sha256(path),
            "alpha_names": artifact["config"]["alpha_names"],
            "instrument_ids": len(artifact["config"]["instrument_ids"]),
            "non_equity_ids": len(non_equity),
            "ledger_config_hash": record.config_hash,
            "ledger_n_obs": record.n_obs,
            "ledger_sharpe_ann": record.sharpe_ann,
        }

    entries = {
        "7c522581b35475e3": {
            "config_hash": preliminary.config_hash,
            "status": "AUDITED_NOT_CURRENTLY_COMPLETABLE",
            "blockers": [
                blocker(
                    "result_uncertainty_stress_capacity_and_diversification",
                    "EXACT_PRELIMINARY_CURVE_NOT_PRESERVED",
                    "The correction log preserves the first Sharpe and verdict, but no exact "
                    "preliminary curve, weights, or executable snapshot was preserved.",
                    [
                        {
                            "path": str(insider_result_path.relative_to(REPO)),
                            "sha256": sha256(insider_result_path),
                        }
                    ],
                )
            ],
        },
        "d614fdc1daa2906c": {
            "config_hash": corrected.config_hash,
            "status": "AUDITED_NOT_CURRENTLY_COMPLETABLE",
            "blockers": [
                blocker(
                    "result_uncertainty_stress_capacity_and_diversification",
                    "CURRENT_REPLAY_EXTENDS_IMMUTABLE_WINDOW",
                    f"The current replay has {reconciliation['observation_delta']} additional "
                    "sessions and explicitly refuses exact-first-measurement status.",
                    [
                        {
                            "path": str(insider_result_path.relative_to(REPO)),
                            "sha256": sha256(insider_result_path),
                        }
                    ],
                )
            ],
        },
        "6d151a184bf3e743": {
            "config_hash": carry_record.config_hash,
            "status": "AUDITED_NOT_CURRENTLY_COMPLETABLE",
            "blockers": [
                blocker(
                    "preregistration_and_hashes",
                    "PREREGISTRATION_POSTDATES_FIRST_MEASUREMENT",
                    "The immutable first measurement predates the campaign preregistration "
                    "commit; the later document cannot be applied retroactively.",
                    [
                        {
                            "ledger_recorded_at": dt.datetime.fromtimestamp(
                                carry_record.now_ms / 1000,
                                tz=dt.UTC,
                            ).isoformat()
                        },
                        {
                            "commit": PREREG_COMMIT,
                            "committed_at": prereg_at.isoformat(),
                            "path": str(prereg_path.relative_to(REPO)),
                        },
                    ],
                ),
                blocker(
                    "code_environment_and_reproduction",
                    "ORIGINAL_RUN_LACKS_CODE_AND_ENVIRONMENT_STAMP",
                    "The exact result is preserved, but walkforward.json contains no Git SHA, "
                    "runner hash, lockfile hash, or input-data manifest for the original run.",
                    [{"path": str(carry_path.relative_to(REPO)), "sha256": sha256(carry_path)}],
                ),
                blocker(
                    "result_uncertainty_stress_capacity_and_diversification",
                    "CARRY_SPECIFIC_CAPACITY_UNMEASURED",
                    "The family paper correctly treats the later multi-factor capacity sweep as "
                    "context, not proof of carry-specific capacity.",
                    [
                        {
                            "path": "docs/research/CRYPTO_CARRY_LINEAGE.md",
                            "sha256": sha256(REPO / "docs/research/CRYPTO_CARRY_LINEAGE.md"),
                        }
                    ],
                ),
            ],
        },
    }
    for identity, run_name in PREREG_CROSS_ASSET_TRIALS.items():
        record = records[identity]
        entries[identity] = {
            "config_hash": record.config_hash,
            "status": "AUDITED_NOT_CURRENTLY_COMPLETABLE",
            "blockers": [
                blocker(
                    "code_environment_and_reproduction",
                    "CURRENT_ENGINE_REJECTS_LEGACY_CROSS_ASSET_UNIVERSE",
                    f"The frozen {run_name} artifact contains 60 Binance perpetuals in an "
                    "equity universe. Current code explicitly drops those ids under the "
                    "2026-07-18 shared-lake membership fix, so exact replay would require "
                    "reintroducing a known universe-membership error.",
                    [
                        prereg_evidence[identity],
                        {"path": str(runner_path.relative_to(REPO)), "sha256": sha256(runner_path)},
                    ],
                )
            ],
        }
    for identity, run_name in EXACT_REPLAY_CANDIDATES.items():
        path = REPO / "artifacts" / "walkforward" / run_name / "walkforward.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        record = records[identity]
        if config_hash(record.config) != record.config_hash or any(
            artifact["config"].get(key) != value for key, value in record.config.items()
        ):
            raise ValueError(f"{identity} replay-candidate config does not reconcile")
        if (
            artifact["validation"]["n_obs"] != record.n_obs
            or artifact["validation"]["sr_ann"] != record.sharpe_ann
        ):
            raise ValueError(f"{identity} replay-candidate metrics do not reconcile")
        ids = artifact["config"]["instrument_ids"]
        if len(ids) != 6_820 or any(not item.startswith("XUSE:") for item in ids):
            raise ValueError(f"{identity} is not the corrected 6,820-id equity universe")
        measured_at = dt.datetime.fromtimestamp(record.now_ms / 1000, tz=dt.UTC)
        if singles_prereg_at >= measured_at:
            raise ValueError(f"{identity} measurement does not postdate its preregistration")
        replay_evidence = [
            {
                "path": str(path.relative_to(REPO)),
                "sha256": sha256(path),
                "instrument_ids": len(ids),
                "non_equity_ids": 0,
                "ledger_n_obs": record.n_obs,
                "ledger_sharpe_ann": record.sharpe_ann,
            },
            {
                "commit": FUNDAMENTAL_SINGLES_PREREG_COMMIT,
                "committed_at": singles_prereg_at.isoformat(),
                "measured_at": measured_at.isoformat(),
            },
        ]
        blockers = [
            blocker(
                "code_environment_and_reproduction",
                "EXACT_CURRENT_ENGINE_REPLAY_PENDING",
                "The preserved corrected-universe result is exactly bound to the immutable "
                "ledger and its preregistration predates measurement, but a current-engine "
                "equity-curve replay has not yet completed.",
                replay_evidence,
            )
        ]
        support_dir = REPO / "artifacts" / "probe" / "fundamental_single_replays" / identity
        replay_succeeded_with_support = (support_dir / "result.json").exists()
        replay_failed_with_support = (support_dir / "replay_failure.json").exists()
        replay_failure_status: str | None = None
        if replay_succeeded_with_support and replay_failed_with_support:
            raise ValueError(f"{identity} cannot be both a successful and data-failed replay")
        if replay_succeeded_with_support or replay_failed_with_support:
            support_specs = {
                "curve_evidence.json": "canli.alphac-fundamental-single-curve-evidence.v1",
                "diversification.json": "canli.alphac-canonical-diversification.v1",
                "input_data_manifest.json": ("canli.alphac-fundamental-single-input-manifest.v1"),
                "market_evidence.json": ("canli.alphac-fundamental-single-market-evidence.v1"),
                "replay_environment.json": "canli.alphac-replay-source-environment.v1",
            }
            if replay_succeeded_with_support:
                support_specs["result.json"] = "canli.alphac-fundamental-single-exact-replay.v1"
            else:
                replay_failure = json.loads(
                    (support_dir / "replay_failure.json").read_text(encoding="utf-8")
                )
                failure_schema = replay_failure.get("schema")
                if failure_schema not in {
                    "canli.alphac-fundamental-single-replay-failure.v1",
                    "canli.alphac-fundamental-single-replay-divergence.v1",
                }:
                    raise ValueError(f"{identity} unexpected replay failure schema")
                support_specs["replay_failure.json"] = failure_schema
                if failure_schema == "canli.alphac-fundamental-single-replay-divergence.v1":
                    support_specs["replay_root_cause.json"] = (
                        "canli.alphac-operating-margin-replay-root-cause.v1"
                    )
            for filename, schema in support_specs.items():
                support_path = support_dir / filename
                support = json.loads(support_path.read_text(encoding="utf-8"))
                if support.get("schema") != schema:
                    raise ValueError(f"{identity} unexpected support schema: {filename}")
                bound_identity = support.get(
                    "return_identity_id" if filename == "diversification.json" else "hypothesis_key"
                )
                if filename != "replay_environment.json" and bound_identity != identity:
                    raise ValueError(f"{identity} support is bound to another identity")
                replay_evidence.append(
                    {
                        "path": str(support_path.relative_to(REPO)),
                        "sha256": sha256(support_path),
                        "public_path": (
                            "/glassbox/fundamental_single_"
                            + run_name.removeprefix("single_")
                            + "_"
                            + filename
                        ),
                    }
                )
            input_manifest = json.loads(
                (support_dir / "input_data_manifest.json").read_text(encoding="utf-8")
            )
            market = json.loads((support_dir / "market_evidence.json").read_text(encoding="utf-8"))
            if input_manifest["summary"]["partition_files"] != 223_185:
                raise ValueError(f"{identity} replay input snapshot count changed")
            capacity = market.get("capacity", {})
            p05_capacity = capacity.get("p05_usd_at_1pct_adv")
            if (
                capacity.get("missing_adv_treatment") != "ZERO_CAPACITY_FAIL_CLOSED"
                or int(capacity.get("fills_missing_point_in_time_adv", 0)) <= 0
                or not isinstance(p05_capacity, (int, float))
                or not math.isfinite(float(p05_capacity))
                or float(p05_capacity) < 0.0
            ):
                raise ValueError(f"{identity} replay capacity does not fail closed on missing ADV")
            if replay_succeeded_with_support:
                result = json.loads((support_dir / "result.json").read_text(encoding="utf-8"))
                if (
                    result.get("hypothesis_key") != identity
                    or result.get("verdict") != "KILL"
                    or result.get("exact_first_measurement_reproduced") is not True
                    or result.get("hypotheses_spent") != 0
                    or result.get("immutable_measurement", {}).get("n_obs") != record.n_obs
                    or result.get("immutable_measurement", {}).get("annualized_sharpe")
                    != record.sharpe_ann
                ):
                    raise ValueError(f"{identity} successful replay does not bind the ledger")
                blockers = []
            else:
                replay_failure = json.loads(
                    (support_dir / "replay_failure.json").read_text(encoding="utf-8")
                )
                if (
                    replay_failure.get("status") != "FAILED_CLOSED"
                    or replay_failure.get("packet_status") != "INCOMPLETE"
                ):
                    raise ValueError(f"{identity} replay failure evidence no longer fails closed")
                if replay_failure.get("decision") == "INVALID_CORPORATE_ACTION_SOURCE_ROW":
                    if replay_failure.get("evidence", {}).get("replay_outputs_present") != {
                        "equity.parquet": False,
                        "result.json": False,
                        "walkforward.json": False,
                    }:
                        raise ValueError(f"{identity} data-quality failure output claim changed")
                    replay_failure_status = "AUDITED_EXACT_REPLAY_FAILED_DATA_QUALITY"
                    blockers[0]["code"] = "EXACT_CURRENT_ENGINE_REPLAY_FAILED_DATA_QUALITY"
                    blockers[0]["finding"] = (
                        "The input snapshot, curve uncertainty, canonical diversification, "
                        "execution stress, capacity, and source environment are complete. The "
                        "exact replay failed closed on the sole non-positive dividend row in the "
                        "current Sharadar corporate-action lake; no result or equity curve was "
                        "produced."
                    )
                elif replay_failure.get("decision") == "EXACT_REPRODUCTION_FAILED":
                    comparison = replay_failure.get("comparison", {})
                    diagnostic = replay_failure.get("quarantined_replay_diagnostic", {})
                    immutable = replay_failure.get("immutable_first_measurement", {})
                    if (
                        replay_failure.get("exact_first_measurement_reproduced") is not False
                        or replay_failure.get("hypotheses_spent") != 0
                        or int(comparison.get("equity_mismatch_count", 0)) <= 0
                        or comparison.get("summary_equal") is not False
                        or diagnostic.get("eligible_for_admission") is not False
                        or immutable.get("annualized_sharpe") != record.sharpe_ann
                    ):
                        raise ValueError(f"{identity} divergence failure is not fail-closed")
                    root_cause = json.loads(
                        (support_dir / "replay_root_cause.json").read_text(encoding="utf-8")
                    )
                    if (
                        root_cause.get("status") != "ROOT_CAUSE_ESTABLISHED_REPLAY_REMAINS_INVALID"
                        or root_cause.get("decision")
                        != "CURRENT_REPLAY_CONTAMINATED_BY_UNVERIFIED_DIVIDEND_UNITS"
                        or root_cause.get("hypotheses_spent") != 0
                        or root_cause.get("evidence", {}).get("dividend_consistency_content_hash")
                        != "sha256:57d11336c0c7daca85ea3332b46461c3cad48562fd35f6aea02b96fd320a3510"
                    ):
                        raise ValueError(f"{identity} replay root cause is not sealed")
                    if (
                        identity == OPERATING_MARGIN_IDENTITY
                        and OPERATING_MARGIN_CORRECTED_SEAL.exists()
                    ):
                        corrected_result_path = OPERATING_MARGIN_CORRECTED_DIR / "result.json"
                        corrected_environment_path = (
                            OPERATING_MARGIN_CORRECTED_DIR / "replay_environment.json"
                        )
                        corrected_equity_path = OPERATING_MARGIN_CORRECTED_DIR / "equity.parquet"
                        corrected = json.loads(corrected_result_path.read_text(encoding="utf-8"))
                        corrected_environment = json.loads(
                            corrected_environment_path.read_text(encoding="utf-8")
                        )
                        corrected_seal = json.loads(
                            OPERATING_MARGIN_CORRECTED_SEAL.read_text(encoding="utf-8")
                        )
                        seal_unhashed = {
                            name: value
                            for name, value in corrected_seal.items()
                            if name != "content_hash"
                        }
                        if (
                            corrected.get("schema")
                            != "canli.alphac-fundamental-single-corrected-reproduction.v1"
                            or corrected.get("hypothesis_key") != identity
                            or corrected.get("config_hash") != record.config_hash
                            or corrected.get("verdict") != "KILL"
                            or corrected.get("corrected_data_reproduction") is not True
                            or corrected.get("exact_first_measurement_reproduced") is not False
                            or corrected.get("hypotheses_spent") != 0
                            or corrected.get("corrected_measurement", {}).get("sharpe", 1.0) >= 0.0
                            or corrected.get("corrected_measurement", {}).get("total_return", 1.0)
                            >= 0.0
                            or corrected.get("immutable_measurement", {}).get("annualized_sharpe")
                            != record.sharpe_ann
                            or corrected_environment.get("schema")
                            != "canli.alphac-replay-source-environment.v1"
                            or corrected_environment.get("content_hash")
                            != content_hash(
                                {
                                    name: value
                                    for name, value in corrected_environment.items()
                                    if name != "content_hash"
                                }
                            )
                            or corrected_seal.get("schema")
                            != "canli.alphac-operating-margin-corrected-reproduction-seal.v1"
                            or corrected_seal.get("decision")
                            != "CORRECTED_OPERATING_MARGIN_REPRODUCED_KILL_PRESERVED"
                            or corrected_seal.get("hypotheses_spent") != 0
                            or corrected_seal.get("content_hash") != content_hash(seal_unhashed)
                            or corrected_seal.get("lineage", {}).get("result_sha256")
                            != sha256(corrected_result_path)
                            or corrected_seal.get("lineage", {}).get("environment_sha256")
                            != sha256(corrected_environment_path)
                            or corrected_seal.get("lineage", {}).get("equity_sha256")
                            != sha256(corrected_equity_path)
                        ):
                            raise ValueError(
                                f"{identity} corrected reproduction seal does not reconcile"
                            )
                        corrected_evidence = [
                            {
                                "path": str(OPERATING_MARGIN_CORRECTED_SEAL.relative_to(REPO)),
                                "sha256": sha256(OPERATING_MARGIN_CORRECTED_SEAL),
                                "public_path": (
                                    "/glassbox/operating_margin_corrected_reproduction.json"
                                ),
                            },
                            {
                                "path": str(corrected_result_path.relative_to(REPO)),
                                "sha256": sha256(corrected_result_path),
                            },
                            {
                                "path": str(corrected_environment_path.relative_to(REPO)),
                                "sha256": sha256(corrected_environment_path),
                            },
                            {
                                "path": str(corrected_equity_path.relative_to(REPO)),
                                "sha256": sha256(corrected_equity_path),
                            },
                        ]
                        replay_failure_status = "AUDITED_CORRECTED_REPRODUCTION_KILL_PRESERVED"
                        blockers = [
                            blocker(
                                "execution_and_cost_model",
                                "CORRECTED_REPLAY_EXECUTION_STRESS_NOT_PRESERVED",
                                "The corrected replay records fees and turnover, but no "
                                "fill-level corrected execution receipt or 2x-cost stress was "
                                "preserved. The section remains incomplete.",
                                corrected_evidence,
                            ),
                            blocker(
                                "result_uncertainty_stress_capacity_and_diversification",
                                "CORRECTED_REPLAY_RISK_AND_DIVERSIFICATION_PACKET_PENDING",
                                "The corrected equity curve and negative KILL result are sealed, "
                                "but corrected DSR/PSR, block-bootstrap diversification, and "
                                "fail-closed capacity evidence are not preserved.",
                                corrected_evidence,
                            ),
                        ]
                    else:
                        replay_failure_status = "AUDITED_EXACT_REPLAY_FAILED_REPRODUCTION"
                        blockers[0]["code"] = "EXACT_CURRENT_ENGINE_REPLAY_DIVERGED"
                        blockers[0]["finding"] = (
                            "The corrected-data/current-code replay completed, but its summary "
                            "and 5,383 of 5,385 equity values differ from the immutable first "
                            "measurement. The exact first mismatch is a newly applied dividend, "
                            "and a systemic audit proves unverified dividend units contaminate "
                            "the replay. The output remains quarantined and ineligible for "
                            "admission."
                        )
                else:
                    raise ValueError(f"{identity} unrecognized replay failure decision")
        else:
            blockers.extend(
                [
                    blocker(
                        "point_in_time_data_and_survivorship_controls",
                        "IDENTITY_LEVEL_DATA_MANIFEST_PENDING",
                        "An identity-level manifest of every replay input partition is still "
                        "needed.",
                        [{"path": str(path.relative_to(REPO)), "sha256": sha256(path)}],
                    ),
                    blocker(
                        "result_uncertainty_stress_capacity_and_diversification",
                        "CAPACITY_AND_DIVERSIFICATION_PENDING",
                        "The preserved result has uncertainty and drawdown statistics, but an "
                        "identity-specific capacity sweep and canonical diversification report "
                        "are still required.",
                        [{"path": str(path.relative_to(REPO)), "sha256": sha256(path)}],
                    ),
                ]
            )
        entries[identity] = {
            "config_hash": record.config_hash,
            "status": (
                "AUDITED_CURRENTLY_COMPLETABLE"
                if replay_succeeded_with_support
                else replay_failure_status
                if replay_failed_with_support
                else "AUDITED_EXACT_REPLAY_CANDIDATE"
            ),
            "blockers": blockers,
        }
    family_audit_dir = REPO / "artifacts" / "research"
    for filename, expected_schema in FAMILY_AUDITS.items():
        family_path = family_audit_dir / filename
        family = json.loads(family_path.read_text(encoding="utf-8"))
        if family.get("schema") != expected_schema:
            raise ValueError(f"unexpected family-audit schema: {filename}")
        family_sha256 = sha256(family_path)
        summary = family.get("summary", {})
        identities = family.get("identities")
        if not isinstance(identities, list) or summary.get("distinct_hypothesis_identities") != len(
            identities
        ):
            raise ValueError(f"family-audit identity count mismatch: {filename}")
        for item in identities:
            identity = item.get("hypothesis_key")
            if not isinstance(identity, str) or identity not in records:
                raise ValueError(f"family audit contains an unknown identity: {filename}")
            record = records[identity]
            if item.get("config_hash") != record.config_hash:
                raise ValueError(f"family audit config does not reconcile: {identity}")
            if identity in entries:
                continue
            ledger_path = REPO / str(item.get("ledger_source_path"))
            if not ledger_path.is_file():
                raise ValueError(f"family audit ledger source is missing: {identity}")
            declared_ledger_hash = item.get("ledger_source_sha256")
            if declared_ledger_hash is not None and declared_ledger_hash != sha256(ledger_path):
                raise ValueError(f"family audit ledger hash mismatch: {identity}")
            evidence = [
                {"path": str(family_path.relative_to(REPO)), "sha256": family_sha256},
                {"path": str(ledger_path.relative_to(REPO)), "sha256": sha256(ledger_path)},
            ]
            artifact_path_value = item.get("artifact_path")
            if isinstance(artifact_path_value, str):
                artifact_path = REPO / artifact_path_value
                if not artifact_path.is_file() or item.get("artifact_sha256") != sha256(
                    artifact_path
                ):
                    raise ValueError(f"family audit artifact hash mismatch: {identity}")
                evidence.append({"path": artifact_path_value, "sha256": sha256(artifact_path)})
            evidence_grade = str(item.get("evidence_grade", "artifact_bound"))
            blockers = [
                blocker(
                    "preregistration_and_hashes",
                    "IDENTITY_PREREGISTRATION_AND_ORIGINAL_ENVIRONMENT_NOT_BOUND",
                    "The canonical family audit binds this identity to its immutable ledger "
                    "measurement, but does not bind an identity-level preregistration, original "
                    "code commit, runner hash, lockfile, and input snapshot. Those missing "
                    "historical fields cannot be reconstructed from the family summary.",
                    evidence,
                ),
                blocker(
                    "admission_or_kill_decision",
                    "IDENTITY_LEVEL_DECISION_PACKET_NOT_PRESERVED",
                    f"The family-level admission status is {summary.get('admission_status')}; "
                    "it is not a preserved identity-level gate decision under the complete "
                    "packet contract.",
                    evidence[:1],
                ),
            ]
            if "summary" in evidence_grade:
                blockers.append(
                    blocker(
                        "result_uncertainty_stress_capacity_and_diversification",
                        "IMMUTABLE_SUMMARY_LACKS_COMPLETE_IDENTITY_CURVE",
                        "The immutable ledger summary preserves the first measurement but not "
                        "the complete identity-level curve, uncertainty, stress, capacity, and "
                        "diversification evidence required for packet completion.",
                        evidence,
                    )
                )
            capacity_status = summary.get("capacity_status")
            if isinstance(capacity_status, str) and "UNMEASURED" in capacity_status:
                blockers.append(
                    blocker(
                        "result_uncertainty_stress_capacity_and_diversification",
                        "IDENTITY_CAPACITY_NOT_MEASURED",
                        f"The canonical family audit records capacity as {capacity_status}; no "
                        "identity-level capacity evidence can be credited.",
                        evidence[:1],
                    )
                )
            entries[identity] = {
                "config_hash": record.config_hash,
                "status": "AUDITED_NOT_CURRENTLY_COMPLETABLE",
                "family_audit": str(family_path.relative_to(REPO)),
                "evidence_grade": evidence_grade,
                "blockers": blockers,
            }
    reconciliation = json.loads(TRIAL_DEBT_RECONCILIATION.read_text(encoding="utf-8"))
    if (
        reconciliation.get("schema") != "alphac.trial-debt-reconciliation.v2"
        or reconciliation.get("applied") is not True
        or reconciliation.get("candidate_records") != 78
        or len(reconciliation.get("records", [])) != 78
        or sum(item.get("charged_identities", 0) for item in reconciliation.get("sources", []))
        != 78
    ):
        raise ValueError("trial-debt reconciliation is not the sealed 78-record receipt")
    source_grades: dict[str, str] = {}
    for source in reconciliation["sources"]:
        source_path = REPO / source["path"]
        if not source_path.is_file() or source.get("sha256") != sha256(source_path):
            raise ValueError(f"trial-debt source hash mismatch: {source.get('path')}")
        source_grades[str(source["path"])] = str(source["evidence_grade"])
    records_by_config_hash: dict[str, tuple[str, Any]] = {}
    for identity, record in records.items():
        if record.config_hash in records_by_config_hash:
            raise ValueError(f"duplicate first-record config hash: {record.config_hash}")
        records_by_config_hash[record.config_hash] = (identity, record)
    receipt_sha256 = sha256(TRIAL_DEBT_RECONCILIATION)
    for forensic in reconciliation["records"]:
        config_hash_value = forensic.get("config_hash")
        if config_hash_value not in records_by_config_hash:
            raise ValueError(f"reconciled config is absent from the union: {config_hash_value}")
        identity, record = records_by_config_hash[config_hash_value]
        if identity in entries:
            continue
        source_value = forensic.get("source")
        if not isinstance(source_value, str):
            raise ValueError(f"reconciled identity lacks a source path: {identity}")
        source_path = REPO / source_value
        if not source_path.is_file():
            raise ValueError(f"reconciled identity source is missing: {identity}")
        embedded_source_hash = record.config.get("source_artifact_sha256")
        if embedded_source_hash is not None and embedded_source_hash != sha256(source_path):
            raise ValueError(f"reconciled identity embedded source hash mismatch: {identity}")
        evidence_grade = next(
            (
                grade
                for path, grade in source_grades.items()
                if source_value == path or source_value.startswith(str(Path(path).parent) + "/")
            ),
            None,
        )
        if evidence_grade is None:
            raise ValueError(f"reconciled identity has no declared evidence grade: {identity}")
        evidence = [
            {
                "path": str(TRIAL_DEBT_RECONCILIATION.relative_to(REPO)),
                "sha256": receipt_sha256,
            },
            {"path": source_value, "sha256": sha256(source_path)},
        ]
        blockers = [
            blocker(
                "preregistration_and_hashes",
                "FORENSIC_ACCOUNTING_POSTDATES_ORIGINAL_MEASUREMENT",
                "This identity was recovered by the 2026-08-17 forensic accounting correction. "
                "The receipt charges the historical configuration but cannot retroactively prove "
                "an identity-level preregistration or original environment stamp.",
                evidence,
            ),
            blocker(
                "admission_or_kill_decision",
                "ORIGINAL_IDENTITY_GATE_DECISION_NOT_PRESERVED",
                "The source preserves a historical measurement, not a complete identity-level "
                "admission or kill packet under the current contract.",
                evidence,
            ),
        ]
        if forensic.get("kind") == "summary_only_screen":
            blockers.append(
                blocker(
                    "result_uncertainty_stress_capacity_and_diversification",
                    "FORENSIC_SOURCE_IS_SUMMARY_ONLY",
                    f"The declared evidence grade is {evidence_grade}. The exact daily curve and "
                    "complete uncertainty, stress, capacity, and diversification evidence are "
                    "not preserved by this source.",
                    evidence,
                )
            )
        elif forensic.get("kind") == "complete_walkforward":
            blockers.append(
                blocker(
                    "result_uncertainty_stress_capacity_and_diversification",
                    "FORENSIC_CURVE_LACKS_COMPLETE_PACKET_STRESS_EVIDENCE",
                    "The walk-forward curve and configuration are preserved, but the forensic "
                    "receipt does not bind identity-level capacity, canonical diversification, "
                    "or every stress result required by the current packet contract.",
                    evidence,
                )
            )
        else:
            raise ValueError(f"reconciled identity has an unknown evidence kind: {identity}")
        entries[identity] = {
            "config_hash": record.config_hash,
            "status": "AUDITED_NOT_CURRENTLY_COMPLETABLE",
            "forensic_reconciliation": str(TRIAL_DEBT_RECONCILIATION.relative_to(REPO)),
            "evidence_grade": evidence_grade,
            "blockers": blockers,
        }
    binding_payload = json.loads(IDENTITY_EVIDENCE_BINDINGS.read_text(encoding="utf-8"))
    if binding_payload.get("schema") != "canli.alphac-identity-trial-evidence-bindings.v1":
        raise ValueError("identity evidence bindings schema mismatch")
    complete_binding_identities = {
        identity
        for identity, binding in binding_payload.get("bindings", {}).items()
        if binding.get("packet_completion_expected", True)
    }
    if not complete_binding_identities <= set(records):
        raise ValueError("identity evidence bindings contain an unknown union identity")
    if complete_binding_identities & set(entries):
        raise ValueError("a complete identity binding also appears in recoverability debt")

    ledger_source_by_config_hash: dict[str, Path] = {}
    for ledger_path in ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO).paths:
        if not ledger_path.exists():
            continue
        for ledger_record in ExperimentLog(ledger_path).all():
            ledger_source_by_config_hash.setdefault(ledger_record.config_hash, ledger_path)

    walkforward_artifacts: list[dict[str, Any]] = []
    walkforward_corpus: list[dict[str, str]] = []
    for path in sorted((REPO / "artifacts").rglob("walkforward.json")):
        if path.is_relative_to(DERIVED_CURVE_EVIDENCE_DIR):
            continue
        relative = str(path.relative_to(REPO))
        artifact_sha256 = sha256(path)
        walkforward_corpus.append({"path": relative, "sha256": artifact_sha256})
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(artifact, dict) or not isinstance(artifact.get("validation"), dict):
            continue
        config = artifact.get("trial_config") or artifact.get("config") or {}
        validation = artifact["validation"]
        if (
            not isinstance(config, dict)
            or not isinstance(validation.get("sr_ann"), (int, float))
            or not isinstance(validation.get("n_obs"), int)
        ):
            continue
        equity_path = path.parent / "equity.parquet"
        walkforward_artifacts.append(
            {
                "path": path,
                "relative_path": relative,
                "sha256": artifact_sha256,
                "config": config,
                "annualized_sharpe": validation["sr_ann"],
                "observations": validation["n_obs"],
                "equity_path": equity_path if equity_path.is_file() else None,
                "top_level_keys": set(artifact),
            }
        )
    walkforward_corpus_hash = content_hash({"files": walkforward_corpus})
    systematic_counts = {
        "UNIQUE_EXACT_ARTIFACT_BINDING": 0,
        "AMBIGUOUS_EXACT_ARTIFACT_MATCHES": 0,
        "LEDGER_SUMMARY_ONLY_NO_ARTIFACT_MATCH": 0,
        "METRIC_MATCH_CONFIG_MISMATCH": 0,
    }
    for identity, record in records.items():
        if identity in entries or identity in complete_binding_identities:
            continue
        alpha_names = record.config.get("alpha_names")
        metric_matches = [
            artifact
            for artifact in walkforward_artifacts
            if artifact["annualized_sharpe"] == record.sharpe_ann
            and artifact["observations"] == record.n_obs
            and artifact["config"].get("alpha_names") == alpha_names
        ]
        exact_matches = [
            artifact
            for artifact in metric_matches
            if all(
                artifact["config"].get(key, "<MISSING>") == value
                for key, value in record.config.items()
            )
        ]
        if len(exact_matches) == 1:
            classification = "UNIQUE_EXACT_ARTIFACT_BINDING"
            selected = exact_matches[0]
            if selected["equity_path"] is None:
                raise ValueError(f"unique exact artifact lacks its equity curve: {identity}")
            forbidden_environment_fields = {
                "code_commit",
                "git_sha",
                "input_manifest_sha256",
                "lockfile_sha256",
                "runner_sha256",
            }
            if forbidden_environment_fields.intersection(
                set(selected["config"]) | selected["top_level_keys"]
            ):
                raise ValueError(
                    f"{identity} unexpectedly gained environment fields; audit it explicitly"
                )
            ledger_path = ledger_source_by_config_hash[record.config_hash]
            evidence = [
                {
                    "path": selected["relative_path"],
                    "sha256": selected["sha256"],
                },
                {
                    "path": str(selected["equity_path"].relative_to(REPO)),
                    "sha256": sha256(selected["equity_path"]),
                },
                {
                    "path": str(ledger_path.relative_to(REPO)),
                    "sha256": sha256(ledger_path),
                    "config_hash": record.config_hash,
                },
            ]
            source_blocker = blocker(
                "code_environment_and_reproduction",
                "EXACT_ARTIFACT_LACKS_ORIGINAL_ENVIRONMENT_STAMP",
                "One persisted walk-forward artifact and equity curve uniquely match every "
                "identity-bearing ledger field and the immutable measurement. The artifact does "
                "not preserve the original code commit, runner hash, lockfile, and input manifest.",
                evidence,
            )
        elif len(exact_matches) > 1:
            classification = "AMBIGUOUS_EXACT_ARTIFACT_MATCHES"
            evidence = [
                {"path": item["relative_path"], "sha256": item["sha256"]} for item in exact_matches
            ]
            source_blocker = blocker(
                "code_environment_and_reproduction",
                "MULTIPLE_BYTE_DISTINCT_ARTIFACTS_MATCH_IDENTITY",
                f"{len(exact_matches)} byte-distinct walk-forward artifacts match every ledger "
                "identity field and immutable measurement. The original source cannot be selected "
                "without inventing lineage.",
                evidence,
            )
        elif metric_matches:
            classification = "METRIC_MATCH_CONFIG_MISMATCH"
            evidence = [
                {"path": item["relative_path"], "sha256": item["sha256"]} for item in metric_matches
            ]
            source_blocker = blocker(
                "code_environment_and_reproduction",
                "METRIC_MATCHES_BUT_IDENTITY_CONFIG_DIFFERS",
                f"{len(metric_matches)} artifact(s) match the alpha list and immutable "
                "measurement, "
                "but none preserve every identity-bearing ledger field. Metric equality cannot "
                "repair a configuration-lineage mismatch.",
                evidence,
            )
        else:
            classification = "LEDGER_SUMMARY_ONLY_NO_ARTIFACT_MATCH"
            ledger_path = ledger_source_by_config_hash[record.config_hash]
            evidence = [
                {"path": str(ledger_path.relative_to(REPO)), "sha256": sha256(ledger_path)},
                {
                    "walkforward_corpus_hash": walkforward_corpus_hash,
                    "walkforward_files_scanned": len(walkforward_corpus),
                },
            ]
            source_blocker = blocker(
                "result_uncertainty_stress_capacity_and_diversification",
                "NO_MATCHING_PERSISTED_WALKFORWARD_ARTIFACT",
                "The immutable ledger summary is preserved, but no walk-forward artifact in the "
                "declared byte-hashed corpus matches its alpha list, observation count, and exact "
                "annualized Sharpe. The missing curve cannot be reconstructed.",
                evidence,
            )
        systematic_counts[classification] += 1
        entries[identity] = {
            "config_hash": record.config_hash,
            "status": "AUDITED_NOT_CURRENTLY_COMPLETABLE",
            "artifact_recoverability_class": classification,
            "walkforward_corpus_hash": walkforward_corpus_hash,
            "blockers": [
                source_blocker,
                blocker(
                    "preregistration_and_hashes",
                    "IDENTITY_PREREGISTRATION_NOT_PRESERVED",
                    "No identity-level preregistration and immutable pre-result hash are bound to "
                    "this historical measurement.",
                    evidence[:1],
                ),
                blocker(
                    "admission_or_kill_decision",
                    "IDENTITY_LEVEL_DECISION_PACKET_NOT_PRESERVED",
                    "No complete identity-level admission or kill packet under the current "
                    "contract is preserved for this historical measurement.",
                    evidence[:1],
                ),
            ],
        }
    if set(entries) | complete_binding_identities != set(records):
        raise ValueError("recoverability audit does not account for every union identity")
    payload: dict[str, Any] = {
        "schema": "canli.alphac-identity-packet-recoverability.v1",
        "evidence_date": "2026-08-22",
        "claim_boundary": (
            "AUDITED_NOT_CURRENTLY_COMPLETABLE describes missing historical proof, not strategy "
            "quality. It may be revised only if stronger archived evidence is recovered."
        ),
        "summary": {
            "audited_identities": len(entries),
            "audited_currently_completable": sum(
                item["status"] == "AUDITED_CURRENTLY_COMPLETABLE" for item in entries.values()
            ),
            "audited_exact_replay_candidates": sum(
                item["status"] == "AUDITED_EXACT_REPLAY_CANDIDATE" for item in entries.values()
            ),
            "audited_exact_replays_failed_data_quality": sum(
                item["status"] == "AUDITED_EXACT_REPLAY_FAILED_DATA_QUALITY"
                for item in entries.values()
            ),
            "audited_exact_replays_failed_reproduction": sum(
                item["status"] == "AUDITED_EXACT_REPLAY_FAILED_REPRODUCTION"
                for item in entries.values()
            ),
            "audited_corrected_reproductions_kill_preserved": sum(
                item["status"] == "AUDITED_CORRECTED_REPRODUCTION_KILL_PRESERVED"
                for item in entries.values()
            ),
            "failed_replays_with_support_evidence_complete": sum(
                item["status"]
                in {
                    "AUDITED_EXACT_REPLAY_FAILED_DATA_QUALITY",
                    "AUDITED_EXACT_REPLAY_FAILED_REPRODUCTION",
                }
                for item in entries.values()
            ),
            "union_identities_after_aborted_replay": len(records),
            "walkforward_artifacts_indexed": len(walkforward_corpus),
            "walkforward_corpus_hash": walkforward_corpus_hash,
            "systematic_recoverability_classes": systematic_counts,
        },
        "identities": entries,
    }
    payload["content_hash"] = content_hash(payload)
    return payload


def main() -> int:
    payload = build_audit()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered)
    for path in HOSTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)
    print(f"identity packet recoverability: {payload['summary']['audited_identities']} audited")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
