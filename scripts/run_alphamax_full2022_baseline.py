"""Frozen AlphaMax full2022 current-input baseline; prepare and preflight compute no signals."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

from alphaforge.config.settings import Settings
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "evidence/crypto-terminal-inputs-20260913"
OUT = ROOT / "artifacts/analysis/alphamax_full2022_baseline_20260913"
DESIGN = ROOT / "evidence/alphamax-full2022-baseline-20260913/EXPERIMENT_SPEC.json"


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
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    from alphaforge.config.settings import load_settings

    OUT.mkdir(parents=True, exist_ok=False)
    design = json.loads(DESIGN.read_text())
    dep_root = ROOT / "evidence/alphamax-warmup-dependencies-20260913"
    metadata_path = dep_root / "instrument_versions.json"
    dependency = json.loads((dep_root / "summary.json").read_text())
    verify(metadata_path, dependency["metadata_snapshot_sha256"])
    records = json.loads(metadata_path.read_text())
    latest = {row["instrument_id"]: row for row in records}
    ids = sorted(latest)
    assert ids == design["scope"]["instrument_ids"]
    prod = Path("/Users/arhancanli/alphaforge")
    build = prod / "artifacts/audit/sharadar_corporate_action_corrected_lake.json"
    source_lake = prod / json.loads(build.read_text())["corrected_lake"]
    state = OUT / "state"
    state.mkdir()
    source_bindings = {}
    for iid in ids:
        for year in range(2010, 2023):
            relative = Path("ohlcv_1d") / f"instrument_id={iid}" / f"year={year}" / "data.parquet"
            source = source_lake / relative
            if source.exists():
                destination = state / "corrected_snapshot" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                before = sha(source)
                shutil.copyfile(source, destination)
                verify(destination, before)
                source_bindings[str(source)] = before
    membership_path = ROOT / "evidence/historical-extension-inputs-20260913/membership_rows.parquet"
    membership = pd.read_parquet(membership_path)
    membership = membership[(membership.sleeve == "k30_dn_63") & membership.instrument_id.isin(ids)]
    for row in membership.drop_duplicates("path").itertuples():
        source = Path(row.path)
        verify(source, row.sha256)
        relative = source.relative_to(prod / "data/lake")
        destination = state / "corrected_snapshot" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        source_bindings[str(source)] = row.sha256
    action_rows = 0
    for iid in ids:
        for year in range(2019, 2023):
            relative = (
                Path("corporate_actions") / f"instrument_id={iid}" / f"year={year}" / "data.parquet"
            )
            source = source_lake / relative
            if not source.exists():
                continue
            source_bindings[str(source)] = sha(source)
            table = pq.ParquetFile(source).read()
            dates = (
                table.column("ex_date").to_pandas().astype("datetime64[ms, UTC]").astype("int64")
            )
            selected = table.take(
                pa.array(
                    [
                        int(i)
                        for i in dates.index[(dates >= 1577664000000) & (dates < 1672531200000)]
                    ],
                    type=pa.int64(),
                )
            )
            if selected.num_rows:
                destination = state / "corrected_snapshot" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(selected, destination)
                action_rows += selected.num_rows
    names = {field.name for field in fields(Instrument)}
    for multiplier in [1, 2]:
        with InstrumentStore(state / f"ops_cost{multiplier}.sqlite") as store:
            for row in latest.values():
                values = {k: v for k, v in row.items() if k in names}
                values["asset_class"] = AssetClass(values["asset_class"])
                values["market_type"] = MarketType(values["market_type"])
                values["can_short"] = bool(values["can_short"])
                values["maker_fee_bps"] *= multiplier
                values["taker_fee_bps"] *= multiplier
                store.upsert(Instrument(**values), as_of=1)
    legacy = ROOT / "artifacts/analysis/alphamax_durable_replay_20260912/workspace"
    settings = load_settings("equity", root=legacy)
    assert settings.portfolio.rank_top_k == 30
    assert settings.portfolio.dollar_neutral and settings.signals.horizon_bars == 21
    write(state / "settings.json", settings.model_dump(mode="json"))
    write(
        state / "metadata_model.json",
        {
            "source_versions": records,
            "compiled_as_of": 1,
            "meaning": "Latest metadata modeled historically; epoch1 is compatibility index, not observed time.",
            "terminal_policy": "Retain original date labels and bars; parent final-recorded-close administrative liquidation modeled, not actual acquisition proceeds.",
            "action_filter": "Corrected source ex_date >=2019-12-30 and <2023-01-01; original excluded records retained in source bindings.",
        },
    )
    write(OUT / "source_lineage.json", {"sha256": source_bindings, "action_rows": action_rows})
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in sorted(state.rglob("*")) if p.is_file()}
    refs = [
        DESIGN,
        metadata_path,
        membership_path,
        build,
        OUT / "source_lineage.json",
        legacy / "configs/base.yaml",
        legacy / "configs/equity.yaml",
        ROOT / "evidence/alphamax-full-context-grid-20260913/closure.json",
        ROOT / "evidence/alphamax-corporate-action-route-20260913/closure.json",
    ]
    for p in refs:
        inputs[str(p)] = sha(p)
    for p in sorted((ROOT / "src/alphaforge").rglob("*.py")):
        inputs[str(p.relative_to(ROOT))] = sha(p)
    for p in [Path(__file__), ROOT / "pyproject.toml", ROOT / "uv.lock"]:
        inputs[str(p.relative_to(ROOT))] = sha(p)
    write(OUT / "protocol.json", design)
    write(
        OUT / "input_manifest.json",
        {
            "sha256": inputs,
            "protocol_sha256": sha(OUT / "protocol.json"),
            "design_sha256": sha(DESIGN),
            "metadata_mode": "MODELED_LATEST_METADATA_NOT_OBSERVED_PIT",
            "information_timing": "Current-vintage source; corrected dividend basis; modeled ex-date availability and final recorded close settlement.",
            "qualification": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "PREPARED_NO_SIGNALS_OR_RETURNS",
                "bound_files": len(inputs),
                "action_rows": action_rows,
                "instruments": len(ids),
            }
        )
    )


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
    import alphaforge.features.library.equity_price  # noqa: F401
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.backtest.engine import EventDrivenBacktester
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService
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
        family_trial_account="alphamax_full2022_baseline",
        return_identity_id=f"alphamax_full2022_{arm_id}_20260913",
        packet_public_path=f"/glassbox/trial-packets/alphamax-full2022-{arm_id}-20260913",
        paper_public_path=f"/research/alphamax-full2022-{arm_id}-20260913",
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
    factory = EventDrivenBacktester
    with InstrumentStore(OUT / f"state/ops_cost{multiplier}.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        registry = default_registry()
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            registry,
            settings.signals,
            sleeve=sleeve_for(settings.data.asset_class),
            alpha_names=trial["alpha_names"],
        )
        result = WalkForwardRunner(
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
