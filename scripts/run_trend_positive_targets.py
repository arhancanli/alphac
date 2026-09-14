"""Registered positive-target comparison against confirmed controls."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from scipy.stats import kurtosis, skew

from alphaforge.analytics.session_metrics import summarize_equity_sessions
from alphaforge.config.settings import Settings, load_settings
from alphaforge.config.sleeve import sleeve_for
from alphaforge.core.instruments import InstrumentStore
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import default_registry
from alphaforge.portfolio.trend_positive_targets import PositiveTargetsStrategy
from alphaforge.research.zoo import register_mf_trend_grid
from alphaforge.signals.raw_label_trend import RawLabelTrendSignalService
from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash
from alphaforge.validation.trend_confirmation_bundle import DirectionConfirmationBundle
from alphaforge.validation.trend_dividend_settlement import DividendPayment
from alphaforge.validation.trend_observation import ObservationError
from alphaforge.validation.trend_price_bridge import Action, ActionSnapshot
from alphaforge.validation.trend_runner_bundle import TrendRunnerBundle
from alphaforge.validation.trial_reservation import validate_reservation

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evidence/alphatrend-retrospective-execution-20260912"
OUT = ROOT / "artifacts/analysis/alphatrend_positive_targets_20260913"
REPLAY = ROOT / "artifacts/analysis/alphatrend_confirmation_20260913"
SAVED = ROOT / "artifacts/analysis/alphatrend_retrospective_comparison_20260912/baseline"
SPEC = ROOT / "evidence/alphatrend-positive-targets-20260913/EXPERIMENT_SPEC.json"
PARENT = ROOT / "artifacts/analysis/alphatrend_causal_continuous_20260912"
OPS = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2/state/ops.sqlite"
START = 1420156800000  # 2015-01-02 UTC session label
END = 1789171200000  # 2026-09-12 exclusive
ANCHOR = 1325548800000  # 2012-01-03 first XNYS session


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, data):
    with p.open("x") as f:
        json.dump(data, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


class ComparisonBundle(TrendRunnerBundle):
    def __init__(self, *args, normalization, **kwargs):
        if normalization not in {"cross_sectional_zscore", "directional_rms"}:
            raise ValueError("Fixed comparison arm required")
        self.normalization = normalization
        super().__init__(*args, **kwargs)

    def signal_service(self, store, settings, *, history_anchor):
        self.verify()
        self._bind_settings(settings)
        registry = default_registry()
        register_mf_trend_grid(registry)
        universe = UniverseStore(self.signal_paths)
        return RawLabelTrendSignalService(
            FeatureEngine(
                PITDataReader(self.signal_paths),
                store,
                universe,
                asset_class=settings.data.asset_class,
            ),
            universe,
            registry,
            settings.signals,
            alpha_names=["mf_trend_63", "mf_trend_126", "mf_trend_252"],
            sleeve=sleeve_for(settings.data.asset_class),
            history_anchor=history_anchor,
            raw_label_provider=self.provider,
            blend_normalization=self.normalization,
        )


class ConfirmationComparisonBundle(ComparisonBundle):
    strategy = DirectionConfirmationBundle.strategy


class PositiveComparisonBundle(ConfirmationComparisonBundle):
    def strategy(self, settings, signal_frame, **kwargs):
        self.verify()
        self._bind_settings(settings)
        if self._signals_digest is None or self._frame_digest(signal_frame) != self._signals_digest:
            raise ObservationError("Signal frame is not the bound runner output")
        return PositiveTargetsStrategy(
            settings, signal_frame=signal_frame, allocator="trend",
            signal_reader=PITDataReader(self.signal_paths),
            input_digest=self.binding["paired_input_sha256"], **kwargs,
        )


def bundle_for(normalization, positive_targets):
    schedule = json.loads((SOURCE / "schedule.json").read_text())
    snapshots = {
        s: ActionSnapshot(**{**a, "actions": tuple(Action(**e) for e in a["actions"])})
        for s, a in schedule["snapshots"].items()
    }
    payments = [
        DividendPayment(**{**p, "cash_per_share": Decimal(p["cash_per_share"])})
        for p in schedule["payments"]
    ]
    cls = PositiveComparisonBundle if positive_targets else ConfirmationComparisonBundle
    return cls(
        pd.read_parquet(SOURCE / "paired_prices.parquet"),
        instrument_symbols=schedule["instrument_symbols"],
        snapshots=snapshots,
        payments=payments,
        mode="DIAGNOSTIC_CURRENT_VINTAGE",
        retrospective_vintage_ms=schedule["retrospective_vintage_ms"],
        normalization=normalization,
    )


def close_packet(directory, reservation):
    record = json.loads((directory / "experiments.jsonl").read_text().splitlines()[-1])
    template = json.loads(
        (ROOT / "artifacts/research/trial_packets/59901461092dd7a6.json").read_text()
    )
    packet = {
        k: v
        for k, v in template.items()
        if k not in {"content_hash", "required_sections", "immutable_first_measurement"}
    }
    files = [
        directory / n
        for n in [
            "reservation.json",
            "preregistration.json",
            "reservation_validation.json",
            "experiments.jsonl",
            "result.json",
            "REPORT.md",
            "run/run_meta.json",
            "run/session_summary.json",
        ]
    ] + [OUT / "protocol.json", OUT / "input_manifest.json"]
    evidence = [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in files]
    limitation = (
        "Current-vintage development comparison on inspected history; "
        "explicit raw fills and payable dividends. "
        "Modeled costs/borrow, static metadata, "
        "no contemporaneous publication or historical borrow proof. "
        "No untouched test, independent reproduction, capacity validation or admission. "
        "Accounting complete; comparative decision follows both fixed arms."
    )
    packet.update(
        hypothesis_key=reservation["hypothesis_identity"],
        config_hash=record["config_hash"],
        configuration=record["config"],
        immutable_first_measurement=record,
        claim_boundary=limitation,
    )
    packet["required_sections"] = {
        name: {
            "status": "MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION",
            "statement": limitation,
            "evidence": evidence,
        }
        for name in template["required_sections"]
    }
    packet["content_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    write(
        ROOT / "artifacts/research/trial_packets" / f"{reservation['hypothesis_identity']}.json",
        packet,
    )


def main():
    seal = json.loads((SOURCE / "closure.json").read_text())
    for path, digest in seal["files"].items():
        if sha(ROOT / path) != digest:
            raise ValueError(f"Source seal mismatch: {path}")
    if ExperimentUnion.discover(OUT / "baseline/experiments.jsonl", ROOT).n_hypotheses() != 256:
        raise ValueError("Expected starting union 256")
    spec = json.loads(SPEC.read_text())
    for path, digest in spec["source_sha256"].items():
        assert sha(ROOT / path) == digest
    OUT.mkdir(parents=True, exist_ok=False)
    loaded = load_settings("managed_futures", root=ROOT)
    old_config = json.loads((SAVED / "reservation.json").read_text())["trial_config"]
    base = Settings.model_validate({**old_config["resolved_settings"], "paths": loaded.paths})
    files = [
        Path(__file__),
        OPS,
        REPLAY / "candidate/run/equity.parquet",
        REPLAY / "candidate_stress/run/equity.parquet",
        SPEC,
        SAVED / "signals.parquet",
        SAVED / "result.json",
        SAVED / "reservation.json",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        SOURCE / "closure.json",
    ]
    # Bind all implementation files, including inherited feature/risk/execution paths.
    files += sorted((ROOT / "src/alphaforge").rglob("*.py"))
    write(
        OUT / "input_manifest.json",
        {"source_seal": seal, "bindings": {str(p.relative_to(ROOT)): sha(p) for p in files}},
    )
    write(
        OUT / "protocol.json",
        {
            "spec": spec,
            "spec_sha256": sha(SPEC),
            "planned_new_identities": 4,
            "baseline_replay_reason": (
                "Require confirmed control parity against246/248 before each candidate"
            ),
            "baseline": str(SAVED),
            "signal_reuse": "exact hash-bound baseline forecasts; no recomputation",
            "cost_stress_fields": [
                "equity_commission_bps",
                "equity_half_spread_bps",
                "impact_coef",
                "latency_addon_bps",
                "equity_borrow_bps_annual",
            ],
        },
    )
    results = {"baseline": json.loads((SAVED / "result.json").read_text())["metrics"]}
    for arm, positive_targets, stress in [
        ("baseline", False, False),
        ("baseline_stress", False, True),
        ("candidate", True, False),
        ("candidate_stress", True, True),
    ]:
        normalization = "cross_sectional_zscore"
        ordinal = ExperimentUnion.discover(OUT / arm / "experiments.jsonl", ROOT).n_hypotheses() + 1
        directory = OUT / arm
        directory.mkdir()
        bundle = bundle_for(normalization, positive_targets)
        bundle.prepare(directory / "inputs")
        arm_base = base
        if stress:
            fields = [
                "equity_commission_bps",
                "equity_half_spread_bps",
                "impact_coef",
                "latency_addon_bps",
                "equity_borrow_bps_annual",
            ]
            arm_base = base.model_copy(
                update={
                    "costs": base.costs.model_copy(
                        update={k: 2 * getattr(base.costs, k) for k in fields}
                    )
                }
            )
        settings = arm_base.model_copy(
            update={
                "paths": base.paths.model_copy(
                    update={"lake_dir": bundle.execution_paths.root, "var_dir": directory}
                )
            }
        )
        # The exact fully resolved settings, historical data and implementation enter identity.
        config = {
            "allocator": "trend",
            "direction_confirmation": True,
            "positive_targets": positive_targets,
            "cost_stress": stress,
            "positive_targets_spec_sha256": sha(SPEC),
            "saved_signal_sha256": sha(SAVED / "signals.parquet"),
            "alpha_names": ["mf_trend_63", "mf_trend_126", "mf_trend_252"],
            "start": START,
            "end": END,
            "history_start": ANCHOR,
            "trend_ic_history_anchor": ANCHOR,
            "trend_blend_normalization": normalization,
            "trend_label_availability": "raw_cash_exit_session_close_v2",
            "evaluation_policy": "continuous_retrospective_payable_book_v1",
            "initial_cash": 100000.0,
            "cov_window_bars": 720,
            "cov_min_periods": 240,
            "cov_halflife_days": None,
            "rebalance_bars": 10,
            "no_trade_band": 0.001,
            "metric_basis": "xnys_252_sessions_elapsed_cagr_v1",
            "instrument_ids": sorted(bundle._mapping),
            "input_binding": dict(bundle.binding),
            "implementation_manifest_sha256": sha(OUT / "input_manifest.json"),
            "resolved_settings": {
                k: v for k, v in settings.model_dump(mode="json").items() if k != "paths"
            },
        }
        write(
            directory / "preregistration.json",
            {
                "reserved_at": datetime.now(UTC).isoformat(),
                "trial_config": config,
                "protocol_sha256": sha(OUT / "protocol.json"),
            },
        )
        reservation = copy.deepcopy(json.loads((PARENT / "candidate/reservation.json").read_text()))
        reservation.update(
            reserved_at=datetime.now(UTC).isoformat(),
            trial_config=config,
            hypothesis_identity=hypothesis_hash(config),
            family_trial_account="alphatrend_positive_targets",
            return_identity_id=f"alphatrend_positive_targets_{arm}_20260913",
            packet_public_path=f"/glassbox/trial-packets/alphatrend-positive-targets-{arm}-20260913",
            paper_public_path=f"/research/alphatrend-positive-targets-{arm}-20260913",
        )
        reservation["governance_epoch"]["reservation_ordinal"] = ordinal
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
            validate_reservation(reservation, trial_config=config, repo=ROOT),
        )
        log = ExperimentUnion.discover(directory / "experiments.jsonl", ROOT)
        log.preflight_registration(config, reservation_path=directory / "reservation.json")
        print(
            f"Registered {arm} {reservation['hypothesis_identity']}; loading saved signals",
            flush=True,
        )
        shutil.copy2(OPS, directory / "ops.sqlite")
        with InstrumentStore(directory / "ops.sqlite") as store:
            signals = pd.read_parquet(SAVED / "signals.parquet")
            assert sha(SAVED / "signals.parquet") == config["saved_signal_sha256"]
            service = bundle.signal_service(store, settings, history_anchor=ANCHOR)
            bundle._signals_digest = bundle._frame_digest(signals)
            bundle.binding.update(service.trial_binding)
            bundle.binding["signals_sha256"] = bundle._signals_digest
            bundle.binding["saved_signal_file_sha256"] = config["saved_signal_sha256"]
            bundle.binding["signal_window"] = [ANCHOR, END]
            signals.to_parquet(directory / "signals.parquet")
            print(
                f"{arm} signals persisted ({len(signals)} rows); running continuous portfolio",
                flush=True,
            )
            strategy = bundle.strategy(
                settings,
                signals,
                rebalance_bars=10,
                cov_window_bars=720,
                cov_min_periods=240,
                cov_halflife_days=None,
            )
            result = bundle.engine(
                store,
                settings,
                no_trade_band_frac=0.001,
                clamp_reduce_only_adv=settings.risk.clamp_reduce_only_adv,
            ).run(strategy, config["instrument_ids"], start=START, end=END, initial_cash=100000.0)
        write(directory / "direction_audit.json", strategy.direction_audit)
        if positive_targets:
            assert all(w >= 0 for row in strategy.direction_audit for w in row["targets"].values())
        summary = summarize_equity_sessions(
            result.equity, fills=result.fills, funding=result.funding, positions=result.positions
        )
        rets = result.equity.pct_change(fill_method=None).dropna()
        log.record(
            config,
            sharpe_ann=float(summary.sharpe),
            sharpe_per_period=float(rets.mean() / rets.std(ddof=1)),
            n_obs=len(rets),
            skew=float(skew(rets, bias=True)),
            kurtosis=float(kurtosis(rets, fisher=False, bias=True)),
            now_ms=int(datetime.now(UTC).timestamp() * 1000),
            reservation_path=directory / "reservation.json",
        )
        run = directory / "run"
        run.mkdir()
        pd.DataFrame({"ts": result.equity.index, "equity": result.equity.to_numpy()}).to_parquet(
            run / "equity.parquet", index=False
        )
        for name, frame in {
            "fills": result.fills,
            "orders": result.orders,
            "positions": result.positions,
            "corporate_actions": result.corporate_actions,
            "financing": result.financing_events,
            "funding": result.funding_events,
        }.items():
            frame.to_parquet(run / f"{name}.parquet", index=False)
        write(
            run / "run_meta.json",
            {
                "config": result.config,
                "counters": result.counters,
                "metric_basis": config["metric_basis"],
            },
        )
        write(run / "session_summary.json", asdict(summary))
        metrics = {
            k: float(getattr(summary, k))
            for k in [
                "sharpe",
                "cagr",
                "max_dd",
                "turnover_ann",
                "vol_ann",
                "fees_paid",
                "final_equity",
            ]
        }
        write(
            directory / "result.json",
            {
                "metrics": metrics,
                "return_observations": len(rets),
                "union_hypotheses": log.n_hypotheses(),
                "admitted": False,
                "point_in_time_proven": False,
            },
        )
        (directory / "REPORT.md").write_text(
            f"# {arm}: retrospective development result\n\n"
            "No admission or forward performance claim.\n\n" + json.dumps(metrics, indent=2) + "\n"
        )
        close_packet(directory, reservation)
        results[arm] = metrics
        if arm in {"baseline", "baseline_stress"}:
            source_arm = "candidate_stress" if stress else "candidate"
            old = pd.read_parquet(REPLAY / source_arm / "run/equity.parquet")
            assert old.ts.tolist() == result.equity.index.tolist()
            error = float(abs(old.equity.to_numpy() - result.equity.to_numpy()).max())
            write(
                OUT / f"{arm}_replay_parity.json",
                {"max_abs_equity_error": error, "tolerance": 1e-8, "pass": error <= 1e-8},
            )
            if error > 1e-8:
                raise ValueError("Baseline replay differs; candidate must not run")
        print(f"Completed {arm}: {json.dumps(metrics)}", flush=True)
    write(
        OUT / "comparison.json",
        {"arms": results, "standalone_descriptive_only": True,
         "combined_gates_pending": True, "hypothesis_union": log.n_hypotheses(),
         "admitted": False},
    )


if __name__ == "__main__":
    main()
