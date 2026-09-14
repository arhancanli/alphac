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
OUT = ROOT / "artifacts/analysis/alphamax_total_return_momentum_20260913"
DESIGN = ROOT / "evidence/alphamax-total-return-integration-20260913/EXPERIMENT_SPEC.json"


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
    from dataclasses import fields
    from alphaforge.core.instruments import Instrument
    from alphaforge.core.types import AssetClass, MarketType
    snapshot = ROOT / "evidence/core-2023-2026-frozen-inputs-20260913"
    manifest = json.loads((snapshot / "manifest.json").read_text())
    design = json.loads(DESIGN.read_text())
    verify(snapshot / "manifest.json", design["snapshot_manifest_sha256"])
    for path, expected in manifest["output_sha256"].items():
        verify(snapshot / path, expected)
    OUT.mkdir(parents=True, exist_ok=False)
    state = OUT / "state"
    state.mkdir()
    settings_path = snapshot / "references/9_settings.json"
    settings = Settings(**json.loads(settings_path.read_text()))
    original_settings = settings.model_dump(mode="json")
    risk_values = settings.risk.model_dump()
    assert risk_values['flat_cooldown_bars'] == 336
    risk_values['flat_cooldown_bars'] = 10
    settings = settings.model_copy(update={'risk': type(settings.risk)(**risk_values)})
    expected = copy.deepcopy(original_settings)
    expected['risk']['flat_cooldown_bars'] = 10
    assert settings.model_dump(mode="json") == expected
    for path, digest in design['source_sha256'].items():
        verify(ROOT/path, digest)
    write(state / "settings.json", settings.model_dump(mode="json"))
    metadata_path = snapshot / "references/2_instrument_versions.json"
    latest = {r["instrument_id"]: r for r in json.loads(metadata_path.read_text())}
    field_names = {f.name for f in fields(Instrument)}
    for multiplier in [1, 2]:
        with InstrumentStore(state / f"ops_cost{multiplier}.sqlite") as store:
            for iid in design["scope"]["instrument_ids"]:
                values = {k: v for k, v in latest[iid].items() if k in field_names}
                values["asset_class"] = AssetClass(values["asset_class"])
                values["market_type"] = MarketType(values["market_type"])
                values["can_short"] = bool(values["can_short"])
                values["maker_fee_bps"] *= multiplier
                values["taker_fee_bps"] *= multiplier
                store.upsert(Instrument(**values), as_of=1)
    write(state / "metadata_model.json", {"mode": "MODELED_HISTORICAL_APPLICABILITY_NOT_OBSERVED_PIT", "compiled_as_of": 1, "source_sha256": sha(metadata_path), "cost2": "Metadata fees doubled; lifecycle unchanged"})
    inputs = {str((snapshot / p).relative_to(ROOT)): h for p, h in manifest["output_sha256"].items()}
    files = [snapshot / "manifest.json", DESIGN, Path(__file__), ROOT / "pyproject.toml", ROOT / "uv.lock"]
    files += sorted((ROOT / "src/alphaforge").rglob("*.py"))
    files += [ROOT / "scripts" / p for p in ["alphamax_replay_support_v2.py", "alphamax_share_ratio_service.py", "alphamax_share_ratio_features.py", "alphamax_covariance_engine.py", "alphamax_session_price_basis.py", "alphamax_total_return_momentum.py", "alphamax_total_return_service.py"]]
    files += [p for p in state.rglob("*") if p.is_file()]
    for p in files:
        inputs[str(p.relative_to(ROOT))] = sha(p)
    write(OUT / "protocol.json", design)
    write(OUT / "input_manifest.json", {"sha256": inputs, "protocol_sha256": sha(OUT / "protocol.json"), "metadata_mode": "MODELED_HISTORICAL_APPLICABILITY_NOT_OBSERVED_PIT", "information_timing": "Research bar-close availability; source-session equity alignment required; historical corporate-action and borrow limits retained"})
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
    if arm_id != "candidate":
        raise ValueError("Stress execution requires a separately bound gate after normal combined passes")
    from alphamax_covariance_engine import covariance_engine_factory
    from alphamax_replay_support_v2 import TailSafeWalkForwardRunner
    from alphamax_total_return_service import TotalReturnMomentumSignalService

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
        family_trial_account="alphamax_total_return_momentum",
        return_identity_id=f"alphamax_total_return_momentum_{arm_id}_20260913",
        packet_public_path=f"/glassbox/trial-packets/alphamax-total-return-momentum-{arm_id}-20260913",
        paper_public_path=f"/research/alphamax-total-return-momentum-{arm_id}-20260913",
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
    paths = LakePaths(ROOT / "evidence/core-2023-2026-frozen-inputs-20260913/lake")
    factory = covariance_engine_factory(directory / "durable_legs", arm["covariance_basis"])
    with InstrumentStore(OUT / f"state/ops_cost{multiplier}.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        registry = default_registry()
        service = TotalReturnMomentumSignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            registry,
            settings.signals,
            correction_mode=arm["correction_mode"],
            total_return_mode="candidate",
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
