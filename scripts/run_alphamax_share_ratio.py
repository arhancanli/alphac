"""Frozen AlphaMax full2022 current-input baseline; prepare and preflight compute no signals."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from alphaforge.config.settings import Settings
from alphaforge.core.instruments import InstrumentStore

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "evidence/crypto-terminal-inputs-20260913"
OUT = ROOT / "artifacts/analysis/alphamax_share_ratio_20260913"
DESIGN = ROOT / "evidence/alphamax-share-ratio-20260913/EXPERIMENT_SPEC.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def verify(path, expected):
    if sha(path) != expected:
        raise ValueError(f"Hash mismatch: {path}")


def prepare():
    previous = ROOT / "artifacts/analysis/alphamax_full2022_baseline_v2_20260913"
    original = json.loads((previous / "input_manifest.json").read_text())
    for path, expected in original["sha256"].items():
        verify(ROOT / path, expected)
    OUT.mkdir(parents=True, exist_ok=False)
    shutil.copytree(previous / "state", OUT / "state")
    inputs = {
        str(p.relative_to(ROOT)): sha(p) for p in sorted((OUT / "state").rglob("*")) if p.is_file()
    }
    for path, expected in original["sha256"].items():
        if not str(ROOT / path).startswith(str(previous / "state")):
            inputs[path] = expected
    for p in [
        DESIGN,
        Path(__file__),
        ROOT / "scripts/alphamax_replay_support_v2.py",
        previous / "input_manifest.json",
        previous / "baseline/closure.json",
        ROOT / "tests/unit/test_alphamax_replay_support_v2.py",
        ROOT / "scripts/alphamax_share_ratio_service.py",
        ROOT / "scripts/alphamax_share_ratio_features.py",
        ROOT / "tests/unit/test_alphamax_share_ratio_features.py",
        ROOT / "tests/unit/test_alphamax_share_ratio_service.py",
        ROOT / "evidence/alphamax-share-ratio-correction-20260913/closure.json",
    ]:
        inputs[str(p.relative_to(ROOT))] = sha(p)
    design = json.loads(DESIGN.read_text())
    write(OUT / "protocol.json", design)
    manifest = dict(original)
    manifest.update(
        sha256=inputs, protocol_sha256=sha(OUT / "protocol.json"), design_sha256=sha(DESIGN)
    )
    write(OUT / "input_manifest.json", manifest)
    print(json.dumps({"status": "PREPARED_NO_SIGNALS_OR_RETURNS", "bound_files": len(inputs)}))


def preflight(arm_id):
    if any(key.startswith("AF_") for key in os.environ):
        raise ValueError("AF environment overrides forbidden for frozen comparison")
    manifest = json.loads((OUT / "input_manifest.json").read_text())
    for path, expected in manifest["sha256"].items():
        verify(ROOT / path, expected)
    design = json.loads((OUT / "protocol.json").read_text())
    verify(OUT / "protocol.json", manifest["protocol_sha256"])
    arm = next(a for a in design["arms"] if a["id"] == arm_id)
    scope = design["scope"]
    binding = {
        "scenario": arm,
        "tail_policy": "merge_singleton_into_previous_keep_previous_training_v1",
        "leg_persistence": "save_each_engine_result_before_next_leg_v1",
        "input_manifest_sha256": sha(OUT / "input_manifest.json"),
        "design_source_sha256": sha(DESIGN),
        "metadata_mode": manifest["metadata_mode"],
        "timing_mode": manifest["information_timing"],
    }
    trial = {
        k: scope[k]
        for k in [
            "start",
            "end",
            "train_bars",
            "test_bars",
            "allocator",
            "rebalance_bars",
            "instrument_ids",
            "alpha_names",
        ]
    }
    trial["no_trade_band"] = 0.001
    trial["research_engine"] = binding
    return arm, trial


def execute(arm_id):
    from alphamax_replay_support_v2 import TailSafeWalkForwardRunner, persisting_engine_factory
    from alphamax_share_ratio_service import ShareRatioSignalService

    import alphaforge.features.library.equity_price  # noqa: F401
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash
    from alphaforge.validation.trial_reservation import validate_reservation

    arm, trial = preflight(arm_id)
    directory = OUT / arm_id
    directory.mkdir(exist_ok=False)
    log = ExperimentUnion.discover(directory / "experiments.jsonl", ROOT)
    reservation = copy.deepcopy(
        json.loads(
            (
                ROOT
                / "artifacts/analysis/alphatrend_category_targets_20260913"
                / "baseline/reservation.json"
            ).read_text()
        )
    )
    now = datetime.now(UTC)
    reservation.update(
        reserved_at=now.isoformat(),
        trial_config=trial,
        hypothesis_identity=hypothesis_hash(trial),
        family_trial_account="alphamax_share_ratio",
        return_identity_id=f"alphamax_share_ratio_{arm_id}_20260913",
        packet_public_path=f"/glassbox/trial-packets/alphamax-share-ratio-{arm_id}-20260913",
        paper_public_path=f"/research/alphamax-share-ratio-{arm_id}-20260913",
    )
    reservation["governance_epoch"]["reservation_ordinal"] = log.n_hypotheses() + 1
    write(
        directory / "preregistration.json",
        {
            "trial_config": trial,
            "reserved_at": now.isoformat(),
            "protocol_sha256": sha(OUT / "protocol.json"),
        },
    )
    evidence = {
        "preregistration": directory / "preregistration.json",
        "input_data_manifest": OUT / "input_manifest.json",
        "runner": Path(__file__),
        "python_project": ROOT / "pyproject.toml",
        "locked_environment": ROOT / "uv.lock",
    }
    reservation["evidence"] = {
        k: {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for k, p in evidence.items()
    }
    write(directory / "reservation.json", reservation)
    write(
        directory / "reservation_validation.json",
        validate_reservation(reservation, trial_config=trial, repo=ROOT),
    )
    log.preflight_registration(trial, reservation_path=directory / "reservation.json")
    multiplier = arm.get("execution_cost_multiplier", 1)
    settings = Settings(**json.loads((OUT / "state/settings.json").read_text()))
    costs = settings.costs.model_dump()
    for key in [
        "equity_commission_bps",
        "equity_half_spread_bps",
        "equity_borrow_bps_annual",
        "impact_coef",
        "latency_addon_bps",
    ]:
        costs[key] *= multiplier
    settings = settings.model_copy(update={"costs": type(settings.costs)(**costs)})
    paths = LakePaths(OUT / "state" / arm["data"])
    factory = persisting_engine_factory(directory / "durable_legs")
    with InstrumentStore(OUT / f"state/ops_cost{multiplier}.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        registry = default_registry()
        service = ShareRatioSignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            registry,
            settings.signals,
            correction_mode=arm["correction_mode"],
            sleeve=sleeve_for(settings.data.asset_class),
            alpha_names=trial["alpha_names"],
        )
        result = TailSafeWalkForwardRunner(
            reader,
            store,
            universe,
            TransactionCostModel.from_settings(settings),
            service,
            settings,
            engine_factory=factory,
            engine_research_config=trial["research_engine"],
        ).run(
            trial["start"],
            trial["end"],
            train_bars=trial["train_bars"],
            test_bars=trial["test_bars"],
            allocator=trial["allocator"],
            embargo_bars=274,
            initial_cash=100000.0,
            instrument_ids=trial["instrument_ids"],
            rebalance_bars=trial["rebalance_bars"],
            no_trade_band=trial["no_trade_band"],
            out_dir=directory / "run",
            now_ms=int(now.timestamp() * 1000),
            alpha_names=trial["alpha_names"],
            experiment_log=log,
            trial_reservation=directory / "reservation.json",
        )
    write(
        directory / "execution_complete.json",
        {
            "status": "MEASURED_AWAITING_INDEPENDENT_AUDIT_AND_PACKET",
            "legs": len(result.legs),
            "qualified": False,
        },
    )
    print(f"{arm_id}: measured; independent audit and packet closure required before next arm.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--arm")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.arm:
        if args.execute:
            execute(args.arm)
        else:
            _, trial = preflight(args.arm)
            print(json.dumps({"status": "PREFLIGHT_NO_SIGNALS_OR_RETURNS", "trial_config": trial}))
    else:
        parser.error("Choose --prepare or --arm")


if __name__ == "__main__":
    main()
