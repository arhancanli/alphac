"""Fixed, registered combined replacement comparison with immutable source curves."""

import copy
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew

from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash
from alphaforge.validation.trial_reservation import validate_reservation
from run_alphac_inverse_vol import ROOT, close_packet, metrics, sha, write

OUT = ROOT / "artifacts/analysis/alphac_confirmation_combined_20260913"
SPEC = ROOT / "evidence/alphac-confirmation-combined-20260913/EXPERIMENT_SPEC.json"
SOURCE = ROOT / "artifacts/analysis/alphatrend_confirmation_20260913"
CSV = ROOT / "evidence/alphac-algorithm-contributions-20260913/baseline_components.csv"
ARMS = ("baseline", "candidate", "baseline_stress", "candidate_stress")


def main():
    spec = json.loads(SPEC.read_text())
    for path, digest in spec["source_sha256"].items():
        assert sha(ROOT / path) == digest
    assert ExperimentUnion.discover(OUT / "baseline/experiments.jsonl", ROOT).n_hypotheses() == 248
    frame = pd.read_csv(CSV, index_col=0, parse_dates=True)
    assert len(frame) == 1061 and frame.index.is_unique
    assert (frame.index.to_series().diff().iloc[1:] == pd.Timedelta(days=1)).all()
    cal = XNYSCalendar()
    curves = {}
    for arm in ARMS:
        x = pd.read_parquet(SOURCE / arm / "run/equity.parquet")
        expected = list(
            cal.expected_bar_opens(int(x.ts.min()), int(x.ts.max()) + 86400000, Timeframe.D1)
        )
        assert x.ts.tolist() == expected and (x.equity > 0).all()
        curves[arm] = x
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
    other = frame.drop(columns="managed_futures").sum(axis=1).to_numpy()
    results = {}
    template = json.loads((SOURCE / "baseline/reservation.json").read_text())
    for arm in ARMS:
        directory = OUT / arm
        directory.mkdir()
        log = ExperimentUnion.discover(directory / "experiments.jsonl", ROOT)
        config = {
            "family": "alphac_confirmation_combined",
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
            family_trial_account="alphac_confirmation_combined",
            return_identity_id=f"alphac_confirmation_combined_{arm}_20260913",
            packet_public_path=f"/glassbox/trial-packets/alphac-confirmation-combined-{arm}",
            paper_public_path="/research/alphac-confirmation-combined-20260913",
        )
        reservation["governance_epoch"]["reservation_ordinal"] = log.n_hypotheses() + 1
        evidence = {
            "preregistration": directory / "preregistration.json",
            "input_data_manifest": OUT / "input_manifest.json",
            "runner": ROOT / "scripts/run_combined_confirmation.py",
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
        x = curves[arm]
        returns = pd.Series(
            x.equity.pct_change().to_numpy()[1:],
            index=pd.to_datetime(x.ts.to_numpy()[1:], unit="ms"),
        )
        trend = returns.reindex(frame.index).fillna(0).to_numpy()
        net = other + 0.25 * trend
        result = metrics(net)
        log.record(
            config,
            sharpe_ann=result["sharpe"],
            sharpe_per_period=result["sharpe"] / np.sqrt(365),
            n_obs=len(net),
            skew=float(skew(net, bias=False)),
            kurtosis=float(kurtosis(net, fisher=False)),
            now_ms=int(datetime.now(UTC).timestamp() * 1000),
            reservation_path=directory / "reservation.json",
        )
        pd.DataFrame(
            {"other": other, "trend_weighted": 0.25 * trend, "combined": net}, index=frame.index
        ).to_csv(directory / "daily.csv")
        write(directory / "result.json", {"metrics": result, "admitted": False})
        (directory / "REPORT.md").write_text("Inspected-history replacement; no qualification.\n")
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
