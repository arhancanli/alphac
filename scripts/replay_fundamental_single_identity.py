#!/usr/bin/env python3
"""Replay one corrected-universe fundamental trial without spending a new identity.

The historical result remains immutable. This runner writes to a separate probe directory,
keeps every experiment ledger untouched, and calls a replay exact only when the full OOS equity
frame and summary metrics match the preserved artifact.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pandas as pd

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion, config_hash
from alphaforge.validation.prereg import assert_matches

REPO: Final[Path] = Path(__file__).resolve().parent.parent
LEDGER: Final[Path] = REPO / "var" / "experiments.jsonl"
PREREG: Final[Path] = REPO / "docs" / "design" / "PREREG_FUNDAMENTAL_SINGLES.md"
PREREG_COMMIT: Final[str] = "eefb04a10bc8e98981506667289aa66b206ec133"
BASE_LAKE: Final[Path] = REPO / "data" / "lake_sharadar"
CORRECTED_LAKE_MANIFEST: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_hdb_corrected_lake.json"
)
CORPORATE_ACTION_LAKE_MANIFEST: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_corporate_action_corrected_lake.json"
)
OPERATING_MARGIN_REPLAY_AUTHORIZATION: Final[Path] = (
    REPO / "artifacts" / "audit" / "operating_margin_corrected_replay_authorization.json"
)
CANDIDATES: Final[dict[str, str]] = {
    "single_gross_profitability": "1d2924f28fe31a9a",
    "single_book_to_price": "a238c1a5ecc5d1e3",
    "single_earnings_yield": "e86109044ab18734",
    "single_sales_to_price": "2d966892fb5db520",
    "single_operating_margin": "e5f48adc25065ce9",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _first_records() -> dict[str, Any]:
    union = ExperimentUnion.discover(LEDGER, REPO)
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


def _commit_time(commit: str) -> dt.datetime:
    value = subprocess.check_output(
        ["git", "show", "-s", "--format=%cI", commit], cwd=REPO, text=True
    ).strip()
    return dt.datetime.fromisoformat(value).astimezone(dt.UTC)


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _operating_margin_authorization() -> dict[str, Any]:
    payload = json.loads(OPERATING_MARGIN_REPLAY_AUTHORIZATION.read_text(encoding="utf-8"))
    if (
        payload.get("content_hash") != _content_hash(payload)
        or payload.get("decision") != "OPERATING_MARGIN_CORRECTED_REPLAY_AUTHORIZED_FAIL_CLOSED"
        or payload.get("run_name") != "single_operating_margin"
        or payload.get("hypothesis_key") != CANDIDATES["single_operating_margin"]
    ):
        raise ValueError("operating-margin corrected replay authorization is invalid")
    expected_code = payload["execution_code"]
    for relative, declared_sha in expected_code.items():
        if _sha256(REPO / relative) != declared_sha:
            raise ValueError(f"authorized execution code changed: {relative}")
    return payload


def _verified_split_events(authorization: dict[str, Any]) -> dict[tuple[str, int], float]:
    return {
        (str(row["instrument_id"]), int(row["ex_date_ms"])): float(row["ratio"])
        for row in authorization["verified_split_events"]
    }


def _data_environment(lake_dir: Path, *, run_name: str | None = None) -> dict[str, Any]:
    resolved = lake_dir.resolve()
    if resolved == BASE_LAKE.resolve():
        return {
            "lake_dir": str(BASE_LAKE.relative_to(REPO)),
            "kind": "FROZEN_ORIGINAL_SHARADAR_LAKE",
            "versioned_correction_manifest": None,
        }
    manifest = json.loads(CORRECTED_LAKE_MANIFEST.read_text(encoding="utf-8"))
    declared = (REPO / str(manifest["corrected_lake"])).resolve()
    if (
        manifest.get("content_hash") != _content_hash(manifest)
        or manifest.get("decision") != "VERSIONED_LAKE_READY_FOR_EXACT_REPLAY"
        or resolved != declared
        or not resolved.is_dir()
        or not str(resolved).endswith("data/lake_sharadar")
    ):
        corporate_manifest = json.loads(CORPORATE_ACTION_LAKE_MANIFEST.read_text(encoding="utf-8"))
        corporate_declared = (REPO / str(corporate_manifest["corrected_lake"])).resolve()
        if (
            run_name != "single_operating_margin"
            or corporate_manifest.get("content_hash") != _content_hash(corporate_manifest)
            or resolved != corporate_declared
            or not resolved.is_dir()
            or not str(resolved).endswith("data/lake_sharadar")
        ):
            raise ValueError("alternate replay lake is not an authorized versioned correction")
        authorization = _operating_margin_authorization()
        if authorization["corrected_lake"] != corporate_manifest["corrected_lake"]:
            raise ValueError("alternate replay lake is not an authorized versioned correction")
        return {
            "lake_dir": corporate_manifest["corrected_lake"],
            "kind": "TRIAL_SPECIFIC_CORPORATE_ACTION_CORRECTION_FAIL_CLOSED",
            "global_split_gate_passed": False,
            "versioned_correction_manifest": str(CORPORATE_ACTION_LAKE_MANIFEST.relative_to(REPO)),
            "versioned_correction_manifest_sha256": _sha256(CORPORATE_ACTION_LAKE_MANIFEST),
            "versioned_correction_content_hash": corporate_manifest["content_hash"],
            "replay_authorization": str(OPERATING_MARGIN_REPLAY_AUTHORIZATION.relative_to(REPO)),
            "replay_authorization_sha256": _sha256(OPERATING_MARGIN_REPLAY_AUTHORIZATION),
            "replay_authorization_content_hash": authorization["content_hash"],
            "verified_split_events": authorization["verified_split_events"],
        }
    return {
        "lake_dir": str(lake_dir.relative_to(REPO) if lake_dir.is_absolute() else lake_dir),
        "kind": "VERSIONED_SHARADAR_HDB_ZERO_MARKER_QUARANTINE",
        "versioned_correction_manifest": str(CORRECTED_LAKE_MANIFEST.relative_to(REPO)),
        "versioned_correction_manifest_sha256": _sha256(CORRECTED_LAKE_MANIFEST),
        "versioned_correction_content_hash": manifest["content_hash"],
        "corrected_corporate_actions_root": manifest["lineage"]["corrected_corporate_actions_root"],
        "rows_quarantined": manifest["correction"]["rows_quarantined"],
        "cash_amount_imputed": manifest["correction"]["cash_amount_imputed"],
    }


def preflight(run_name: str, *, lake_dir: Path = BASE_LAKE) -> dict[str, Any]:
    identity = CANDIDATES[run_name]
    data_environment = _data_environment(lake_dir, run_name=run_name)
    artifact_dir = REPO / "artifacts" / "walkforward" / run_name
    artifact_path = artifact_dir / "walkforward.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    record = _first_records()[identity]
    if config_hash(record.config) != record.config_hash:
        raise ValueError("immutable ledger config hash does not reconcile")
    if any(artifact["config"].get(key) != value for key, value in record.config.items()):
        raise ValueError("preserved artifact config does not reconcile to immutable ledger")
    if (
        artifact["validation"]["n_obs"] != record.n_obs
        or artifact["validation"]["sr_ann"] != record.sharpe_ann
    ):
        raise ValueError("preserved artifact metrics do not reconcile to immutable ledger")
    ids = artifact["config"]["instrument_ids"]
    if len(ids) != 6_820 or any(not item.startswith("XUSE:") for item in ids):
        raise ValueError("candidate is not the corrected 6,820-id equity universe")
    measured_at = dt.datetime.fromtimestamp(record.now_ms / 1000, tz=dt.UTC)
    prereg_at = _commit_time(PREREG_COMMIT)
    if prereg_at >= measured_at:
        raise ValueError("preregistration does not predate the immutable measurement")
    assert_matches(
        PREREG,
        lake_dir=lake_dir,
        profile="sharadar",
        allocator=str(record.config["allocator"]),
    )
    return {
        "run_name": run_name,
        "hypothesis_key": identity,
        "record": record,
        "artifact": artifact,
        "artifact_dir": artifact_dir,
        "artifact_path": artifact_path,
        "preregistered_at": prereg_at.isoformat(),
        "measured_at": measured_at.isoformat(),
        "data_environment": data_environment,
    }


def _ledger_state() -> dict[str, int]:
    union = ExperimentUnion.discover(LEDGER, REPO)
    return {
        "active_rows": len(ExperimentLog(LEDGER).all()),
        "union_identities": union.n_hypotheses(),
    }


def _source_environment(
    lake_dir: Path = BASE_LAKE, *, run_name: str | None = None
) -> dict[str, Any]:
    paths = sorted((REPO / "src" / "alphaforge").rglob("*.py"))
    paths.extend(
        [
            Path(__file__).resolve(),
            REPO / "configs" / "base.yaml",
            REPO / "configs" / "sharadar.yaml",
            REPO / "pyproject.toml",
            REPO / "uv.lock",
            PREREG,
            OPERATING_MARGIN_REPLAY_AUTHORIZATION,
        ]
    )
    leaves = [
        {
            "path": str(path.relative_to(REPO)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(set(paths))
    ]
    payload: dict[str, Any] = {
        "schema": "canli.alphac-replay-source-environment.v1",
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "pyarrow", "scipy")
        },
        "source_files": len(leaves),
        "source_bytes": sum(item["bytes"] for item in leaves),
        "leaves": leaves,
        "data_environment": _data_environment(lake_dir, run_name=run_name),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return payload


def _exact_frame_match(original_path: Path, replay_path: Path) -> None:
    original = pd.read_parquet(original_path)
    replay = pd.read_parquet(replay_path)
    pd.testing.assert_frame_equal(original, replay, check_exact=True)


def replay(run_name: str, *, lake_dir: Path = BASE_LAKE) -> dict[str, Any]:
    audit = preflight(run_name, lake_dir=lake_dir)
    record = audit["record"]
    artifact = audit["artifact"]
    before = _ledger_state()
    corrected_mode = audit["data_environment"]["kind"] == (
        "TRIAL_SPECIFIC_CORPORATE_ACTION_CORRECTION_FAIL_CLOSED"
    )
    out_dir = REPO / "artifacts" / "probe" / "fundamental_single_replays" / audit["hypothesis_key"]
    if corrected_mode:
        auth_hash = audit["data_environment"]["replay_authorization_content_hash"].split(":")[1]
        out_dir = out_dir / f"corrected_corporate_actions_{auth_hash[:16]}"
        if (out_dir / "walkforward.json").exists():
            raise FileExistsError(f"corrected replay output already exists: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    environment = _source_environment(lake_dir, run_name=run_name)
    environment_path = out_dir / "replay_environment.json"
    environment_path.write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    import alphaforge.features.library  # noqa: F401
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.logging import setup_logging
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService

    settings = load_settings("sharadar")
    settings = settings.model_copy(
        update={"paths": settings.paths.model_copy(update={"lake_dir": lake_dir.resolve()})}
    )
    setup_logging(settings.paths.var_dir / "log")
    sleeve = sleeve_for(settings.data.asset_class)
    paths = LakePaths(settings.paths.lake_dir)
    alpha_names = list(record.config["alpha_names"])
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            default_registry(),
            settings.signals,
            sleeve=sleeve,
            alpha_names=alpha_names,
        )
        authorization = _operating_margin_authorization() if corrected_mode else None
        runner = WalkForwardRunner(
            reader,
            store,
            universe,
            TransactionCostModel.from_settings(settings),
            service,
            settings,
            verified_split_events=(
                _verified_split_events(authorization) if authorization is not None else None
            ),
        )
        runner.run(
            int(record.config["start"]),
            int(record.config["end"]),
            train_bars=int(record.config["train_bars"]),
            test_bars=int(record.config["test_bars"]),
            allocator=record.config["allocator"],
            embargo_bars=int(artifact["config"]["embargo_bars"]),
            initial_cash=float(artifact["config"]["initial_cash"]),
            instrument_ids=list(record.config["instrument_ids"]),
            rebalance_bars=int(record.config["rebalance_bars"]),
            no_trade_band=float(record.config["no_trade_band"]),
            out_dir=out_dir,
            now_ms=None,
            alpha_names=alpha_names,
            experiment_log=None,
        )

    after = _ledger_state()
    if after != before:
        raise RuntimeError(f"ledger changed during zero-trial replay: {before} -> {after}")
    environment_after = _source_environment(lake_dir, run_name=run_name)
    if environment_after["content_hash"] != environment["content_hash"]:
        raise RuntimeError("source environment changed while the replay was running")
    replay_path = out_dir / "walkforward.json"
    replay_artifact = json.loads(replay_path.read_text(encoding="utf-8"))
    if not corrected_mode:
        if replay_artifact.get("summary") != artifact.get("summary"):
            raise ValueError("replay summary differs from the preserved first measurement")
        _exact_frame_match(
            audit["artifact_dir"] / "equity.parquet",
            out_dir / "equity.parquet",
        )
    corrected_summary = replay_artifact["summary"]
    corrected_sharpe = corrected_summary["sharpe"]
    corrected_verdict = (
        "KILL" if corrected_mode and (corrected_sharpe is None or corrected_sharpe <= 0) else None
    )
    result = {
        "schema": (
            "canli.alphac-fundamental-single-corrected-reproduction.v1"
            if corrected_mode
            else "canli.alphac-fundamental-single-exact-replay.v1"
        ),
        "evidence_date": "2026-08-22",
        "author": "Arhan Canli",
        "hypothesis_key": audit["hypothesis_key"],
        "config_hash": record.config_hash,
        "verdict": corrected_verdict or "KILL",
        "exact_first_measurement_reproduced": not corrected_mode,
        "corrected_data_reproduction": corrected_mode,
        "hypotheses_spent": 0,
        "preregistered_at": audit["preregistered_at"],
        "first_measured_at": audit["measured_at"],
        "immutable_measurement": {
            "n_obs": record.n_obs,
            "annualized_sharpe": record.sharpe_ann,
            "maximum_drawdown": artifact["summary"]["max_dd"],
        },
        "corrected_measurement": corrected_summary if corrected_mode else None,
        "ledger_state_before_and_after": before,
        "lineage": {
            "preregistration_path": str(PREREG.relative_to(REPO)),
            "preregistration_sha256": _sha256(PREREG),
            "preserved_artifact_path": str(audit["artifact_path"].relative_to(REPO)),
            "preserved_artifact_sha256": _sha256(audit["artifact_path"]),
            "preserved_equity_sha256": _sha256(audit["artifact_dir"] / "equity.parquet"),
            "replay_artifact_sha256": _sha256(replay_path),
            "replay_equity_sha256": _sha256(out_dir / "equity.parquet"),
            "runner_sha256": _sha256(Path(__file__)),
            "source_environment_path": str(environment_path.relative_to(REPO)),
            "source_environment_sha256": _sha256(environment_path),
            "source_environment_content_hash": environment["content_hash"],
            "data_environment": environment["data_environment"],
            "walkforward_engine_sha256": _sha256(
                REPO / "src" / "alphaforge" / "analytics" / "walkforward.py"
            ),
            "pyproject_sha256": _sha256(REPO / "pyproject.toml"),
            "uv_lock_sha256": _sha256(REPO / "uv.lock"),
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
            ).strip(),
        },
        "claim_boundary": (
            "This is a zero-trial corrected-data reproduction of the immutable identity under a "
            "trial-specific fail-closed corporate-action authorization. The historical KILL "
            "remains immutable; the global lake split gate remains failed; this does not establish "
            "capacity, "
            "diversification, admission, or future performance."
            if corrected_mode
            else "This proves exact current-code reproduction of the preserved OOS curve and "
            "summary. "
            "It does not establish capacity, diversification, admission, or future performance."
        ),
    }
    result_path = out_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name", choices=tuple(CANDIDATES))
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--lake-dir", type=Path, default=BASE_LAKE)
    args = parser.parse_args()
    lake_dir = args.lake_dir if args.lake_dir.is_absolute() else REPO / args.lake_dir
    if args.preflight_only:
        audit = preflight(args.run_name, lake_dir=lake_dir)
        print(
            json.dumps(
                {
                    key: value
                    for key, value in audit.items()
                    if key not in {"record", "artifact", "artifact_dir", "artifact_path"}
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    result = replay(args.run_name, lake_dir=lake_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
