"""Benchmark retained session returns and close an AlphaMax evidence packet."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/alphamax_covariance_basis_20260913"
DFF = ROOT / "evidence/alphac-capital-budget-20260913/DFF.parquet"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    with path.open("x") as stream:
        json.dump(obj, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("arm", choices=["sessions", "sessions_stress", "sessions_splits", "sessions_splits_stress"])
    directory = OUT / parser.parse_args().arm
    assert (directory / "execution_complete.json").exists()
    audit = json.loads((directory / "independent_audit.json").read_text())
    for path, digest in audit["source_sha256"].items():
        assert sha(ROOT / path) == digest
    assert sha(DFF) == "f591aa86f5058cb75d319a2b64d83983fc82b78a22c28c3f33d72e5dc971aa27"
    policy = {
        "benchmark": "Current-vintage DFF proxy; strict prior publication-date match; ACT/360",
        "session_interval": "Compound daily simple proxy accruals on (previous source session, current source session]; Dec31 2021 predecessor; final Dec30 2022 session.",
        "annualization": 252,
        "qualification": False,
        "selection": "Single declared reporting convention; no benchmark variants or strategy recomputation.",
    }
    write(directory / "benchmark_policy.json", policy)
    frame = pd.read_csv(directory / "calendar2022.csv")
    sessions = pd.to_datetime(frame.session, utc=True).dt.tz_localize(None)
    assert sessions.is_monotonic_increasing and not sessions.duplicated().any()
    assert len(sessions) == 251
    days = pd.DataFrame({"day": pd.date_range("2022-01-01", sessions.iloc[-1], freq="D")})
    rates = (
        pd.read_parquet(DFF)
        .sort_values(["publication_date", "obs_date"])
        .drop_duplicates("publication_date", keep="last")
    )
    days["day"] = days.day.astype("datetime64[ms]")
    rates["publication_date"] = rates.publication_date.astype("datetime64[ms]")
    aligned = pd.merge_asof(
        days,
        rates,
        left_on="day",
        right_on="publication_date",
        direction="backward",
        allow_exact_matches=False,
    )
    assert aligned.value.notna().all()
    assert (aligned.day - aligned.obs_date).dt.days.between(0, 7).all()
    assert (aligned.publication_date < aligned.day).all()
    aligned["daily_proxy"] = aligned.value / 100 / 360
    factors = pd.Series(1 + aligned.daily_proxy.to_numpy(), index=aligned.day)
    previous = pd.Timestamp("2021-12-31")
    benchmark = []
    counts = []
    for day in sessions:
        span = factors.loc[(factors.index > previous) & (factors.index <= day)]
        assert len(span) == (day - previous).days
        benchmark.append(float(span.prod() - 1))
        counts.append(len(span))
        previous = day
    assert sum(counts) == len(days) == 364
    assert abs(np.prod(1 + np.array(benchmark)) - factors.prod()) < 1e-12
    frame["benchmark"] = benchmark
    frame["calendar_days"] = counts
    frame["excess"] = frame["return"] - frame.benchmark
    frame.to_csv(directory / "calendar2022_excess.csv", index=False)
    aligned.to_csv(directory / "benchmark_daily_alignment.csv", index=False)
    excess_sharpe = float(frame.excess.mean() / frame.excess.std(ddof=1) * np.sqrt(252))
    assert (
        abs(
            frame["return"].mean() / frame["return"].std(ddof=1) * np.sqrt(252)
            - audit["raw_sharpe"]
        )
        < 1e-12
    )
    limitation = (
        "Retrospective standalone baseline, not untouched OOS or combined qualification. "
        "DFF is a current-vintage reporting proxy with modeled publication dates, not certified cash yield. "
        "Static borrow and modeled metadata, corporate actions and final-recorded-close liquidation remain. "
        "The last source session is Dec30; no invented Dec31 price or financing observation."
    )
    report = {
        "status": "SESSION_EXCESS_PROXY_RECONCILED",
        "net_excess_sharpe_DFF_proxy": excess_sharpe,
        "benchmark_compound_return": float(factors.prod() - 1),
        "calendar_accrual_days": 364,
        "session_observations": 251,
        "raw_sharpe": audit["raw_sharpe"],
        "total_return": audit["total_return"],
        "max_drawdown": audit["max_drawdown"],
        "qualified": False,
        "limitations": limitation,
        "source_sha256": {
            str(p.relative_to(ROOT)): sha(p)
            for p in [
                DFF,
                directory / "calendar2022.csv",
                directory / "calendar2022_excess.csv",
                directory / "benchmark_daily_alignment.csv",
                directory / "benchmark_policy.json",
            ]
        },
    }
    write(directory / "benchmark_audit.json", report)
    with (directory / "FINAL_REPORT.md").open("x") as stream:
        stream.write(
            f"# AlphaMax {directory.name}: saved accounting and benchmark verified\n\n"
            f"2022 session return {audit['total_return']:.6%}; raw Sharpe {audit['raw_sharpe']:.6f}; "
            f"DFF excess Sharpe proxy {excess_sharpe:.6f}; maxdrawdown {audit['max_drawdown']:.6%}. "
            "251 session returns with observed Dec31 2021 predecessor; all253 engine marks reconcile. "
            "Four legs63/63/63/64; durable outputs match final parquet files.\n\n"
            + limitation
            + "\n"
        )
    reservation = json.loads((directory / "reservation.json").read_text())
    measured = json.loads((directory / "experiments.jsonl").read_text().splitlines()[-1])
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
            "execution_complete.json",
            "independent_audit.json",
            "calendar2022.csv",
            "benchmark_policy.json",
            "benchmark_audit.json",
            "calendar2022_excess.csv",
            "benchmark_daily_alignment.csv",
            "FINAL_REPORT.md",
            "run/walkforward.json",
        ]
    ]
    files += [
        OUT / "protocol.json",
        OUT / "input_manifest.json",
        Path(__file__),
        ROOT / "scripts/audit_alphamax_covariance_basis.py",
    ]
    evidence = [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in files]
    packet.update(
        hypothesis_key=reservation["hypothesis_identity"],
        config_hash=measured["config_hash"],
        configuration=measured["config"],
        immutable_first_measurement=measured,
        claim_boundary=limitation,
    )
    packet["required_sections"] = {
        k: {
            "status": "MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION",
            "statement": limitation,
            "evidence": evidence,
        }
        for k in template["required_sections"]
    }
    packet["content_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    target = (
        ROOT / "artifacts/research/trial_packets" / (reservation["hypothesis_identity"] + ".json")
    )
    write(target, packet)
    write(
        directory / "closure.json",
        {
            "status": "ALPHAMAX_SESSION_BASELINE_ACCOUNTED_PACKET_CLOSED",
            "qualified": False,
            "packet": str(target.relative_to(ROOT)),
            "packet_sha256": sha(target),
        },
    )
    print(json.dumps({k: v for k, v in report.items() if k != "source_sha256"}))


if __name__ == "__main__":
    main()
