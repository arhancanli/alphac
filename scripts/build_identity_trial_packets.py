#!/usr/bin/env python3
"""Publish one deterministic, fail-closed evidence packet per hypothesis identity."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion

REPO: Final[Path] = Path(__file__).resolve().parent.parent
ARTIFACT_DIR: Final[Path] = REPO / "artifacts" / "research" / "trial_packets"
LEGACY_EPOCH_CLOSURE: Final[Path] = (
    REPO / "artifacts" / "research" / "legacy_research_epoch_closure.json"
)
CURVE_EVIDENCE_DIR: Final[Path] = (
    REPO / "artifacts" / "research" / "historical_curve_evidence"
)
EVIDENCE_BINDINGS: Final[Path] = REPO / "config" / "identity_trial_evidence_bindings.json"
LEGACY_ADMISSION_CONTRACT: Final[Path] = (
    REPO / "config" / "archive" / "sleeve_admission_contract_v6_superseded.json"
)
HOST_DIRS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / "trial-packets",
    REPO.parent / "meridian-app" / "public" / "glassbox" / "trial-packets",
)
INDEX_NAME: Final[str] = "index.json"


def _manifest_module() -> ModuleType:
    path = REPO / "scripts" / "build_trial_packet_manifest.py"
    spec = importlib.util.spec_from_file_location("trial_packet_manifest_contract", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recoverability_module() -> ModuleType:
    path = REPO / "scripts" / "audit_identity_packet_recoverability.py"
    spec = importlib.util.spec_from_file_location("identity_packet_recoverability", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _serialized_packet(packet: dict[str, Any]) -> bytes:
    """The exact public bytes; the index binds these in addition to semantic content hashes."""
    return (json.dumps(packet, indent=2, sort_keys=True) + "\n").encode()


def _load_sealed_packets() -> tuple[dict[str, dict[str, Any]], dict[str, Any]] | None:
    """Load the closure-bound legacy packet tree without rebuilding retired history."""
    if not LEGACY_EPOCH_CLOSURE.exists():
        return None
    closure: dict[str, Any] = json.loads(LEGACY_EPOCH_CLOSURE.read_text(encoding="utf-8"))
    claimed_closure_hash = closure.pop("content_hash", None)
    observed_closure_hash = _content_hash(closure)
    closure["content_hash"] = claimed_closure_hash
    if claimed_closure_hash != observed_closure_hash:
        raise ValueError("legacy research epoch closure content hash mismatch")
    if closure.get("status") != "LEGACY_EPOCH_RETIRED_FAIL_CLOSED":
        raise ValueError("legacy research epoch is not sealed fail closed")

    index_path = ARTIFACT_DIR / INDEX_NAME
    binding = closure.get("source_bindings", {}).get("identity_packet_index", {})
    if binding.get("path") != str(index_path.relative_to(REPO)) or not index_path.is_file():
        raise ValueError("sealed legacy identity-packet index is missing")
    if _sha256(index_path) != binding.get("sha256"):
        raise ValueError("sealed legacy identity-packet index file hash mismatch")
    index: dict[str, Any] = json.loads(index_path.read_text(encoding="utf-8"))
    claimed_index_hash = index.pop("content_hash", None)
    observed_index_hash = _content_hash(index)
    index["content_hash"] = claimed_index_hash
    if claimed_index_hash != observed_index_hash or claimed_index_hash != binding.get(
        "content_hash"
    ):
        raise ValueError("sealed legacy identity-packet index content hash mismatch")

    rows = index.get("packets")
    if not isinstance(rows, list) or len(rows) != 228:
        raise ValueError("sealed legacy identity-packet index must contain 228 identities")
    packets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("hypothesis_key")
        if not isinstance(key, str) or key in packets:
            raise ValueError("sealed legacy identity-packet key is invalid or duplicated")
        path = ARTIFACT_DIR / f"{key}.json"
        if _sha256(path) != row.get("packet_file_sha256"):
            raise ValueError(f"{key}: sealed legacy identity-packet file hash mismatch")
        packet: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        claimed_packet_hash = packet.pop("content_hash", None)
        observed_packet_hash = _content_hash(packet)
        packet["content_hash"] = claimed_packet_hash
        if (
            claimed_packet_hash != observed_packet_hash
            or claimed_packet_hash != row.get("packet_content_hash")
            or packet.get("hypothesis_key") != key
        ):
            raise ValueError(f"{key}: sealed legacy identity-packet content mismatch")
        packets[key] = packet
    return packets, index


def _validate_embedded_content_hash(key: str, path: Path, payload: dict[str, Any]) -> None:
    claimed = payload.get("content_hash")
    unhashed = {name: value for name, value in payload.items() if name != "content_hash"}
    if claimed != _content_hash(unhashed):
        raise ValueError(f"{key}: embedded content hash mismatch: {path.relative_to(REPO)}")


def _load_evidence_bindings() -> dict[str, dict[str, Any]]:
    payload = json.loads(EVIDENCE_BINDINGS.read_text(encoding="utf-8"))
    if payload.get("schema") != "canli.alphac-identity-trial-evidence-bindings.v1":
        raise ValueError("unexpected identity evidence binding schema")
    bindings = payload.get("bindings")
    if not isinstance(bindings, dict):
        raise ValueError("identity evidence bindings must be an object")
    return bindings


def _load_historical_curve_evidence() -> dict[str, dict[str, Any]]:
    index_path = CURVE_EVIDENCE_DIR / INDEX_NAME
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("schema") != "canli.alphac-historical-curve-evidence-index.v1":
        raise ValueError("unexpected historical curve evidence index schema")
    claimed_index_hash = index.pop("content_hash", None)
    if claimed_index_hash != _content_hash(index):
        raise ValueError("historical curve evidence index content hash mismatch")
    index["content_hash"] = claimed_index_hash
    rows = index.get("curves")
    if not isinstance(rows, list) or len(rows) != 37:
        raise ValueError("historical curve evidence index must bind exactly 37 curves")

    loaded: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get("hypothesis_key")
        if not isinstance(identity, str) or identity in loaded:
            raise ValueError("historical curve evidence identity is invalid or duplicated")
        path = CURVE_EVIDENCE_DIR / identity / "evidence.json"
        if _sha256(path) != row.get("file_sha256"):
            raise ValueError(f"{identity}: historical curve evidence file hash mismatch")
        payload = json.loads(path.read_text(encoding="utf-8"))
        _validate_embedded_content_hash(identity, path, payload)
        if (
            payload.get("schema") != "canli.alphac-historical-curve-evidence.v1"
            or payload.get("hypothesis_key") != identity
            or payload.get("config_hash") != row.get("config_hash")
            or payload.get("content_hash") != row.get("content_hash")
        ):
            raise ValueError(f"{identity}: historical curve evidence semantic mismatch")
        for name in ("walkforward", "equity"):
            source = payload["source_files"][name]
            source_path = REPO / source["repository_path"]
            published_path = CURVE_EVIDENCE_DIR / identity / Path(source["public_path"]).name
            if _sha256(source_path) != source["sha256"] or _sha256(published_path) != source[
                "sha256"
            ]:
                raise ValueError(f"{identity}: historical {name} source hash mismatch")
        loaded[identity] = {"index_row": row, "payload": payload}
    return loaded


def _validated_file_evidence(item: dict[str, Any]) -> dict[str, Any]:
    relative = item.get("source_path")
    expected = item.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        raise ValueError("bound evidence requires source_path and sha256")
    path = (REPO / relative).resolve()
    try:
        path.relative_to(REPO.resolve())
    except ValueError as error:
        raise ValueError(f"evidence path escapes repository: {relative}") from error
    if not path.is_file():
        raise FileNotFoundError(f"bound evidence is missing: {relative}")
    observed = _sha256(path)
    if observed != expected:
        raise ValueError(f"bound evidence hash mismatch: {relative}: {observed} != {expected}")
    return dict(item)


def _validate_earnings_narrative_replay(
    key: str,
    record: Any,
    binding: dict[str, Any],
    union_identity_count: int,
) -> None:
    """Validate semantic joins that byte hashes alone cannot establish."""
    result_path = REPO / "artifacts/probe/earnings_narrative_change/result.json"
    reservation_path = (
        REPO / "artifacts/probe/earnings_narrative_change/return_identity_reservation.json"
    )
    diversification_path = (
        REPO / "artifacts/probe/earnings_narrative_change/diversification.json"
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
    diversification = json.loads(diversification_path.read_text(encoding="utf-8"))

    excluded = set(binding.get("identity_projection_excludes", []))
    projected_config = {
        name: value for name, value in record.config.items() if name not in excluded
    }
    if reservation.get("trial_config") != projected_config:
        raise ValueError(f"{key}: reservation does not bind the ledger configuration")
    if result.get("return_identity_reservation") != reservation:
        raise ValueError(f"{key}: result does not embed the exact identity reservation")
    if result.get("verdict") != binding.get("verdict") or result.get("verdict") != "KILL":
        raise ValueError(f"{key}: evidence binding may not alter the persisted KILL verdict")
    if result.get("hypotheses_spent") != 1:
        raise ValueError(f"{key}: result must charge exactly one identity")

    metrics = result.get("metrics", {})
    if metrics.get("n_trials_union_including_candidate") != union_identity_count:
        raise ValueError(f"{key}: result does not use the complete union denominator")
    replay_sharpe = metrics.get("net_sharpe")
    if not isinstance(replay_sharpe, (int, float)) or abs(replay_sharpe - record.sharpe_ann) > 5e-6:
        raise ValueError(f"{key}: replay Sharpe does not reconcile to the immutable measurement")
    required_metrics = {
        "net_sharpe",
        "newey_west_t",
        "dsr",
        "psr",
        "net_sharpe_at_2x_costs",
        "max_drawdown",
        "skew",
        "turnover_ann",
        "capacity",
    }
    if not required_metrics <= set(metrics):
        raise ValueError(f"{key}: result uncertainty/stress/capacity metrics are incomplete")

    report = diversification.get("report", {})
    if (
        diversification.get("schema") != "canli.alphac-canonical-diversification.v1"
        or diversification.get("family_trial_account") != "earnings_narrative_change"
        or report.get("bootstrap_samples") != 2_000
        or report.get("bootstrap_block_size") != 21
        or report.get("bootstrap_seed") != 20260816
        or report.get("return_data_opened") is not True
    ):
        raise ValueError(f"{key}: canonical diversification evidence is incomplete")
    if diversification.get("alignment", {}).get("internal_missing_by_series") != {}:
        raise ValueError(f"{key}: diversification alignment dropped internal dates")

    lineage = result.get("lineage", {})
    reproduction = result.get("reproduction", {})
    expected_links = {
        "preregistration_sha256": _sha256(
            REPO / "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md"
        ),
        "data_manifest_sha256": _sha256(
            REPO / "artifacts/probe/earnings_narrative_change/input_data_manifest.json"
        ),
        "runner_sha256": _sha256(REPO / "scripts/probe_earnings_narrative_change.py"),
        "diversification_report_sha256": _sha256(diversification_path),
        "admission_contract_sha256": _sha256(LEGACY_ADMISSION_CONTRACT),
        "return_identity_reservation_sha256": _sha256(reservation_path),
    }
    if any(lineage.get(name) != value for name, value in expected_links.items()):
        raise ValueError(f"{key}: result lineage does not bind current evidence bytes")
    if (
        reproduction.get("command") != binding.get("reproduction_command")
        or reproduction.get("runner_sha256") != expected_links["runner_sha256"]
        or reproduction.get("pyproject_sha256") != _sha256(REPO / "pyproject.toml")
        or reproduction.get("uv_lock_sha256") != _sha256(REPO / "uv.lock")
    ):
        raise ValueError(f"{key}: replay environment is not fully bound")
    admission = result.get("admission_review", {})
    if (
        admission.get("contract_schema") != "canli.alphac-sleeve-admission-contract.v6"
        or admission.get("checks_required_for_technical_eligibility") != 85
        or admission.get("status") != "RESEARCH_SUBSET_FAILED"
        or admission.get("technically_eligible") is not False
    ):
        raise ValueError(f"{key}: kill decision is not reconciled to admission contract v6")


def _validate_eia_petroleum_inventory_replay(
    key: str,
    record: Any,
    binding: dict[str, Any],
    union_identity_count: int,
) -> None:
    """Prove the EIA KILL belongs to the exact ledger identity and frozen inputs."""
    probe_dir = REPO / "artifacts/probe/eia_petroleum_inventory"
    result_path = probe_dir / "result.json"
    input_manifest_path = probe_dir / "input_data_manifest.json"
    source_manifest_path = REPO / "data/lake_inventory_releases/manifest.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))

    excluded = set(binding.get("identity_projection_excludes", []))
    projected_config = {
        name: value for name, value in record.config.items() if name not in excluded
    }
    if result.get("configuration") != projected_config:
        raise ValueError(f"{key}: result does not bind the ledger configuration")
    if result.get("verdict") != binding.get("verdict") or result.get("verdict") != "KILL":
        raise ValueError(f"{key}: evidence binding may not alter the persisted KILL verdict")
    if result.get("hypotheses_spent") != 1:
        raise ValueError(f"{key}: result must charge exactly one identity")

    metrics = result.get("metrics", {})
    if metrics.get("observations") != record.n_obs:
        raise ValueError(f"{key}: replay observation count does not match the ledger")
    if metrics.get("n_trials_union_including_candidate") != union_identity_count:
        raise ValueError(f"{key}: result does not use the complete union denominator")
    replay_sharpe = metrics.get("net_sharpe")
    if not isinstance(replay_sharpe, (int, float)) or record.n_obs < 2:
        raise ValueError(f"{key}: replay Sharpe is missing")
    population_sharpe = replay_sharpe * math.sqrt(record.n_obs / (record.n_obs - 1))
    if not math.isclose(population_sharpe, record.sharpe_ann, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{key}: replay Sharpe does not reconcile to the ledger convention")
    required_metrics = {
        "net_sharpe",
        "newey_west_t",
        "dsr",
        "psr",
        "net_sharpe_at_2x_costs",
        "max_drawdown",
        "skew",
        "turnover_ann",
        "standalone_net_sharpe",
        "capacity",
    }
    if not required_metrics <= set(metrics):
        raise ValueError(f"{key}: result uncertainty/stress/capacity metrics are incomplete")
    correlation = result.get("correlation", {})
    book = result.get("book", {})
    if not {
        "ordinary_by_sleeve",
        "average",
        "max_pair",
        "stressed_by_sleeve",
        "max_stressed",
    } <= set(correlation) or not {
        "delta_sharpe",
        "mean_zero_delta_sharpe",
        "leave_one_year_out_delta",
        "all_leave_one_year_out_positive",
    } <= set(book):
        raise ValueError(f"{key}: diversification evidence is incomplete")

    if input_manifest.get("schema") != "canli.eia-petroleum-inventory-input-manifest.v1":
        raise ValueError(f"{key}: unexpected input manifest schema")
    claimed_content_hash = input_manifest.pop("content_hash", None)
    observed_content_hash = _content_hash(input_manifest)
    input_manifest["content_hash"] = claimed_content_hash
    if claimed_content_hash != observed_content_hash:
        raise ValueError(f"{key}: input manifest content hash mismatch")
    if input_manifest.get("first_release_files_validated") != 783:
        raise ValueError(f"{key}: dated first-release archive is incomplete")
    files = source_manifest.get("files", [])
    if len(files) != 783 or source_manifest.get("accepted_releases") != 782:
        raise ValueError(f"{key}: source release accounting is incomplete")
    for item in files:
        path = REPO / item["path"]
        if _sha256(path) != item.get("sha256"):
            raise ValueError(f"{key}: first-release source hash mismatch: {item['path']}")
    for inventory in input_manifest.get("market_data_partitions", {}).values():
        for item in inventory:
            path = REPO / item["path"]
            if path.stat().st_size != item.get("bytes") or _sha256(path) != item.get("sha256"):
                raise ValueError(f"{key}: market partition mismatch: {item['path']}")
    for item in input_manifest.get("diversification_curves", {}).values():
        if _sha256(REPO / item["path"]) != item.get("sha256"):
            raise ValueError(f"{key}: diversification curve mismatch: {item['path']}")

    lineage = result.get("lineage", {})
    reproduction = result.get("reproduction", {})
    expected_links = {
        "preregistration_sha256": _sha256(
            REPO / "docs/design/PREREG_EIA_PETROLEUM_INVENTORY.md"
        ),
        "events_sha256": _sha256(REPO / "data/lake_inventory_releases/events.parquet"),
        "first_release_manifest_sha256": _sha256(source_manifest_path),
        "input_data_manifest_sha256": _sha256(input_manifest_path),
        "runner_sha256": _sha256(REPO / "scripts/probe_eia_petroleum_inventory.py"),
        "admission_contract_sha256": _sha256(LEGACY_ADMISSION_CONTRACT),
    }
    if any(lineage.get(name) != value for name, value in expected_links.items()):
        raise ValueError(f"{key}: result lineage does not bind current evidence bytes")
    if (
        reproduction.get("command") != binding.get("reproduction_command")
        or reproduction.get("runner_sha256") != expected_links["runner_sha256"]
        or reproduction.get("pyproject_sha256") != _sha256(REPO / "pyproject.toml")
        or reproduction.get("uv_lock_sha256") != _sha256(REPO / "uv.lock")
    ):
        raise ValueError(f"{key}: replay environment is not fully bound")
    admission = result.get("admission_review", {})
    if (
        admission.get("contract_schema") != "canli.alphac-sleeve-admission-contract.v6"
        or admission.get("checks_required_for_technical_eligibility") != 85
        or admission.get("status") != "RESEARCH_SUBSET_FAILED"
        or admission.get("technically_eligible") is not False
    ):
        raise ValueError(f"{key}: kill decision is not reconciled to admission contract v6")


def _validate_fundamental_single_exact_replay(
    key: str,
    record: Any,
    binding: dict[str, Any],
    union_identity_count: int,
) -> None:
    """Bind a zero-trial exact replay to its immutable ledger row and support evidence."""
    import pandas as pd

    probe_dir = REPO / "artifacts/probe/fundamental_single_replays" / key
    preserved_run_name = binding.get("preserved_run_name")
    if not isinstance(preserved_run_name, str) or not preserved_run_name.startswith("single_"):
        raise ValueError(f"{key}: exact-replay binding lacks a preserved run name")
    preserved_dir = REPO / "artifacts" / "walkforward" / preserved_run_name
    paths = {
        name: probe_dir / f"{name}.json"
        for name in (
            "result",
            "curve_evidence",
            "diversification",
            "input_data_manifest",
            "market_evidence",
            "replay_environment",
        )
    }
    payloads = {
        name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()
    }
    result = payloads["result"]
    curve = payloads["curve_evidence"]
    diversification = payloads["diversification"]
    input_manifest = payloads["input_data_manifest"]
    market = payloads["market_evidence"]
    environment = payloads["replay_environment"]
    for name in (
        "curve_evidence",
        "diversification",
        "input_data_manifest",
        "market_evidence",
        "replay_environment",
    ):
        _validate_embedded_content_hash(key, paths[name], payloads[name])

    if (
        result.get("schema") != "canli.alphac-fundamental-single-exact-replay.v1"
        or result.get("hypothesis_key") != key
        or result.get("config_hash") != record.config_hash
        or result.get("verdict") != binding.get("verdict")
        or result.get("verdict") != "KILL"
        or result.get("exact_first_measurement_reproduced") is not True
        or result.get("hypotheses_spent") != 0
    ):
        raise ValueError(f"{key}: exact-replay result identity or verdict is invalid")
    ledger_state = result.get("ledger_state_before_and_after", {})
    if ledger_state != {"active_rows": 226, "union_identities": union_identity_count}:
        raise ValueError(f"{key}: zero-trial replay does not prove an unchanged union ledger")
    preregistered_at = dt.datetime.fromisoformat(result["preregistered_at"])
    first_measured_at = dt.datetime.fromisoformat(result["first_measured_at"])
    expected_measured_at = dt.datetime.fromtimestamp(record.now_ms / 1000, tz=dt.UTC)
    if preregistered_at >= first_measured_at or first_measured_at != expected_measured_at:
        raise ValueError(f"{key}: preregistration timing does not bind the first measurement")

    preserved_artifact_path = preserved_dir / "walkforward.json"
    replay_artifact_path = probe_dir / "walkforward.json"
    preserved_equity_path = preserved_dir / "equity.parquet"
    replay_equity_path = probe_dir / "equity.parquet"
    preserved_artifact = json.loads(preserved_artifact_path.read_text(encoding="utf-8"))
    replay_artifact = json.loads(replay_artifact_path.read_text(encoding="utf-8"))
    if preserved_artifact.get("summary") != replay_artifact.get("summary"):
        raise ValueError(f"{key}: replay summary differs from the immutable artifact")
    pd.testing.assert_frame_equal(
        pd.read_parquet(preserved_equity_path),
        pd.read_parquet(replay_equity_path),
        check_exact=True,
    )
    measurement = result.get("immutable_measurement", {})
    if (
        measurement.get("n_obs") != record.n_obs
        or measurement.get("annualized_sharpe") != record.sharpe_ann
        or measurement.get("maximum_drawdown") != preserved_artifact["summary"]["max_dd"]
    ):
        raise ValueError(f"{key}: replay measurement does not match the immutable ledger")

    lineage = result.get("lineage", {})
    expected_lineage = {
        "preserved_artifact_sha256": _sha256(preserved_artifact_path),
        "preserved_equity_sha256": _sha256(preserved_equity_path),
        "replay_artifact_sha256": _sha256(replay_artifact_path),
        "replay_equity_sha256": _sha256(replay_equity_path),
        "source_environment_sha256": _sha256(paths["replay_environment"]),
        "source_environment_content_hash": environment["content_hash"],
    }
    if any(lineage.get(name) != value for name, value in expected_lineage.items()):
        raise ValueError(f"{key}: replay result does not bind exact artifact bytes")
    environment_leaves = {item["path"]: item for item in environment.get("leaves", [])}
    environment_links = {
        "scripts/replay_fundamental_single_identity.py": "runner_sha256",
        "src/alphaforge/analytics/walkforward.py": "walkforward_engine_sha256",
        "pyproject.toml": "pyproject_sha256",
        "uv.lock": "uv_lock_sha256",
        "docs/design/PREREG_FUNDAMENTAL_SINGLES.md": "preregistration_sha256",
    }
    if (
        environment.get("schema") != "canli.alphac-replay-source-environment.v1"
        or environment.get("source_files") != len(environment_leaves)
        or environment.get("source_bytes")
        != sum(item.get("bytes", -1) for item in environment_leaves.values())
        or any(
            environment_leaves.get(path, {}).get("sha256") != lineage.get(lineage_name)
            for path, lineage_name in environment_links.items()
        )
    ):
        raise ValueError(f"{key}: frozen source environment is incomplete or inconsistent")
    data_environment = environment.get("data_environment", {})
    if lineage.get("data_environment") != data_environment:
        raise ValueError(f"{key}: result does not bind its data environment")
    correction_manifest = data_environment.get("versioned_correction_manifest")
    if correction_manifest is not None:
        correction_path = REPO / correction_manifest
        correction = json.loads(correction_path.read_text(encoding="utf-8"))
        if (
            data_environment.get("kind")
            != "VERSIONED_SHARADAR_HDB_ZERO_MARKER_QUARANTINE"
            or data_environment.get("versioned_correction_manifest_sha256")
            != _sha256(correction_path)
            or data_environment.get("versioned_correction_content_hash")
            != correction.get("content_hash")
            or data_environment.get("rows_quarantined") != 1
            or data_environment.get("cash_amount_imputed") is not False
        ):
            raise ValueError(f"{key}: corrected-lake lineage is incomplete")

    curve_metrics = curve.get("metrics", {})
    if (
        curve.get("schema") != "canli.alphac-fundamental-single-curve-evidence.v1"
        or curve.get("hypothesis_key") != key
        or curve.get("verdict") != "KILL"
        or curve_metrics.get("observations") != record.n_obs
        or not math.isclose(
            curve_metrics.get("annualized_sharpe", math.nan),
            record.sharpe_ann,
            rel_tol=0.0,
            abs_tol=5e-12,
        )
        or curve_metrics.get("current_union_trials") != union_identity_count
        or curve_metrics.get("annualized_sharpe", 0.0) >= 0.0
    ):
        raise ValueError(f"{key}: curve uncertainty evidence does not bind the KILL")
    if curve.get("lineage", {}).get("diversification_content_hash") != diversification.get(
        "content_hash"
    ):
        raise ValueError(f"{key}: curve evidence does not bind diversification bytes")

    report = diversification.get("report", {})
    if (
        diversification.get("schema") != "canli.alphac-canonical-diversification.v1"
        or diversification.get("return_identity_id") != key
        or report.get("bootstrap_samples") != 2_000
        or report.get("bootstrap_block_size") != 21
        or report.get("bootstrap_seed") != 20260816
        or report.get("return_data_opened") is not True
        or diversification.get("alignment", {}).get("internal_missing_by_series") != {}
        or report.get("book_sharpe_delta", 0.0) >= 0.0
        or report.get("minimum_leave_one_period_out_book_sharpe_delta", 0.0) >= 0.0
    ):
        raise ValueError(f"{key}: diversification failure evidence is incomplete")

    datasets = input_manifest.get("datasets", {})
    expected_input_summary = binding.get("expected_input_summary")
    if not isinstance(expected_input_summary, dict):
        raise ValueError(f"{key}: exact-replay binding lacks the input snapshot summary")
    if (
        input_manifest.get("schema") != "canli.alphac-fundamental-single-input-manifest.v1"
        or input_manifest.get("hypothesis_key") != key
        or input_manifest.get("scope", {}).get("instrument_ids") != 6_820
        or input_manifest.get("summary") != expected_input_summary
        or input_manifest.get("data_environment") != data_environment
        or input_manifest.get("instrument_metadata", {}).get("rows") != 6_820
        or set(datasets)
        != {"ohlcv_1d", "fundamentals", "corporate_actions", "universe_membership"}
        or any(len(item.get("root_sha256", "")) != 64 for item in datasets.values())
    ):
        raise ValueError(f"{key}: point-in-time input commitment is incomplete")

    execution = market.get("execution_stress", {})
    capacity = market.get("capacity", {})
    if (
        market.get("schema") != "canli.alphac-fundamental-single-market-evidence.v1"
        or market.get("hypothesis_key") != key
        or market.get("verdict") != "KILL"
        or int(execution.get("fills", 0)) <= 0
        or execution.get("stressed_annualized_sharpe", math.inf)
        >= execution.get("original_annualized_sharpe", -math.inf)
        or capacity.get("missing_adv_treatment") != "ZERO_CAPACITY_FAIL_CLOSED"
        or any(
            capacity.get(name) != 0.0
            for name in (
                "p05_usd_at_1bp_adv",
                "p05_usd_at_5bp_adv",
                "p05_usd_at_10bp_adv",
                "p05_usd_at_1pct_adv",
            )
        )
    ):
        raise ValueError(f"{key}: execution stress or fail-closed capacity evidence is incomplete")


def _validate_fundamental_single_corrected_reproduction(
    key: str,
    record: Any,
    binding: dict[str, Any],
) -> None:
    """Credit only the sections proved by the sealed corrected KILL reproduction."""
    corrected_dir = (
        REPO
        / "artifacts/probe/fundamental_single_replays"
        / key
        / "corrected_corporate_actions_f812e1576bf430ee"
    )
    paths = {
        "result": corrected_dir / "result.json",
        "environment": corrected_dir / "replay_environment.json",
        "equity": corrected_dir / "equity.parquet",
        "authorization": (
            REPO / "artifacts/audit/operating_margin_corrected_replay_authorization.json"
        ),
        "correction": REPO / "artifacts/audit/sharadar_corporate_action_corrected_lake.json",
        "seal": REPO / "artifacts/audit/operating_margin_corrected_reproduction.json",
        "preregistration": REPO / "docs/design/PREREG_FUNDAMENTAL_SINGLES.md",
        "runner": REPO / "scripts/replay_fundamental_single_identity.py",
    }
    result = json.loads(paths["result"].read_text(encoding="utf-8"))
    environment = json.loads(paths["environment"].read_text(encoding="utf-8"))
    authorization = json.loads(paths["authorization"].read_text(encoding="utf-8"))
    correction = json.loads(paths["correction"].read_text(encoding="utf-8"))
    seal = json.loads(paths["seal"].read_text(encoding="utf-8"))
    for name, payload in (
        ("environment", environment),
        ("authorization", authorization),
        ("correction", correction),
        ("seal", seal),
    ):
        _validate_embedded_content_hash(key, paths[name], payload)

    corrected = result.get("corrected_measurement", {})
    immutable = result.get("immutable_measurement", {})
    if (
        binding.get("verdict") != "KILL"
        or result.get("schema")
        != "canli.alphac-fundamental-single-corrected-reproduction.v1"
        or result.get("hypothesis_key") != key
        or result.get("config_hash") != record.config_hash
        or result.get("verdict") != "KILL"
        or result.get("corrected_data_reproduction") is not True
        or result.get("exact_first_measurement_reproduced") is not False
        or result.get("hypotheses_spent") != 0
        or immutable.get("n_obs") != record.n_obs
        or immutable.get("annualized_sharpe") != record.sharpe_ann
        or corrected.get("n_periods") != record.n_obs
        or corrected.get("sharpe", math.inf) >= 0.0
        or corrected.get("total_return", math.inf) >= 0.0
    ):
        raise ValueError(f"{key}: corrected reproduction does not preserve the KILL identity")

    measured_at = dt.datetime.fromtimestamp(record.now_ms / 1_000, tz=dt.UTC)
    preregistered_at = dt.datetime.fromisoformat(result["preregistered_at"]).astimezone(dt.UTC)
    if preregistered_at >= measured_at:
        raise ValueError(f"{key}: corrected reproduction preregistration is not prospective")

    data_environment = environment.get("data_environment", {})
    lineage = result.get("lineage", {})
    environment_leaves = {item["path"]: item for item in environment.get("leaves", [])}
    expected_leaves = {
        "docs/design/PREREG_FUNDAMENTAL_SINGLES.md": _sha256(paths["preregistration"]),
        "scripts/replay_fundamental_single_identity.py": _sha256(paths["runner"]),
        "pyproject.toml": _sha256(REPO / "pyproject.toml"),
        "uv.lock": _sha256(REPO / "uv.lock"),
        "artifacts/audit/operating_margin_corrected_replay_authorization.json": _sha256(
            paths["authorization"]
        ),
    }
    if (
        environment.get("schema") != "canli.alphac-replay-source-environment.v1"
        or environment.get("source_files") != len(environment_leaves)
        or any(
            environment_leaves.get(path, {}).get("sha256") != expected
            for path, expected in expected_leaves.items()
        )
        or data_environment.get("kind")
        != "TRIAL_SPECIFIC_CORPORATE_ACTION_CORRECTION_FAIL_CLOSED"
        or data_environment.get("global_split_gate_passed") is not False
        or data_environment.get("versioned_correction_manifest_sha256")
        != _sha256(paths["correction"])
        or data_environment.get("versioned_correction_content_hash")
        != correction.get("content_hash")
        or lineage.get("data_environment") != data_environment
        or lineage.get("source_environment_sha256") != _sha256(paths["environment"])
        or lineage.get("source_environment_content_hash") != environment.get("content_hash")
        or lineage.get("replay_equity_sha256") != _sha256(paths["equity"])
    ):
        raise ValueError(f"{key}: corrected source/data environment is incomplete")

    if (
        authorization.get("schema")
        != "canli.alphac-operating-margin-corrected-replay-authorization.v1"
        or authorization.get("hypothesis_key") != key
        or authorization.get("hypotheses_spent") != 0
        or authorization.get("return_data_opened") is not False
        or authorization.get("accounting", {}).get("global_split_gate_passed") is not False
        or len(authorization.get("verified_split_events", [])) != 2
        or correction.get("schema")
        != "canli.alphac-sharadar-corporate-action-corrected-lake.v1"
        or correction.get("hypotheses_spent") != 0
        or correction.get("return_data_opened") is not False
    ):
        raise ValueError(f"{key}: corrected-data authorization does not fail closed")

    seal_lineage = seal.get("lineage", {})
    if (
        seal.get("schema")
        != "canli.alphac-operating-margin-corrected-reproduction-seal.v1"
        or seal.get("decision")
        != "CORRECTED_OPERATING_MARGIN_REPRODUCED_KILL_PRESERVED"
        or seal.get("verdict") != "KILL"
        or seal.get("hypotheses_spent") != 0
        or seal.get("corrected_measurement", {}).get("annualized_sharpe")
        != corrected.get("sharpe")
        or seal_lineage.get("result_sha256") != _sha256(paths["result"])
        or seal_lineage.get("environment_sha256") != _sha256(paths["environment"])
        or seal_lineage.get("equity_sha256") != _sha256(paths["equity"])
        or seal_lineage.get("authorization_sha256") != _sha256(paths["authorization"])
    ):
        raise ValueError(f"{key}: corrected KILL seal does not bind reproduction bytes")


def _validated_identity_evidence(
    key: str,
    record: Any,
    family_key: str,
    binding: dict[str, Any] | None,
    union_identity_count: int,
) -> dict[str, list[dict[str, Any]]]:
    if binding is None:
        return {}
    if binding.get("config_hash") != record.config_hash:
        raise ValueError(f"{key}: evidence binding config hash mismatch")
    if binding.get("research_family_key") != family_key:
        raise ValueError(f"{key}: evidence binding family mismatch")
    section_evidence = binding.get("section_evidence")
    if not isinstance(section_evidence, dict):
        raise ValueError(f"{key}: section evidence must be an object")
    unknown = set(section_evidence) - set(_manifest_module().REQUIRED_PACKET_SECTIONS)
    if unknown:
        raise ValueError(f"{key}: unknown evidence sections: {sorted(unknown)}")
    validated = {
        section: [_validated_file_evidence(item) for item in evidence]
        for section, evidence in section_evidence.items()
    }
    if any(not evidence for evidence in validated.values()):
        raise ValueError(f"{key}: verified identity section has no evidence")
    if binding.get("binding_type") == "earnings_narrative_replay_v1":
        _validate_earnings_narrative_replay(key, record, binding, union_identity_count)
    elif binding.get("binding_type") == "eia_petroleum_inventory_replay_v1":
        _validate_eia_petroleum_inventory_replay(key, record, binding, union_identity_count)
    elif binding.get("binding_type") == "fundamental_single_exact_replay_v1":
        _validate_fundamental_single_exact_replay(key, record, binding, union_identity_count)
    elif binding.get("binding_type") == "fundamental_single_corrected_reproduction_v1":
        _validate_fundamental_single_corrected_reproduction(key, record, binding)
    else:
        raise ValueError(f"{key}: unsupported identity evidence binding type")
    return validated


def build_packets() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    sealed = _load_sealed_packets()
    if sealed is not None:
        return sealed
    contract = _manifest_module()
    recoverability = _recoverability_module().build_audit()
    audited_debt = recoverability["identities"]
    evidence_bindings = _load_evidence_bindings()
    historical_curves = _load_historical_curve_evidence()
    union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    first: dict[str, tuple[Any, Path]] = {}
    for path in union.paths:
        if not path.exists():
            continue
        ledger = ExperimentLog(path)
        for record in ledger.all():
            key = ledger._hypothesis_key(record.config)
            prior = first.get(key)
            if prior is None or (record.now_ms, record.config_hash) < (
                prior[0].now_ms,
                prior[0].config_hash,
            ):
                first[key] = (record, path)
    if len(first) != 228:
        raise ValueError(f"expected 228 union identities, found {len(first)}")
    unknown_bindings = set(evidence_bindings) - set(first)
    if unknown_bindings:
        raise ValueError(f"evidence bindings name unknown identities: {sorted(unknown_bindings)}")
    unknown_debt = set(audited_debt) - set(first)
    if unknown_debt:
        raise ValueError(f"recoverability audit names unknown identities: {sorted(unknown_debt)}")
    unknown_curves = set(historical_curves) - set(first)
    if unknown_curves:
        raise ValueError(f"historical curve evidence names unknown identities: {unknown_curves}")

    packets: dict[str, dict[str, Any]] = {}
    index_rows: list[dict[str, Any]] = []
    for key, (record, ledger_path) in sorted(first.items()):
        family_key = contract._family_key(record.config)
        binding = contract.FAMILY_PAPER_BINDINGS.get(family_key)
        if binding is None:
            raise ValueError(f"{key}: no verified family-paper binding")
        identity_evidence = _validated_identity_evidence(
            key, record, family_key, evidence_bindings.get(key), len(first)
        )
        verified = list(binding["verified_shared_sections"])
        verified.extend(
            section for section in contract.REQUIRED_PACKET_SECTIONS if section in identity_evidence
        )
        missing = [
            section for section in contract.REQUIRED_PACKET_SECTIONS if section not in verified
        ]
        assessment = audited_debt.get(key)
        if assessment is not None and assessment.get("config_hash") != record.config_hash:
            raise ValueError(f"{key}: recoverability assessment config hash mismatch")
        curve = historical_curves.get(key)
        expects_curve = (
            assessment is not None
            and assessment.get("artifact_recoverability_class")
            == "UNIQUE_EXACT_ARTIFACT_BINDING"
        )
        if expects_curve != (curve is not None):
            raise ValueError(f"{key}: historical curve evidence coverage mismatch")
        partial_identity_evidence: dict[str, list[dict[str, Any]]] = {}
        if curve is not None:
            curve_payload = curve["payload"]
            curve_row = curve["index_row"]
            partial_identity_evidence[
                "result_uncertainty_stress_capacity_and_diversification"
            ] = [
                {
                    "type": "historical_curve_evidence",
                    "public_path": curve_row["public_path"],
                    "content_hash": curve_payload["content_hash"],
                    "file_sha256": curve_row["file_sha256"],
                    "sha256": curve_row["file_sha256"],
                    "walkforward_public_path": curve_payload["source_files"]["walkforward"][
                        "public_path"
                    ],
                    "walkforward_sha256": curve_payload["source_files"]["walkforward"][
                        "sha256"
                    ],
                    "equity_public_path": curve_payload["source_files"]["equity"][
                        "public_path"
                    ],
                    "equity_sha256": curve_payload["source_files"]["equity"]["sha256"],
                    "claim_boundary": curve_payload["claim_boundary"],
                }
            ]
        completion_assessment = (
            {
                "status": "COMPLETE",
                "claim_boundary": "Every required packet section is verified.",
                "blockers": [],
            }
            if not missing
            else assessment
            if assessment is not None
            else {
                "status": "NOT_YET_AUDITED",
                "claim_boundary": (
                    "Missing sections are fail-closed evidence debt. This identity has not yet "
                    "received a source-by-source recoverability audit."
                ),
                "blockers": [],
            }
        )
        sections = {
            section: {
                "status": (
                    "VERIFIED_IDENTITY_LEVEL_EVIDENCE"
                    if section in identity_evidence
                    else "VERIFIED_SHARED_FAMILY_EVIDENCE"
                    if section in binding["verified_shared_sections"]
                    else "PARTIAL_IDENTITY_LEVEL_EVIDENCE"
                    if section in partial_identity_evidence
                    else "MISSING_IDENTITY_LEVEL_EVIDENCE"
                ),
                "evidence": (
                    identity_evidence[section]
                    if section in identity_evidence
                    else [{"type": "family_paper", "public_path": binding["public_path"]}]
                    if section in binding["verified_shared_sections"]
                    else partial_identity_evidence.get(section, [])
                ),
            }
            for section in contract.REQUIRED_PACKET_SECTIONS
        }
        packet: dict[str, Any] = {
            "schema": "canli.alphac-identity-trial-packet.v2",
            "evidence_date": "2026-08-22",
            "hypothesis_key": key,
            "config_hash": record.config_hash,
            "label": contract._label(record.config),
            "research_family_key": family_key,
            "family_paper_public_path": binding["public_path"],
            "author": "Arhan Canli",
            "claim_boundary": (
                "This stable packet proves the exact identity, immutable first measurement, and "
                "current evidence state. INCOMPLETE means missing sections remain missing; packet "
                "publication is not validation, admission, or a future-return claim."
            ),
            "packet_status": (
                "COMPLETE_EVIDENCED_KILL" if not missing else "INCOMPLETE_BACKFILL_REQUIRED"
            ),
            "configuration": record.config,
            "immutable_first_measurement": {
                "ledger_source_path": str(ledger_path.relative_to(REPO)),
                "ledger_source_sha256": _sha256(ledger_path),
                "recorded_at_unix_ms": record.now_ms,
                "observations": record.n_obs,
                "annualized_sharpe": contract._finite_or_none(record.sharpe_ann),
                "skew": contract._finite_or_none(record.skew),
                "kurtosis": contract._finite_or_none(record.kurtosis),
            },
            "required_sections": sections,
            "verified_sections": verified,
            "partial_sections": list(partial_identity_evidence),
            "missing_sections": missing,
            "completion_assessment": completion_assessment,
            "complete": not missing,
        }
        packet["content_hash"] = _content_hash(packet)
        packet_file_sha256 = hashlib.sha256(_serialized_packet(packet)).hexdigest()
        packets[key] = packet
        index_rows.append(
            {
                "hypothesis_key": key,
                "config_hash": record.config_hash,
                "research_family_key": family_key,
                "public_path": f"/glassbox/trial-packets/{key}.json",
                "packet_content_hash": packet["content_hash"],
                "packet_file_sha256": packet_file_sha256,
                "packet_status": packet["packet_status"],
                "completion_assessment_status": completion_assessment["status"],
                "complete": not missing,
            }
        )
    index: dict[str, Any] = {
        "schema": "canli.alphac-identity-trial-packet-index.v2",
        "evidence_date": "2026-08-22",
        "claim_boundary": (
            "All 228 identities have stable packets. Complete means every required section is "
            "evidenced and verified; it does not mean the trial passed, was admitted, or predicts "
            "future returns."
        ),
        "summary": {
            "distinct_hypothesis_identities": len(index_rows),
            "published_identity_packets": len(index_rows),
            "complete_identity_packets": sum(row["complete"] for row in index_rows),
            "incomplete_identity_packets": sum(not row["complete"] for row in index_rows),
            "packets_with_partial_historical_curve_evidence": len(historical_curves),
            "audited_not_currently_completable": sum(
                row["completion_assessment_status"] == "AUDITED_NOT_CURRENTLY_COMPLETABLE"
                for row in index_rows
            ),
            "audited_exact_replay_candidates": sum(
                row["completion_assessment_status"] == "AUDITED_EXACT_REPLAY_CANDIDATE"
                for row in index_rows
            ),
            "audited_exact_replays_failed_data_quality": sum(
                row["completion_assessment_status"]
                == "AUDITED_EXACT_REPLAY_FAILED_DATA_QUALITY"
                for row in index_rows
            ),
            "audited_exact_replays_failed_reproduction": sum(
                row["completion_assessment_status"]
                == "AUDITED_EXACT_REPLAY_FAILED_REPRODUCTION"
                for row in index_rows
            ),
            "audited_corrected_reproductions_kill_preserved": sum(
                row["completion_assessment_status"]
                == "AUDITED_CORRECTED_REPRODUCTION_KILL_PRESERVED"
                for row in index_rows
            ),
            "incomplete_not_yet_audited": sum(
                row["completion_assessment_status"] == "NOT_YET_AUDITED"
                for row in index_rows
            ),
        },
        "packets": index_rows,
    }
    index["content_hash"] = _content_hash(index)
    return packets, index


def main() -> int:
    packets, index = build_packets()
    destinations = (ARTIFACT_DIR, *HOST_DIRS)
    for directory in destinations:
        directory.mkdir(parents=True, exist_ok=True)
        for key, packet in packets.items():
            (directory / f"{key}.json").write_bytes(_serialized_packet(packet))
        (directory / INDEX_NAME).write_text(
            json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        f"identity packets: {index['summary']['published_identity_packets']} published; "
        f"{index['summary']['complete_identity_packets']} complete"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
