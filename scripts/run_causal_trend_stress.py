"""Fixed doubled-cost validation with session-correct reporting and accounting."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"
PARITY = ROOT / "evidence/alphatrend-causal-parity-20260912"
BASE = ROOT / "artifacts/analysis/alphatrend_causal_continuous_20260912"
OUT = ROOT / "artifacts/analysis/alphatrend_causal_stress_20260912"
COST_KEYS = (
    "equity_commission_bps",
    "equity_half_spread_bps",
    "latency_addon_bps",
    "impact_coef",
    "equity_borrow_bps_annual",
)


def stressed_settings(settings):
    return settings.model_copy(
        update={
            "costs": settings.costs.model_copy(
                update={k: 2 * getattr(settings.costs, k) for k in COST_KEYS}
            )
        }
    )


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    with path.open("x") as f:
        json.dump(data, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def prepare():
    from alphaforge.validation.input_snapshot import validate_input_snapshot

    for arm in ["baseline", "candidate"]:
        validate_input_snapshot(PARENT / arm / "input_snapshot")
    gates = json.loads((PARITY / "result.json").read_text())
    assert gates["all_pass"] and not gates["returns_computed"]
    bindings = json.loads((PARITY / "protocol.json").read_text())["implementation"]
    assert all(sha(ROOT / p) == digest for p, digest in bindings.items())
    for arm in ["baseline", "candidate"]:
        validate_input_snapshot(BASE / arm / "run/input_snapshot")
    closure = json.loads((BASE / "closure.json").read_text())
    assert closure["union_hypotheses"] == 236
    assert all(sha(ROOT / p) == digest for p, digest in closure["files"].items())
    OUT.mkdir(parents=True, exist_ok=False)
    for name in ["input_manifest.json", "environment.json"]:
        shutil.copy2(PARENT / name, OUT / name)
    files = [
        Path(__file__),
        ROOT / "src/alphaforge/signals/causal_trend.py",
        ROOT / "src/alphaforge/portfolio/strategy.py",
        ROOT / "src/alphaforge/backtest/engine.py",
        PARITY / "protocol.json",
        PARITY / "result.json",
        PARITY / "baseline_signals.parquet",
        PARITY / "candidate_signals.parquet",
        ROOT / "src/alphaforge/analytics/session_metrics.py",
        BASE / "metric_correction.json",
        BASE / "closure.json",
    ]
    write(
        OUT / "protocol.json",
        {
            "frozen_at": datetime.now(UTC).isoformat(),
            "scope": "DEVELOPMENT_COMPARISON_ALREADY_INSPECTED_HISTORY",
            "starting_union": 236,
            "new_return_identities": 2,
            "execution": "Register, measure, close baseline; repeat for candidate",
            "signal_rule": "Fixed history anchor; release IC at exit-session close (tau+h+1)",
            "book_rule": "Single uninterrupted backtest; one strategy and book; no load_leg/reset",
            "configuration": "Frozen slate, forecasts and cadence; all five cost components doubled",
            "evaluation_start": 1136246400000,
            "evaluation_end": 1787529600000,
            "initial_cash": 100000.0,
            "decision_rule": "Require higher Sharpe/CAGR, no worse drawdown, lower turnover, "
            "positive Sharpe and CAGR. Otherwise improvement is not established; no tuning.",
            "limitations": "Inspected history; static metadata fallback; modeled borrow and "
            "fills; no PIT borrow availability, capacity, untouched test or admission. "
            "Parity gates verify sampled interfaces, not an operational live collector.",
            "cost_scenario": dict.fromkeys(COST_KEYS, "2x original"),
            "reporting": "252 sessions/year; elapsed-time CAGR; consistent ledger and report",
            "bindings": {str(p.relative_to(ROOT)): sha(p) for p in files},
        },
    )


def reserve(arm, ordinal, config, directory):
    from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash
    from alphaforge.validation.trial_reservation import validate_reservation

    directory.mkdir(exist_ok=False)
    prereg = {
        "reserved_at": datetime.now(UTC).isoformat(),
        "trial_config": config,
        "protocol": {
            "path": str((OUT / "protocol.json").relative_to(ROOT)),
            "sha256": sha(OUT / "protocol.json"),
        },
        "scope": "Fixed doubled-cost causal continuous-book comparison; inspected history",
        "accounting": "External registration includes signal availability, book policy and costs. "
        "The single backtest engine does not register hypotheses; "
        "this wrapper registers before and records after the actual replay.",
    }
    write(directory / "preregistration.json", prereg)
    reservation = copy.deepcopy(json.loads((PARENT / "reservation.json").read_text()))
    reservation.update(
        reserved_at=prereg["reserved_at"],
        trial_config=config,
        hypothesis_identity=hypothesis_hash(config),
        return_identity_id=f"alphatrend_causal_stress_{arm}_20260912",
        packet_public_path=f"/glassbox/trial-packets/alphatrend-causal-stress-{arm}-20260912",
        paper_public_path=f"/research/alphatrend-causal-stress-{arm}-20260912",
    )
    paths = {
        "preregistration": directory / "preregistration.json",
        "input_data_manifest": OUT / "input_manifest.json",
        "runner": Path(__file__),
        "python_project": ROOT / "pyproject.toml",
        "locked_environment": ROOT / "uv.lock",
    }
    reservation["evidence"] = {
        k: {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for k, p in paths.items()
    }
    reservation["governance_epoch"]["reservation_ordinal"] = ordinal
    write(directory / "reservation.json", reservation)
    write(
        directory / "reservation_validation.json",
        validate_reservation(reservation, trial_config=config, repo=ROOT),
    )
    log = ExperimentUnion.discover(directory / "experiments.jsonl", ROOT)
    log.preflight_registration(config, reservation_path=directory / "reservation.json")
    if log.n_hypotheses() != ordinal - 1:
        raise ValueError("Unexpected union size before returns")
    print(f"Registered {arm}: {reservation['hypothesis_identity']}, ordinal {ordinal}", flush=True)
    return log, reservation


def close_packet(directory, reservation):
    record = json.loads((directory / "experiments.jsonl").read_text().splitlines()[-1])
    assert record["config"] == reservation["trial_config"]
    template = json.loads(
        (ROOT / "artifacts/research/trial_packets/ec7ec19175ac10a9.json").read_text()
    )
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
            "run/input_snapshot/manifest.json",
        ]
    ] + [OUT / "protocol.json"]
    evidence = [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in files]
    common = (
        "Fixed corrected-label, uninterrupted-book development comparison on already inspected "
        "ETF history. Costs and risk paths recomputed. Parity evidence covers sampled inputs and "
        "interfaces; does not establish live availability. No independent reproduction, historical "
        "borrow availability, capacity, untouched tests, licensing or publication established. "
        "No admission. All previous hypotheses and invalidated simulations remain counted."
    )
    statements = {
        "admission_or_kill_decision": "Accounting only. No admission; paired "
        "decision follows both arms. Legacy candidate remains on hold.",
        "economic_mechanism_and_falsifiable_hypothesis": "Compare centered vs RMS trend "
        "with causal IC release and a continuous portfolio. Require higher Sharpe/CAGR, no worse "
        "drawdown and lower turnover. This is one family, not an independent sleeve.",
        "execution_and_cost_model": "NextOpenFill with all five cost components doubled. "
        "No artificial leg resets. No verified historical borrow availability or live fills.",
    }
    packet = {
        k: v
        for k, v in template.items()
        if k not in ["content_hash", "required_sections", "immutable_first_measurement"]
    }
    packet.update(
        hypothesis_key=reservation["hypothesis_identity"],
        config_hash=record["config_hash"],
        configuration=record["config"],
        immutable_first_measurement=record,
    )
    packet["required_sections"] = {
        name: {
            "status": "MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION",
            "statement": statements.get(name, common),
            "evidence": evidence,
        }
        for name in template["required_sections"]
    }
    packet["claim_boundary"] = common
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


def execute():
    from scipy.stats import kurtosis, skew

    from alphaforge.analytics.session_metrics import summarize_equity_sessions
    from alphaforge.analytics.tearsheet import render_text
    from alphaforge.backtest import EventDrivenBacktester
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.portfolio.strategy import BlendStrategy
    from alphaforge.validation.input_snapshot import (
        seal_walkforward_input_snapshot,
        validate_input_snapshot,
    )

    parent = json.loads((PARENT / "reservation.json").read_text())["trial_config"]
    base = load_settings("managed_futures", root=ROOT)
    old = json.loads((PARENT / "candidate/input_snapshot/declared_run.json").read_text())[
        "resolved_settings"
    ]
    assert {k: v for k, v in base.model_dump(mode="json").items() if k != "paths"} == {
        k: v for k, v in old.items() if k != "paths"
    }
    gate = json.loads((PARITY / "result.json").read_text())
    base = stressed_settings(base)
    results = {}
    for arm, ordinal in [("baseline", 237), ("candidate", 238)]:
        directory = OUT / arm
        config = {
            k: v
            for k, v in parent.items()
            if k not in ["train_bars", "test_bars", "trend_blend_normalization"]
        }
        config.update(gate["arms"][arm]["trial_binding"])
        config.update(
            start=1136246400000,
            history_start=parent["start"],
            evaluation_policy="continuous_single_book_v1",
            initial_cash=100000.0,
            metric_basis="xnys_252_sessions_elapsed_cagr_v1",
            cov_window_bars=720,
            cov_min_periods=240,
            cov_halflife_days=None,
            execution_cost_scenario={
                "name": "double_all_modeled_costs_v1",
                "resolved_costs": base.costs.model_dump(mode="json"),
            },
        )
        log, reservation = reserve(arm, ordinal, config, directory)
        shutil.copy2(PARENT / "state/ops.sqlite", directory / "ops.sqlite")
        settings = base.model_copy(
            update={
                "paths": base.paths.model_copy(
                    update={"lake_dir": PARENT / "lake_mf", "var_dir": directory}
                )
            }
        )
        sleeve = sleeve_for(settings.data.asset_class)
        paths = LakePaths(settings.paths.lake_dir)
        frame = pd.read_parquet(PARITY / f"{arm}_signals.parquet")
        with InstrumentStore(directory / "ops.sqlite") as store:
            seal_walkforward_input_snapshot(
                directory / "run/input_snapshot",
                signal_frame=frame,
                instrument_ids=config["instrument_ids"],
                universe=UniverseStore(paths),
                instruments=store,
                lake_paths=paths,
                start=parent["start"],
                end=config["end"],
                timeframe=sleeve.anchor_tf,
                asset_class=settings.data.asset_class,
                declared_run=config,
                resolved_settings=settings.model_dump(mode="json"),
                repo_root=ROOT,
            )
            strategy = BlendStrategy(
                settings,
                signal_frame=frame,
                allocator="trend",
                rebalance_bars=10,
                cov_window_bars=720,
                cov_min_periods=240,
                cov_halflife_days=None,
            )
            engine = EventDrivenBacktester(
                PITDataReader(paths),
                store,
                TransactionCostModel.from_settings(settings),
                tf=sleeve.anchor_tf,
                asset_class=settings.data.asset_class,
                no_trade_band_frac=0.001,
                clamp_reduce_only_adv=settings.risk.clamp_reduce_only_adv,
                config_echo={"trial_config": config},
            )
            result = engine.run(
                strategy,
                config["instrument_ids"],
                start=config["start"],
                end=config["end"],
                initial_cash=100000.0,
            )
        summary = summarize_equity_sessions(
            result.equity, fills=result.fills, funding=result.funding, positions=result.positions
        )
        # Correct calendar basis BEFORE immutable first measurement is recorded.
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
        # Legacy save/load and tearsheets recompute a 365-day summary. Persist
        # raw artifacts directly and write only the corrected session summary.
        run = directory / "run"
        pd.DataFrame({"ts": result.equity.index, "equity": result.equity.to_numpy()}).to_parquet(
            run / "equity.parquet", index=False
        )
        for filename, frame_to_save in {
            "fills": result.fills,
            "funding": result.funding_events,
            "corporate_actions": result.corporate_actions,
            "financing": result.financing_events,
            "orders": result.orders,
            "positions": result.positions,
        }.items():
            frame_to_save.to_parquet(run / f"{filename}.parquet", index=False)
        write(
            run / "run_meta.json",
            {
                "config": result.config,
                "counters": result.counters,
                "metric_basis": config["metric_basis"],
            },
        )
        write(run / "session_summary.json", asdict(summary))
        (run / "summary.txt").write_text(render_text(summary))
        validate_input_snapshot(directory / "run/input_snapshot")
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
                "union_hypotheses": log.n_hypotheses(),
                "return_observations": len(rets),
                "snapshot_verified": True,
                "claim_boundary": "Development comparison; no forward performance or admission",
            },
        )
        (directory / "REPORT.md").write_text(
            f"# {arm}: causal doubled-cost comparison\n\nInspected history. No admission.\n\n"
            + "\n".join(f"- {k}: {v:.8f}" for k, v in metrics.items())
            + "\n"
        )
        close_packet(directory, reservation)
        results[arm] = metrics
        print(f"Completed {arm}: {json.dumps(metrics)}", flush=True)
    a, b = results["baseline"], results["candidate"]
    criteria = {
        "higher_sharpe": b["sharpe"] > a["sharpe"],
        "higher_cagr": b["cagr"] > a["cagr"],
        "no_worse_drawdown": b["max_dd"] <= a["max_dd"],
        "lower_turnover": b["turnover_ann"] < a["turnover_ann"],
        "positive_sharpe": b["sharpe"] > 0,
        "positive_cagr": b["cagr"] > 0,
    }
    write(
        OUT / "comparison.json",
        {
            "arms": results,
            "criteria": criteria,
            "disposition": "PASS_FIXED_DEVELOPMENT_COMPARISON"
            if all(criteria.values())
            else "IMPROVEMENT_NOT_ESTABLISHED",
            "union_hypotheses": 238,
            "admitted": False,
        },
    )


if __name__ == "__main__":
    prepare()
    execute()
