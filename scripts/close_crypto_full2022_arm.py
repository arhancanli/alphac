"""Validate saved full2022 terminal evidence and close its research packet."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/crypto_full2022_terminal_20260913"


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
    year = json.loads((directory / "calendar2022_audit.json").read_text())
    assert year["coverage_complete"] and year["observations"] == 365
    assert sha(directory / "run/equity.parquet") == year["equity_sha256"]
    assert sha(directory / "calendar2022.csv") == year["daily_csv_sha256"]
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
    assert len(records) == 1
    record = records[0]
    assert record["ts"] == boundary and record["price"] == float(scenario["price"])
    expected_fee = abs(record["qty_before"]) * record["price"] * scenario["fee_fraction"]
    assert abs(record["fee_quote"] - expected_fee) < 1e-10
    terminal = fills[
        (fills.instrument_id == iid) & (fills.reason == "administrative_terminal_settlement")
    ]
    assert len(terminal) == int(record["qty_before"] != 0)
    if len(terminal):
        assert terminal.iloc[0].ts == boundary
        assert terminal.iloc[0].qty == abs(record["qty_before"])
        assert terminal.iloc[0].price == record["price"]
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
    report = f"""# Full2022 {name}: measured and reconciled

Calendar2022 return{year["total_return"]:.6%}; rawSharpe{year["raw_sharpe"]:.6f}; DFF excess
Sharpe proxy{year["net_excess_sharpe_DFF_proxy"]:.6f}; daily
maxdrawdown{year["max_drawdown"]:.6%}. All365 daily returns have observed scheduled marks and
the required December31predecessor. Engine whole-run metrics include extra boundary
observations and are kept separately.

All{snapshots} hourly snapshots reconcile within1e-6 quote units. One terminal event processed
at its exact timestamp; quantity before settlement{record["qty_before"]},
fee{record["fee_quote"]}, later blocked orders{blocked}. No post-termination market fills,
nonzero positions or funding. A flat closure does not certify the modeled settlement price.

Six fixed walk-forward legs preserve6048-hour training,1512-hour tests and weekly rebalancing.
Static metadata applicability, funding marks, notice/settlement timing and DFF publication are
modeled; USD benchmark versus USDT accounting and collateral financing remain unverified.
Full-year coverage is evidence for this research slice, not untouched OOS or qualification.
The11% target applies to the combined portfolio, not each sleeve separately. All endpoint/cost
scenarios remain in the comparison; no tuning or favorable endpoint selection. Combined
AlphaMax2022coverage remains outstanding.
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
        "Full2022 retrospective crypto horizon extension; calendar/accounting verified, "
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
            "calendar2022_audit.json",
            "calendar2022.csv",
            "terminal_invariants.json",
            "REPORT.md",
            "run/walkforward.json",
        ]
    ]
    files += [
        OUT / "protocol.json",
        OUT / "input_manifest.json",
        Path(__file__),
        ROOT / "scripts/audit_crypto_full2022_accounting.py",
        ROOT / "scripts/audit_crypto_full2022_horizon.py",
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
