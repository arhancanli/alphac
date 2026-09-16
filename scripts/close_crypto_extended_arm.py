"""Validate saved full2022 terminal evidence and close its research packet."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/crypto_extended_reference_20260913"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("arm")
    name = parser.parse_args().arm
    directory = OUT / name
    reservation = json.loads((directory / "reservation.json").read_text())
    scenario = reservation["trial_config"]["research_engine"]["scenario"]
    audit = json.loads((directory / "independent_audit.json").read_text())
    year = json.loads((directory / "calendar2023_2026_audit.json").read_text())
    assert year["coverage_complete"] and year["observations"] == 1248
    assert sha(directory / "run/equity.parquet") == year["equity_sha256"]
    assert sha(directory / "calendar2023_2026.csv") == year["daily_csv_sha256"]
    for path, digest in audit["source_sha256"].items():
        assert sha(ROOT / path) == digest
    iid, boundary = scenario["terminal_instrument"], scenario["terminal_ts"]

    def table(name):
        return pd.concat(
            [pd.read_parquet(p) for p in sorted((directory / "run/legs").glob(f"*/{name}.parquet"))]
        )

    fills, positions, funding = table("fills"), table("positions"), table("funding")
    records, blocked = [], 0
    for path in sorted((directory / "run/legs").glob("*/run_meta.json")):
        meta = json.loads(path.read_text())
        records.extend(meta["config"]["terminal_records"])
        blocked += meta["counters"].get("terminal_orders_blocked", 0)
    assert not records, "LUNA terminal predates all test legs; no settlement allowed"
    boundary_audit = json.loads((directory / 'boundary_audit.json').read_text())
    assert not boundary_audit['violations']
    for path, digest in boundary_audit['sha256'].items():
        assert sha(ROOT / path) == digest
    assert fills[
        (fills.instrument_id == iid)
        & (fills.ts >= boundary)
        & (fills.reason != "administrative_terminal_settlement")
    ].empty
    assert positions[
        (positions.instrument_id == iid)
        & (positions.ts >= boundary)
        & (positions.qty.abs() > 1e-10)
    ].empty
    assert funding[(funding.instrument_id == iid) & (funding.ts_funding > boundary)].empty
    write(
        directory / "terminal_invariants.json",
        {
            "status": "TERMINAL_INVARIANTS_VERIFIED",
            "records": records,
            "later_orders_blocked": blocked,
            "post_boundary_market_fills": 0,
            "post_boundary_positions": 0,
            "post_boundary_funding": 0,
            "run_metadata_sha256": {
                str(p.relative_to(ROOT)): sha(p)
                for p in sorted((directory / "run/legs").glob("*/run_meta.json"))
            },
        },
    )
    snapshots = sum(x["snapshots"] for x in audit["legs"])
    report = f"""# Extended crypto {name}: accounting and coverage verified

Jan2023–June1 2026 total return {year['total_return']:.6%}; excess DFF Sharpe proxy {year['net_excess_sharpe_DFF_proxy']:.6f}; daily maximum drawdown {year['max_drawdown']:.6%}. All1,248 full UTC-day returns use next-midnight equity endpoints and an observed Jan1 2023 predecessor. Whole-run engine metrics use a different daily sampling convention and remain separate.

All{snapshots} hourly marks reconcile within1e-6 quote units. Twenty legs retain6048-hour training,1512-hour test windows (final1248 hours),168-hour rebalance. Durable outputs match final parquet. No LUNA position, fill, funding or terminal settlement occurs; its terminal event predates all tests and only eligibility applies. Source boundary exposure screen passes, but does not certify exchange funding schedule completeness or actual terminal proceeds.

Standalone retrospective research, not combined AlphaC performance or sleeve qualification. Funding availability, metadata, execution costs, settlement and USD DFF versus USDT remain modeled. The inherited scope.initial_diagnostic prose refers to the old2022 run and is obsolete; scope.start/end and the explicit evaluation section govern this experiment. No historical result or source was overwritten.
"""
    with (directory / "REPORT.md").open("x") as f:
        f.write(report)
    measured = json.loads((directory / "experiments.jsonl").read_text().splitlines()[-1])
    template = json.loads(
        (ROOT / "artifacts/research/trial_packets/59901461092dd7a6.json").read_text()
    )
    packet = {
        k: v
        for k, v in template.items()
        if k not in {"content_hash", "required_sections", "immutable_first_measurement"}
    }
    limitation = (
        "2023–June2026 retrospective crypto horizon extension; calendar/accounting verified, "
        "source availability, metadata, funding, settlement and benchmark remain modeled. "
        "No combined qualification, new sleeve, untouched OOS or admission."
    )
    files = [
        directory / n
        for n in [
            "reservation.json",
            "preregistration.json",
            "reservation_validation.json",
            "experiments.jsonl",
            "execution_complete.json",
            "independent_audit.json",
            "calendar2023_2026_audit.json",
            "calendar2023_2026.csv",
            "terminal_invariants.json",
            "boundary_audit.json",
            "REPORT.md",
            "run/walkforward.json",
        ]
    ]
    files += [
        OUT / "protocol.json",
        OUT / "input_manifest.json",
        Path(__file__),
        ROOT / "scripts/audit_crypto_extended_accounting.py",
        ROOT / "scripts/audit_crypto_extended_horizon.py",
        ROOT / "scripts/audit_crypto_extended_boundaries.py",
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
        ROOT / "artifacts/research/trial_packets" / f"{reservation['hypothesis_identity']}.json"
    )
    write(target, packet)
    write(
        directory / "closure.json",
        {
            "status": "FULL2022_ARM_RECONCILED_PACKET_CLOSED",
            "qualified": False,
            "packet": str(target.relative_to(ROOT)),
            "packet_sha256": sha(target),
        },
    )
    print(
        json.dumps(
            {
                "arm": name,
                "return": year["total_return"],
                "excess_sharpe": year["net_excess_sharpe_DFF_proxy"],
                "drawdown": year["max_drawdown"],
                "terminal_qty": record["qty_before"],
                "packet": "closed",
            }
        )
    )


if __name__ == "__main__":
    main()
