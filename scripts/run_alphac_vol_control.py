"""Execute exactly the sealed combined risk-control experiment and mandatory cost stress."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew

from alphaforge.portfolio.research_vol_control import apply_control
from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash
from alphaforge.validation.trial_reservation import validate_reservation

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evidence/alphac-algorithm-contributions-20260913"
OUT = ROOT / "artifacts/analysis/alphac_vol_control_20260913"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def metrics(r):
    wealth = np.r_[1.0, np.cumprod(1 + r)]
    return {
        "sharpe": float(r.mean() / r.std(ddof=1) * np.sqrt(365)),
        "cagr": float(wealth[-1] ** (365 / len(r)) - 1),
        "maxdd": float(np.max(1 - wealth / np.maximum.accumulate(wealth))),
    }


def close_packet(directory, reservation, config, record):
    template = json.loads(
        (ROOT / "artifacts/research/trial_packets/59901461092dd7a6.json").read_text()
    )
    packet = {
        k: v
        for k, v in template.items()
        if k not in ("content_hash", "required_sections", "immutable_first_measurement")
    }
    evidence = [
        {"path": str(p.relative_to(ROOT)), "sha256": sha(p)}
        for p in sorted(directory.iterdir())
        if p.is_file()
    ]
    limitation = (
        "Known-history combined portfolio development experiment; fixed parameters, "
        "cost proxy only, zero cash benchmark, additive overlay and inherited calendar "
        "limitations. No untouched validation, independent replication, capacity or admission."
    )
    packet.update(
        hypothesis_key=reservation["hypothesis_identity"],
        config_hash=record["config_hash"],
        configuration=config,
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
    OUT.mkdir(exist_ok=False)
    spec = json.loads((SOURCE / "EXPERIMENT_SPEC.json").read_text())
    assert sha(SOURCE / "baseline_components.csv") == spec["control_component_csv_sha256"]
    write(OUT / "protocol.json", spec)
    write(
        OUT / "input_manifest.json",
        {
            str(SOURCE / "baseline_components.csv"): sha(SOURCE / "baseline_components.csv"),
            "spec_sha256": sha(SOURCE / "EXPERIMENT_SPEC.json"),
        },
    )
    frame = pd.read_csv(SOURCE / "baseline_components.csv", index_col=0, parse_dates=True)
    control = frame.sum(axis=1).to_numpy()
    weekdays = frame.index.weekday.to_numpy()
    assert len(control) == 1061 and all(frame.index.to_series().diff().iloc[1:] == pd.Timedelta(days=1))
    baseline = metrics(control)
    template = json.loads(
        (
            ROOT / "artifacts/analysis/alphatrend_retrospective_comparison_20260912/"
            "candidate/reservation.json"
        ).read_text()
    )
    results = {}
    for arm, cost_rate in [("primary", 0.0001), ("cost_stress", 0.0005)]:
        directory = OUT / arm
        directory.mkdir()
        log = ExperimentUnion.discover(directory / "experiments.jsonl", ROOT)
        count = log.n_hypotheses()
        config = {
            "family": "alphac_combined_risk_control",
            "candidate": spec["candidate"],
            "input_sha256": spec["control_component_csv_sha256"],
            "cost_rate": cost_rate,
            "spec_sha256": sha(SOURCE / "EXPERIMENT_SPEC.json"),
            "implementation_sha256": sha(ROOT / "src/alphaforge/portfolio/research_vol_control.py"),
        }
        prereg = {
            "reserved_at": datetime.now(UTC).isoformat(),
            "trial_config": config,
            "source_specification": str(SOURCE / "EXPERIMENT_SPEC.json"),
            "cost_scenarios_counted_separately": True,
        }
        write(directory / "preregistration.json", prereg)
        reservation = copy.deepcopy(template)
        reservation.update(
            reserved_at=prereg["reserved_at"],
            trial_config=config,
            family_trial_account="alphac_combined_risk_control",
            return_identity_id=f"alphac_vol_control_{arm}_20260913",
            hypothesis_identity=hypothesis_hash(config),
            packet_public_path=f"/glassbox/trial-packets/alphac-vol-control-{arm}-20260913",
            paper_public_path="/research/alphac-vol-control-20260913",
        )
        reservation["governance_epoch"]["reservation_ordinal"] = count + 1
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
        log.preflight_registration(config, reservation_path=directory / "reservation.json")
        print("Reservation passed:", count + 1, arm, flush=True)
        net, scale, cost = apply_control(control, weekdays, cost_rate)
        result = {
            "metrics": metrics(net),
            "control": baseline,
            "scale_min": float(scale.min()),
            "scale_mean": float(scale.mean()),
            "incremental_cost_sum": float(cost.sum()),
            "worst_control_day_scale": float(scale[np.argmin(control)]),
            "yearly": {
                str(year): {
                    "rows": int(sum(frame.index.year == year)),
                    "control": metrics(control[frame.index.year == year]),
                    "candidate": metrics(net[frame.index.year == year]),
                }
                for year in sorted(set(frame.index.year))
            },
            "qualification": False,
        }
        log.record(
            config,
            sharpe_ann=result["metrics"]["sharpe"],
            sharpe_per_period=result["metrics"]["sharpe"] / np.sqrt(365),
            n_obs=len(net),
            skew=float(skew(net, bias=False)),
            kurtosis=float(kurtosis(net, fisher=False)),
            now_ms=int(datetime.now(UTC).timestamp() * 1000),
            reservation_path=directory / "reservation.json",
        )
        pd.DataFrame(
            {"control": control, "scale": scale, "added_cost": cost, "candidate": net},
            index=frame.index,
        ).to_csv(directory / "daily.csv")
        write(directory / "result.json", result)
        (directory / "REPORT.md").write_text(
            "Known-data development measurement; no admission. "
            "See result.json and parent protocol.\n"
        )
        record = json.loads((directory / "experiments.jsonl").read_text().splitlines()[-1])
        close_packet(directory, reservation, config, record)
        results[arm] = result
    p, s = results["primary"]["metrics"], results["cost_stress"]["metrics"]
    gates = {
        "sharpe_delta": p["sharpe"] - baseline["sharpe"] >= 0.1,
        "drawdown_not_worse": p["maxdd"] <= baseline["maxdd"],
        "retain_cagr": p["cagr"] >= 0.9 * baseline["cagr"],
        "stress_improves_sharpe": s["sharpe"] > baseline["sharpe"],
    }
    write(
        OUT / "comparison.json",
        {
            "results": results,
            "development_gates": gates,
            "development_pass": all(gates.values()),
            "union_after": log.n_hypotheses(),
            "admission": False,
        },
    )
    print(
        json.dumps(
            {
                "baseline": baseline,
                "primary": p,
                "stress": s,
                "gates": gates,
                "union": log.n_hypotheses(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
