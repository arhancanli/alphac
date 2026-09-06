#!/usr/bin/env python3
"""Dry-run by default; execute one reserved crypto_carry_portable_v1 trial explicitly."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
RUN_CONFIG: Final = ROOT / "config/crypto_carry_portable_v1_run.json"
AUTHORIZATION_TOKEN: Final = "SPEND_EXACTLY_ONE_CRYPTO_CARRY_PORTABLE_V1_IDENTITY"


class PortableRunError(RuntimeError):
    """The governed portable trial is not exactly ready or explicitly armed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PortableRunError(f"required JSON is missing: {path}")
    try:
        document = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise PortableRunError(f"required JSON is unreadable: {path}") from error
    if document.get("content_hash") != _content_hash(document):
        raise PortableRunError(f"content hash mismatch: {path}")
    return document


def _bound_file(repo: Path, binding: dict[str, Any]) -> Path:
    relative = str(binding["path"])
    path = (repo / relative).resolve()
    try:
        path.relative_to(repo.resolve())
    except ValueError as error:
        raise PortableRunError(f"bound path escapes repository: {relative}") from error
    if not path.is_file() or _sha256(path) != binding["sha256"]:
        raise PortableRunError(f"bound file hash drifted: {relative}")
    return path


def _verify_private_lake(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    public_receipt_path = _bound_file(repo, config["bindings"]["portable_lake_readiness"])
    receipt = _verified_json(public_receipt_path)
    expected_receipt_hash = config["bindings"]["portable_lake_readiness"]["content_hash"]
    if receipt["content_hash"] != expected_receipt_hash:
        raise PortableRunError("portable lake readiness content binding drifted")
    private_root = (repo / config["private_lake_root"]).resolve()
    manifest_path = private_root / "portable_lake_manifest.json"
    manifest = _verified_json(manifest_path)
    public_binding = receipt["private_lake_binding"]
    if (
        _sha256(manifest_path) != public_binding["manifest_sha256"]
        or manifest["content_hash"] != public_binding["manifest_content_hash"]
    ):
        raise PortableRunError("private portable lake manifest drifted from public receipt")
    observed_leaves = []
    for path in sorted((private_root / "lake").rglob("data.parquet")):
        observed_leaves.append(
            {
                "path": str(path.relative_to(private_root)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if observed_leaves != manifest["output_inventory"]["leaves"]:
        raise PortableRunError("private portable lake leaf inventory drifted")
    ops = private_root / "ops.sqlite"
    if not ops.is_file() or _sha256(ops) != manifest["output_inventory"]["ops_sqlite_sha256"]:
        raise PortableRunError("private portable instrument store drifted")
    return manifest


def preflight(repo: Path, config_path: Path) -> dict[str, Any]:
    repo = repo.resolve()
    config = _verified_json(config_path)
    if config.get("schema") != "canli.alphac-crypto-carry-portable-run.v1":
        raise PortableRunError("portable run config schema mismatch")
    if config.get("status") != "FROZEN_BEFORE_RETURN_COMPUTE":
        raise PortableRunError("portable run config is not frozen")
    forbidden_env = sorted(name for name in os.environ if name.startswith("AF_"))
    if forbidden_env:
        raise PortableRunError(f"AlphaForge environment overrides are forbidden: {forbidden_env}")
    for binding in config["bindings"].values():
        _bound_file(repo, binding)
    manifest = _verify_private_lake(repo, config)
    if config["trial_config"]["instrument_ids"] != manifest["construction"]["instrument_ids"]:
        raise PortableRunError("trial instrument ids differ from the sealed private lake")

    from alphaforge.validation.experiments import config_hash, hypothesis_hash
    from alphaforge.validation.prereg import assert_matches

    prereg_path = repo / config["bindings"]["preregistration"]["path"]
    assert_matches(
        prereg_path,
        profile="base",
        lake_dir=repo / config["private_lake_root"] / "lake",
        alpha_names=cast(list[str], config["trial_config"]["alpha_names"]),
        allocator=str(config["trial_config"]["allocator"]),
        extra={
            "return_identity_id": config["return_identity_id"],
            "instrument_count": len(config["trial_config"]["instrument_ids"]),
            "train_bars": config["trial_config"]["train_bars"],
            "test_bars": config["trial_config"]["test_bars"],
            "rebalance_bars": config["trial_config"]["rebalance_bars"],
        },
    )
    trial_config = cast(dict[str, Any], config["trial_config"])
    if config["config_hash"] != config_hash(trial_config):
        raise PortableRunError("frozen config_hash does not match trial_config")
    if config["hypothesis_identity"] != hypothesis_hash(trial_config):
        raise PortableRunError("frozen hypothesis_identity does not match trial_config")

    reservation_path = repo / config["reservation_path"]
    reservation_status = "MISSING_RETURN_BLOCKED"
    reservation_validation: dict[str, Any] | None = None
    if reservation_path.is_file():
        from alphaforge.validation.trial_reservation import validate_reservation

        reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
        reservation_validation = validate_reservation(
            reservation, trial_config=trial_config, repo=repo
        )
        reservation_status = str(reservation_validation["status"])

    output = repo / config["output_path"]
    if output.exists():
        raise PortableRunError(f"return output path already exists: {output}")
    return {
        "status": (
            "PASS_EXACT_TRIAL_PREFLIGHT_RETURN_REQUIRES_EXPLICIT_ARMING"
            if reservation_validation is not None
            else "PASS_DATA_AND_CONFIG_PREFLIGHT_RESERVATION_MISSING_RETURN_BLOCKED"
        ),
        "return_identity_id": config["return_identity_id"],
        "config_hash": config["config_hash"],
        "hypothesis_identity": config["hypothesis_identity"],
        "instrument_count": len(trial_config["instrument_ids"]),
        "walkforward_legs": config["expected_walkforward_legs"],
        "reservation_status": reservation_status,
        "reservation_validation": reservation_validation,
        "output_path_absent": True,
        "return_metrics_computed": False,
        "hypotheses_spent": 0,
    }


def execute(repo: Path, config_path: Path) -> None:
    preflight_result = preflight(repo, config_path)
    if preflight_result["reservation_status"] != "VALIDATED_BEFORE_RETURN_COMPUTE":
        raise PortableRunError("return execution requires a validated reservation")
    config = _verified_json(config_path)
    trial = config["trial_config"]
    engine = config["engine_config"]

    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import now_ms
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService
    from alphaforge.validation.experiments import ExperimentUnion

    settings = load_settings(root=repo)
    private_root = repo / config["private_lake_root"]
    paths_cfg = settings.paths.model_copy(
        update={
            "lake_dir": private_root / "lake",
            "var_dir": repo / "var",
            "artifacts_dir": repo / "artifacts",
        }
    )
    settings = settings.model_copy(update={"paths": paths_cfg})
    paths = LakePaths(paths_cfg.lake_dir)
    output = repo / config["output_path"]
    reservation = repo / config["reservation_path"]
    experiment_union = ExperimentUnion.discover(repo / "var/experiments.jsonl", repo)
    with InstrumentStore(private_root / "ops.sqlite") as instruments:
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(
                PITDataReader(paths),
                instruments,
                universe,
                asset_class=settings.data.asset_class,
            ),
            universe,
            default_registry(),
            settings.signals,
            sleeve=sleeve_for(settings.data.asset_class),
            alpha_names=trial["alpha_names"],
        )
        result = WalkForwardRunner(
            PITDataReader(paths),
            instruments,
            universe,
            TransactionCostModel.from_settings(settings),
            service,
            settings,
        ).run(
            trial["start"],
            trial["end"],
            train_bars=trial["train_bars"],
            test_bars=trial["test_bars"],
            allocator=trial["allocator"],
            embargo_bars=engine["embargo_bars"],
            initial_cash=engine["initial_cash"],
            instrument_ids=trial["instrument_ids"],
            rebalance_bars=trial["rebalance_bars"],
            no_trade_band=trial["no_trade_band"],
            cov_window_bars=engine["cov_window_bars"],
            cov_halflife_days=engine["cov_halflife_days"],
            cov_min_periods=engine["cov_min_periods"],
            out_dir=output,
            now_ms=now_ms(),
            alpha_names=trial["alpha_names"],
            experiment_log=experiment_union,
            ml=False,
            regime=False,
            trial_reservation=reservation,
        )
    print(json.dumps(dataclasses.asdict(result.summary), indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=RUN_CONFIG)
    parser.add_argument("--execute-return-trial", action="store_true")
    parser.add_argument("--authorization-token")
    args = parser.parse_args()
    if not args.execute_return_trial:
        print(json.dumps(preflight(ROOT, args.config), indent=2, sort_keys=True))
        return
    if args.authorization_token != AUTHORIZATION_TOKEN:
        raise PortableRunError(
            "explicit execution requires --authorization-token " + AUTHORIZATION_TOKEN
        )
    execute(ROOT, args.config)


if __name__ == "__main__":
    main()
