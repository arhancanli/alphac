"""Frozen four-arm source-day combined2022 diagnostic, not admission evidence."""

import argparse
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from scipy.stats import kurtosis, skew

from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash
from alphaforge.validation.trial_reservation import validate_reservation

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/combined_crypto_retention_20260913"
SPEC = ROOT / "evidence/combined-crypto-retention-20260913/EXPERIMENT_SPEC.json"
TREND = ROOT / "artifacts/analysis/trend_extended_reference_20260913"
MAX = ROOT / "artifacts/analysis/alphamax_session_cooldown_20260913"
CRYPTO = ROOT / "artifacts/analysis/crypto_rank_retention_20260913"
VINTAGE = (
    ROOT / "evidence/combined-baseline-audit-20260912/sources/artifacts/probe/cpi_surprise_size"
)
OVERLAY = ROOT / "evidence/alphac-algorithm-contributions-20260913/overlay_sources"
DFF = ROOT / "evidence/alphac-capital-budget-20260913/DFF.parquet"
ARMS = ["candidate", "candidate_stress"]
CONTROL = ROOT / "artifacts/analysis/combined_2022_corrected_max_20260913"
LIMIT = "Retrospective fixed-weight combined research proxy; 22.5% each Max/crypto/confirmedTrend and32.5%zero-yield cash. Full NAV DFF benchmark. Source-session equity vs fullUTC crypto alignment verified, but intraday synchronization, inter-sleeve rebalance execution, collateral and funding/borrow/metadata source timing remain modeled. No new sleeve, untouched OOS, admission or launch evidence."


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, value):
    with p.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def source_arm(source, arm):
    return arm if source in (MAX, CRYPTO) else arm.replace("candidate", "baseline")


def inputs():
    paths = [SPEC, Path(__file__), ROOT/'pyproject.toml', ROOT/'uv.lock', DFF]
    for arm in ARMS:
        for source, csv_name, closure in [(MAX,'calendar2023_2026_excess.csv','closure.json'),(CRYPTO,'calendar2023_2026.csv','closure.json'),(TREND,'calendar2023_2026_excess.csv','audit_closure.json')]:
            paths.extend(source/source_arm(source,arm)/name for name in [csv_name,closure,'independent_audit.json','reservation.json','run/equity.parquet'])
    paths.append(ROOT/'evidence/crypto-rank-retention-20260913/EXPERIMENT_SPEC.json')
    paths.extend((ROOT/'src/alphaforge').rglob('*.py'))
    return sorted(paths)


def prepare():
    OUT.mkdir(exist_ok=False)
    write(OUT / "protocol.json", json.loads(SPEC.read_text()))
    write(
        OUT / "input_manifest.json",
        {"sha256": {str(p.relative_to(ROOT)): sha(p) for p in inputs()}},
    )
    print("Prepared and bound sources; no combined returns computed.")


def close_packet(directory, reservation, record):
    template = json.loads(
        (ROOT / "artifacts/research/trial_packets/59901461092dd7a6.json").read_text()
    )
    packet = {
        k: v
        for k, v in template.items()
        if k not in ["content_hash", "required_sections", "immutable_first_measurement"]
    }
    refs = [
        {"path": str(p.relative_to(ROOT)), "sha256": sha(p)}
        for p in sorted(directory.iterdir())
        if p.is_file()
    ]
    refs.extend(
        {"path": str(p.relative_to(ROOT)), "sha256": sha(p)}
        for p in [OUT / "input_manifest.json", OUT / "protocol.json", Path(__file__)]
    )
    packet.update(
        hypothesis_key=reservation["hypothesis_identity"],
        config_hash=record["config_hash"],
        configuration=record["config"],
        immutable_first_measurement=record,
        claim_boundary=LIMIT,
    )
    packet["required_sections"] = {
        k: {
            "status": "MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION",
            "statement": LIMIT,
            "evidence": refs,
        }
        for k in template["required_sections"]
    }
    packet["content_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    p = ROOT / "artifacts/research/trial_packets" / (reservation["hypothesis_identity"] + ".json")
    write(p, packet)
    write(
        directory / "closure.json",
        {
            "status": "DIAGNOSTIC_PACKET_CLOSED",
            "qualified": False,
            "packet": str(p.relative_to(ROOT)),
            "packet_sha256": sha(p),
        },
    )


def execute(arm):
    manifest = json.loads((OUT / "input_manifest.json").read_text())
    for p, h in manifest["sha256"].items():
        assert sha(ROOT / p) == h, p
    directory = OUT / arm
    directory.mkdir(exist_ok=False)
    config = {
        "family": "combined_crypto_retention",
        "arm": arm,
        "spec_sha256": sha(SPEC),
        "input_manifest_sha256": sha(OUT / "input_manifest.json"),
    }
    log = ExperimentUnion.discover(directory / "experiments.jsonl", ROOT)
    now = datetime.now(UTC)
    reservation = copy.deepcopy(json.loads((CONTROL / "baseline/reservation.json").read_text()))
    reservation.update(
        reserved_at=now.isoformat(),
        trial_config=config,
        hypothesis_identity=hypothesis_hash(config),
        family_trial_account="combined_crypto_retention",
        return_identity_id=f"combined_crypto_retention_{arm}_20260913",
        packet_public_path=f"/glassbox/trial-packets/combined-extended-reference-{arm}",
        paper_public_path="/research/combined-crypto-retention-20260913",
    )
    reservation["governance_epoch"]["reservation_ordinal"] = log.n_hypotheses() + 1
    write(
        directory / "preregistration.json",
        {"trial_config": config, "reserved_at": now.isoformat(), "limitations": LIMIT},
    )
    sources = {
        "preregistration": directory / "preregistration.json",
        "input_data_manifest": OUT / "input_manifest.json",
        "runner": Path(__file__),
        "python_project": ROOT / "pyproject.toml",
        "locked_environment": ROOT / "uv.lock",
    }
    reservation["evidence"] = {
        k: {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for k, p in sources.items()
    }
    write(directory / "reservation.json", reservation)
    write(
        directory / "reservation_validation.json",
        validate_reservation(reservation, trial_config=config, repo=ROOT),
    )
    log.preflight_registration(config, reservation_path=directory / "reservation.json")
    days = pd.date_range('2023-01-01','2026-06-01')
    frame = pd.DataFrame({'day':days})
    expected = XNYSCalendar().expected_bar_opens(1672531200000,1780358400000,Timeframe.D1)
    expected_dates = pd.to_datetime(expected,unit='ms')
    for key,source in [('max',MAX),('trend',TREND)]:
        data = pd.read_csv(source/source_arm(source,arm)/'calendar2023_2026_excess.csv')
        session = pd.to_datetime(data.session,utc=True).dt.tz_localize(None)
        assert session.tolist()==expected_dates.tolist()
        values = pd.Series(data['return'].to_numpy(),index=session)
        aligned = values.reindex(days)
        assert aligned.isna().equals(pd.Series(~days.isin(expected_dates),index=days))
        frame[key] = aligned.fillna(0).to_numpy()
    crypto = pd.read_csv(CRYPTO/source_arm(CRYPTO,arm)/'calendar2023_2026.csv')
    assert pd.to_datetime(crypto.day).tolist()==days.tolist()
    frame['crypto']=crypto['return'].to_numpy()
    frame['benchmark']=crypto.benchmark.to_numpy()
    frame["cash_contribution"] = 0.0
    frame["total"] = 0.225 * (frame["max"] + frame.crypto + frame.trend)
    frame["excess"] = frame.total - frame.benchmark
    assert len(frame) == 1248 and np.isfinite(frame.select_dtypes("number")).all().all()
    frame.to_csv(directory / "daily.csv", index=False)
    curve = np.r_[1.0, np.cumprod(1 + frame.total.to_numpy())]
    excess_sr = float(frame.excess.mean() / frame.excess.std(ddof=1) * np.sqrt(365))
    result = {
        "return": float(curve[-1] - 1),
        "raw_sharpe": float(frame.total.mean() / frame.total.std(ddof=1) * np.sqrt(365)),
        "excess_sharpe_proxy": excess_sr,
        "max_drawdown": float((1 - curve / np.maximum.accumulate(curve)).max()),
        "observations": 1248,
        "qualified": False,
        "limitations": LIMIT,
    }
    record = log.record(
        config,
        sharpe_ann=excess_sr,
        sharpe_per_period=excess_sr / np.sqrt(365),
        n_obs=1248,
        skew=float(skew(frame.excess, bias=False)),
        kurtosis=float(kurtosis(frame.excess, fisher=False)),
        now_ms=int(now.timestamp() * 1000),
        reservation_path=directory / "reservation.json",
    )
    write(directory / "result.json", result)
    close_packet(directory, reservation, record.to_json_obj())
    print(json.dumps({"arm": arm, **result}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--arm", choices=ARMS)
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.arm:
        execute(args.arm)
    else:
        parser.error("Choose prepare or arm")
