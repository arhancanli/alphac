"""Frozen four-arm source-day combined2022 diagnostic, not admission evidence."""

import argparse
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from combined_2022_alignment import DAY, END, PREDECESSOR, crypto_daily, equity_daily
from scipy.stats import kurtosis, skew

from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash
from alphaforge.validation.trial_reservation import validate_reservation

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/combined_2022_diagnostic_20260913"
SPEC = ROOT / "evidence/combined-2022-diagnostic-20260913/EXPERIMENT_SPEC.json"
TREND = ROOT / "artifacts/analysis/alphatrend_positive_targets_20260913"
MAX = ROOT / "artifacts/analysis/alphamax_full2022_baseline_v2_20260913"
CRYPTO = ROOT / "artifacts/analysis/crypto_full2022_terminal_20260913"
VINTAGE = (
    ROOT / "evidence/combined-baseline-audit-20260912/sources/artifacts/probe/cpi_surprise_size"
)
OVERLAY = ROOT / "evidence/alphac-algorithm-contributions-20260913/overlay_sources"
DFF = ROOT / "evidence/alphac-capital-budget-20260913/DFF.parquet"
ARMS = ["baseline", "candidate", "baseline_stress", "candidate_stress"]
LIMIT = (
    "Retrospective diagnostic, not synchronized executable NAV or qualification. "
    "Source-day equity closes and full UTC crypto days grouped by economic date, "
    "with modeled equity overnight accrual allocation. Vintage is a killed CPI probe; "
    "its log-spread-as-simple-return construction is retained without endorsement. "
    "BTC perpetual/SPY overlay uses price returns without funding, dividends or execution costs. "
    "Daily fixed capital weights imply uncharged inter-sleeve rebalancing; cash financing, "
    "collateral and PIT availability unverified. Stress doubles only Max/crypto/Trend costs. "
    "No new qualified sleeve, untouched validation or launch authorization evidence."
)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, value):
    with p.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def inputs():
    paths = [
        DFF,
        SPEC,
        Path(__file__),
        ROOT / "scripts/combined_2022_alignment.py",
        ROOT / "tests/unit/test_combined_2022_alignment.py",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        VINTAGE / "equity.parquet",
        VINTAGE / "result.json",
        ROOT / "evidence/combined-2022-timing-20260913/result.json",
    ]
    for arm in ARMS:
        paths.append(TREND / arm / "run/equity.parquet")
    for arm in ["baseline", "cost_stress"]:
        paths.extend([MAX / arm / "run/equity.parquet", MAX / arm / "closure.json"])
    for arm in ["terminal_lower", "terminal_lower_cost_stress"]:
        paths.extend([CRYPTO / arm / "run/equity.parquet", CRYPTO / arm / "closure.json"])
    for iid, lake in [("BINANCE:PERP:BTCUSDT", "data/lake"), ("XUSE:CASH:SPYUSD", "data/lake_mf")]:
        for year in [2021, 2022]:
            paths.append(
                OVERLAY
                / lake
                / "ohlcv_1d"
                / f"instrument_id={iid}"
                / f"year={year}"
                / "data.parquet"
            )
    paths.extend((ROOT / "src/alphaforge").rglob("*.py"))
    return sorted(set(paths))


def prepare():
    OUT.mkdir(exist_ok=False)
    write(OUT / "protocol.json", json.loads(SPEC.read_text()))
    write(
        OUT / "input_manifest.json",
        {"sha256": {str(p.relative_to(ROOT)): sha(p) for p in inputs()}},
    )
    print("Prepared and bound sources; no combined returns computed.")


def price_frame(iid, lake):
    frames = []
    for year in [2021, 2022]:
        p = OVERLAY / lake / "ohlcv_1d" / f"instrument_id={iid}" / f"year={year}" / "data.parquet"
        x = pd.read_parquet(p, columns=["ts_open", "close"])
        x["ts"] = pd.to_datetime(x.ts_open, utc=True).astype("datetime64[ms, UTC]").astype("int64")
        frames.append(x[["ts", "close"]].rename(columns={"close": "equity"}))
    return pd.concat(frames).sort_values("ts")


def benchmark():
    rates = (
        pd.read_parquet(DFF)
        .sort_values(["publication_date", "obs_date"])
        .drop_duplicates("publication_date", keep="last")
    )
    rates["publication_date"] = rates.publication_date.astype("datetime64[ms]")
    days = pd.DataFrame({"day": pd.date_range("2022-01-01", "2022-12-31").astype("datetime64[ms]")})
    aligned = pd.merge_asof(
        days,
        rates,
        left_on="day",
        right_on="publication_date",
        direction="backward",
        allow_exact_matches=False,
    )
    assert (
        aligned.value.notna().all() and (aligned.day - aligned.obs_date).dt.days.between(0, 7).all()
    )
    return aligned.value.to_numpy() / 100 / 360


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
        "family": "combined_2022_source_day_diagnostic",
        "arm": arm,
        "spec_sha256": sha(SPEC),
        "input_manifest_sha256": sha(OUT / "input_manifest.json"),
    }
    log = ExperimentUnion.discover(directory / "experiments.jsonl", ROOT)
    now = datetime.now(UTC)
    reservation = copy.deepcopy(json.loads((MAX / "baseline/reservation.json").read_text()))
    reservation.update(
        reserved_at=now.isoformat(),
        trial_config=config,
        hypothesis_identity=hypothesis_hash(config),
        family_trial_account="combined_2022_source_day_diagnostic",
        return_identity_id=f"combined2022_source_day_{arm}_20260913",
        packet_public_path=f"/glassbox/trial-packets/combined2022-source-day-{arm}",
        paper_public_path="/research/combined2022-source-day-20260913",
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
    stress = arm.endswith("_stress")
    eq = lambda p: pd.read_parquet(p, columns=["ts", "equity"])
    trend = equity_daily(eq(TREND / arm / "run/equity.parquet"), next_session_label=True)
    max_arm = "cost_stress" if stress else "baseline"
    max_r = equity_daily(eq(MAX / max_arm / "run/equity.parquet"), next_session_label=True)
    crypto_arm = "terminal_lower_cost_stress" if stress else "terminal_lower"
    crypto = crypto_daily(eq(CRYPTO / crypto_arm / "run/equity.parquet"))
    vintage = equity_daily(eq(VINTAGE / "equity.parquet"), next_session_label=False)
    spy = equity_daily(price_frame("XUSE:CASH:SPYUSD", "data/lake_mf"), next_session_label=False)
    btc = (
        price_frame("BINANCE:PERP:BTCUSDT", "data/lake")
        .set_index("ts")
        .equity.loc[np.arange(PREDECESSOR, END, DAY)]
    )
    assert len(btc) == 366 and (btc > 0).all()
    btc = btc.pct_change().iloc[1:].to_numpy()
    frame = pd.DataFrame(
        {
            "day": pd.date_range("2022-01-01", "2022-12-31"),
            "max": max_r,
            "crypto": crypto,
            "trend": trend,
            "vintage": vintage,
            "btc_overlay": btc,
            "spy_overlay": spy,
            "benchmark": benchmark(),
        }
    )
    frame["total"] = 0.225 * (frame["max"] + frame.crypto + frame.trend + frame.vintage) + 0.05 * (
        frame.btc_overlay + frame.spy_overlay
    )
    frame["excess"] = frame.total - frame.benchmark
    assert len(frame) == 365 and np.isfinite(frame.select_dtypes("number")).all().all()
    frame.to_csv(directory / "daily.csv", index=False)
    curve = np.r_[1.0, np.cumprod(1 + frame.total.to_numpy())]
    excess_sr = float(frame.excess.mean() / frame.excess.std(ddof=1) * np.sqrt(365))
    result = {
        "return": float(curve[-1] - 1),
        "raw_sharpe": float(frame.total.mean() / frame.total.std(ddof=1) * np.sqrt(365)),
        "excess_sharpe_proxy": excess_sr,
        "max_drawdown": float((1 - curve / np.maximum.accumulate(curve)).max()),
        "observations": 365,
        "qualified": False,
        "limitations": LIMIT,
    }
    record = log.record(
        config,
        sharpe_ann=excess_sr,
        sharpe_per_period=excess_sr / np.sqrt(365),
        n_obs=365,
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
