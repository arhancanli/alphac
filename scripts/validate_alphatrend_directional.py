"""Two registered doubled-cost replays plus frozen exposure diagnostics; no tuning."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"
OUT = ROOT / "artifacts/analysis/alphatrend_directional_validation_20260912"
COST_KEYS = (
    "equity_commission_bps",
    "equity_half_spread_bps",
    "latency_addon_bps",
    "impact_coef",
    "equity_borrow_bps_annual",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    with path.open("x") as f:
        json.dump(data, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def stressed_settings(settings):
    """One fixed 2x scenario, including impact and borrow; no financing invented."""
    return settings.model_copy(
        update={
            "costs": settings.costs.model_copy(
                update={key: 2 * getattr(settings.costs, key) for key in COST_KEYS}
            )
        }
    )


class ArchivedSignals:
    """The exact pre-cost forecasts already sealed by the measured parent trial."""

    def __init__(self, arm, config):
        self.frame = pd.read_parquet(PARENT / arm / "input_snapshot/derived_signal_frame.parquet")
        self.config = config
        self.trial_binding = (
            {"trend_blend_normalization": "directional_rms"} if arm == "candidate" else {}
        )

    def compute_research(self, start, end):
        if (start, end) != (self.config["start"], self.config["end"]):
            raise ValueError("Archived signal interval mismatch")
        return self.frame.copy()


def prepare():
    from alphaforge.validation.input_snapshot import validate_input_snapshot

    OUT.mkdir(parents=True, exist_ok=False)
    for arm in ["baseline", "candidate"]:
        validate_input_snapshot(PARENT / arm / "input_snapshot")
    parent = json.loads((PARENT / "preregistration.json").read_text())
    for row in parent["implementation_evidence"].values():
        if sha(ROOT / row["path"]) != row["sha256"]:
            raise ValueError("Parent implementation drift")
    for name in ["input_manifest.json", "environment.json"]:
        shutil.copy2(PARENT / name, OUT / name)
    write(
        OUT / "protocol.json",
        {
            "frozen_at": datetime.now(UTC).isoformat(),
            "scope": "DEVELOPMENT_VALIDATION_ALREADY_INSPECTED_HISTORY",
            "parent_hypothesis": "ec7ec19175ac10a9",
            "script_sha256": sha(Path(__file__)),
            "analysis_script_sha256": sha(ROOT / "scripts/analyze_alphatrend_validation.py"),
            "new_return_identities": 2,
            "starting_union": 232,
            "execution": "Full engine replays in fixed order baseline then candidate, "
            "each registered and counted separately; first packet closes before second.",
            "cost_scenario": dict.fromkeys(COST_KEYS, "2x original"),
            "decision_rule": "Cost robustness requires candidate Sharpe and CAGR above stressed baseline, "  # noqa: E501
            "no worse drawdown, lower turnover, and candidate CAGR and Sharpe positive. "
            "Failure means robustness not established; no parameter or rule changes.",
            "unchanged": "Forecast frames, dates, universe, cadence, limits and funding/financing settings",  # noqa: E501
            "exposure_diagnostics": "Parent candidate-minus-baseline daily return OLS on SPY, IEF, GLD, "  # noqa: E501
            "UUP close returns plus intercept. Close labels align to next UTC "
            "midnight equity timestamps; complete cases only, no forward fill. "
            "HAC 21 lags. Intercept is raw-return unexplained mean, not excess alpha.",
            "uncertainty": "Paired circular bootstrap of parent session returns, 63-session blocks, "  # noqa: E501
            "2000 draws, seed 20260912, annualization 252, Sharpe difference interval.",
            "eras": ["2006-2012", "2013-2019", "2020-2026"],
            "forbidden_claims": [
                "untouched validation",
                "live performance",
                "admission",
                "cost doubling is a capacity test",
                "independent sleeves",
            ],
            "input_bindings": {
                arm: {
                    "snapshot": sha(PARENT / arm / "input_snapshot/manifest.json"),
                    "equity": sha(PARENT / arm / "equity.parquet"),
                }
                for arm in ["baseline", "candidate"]
            },
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
        "scope": "Fixed doubled-cost sensitivity, not an optimized strategy",
        "accounting": "External registration includes complete cost settings. Engine "
        "now_ms=None suppresses its narrower default identity only; "
        "this wrapper registers before and records after the actual replay.",
    }
    write(directory / "preregistration.json", prereg)
    reservation = copy.deepcopy(json.loads((PARENT / "reservation.json").read_text()))
    reservation.update(
        reserved_at=prereg["reserved_at"],
        trial_config=config,
        hypothesis_identity=hypothesis_hash(config),
        return_identity_id=f"alphatrend_2x_cost_{arm}_20260912",
        packet_public_path=f"/glassbox/trial-packets/alphatrend-2x-cost-{arm}-20260912",
        paper_public_path=f"/research/alphatrend-2x-cost-{arm}-20260912",
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
    """Complete accounting of one fixed stress arm before registering the next."""
    record = json.loads((directory / "experiments.jsonl").read_text().splitlines()[-1])
    assert record["config"] == reservation["trial_config"]
    template = json.loads(
        (ROOT / "artifacts/research/trial_packets/ec7ec19175ac10a9.json").read_text()
    )
    statements = {
        "admission_or_kill_decision": "Single preregistered stress arm completed. No admission. "
        "Paired robustness decision is made only after both fixed arms.",
        "economic_mechanism_and_falsifiable_hypothesis": "Fixed 2x cost replay of the parent strategy. "  # noqa: E501
        "Not a new independent economic mechanism. No tuning or candidate selection.",
        "result_uncertainty_stress_capacity_and_diversification": "One full-engine doubled-cost "
        "scenario measured. Capacity, independent replication, untouched validation and "
        "portfolio integration remain unmeasured. Parent diagnostics do not establish them.",
        "execution_and_cost_model": "Commission, spread, latency, impact coefficient and modeled "
        "borrow doubled. Positions, actual order sizes and risk paths recomputed by engine. "
        "Historical borrow availability and live fills remain unverified.",
        "preregistration_and_hashes": "Reservation and protocol validated before returns; snapshots "  # noqa: E501
        "and full cost settings are bound. No public release was performed.",
    }
    common = (
        "Source-bound development stress evidence is preserved locally. Fixed ETF basket and "
        "already-inspected historical data; no independent reproduction, public publication, "
        "data-licensing clearance, untouched validation or admission is claimed. "
        "All previous trials remain counted in the complete union."
    )
    files = [
        directory / "reservation.json",
        directory / "preregistration.json",
        directory / "reservation_validation.json",
        directory / "experiments.jsonl",
        directory / "result.json",
        directory / "REPORT.md",
        directory / "run/walkforward.json",
        directory / "run/input_snapshot/manifest.json",
        OUT / "protocol.json",
    ]
    evidence = [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in files]
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
    packet["claim_boundary"] = (
        "Accounting is complete, admission evidence is not. Fixed stress "
        "measurement does not establish capacity or untouched performance."
    )
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

    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.config.settings import load_settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.validation.input_snapshot import validate_input_snapshot

    parent_config = json.loads((PARENT / "reservation.json").read_text())["trial_config"]
    parent_settings = json.loads(
        (PARENT / "candidate/input_snapshot/declared_run.json").read_text()
    )["resolved_settings"]
    base_settings = load_settings("managed_futures", root=ROOT)
    current = base_settings.model_dump(mode="json")
    assert {k: v for k, v in current.items() if k != "paths"} == {
        k: v for k, v in parent_settings.items() if k != "paths"
    }
    results = {}
    for arm, ordinal in [("baseline", 233), ("candidate", 234)]:
        directory = OUT / arm
        settings = stressed_settings(base_settings)
        config = {
            **parent_config,
            "execution_cost_scenario": {
                "name": "double_all_modeled_costs_v1",
                "resolved_costs": settings.costs.model_dump(mode="json"),
            },
        }
        if arm == "baseline":
            config.pop("trend_blend_normalization")
        log, reservation = reserve(arm, ordinal, config, directory)
        shutil.copy2(PARENT / "state/ops.sqlite", directory / "ops.sqlite")
        settings = settings.model_copy(
            update={
                "paths": settings.paths.model_copy(
                    update={"lake_dir": PARENT / "lake_mf", "var_dir": directory}
                )
            }
        )
        paths = LakePaths(settings.paths.lake_dir)
        with InstrumentStore(directory / "ops.sqlite") as store:
            runner = WalkForwardRunner(
                PITDataReader(paths),
                store,
                UniverseStore(paths),
                TransactionCostModel.from_settings(settings),
                ArchivedSignals(arm, parent_config),
                settings,
            )
            result = runner.run(
                config["start"],
                config["end"],
                train_bars=504,
                test_bars=126,
                allocator="trend",
                embargo_bars=21,
                initial_cash=100000.0,
                instrument_ids=config["instrument_ids"],
                rebalance_bars=10,
                no_trade_band=0.001,
                out_dir=directory / "run",
                alpha_names=config["alpha_names"],
                now_ms=None,
            )
        rets = result.equity.pct_change(fill_method=None).dropna()
        log.record(
            config,
            sharpe_ann=float(result.summary.sharpe),
            sharpe_per_period=float(rets.mean() / rets.std(ddof=1)),
            n_obs=len(rets),
            skew=float(skew(rets, bias=True)),
            kurtosis=float(kurtosis(rets, fisher=False, bias=True)),
            now_ms=int(datetime.now(UTC).timestamp() * 1000),
            reservation_path=directory / "reservation.json",
        )
        validate_input_snapshot(directory / "run/input_snapshot")
        actual = json.loads((directory / "run/input_snapshot/declared_run.json").read_text())
        assert (
            actual["resolved_settings"]["costs"]
            == config["execution_cost_scenario"]["resolved_costs"]
        )
        pd.testing.assert_frame_equal(
            pd.read_parquet(directory / "run/input_snapshot/derived_signal_frame.parquet"),
            pd.read_parquet(PARENT / arm / "input_snapshot/derived_signal_frame.parquet"),
            check_exact=True,
        )
        metrics = {
            k: float(getattr(result.summary, k))
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
                "snapshot_verified": True,
                "archived_forecasts_exact": True,
                "claim_boundary": "Fixed full-engine stress arm; not admission",
            },
        )
        (directory / "REPORT.md").write_text(
            "# " + arm + " doubled-cost stress arm\n\n"
            "Completed under the frozen validation protocol. No admission or untouched evidence.\n\n"  # noqa: E501
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
        "positive_candidate_sharpe": b["sharpe"] > 0,
        "positive_candidate_cagr": b["cagr"] > 0,
    }
    write(
        OUT / "cost_robustness.json",
        {
            "arms": results,
            "criteria": criteria,
            "disposition": "PASS_FIXED_COST_STRESS"
            if all(criteria.values())
            else "COST_ROBUSTNESS_NOT_ESTABLISHED",
            "union_hypotheses": 234,
        },
    )


if __name__ == "__main__":
    prepare()
    execute()
