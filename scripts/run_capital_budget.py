"""Fixed, registered capital-budget proxy comparison with immutable source curves."""

import copy
import hashlib
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from run_alphac_inverse_vol import ROOT, metrics, sha, write
from scipy.stats import kurtosis, skew

from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash
from alphaforge.validation.trial_reservation import validate_reservation

OUT = ROOT / "artifacts/analysis/alphac_capital_budget_20260913"
SPEC = ROOT / "evidence/alphac-capital-budget-20260913/EXPERIMENT_SPEC.json"
SOURCE = ROOT / "artifacts/analysis/alphac_confirmation_combined_20260913"
CSV = ROOT / "evidence/alphac-algorithm-contributions-20260913/baseline_components.csv"
ARMS = ("baseline", "candidate", "baseline_stress", "candidate_stress")


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
        "capital-budget proxy, lagged modeled DFF benchmark, unresolved internal financing and "
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
    spec = json.loads(SPEC.read_text())
    for path, digest in spec["source_sha256"].items():
        assert sha(ROOT / path) == digest
    assert ExperimentUnion.discover(OUT / "baseline/experiments.jsonl", ROOT).n_hypotheses() == 252
    frame = pd.read_csv(CSV, index_col=0, parse_dates=True)
    assert len(frame) == 1061 and frame.index.is_unique
    assert (frame.index.to_series().diff().iloc[1:] == pd.Timedelta(days=1)).all()
    benchmark = pd.read_csv(SPEC.parent / "benchmark.csv", parse_dates=["day"])
    assert benchmark.day.tolist() == frame.index.tolist()
    rf = benchmark.benchmark_daily.to_numpy()
    OUT.mkdir(exist_ok=False)
    write(OUT / "protocol.json", spec)
    write(
        OUT / "input_manifest.json",
        {
            "sources": spec["source_sha256"],
            "spec_sha256": sha(SPEC),
            "helper_sha256": sha(ROOT / "scripts/run_alphac_inverse_vol.py"),
        },
    )
    original = frame.sum(axis=1).to_numpy()
    overlay = frame.strategic_overlay.to_numpy()
    results = {}
    template = json.loads((SOURCE / "baseline/reservation.json").read_text())
    for arm in ARMS:
        directory = OUT / arm
        directory.mkdir()
        log = ExperimentUnion.discover(directory / "experiments.jsonl", ROOT)
        config = {
            "family": "alphac_capital_budget",
            "arm": arm,
            "spec_sha256": sha(SPEC),
            "input_manifest_sha256": sha(OUT / "input_manifest.json"),
        }
        now = datetime.now(UTC).isoformat()
        write(directory / "preregistration.json", {"reserved_at": now, "trial_config": config})
        reservation = copy.deepcopy(template)
        reservation.update(
            reserved_at=now,
            trial_config=config,
            hypothesis_identity=hypothesis_hash(config),
            family_trial_account="alphac_capital_budget",
            return_identity_id=f"alphac_capital_budget_{arm}_20260913",
            packet_public_path=f"/glassbox/trial-packets/alphac-capital-budget-{arm}",
            paper_public_path="/research/alphac-capital-budget-20260913",
        )
        reservation["governance_epoch"]["reservation_ordinal"] = log.n_hypotheses() + 1
        evidence = {
            "preregistration": directory / "preregistration.json",
            "input_data_manifest": OUT / "input_manifest.json",
            "runner": ROOT / "scripts/run_capital_budget.py",
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
        previous = pd.read_csv(SOURCE / arm / "daily.csv", index_col=0, parse_dates=True)
        assert previous.index.equals(frame.index)
        net = 0.9 * (previous.combined.to_numpy() - overlay) + overlay
        excess = net - rf
        result = metrics(net)
        result["raw_sharpe"] = result["sharpe"]
        result["sharpe"] = float(excess.mean() / excess.std(ddof=1) * np.sqrt(365))
        log.record(
            config,
            sharpe_ann=result["sharpe"],
            sharpe_per_period=result["sharpe"] / np.sqrt(365),
            n_obs=len(net),
            skew=float(skew(excess, bias=False)),
            kurtosis=float(kurtosis(excess, fisher=False)),
            now_ms=int(datetime.now(UTC).timestamp() * 1000),
            reservation_path=directory / "reservation.json",
        )
        pd.DataFrame({"total": net, "benchmark": rf, "excess": excess}, index=frame.index).to_csv(
            directory / "daily.csv"
        )
        write(directory / "result.json", {"metrics": result, "admitted": False})
        (directory / "REPORT.md").write_text(
            "Capital-budget and benchmark proxy; no financing qualification.\n"
        )
        record = json.loads((directory / "experiments.jsonl").read_text().splitlines()[-1])
        close_packet(directory, reservation, config, record)
        results[arm] = result
        print(arm, result, flush=True)
    a, b = results["baseline"], results["candidate"]
    gates = {
        "higher_sharpe": b["sharpe"] > a["sharpe"],
        "retain_cagr": b["cagr"] >= 0.9 * a["cagr"],
        "no_worse_dd": b["maxdd"] <= a["maxdd"],
        "stress_higher_sharpe": results["candidate_stress"]["sharpe"]
        > results["baseline_stress"]["sharpe"],
    }
    write(
        OUT / "comparison.json",
        {
            "original_reference": metrics(original),
            "arms": results,
            "gates": gates,
            "development_pass": all(gates.values()),
            "union": log.n_hypotheses(),
            "qualified": False,
        },
    )


if __name__ == "__main__":
    main()
