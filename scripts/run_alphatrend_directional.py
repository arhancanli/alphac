"""One preregistered development comparison on sealed, already-inspected AlphaTrend data."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def copy_bound(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if digest(source) != digest(destination):
            raise ValueError(f"Existing file differs; refusing overwrite: {destination}")
    else:
        shutil.copy2(source, destination)


def prepare():
    OUT.mkdir(parents=True, exist_ok=False)
    manifest_path = PRODUCTION / "artifacts/publication/alphatrend_upstream_replay_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for section in ("private_input_snapshot", "private_reference_output"):
        meta = manifest[section]
        for row in meta["records"]:
            path = PRODUCTION / meta["path"] / row["path"]
            if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
                raise ValueError(f"Sealed file drift: {path}")
    copy_bound(manifest_path, OUT / "input_manifest.json")
    source = PRODUCTION / manifest["private_input_snapshot"]["path"]
    shutil.copytree(source / "lake_mf", OUT / "lake_mf")
    copy_bound(source / "var_mf/ops.sqlite", OUT / "state/ops.sqlite")
    # Preserve the current complete selection union and its admission governance.
    # These are read-only source copies, never writes to production.
    paths = [
        *PRODUCTION.glob("var*/experiments.jsonl"),
        *PRODUCTION.glob("artifacts/**/experiments.jsonl"),
    ]
    for path in paths:
        rel = path.relative_to(PRODUCTION)
        if not any("archive" in part.casefold() for part in rel.parts):
            copy_bound(path, ROOT / rel)
    for path in (PRODUCTION / "artifacts/research").rglob("*"):
        if path.is_file():
            copy_bound(path, ROOT / path.relative_to(PRODUCTION))
    for name in (
        "sleeve_admission_contract.json",
        "trial_accounting.json",
        "admission_v7_promotion.json",
    ):
        copy_bound(PRODUCTION / "config" / name, ROOT / "config" / name)
    write(
        OUT / "environment.json",
        {
            "python": sys.version,
            "distributions": sorted(
                (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
            ),
        },
    )


def execute():
    import numpy as np
    import pandas as pd

    import alphaforge.features.library  # noqa: F401
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import parse_utc
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.research import zoo
    from alphaforge.signals.service import SignalService
    from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash
    from alphaforge.validation.trial_reservation import (
        _effective_contract_hash,
        validate_reservation,
    )

    zoo.register_all()
    settings = load_settings("managed_futures", root=ROOT)
    settings = settings.model_copy(
        update={
            "paths": settings.paths.model_copy(
                update={"lake_dir": OUT / "lake_mf", "var_dir": OUT / "state"}
            )
        }
    )
    frozen_settings = json.loads(
        (
            ROOT
            / "artifacts/analysis/alphatrend_cash_retention_20260912"
            / "baseline/input_snapshot/declared_run.json"
        ).read_text()
    )["resolved_settings"]
    current_settings = settings.model_dump(mode="json")
    if {k: v for k, v in current_settings.items() if k != "paths"} != {
        k: v for k, v in frozen_settings.items() if k != "paths"
    }:
        raise ValueError("Resolved settings differ from the preserved baseline")
    start, end = parse_utc("2003-01-01T00:00:00Z"), parse_utc("2026-08-24T00:00:00Z")
    alphas = ["mf_trend_63", "mf_trend_126", "mf_trend_252"]
    old_manifest = json.loads((OUT / "input_manifest.json").read_text())
    reference = PRODUCTION / old_manifest["private_reference_output"]["path"]
    old = json.loads((reference / "walkforward.json").read_text())
    ids = old["config"]["instrument_ids"]
    binding = {"trend_blend_normalization": "directional_rms"}
    config = {
        "start": start,
        "end": end,
        "train_bars": 504,
        "test_bars": 126,
        "allocator": "trend",
        "rebalance_bars": 10,
        "no_trade_band": 0.001,
        "instrument_ids": ids,
        "alpha_names": alphas,
        **binding,
    }
    prereg = {
        "reserved_at": datetime.now(UTC).isoformat(),
        "scope": "DEVELOPMENT_ALREADY_INSPECTED_DATA",
        "trial_config": config,
        "new_hypotheses": 1,
        "arms": ["baseline_cross_sectional_zscore", "candidate_directional_rms"],
        "execution_model": (
            "Both arms use identical existing NextOpenFill costs: 1bp commission, "
            "3bp halfspread, 2bp latency, impact coefficient 1 with actual lagged "
            "size/ADV/vol, 50bp modeled annual borrow and zero financing. No cost gate."
        ),
        "selection_rule": "Retain for further testing only if candidate net Sharpe and CAGR are both higher, maximum drawdown no worse, and annual turnover lower than baseline. Otherwise reject this construction under this scenario.",  # noqa: E501
        "forbidden_claims": [
            "untouched validation",
            "admission",
            "historically verified borrow availability",
        ],
        "parameter_search": False,
        "no_retries_with_changed_parameters": True,
        "runner_sha256": digest(Path(__file__)),
        "project_sha256": digest(ROOT / "pyproject.toml"),
        "lock_sha256": digest(ROOT / "uv.lock"),
        "environment_sha256": digest(OUT / "environment.json"),
    }
    prereg["signal_rule"] = (
        "Use the same causal IC weights and 63/126/252 horizon factors. "
        "Replace cross-sectional mean subtraction and sample-standard-deviation scaling "
        "with division by cross-sectional RMS, over complete PIT members only. "
        "Require at least five members; zero RMS stays missing. No mean subtraction, "
        "winsorization change, factor sign flip, cost gate or weight-estimation change. "
        "Unanimous nonzero directional signals remain usable. Trend allocation uses sign "
        "and inverse volatility; normalization magnitudes are not a cost forecast claim."
    )
    prereg["comparison_to_prior_trial"] = (
        "Prior filters remain rejected and counted. Audit found a direction mismatch; "
        "this new identity tests the directional mechanism with the same baseline, "
        "universe, costs, cadence and acceptance rule. Already-inspected development data."
    )
    prereg["audit_evidence_sha256"] = digest(
        ROOT / "artifacts/analysis/alphatrend_forecast_audit_20260912/results.json"
    )
    prior = json.loads(
        (
            ROOT / "artifacts/analysis/alphatrend_cash_retention_20260912" / "preregistration.json"
        ).read_text()
    )
    if prereg["selection_rule"] != prior["selection_rule"]:
        raise ValueError("The comparison rule must not change after the earlier result")
    implementation_paths = {
        "signal_service": ROOT / "src/alphaforge/signals/service.py",
        "blend_implementation": ROOT / "src/alphaforge/signals/blending.py",
        "walkforward_implementation": ROOT / "src/alphaforge/analytics/walkforward.py",
        "forecast_audit": ROOT
        / "artifacts/analysis/alphatrend_forecast_audit_20260912/results.json",
    }
    prereg["implementation_evidence"] = {
        name: {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}
        for name, path in implementation_paths.items()
    }
    prereg["preparation_history"] = (
        "First preparation rejected extra reservation evidence keys before returns; "
        "implementation bindings moved into preregistration. No parameter or rule change."
    )
    write(OUT / "preregistration.json", prereg)
    evidence_paths = {
        "preregistration": OUT / "preregistration.json",
        "input_data_manifest": OUT / "input_manifest.json",
        "runner": Path(__file__),
        "python_project": ROOT / "pyproject.toml",
        "locked_environment": ROOT / "uv.lock",
    }
    contract = json.loads((ROOT / "config/sleeve_admission_contract.json").read_text())
    reservation = {
        "schema": "canli.alphac-forward-trial-reservation.v1",
        "status": "RETURN_IDENTITY_RESERVED",
        "reserved_at": prereg["reserved_at"],
        "family_trial_account": "managed_futures_trend",
        "return_identity_id": "alphatrend_directional_20260912",
        "hypotheses_spent": 1,
        "trial_config": config,
        "hypothesis_identity": hypothesis_hash(config),
        "packet_public_path": "/glassbox/trial-packets/alphatrend-directional-20260912",
        "paper_public_path": "/research/alphatrend-directional-20260912",
        "evidence": {
            k: {"path": str(p.relative_to(ROOT)), "sha256": digest(p)}
            for k, p in evidence_paths.items()
        },
        "governance_epoch": {
            "effective_contract_hash": _effective_contract_hash(contract),
            "reservation_ordinal": 232,
        },
    }
    for key, name in [
        ("admission_contract", "sleeve_admission_contract.json"),
        ("trial_policy", "trial_accounting.json"),
        ("promotion_receipt", "admission_v7_promotion.json"),
    ]:
        reservation["governance_epoch"][key + "_path"] = "config/" + name
        reservation["governance_epoch"][key + "_sha256"] = digest(ROOT / "config" / name)
    write(OUT / "reservation.json", reservation)
    validation = validate_reservation(reservation, trial_config=config, repo=ROOT)
    write(OUT / "reservation_validation.json", validation)
    print(
        "Reservation validated before returns: identity " + reservation["hypothesis_identity"],
        flush=True,
    )
    log = ExperimentUnion.discover(OUT / "experiments.jsonl", ROOT)
    log.preflight_registration(config, reservation_path=OUT / "reservation.json")
    write(
        OUT / "selection_union_before.json",
        {
            "hypotheses": log.n_hypotheses(),
            "files": [
                {"path": str(p.relative_to(ROOT)), "sha256": digest(p)}
                for p in log.paths
                if p.exists()
            ],
        },
    )
    paths = LakePaths(settings.paths.lake_dir)
    results = {}
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        for name, normalization in [
            ("baseline", "cross_sectional_zscore"),
            ("candidate", "directional_rms"),
        ]:
            print("Running " + name + " on sealed inputs", flush=True)
            reader = PITDataReader(paths)
            universe = UniverseStore(paths)
            service = SignalService(
                FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
                universe,
                default_registry(),
                settings.signals,
                alpha_names=alphas,
                sleeve=sleeve_for(settings.data.asset_class),
                blend_normalization=normalization,
            )
            runner = WalkForwardRunner(
                reader,
                store,
                universe,
                TransactionCostModel.from_settings(settings),
                service,
                settings,
            )
            result = runner.run(
                start,
                end,
                train_bars=504,
                test_bars=126,
                allocator="trend",
                embargo_bars=21,
                initial_cash=100000.0,
                instrument_ids=ids,
                rebalance_bars=10,
                no_trade_band=0.001,
                out_dir=OUT / name,
                now_ms=int(datetime.now(UTC).timestamp() * 1000),
                alpha_names=alphas,
                experiment_log=log,
                trial_reservation=OUT / "reservation.json" if name == "candidate" else None,
            )
            results[name] = result
            print("Completed " + name, flush=True)
    a, b = results["baseline"].summary, results["candidate"].summary
    fields = [
        "sharpe",
        "cagr",
        "max_dd",
        "turnover_ann",
        "vol_ann",
        "fees_paid",
        "final_equity",
        "total_return",
    ]
    comparison = {
        name: {f: float(getattr(result.summary, f)) for f in fields}
        for name, result in results.items()
    }
    comparison["delta"] = {
        f: comparison["candidate"][f] - comparison["baseline"][f] for f in fields
    }
    keep = (
        b.sharpe > a.sharpe
        and b.cagr > a.cagr
        and b.max_dd <= a.max_dd
        and b.turnover_ann < a.turnover_ann
    )
    reference_equity = pd.read_parquet(reference / "equity.parquet").equity.to_numpy()
    current = results["baseline"].equity.to_numpy()
    comparison.update(
        disposition="RETAIN_FOR_FURTHER_TESTING" if keep else "REJECT_UNDER_FROZEN_SCENARIO",
        claim_boundary="One registered development trial, reused data, no admission or untouched validation",  # noqa: E501
        baseline_reference_max_equity_difference=float(np.max(np.abs(reference_equity - current)))
        if len(current) == len(reference_equity)
        else None,
        union_hypotheses_after=log.n_hypotheses(),
        new_hypotheses=1,
    )
    write(OUT / "comparison.json", comparison)
    print(json.dumps(comparison, indent=2), flush=True)


if __name__ == "__main__":
    prepare()
    execute()
