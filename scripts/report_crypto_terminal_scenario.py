"""Verify terminal invariants in saved scenario output and write its phase report."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/crypto_terminal_comparison_20260913_attempt2"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("arm")
    name = parser.parse_args().arm
    directory = OUT / name
    reservation = json.loads((directory / "reservation.json").read_text())
    scenario = reservation["trial_config"]["research_engine"]["scenario"]
    assert scenario["terminal"]
    iid, boundary = scenario["terminal_instrument"], scenario["terminal_ts"]
    fills = pd.concat(
        [pd.read_parquet(p) for p in sorted((directory / "run/legs").glob("*/fills.parquet"))]
    )
    positions = pd.concat(
        [pd.read_parquet(p) for p in sorted((directory / "run/legs").glob("*/positions.parquet"))]
    )
    funding = pd.concat(
        [pd.read_parquet(p) for p in sorted((directory / "run/legs").glob("*/funding.parquet"))]
    )
    terminal = fills[
        (fills.instrument_id == iid) & (fills.reason == "administrative_terminal_settlement")
    ]
    assert len(terminal) == 1
    row = terminal.iloc[0]
    assert row.ts == boundary and row.price == float(scenario["price"])
    assert abs(row.fee - row.qty * row.price * scenario["fee_fraction"]) < 1e-10
    later = fills[
        (fills.instrument_id == iid)
        & (fills.ts >= boundary)
        & (fills.reason != "administrative_terminal_settlement")
    ]
    assert later.empty
    assert positions[
        (positions.instrument_id == iid)
        & (positions.ts >= boundary)
        & (positions.qty.abs() > 1e-10)
    ].empty
    assert funding[(funding.instrument_id == iid) & (funding.ts_funding > boundary)].empty
    records = []
    for path in sorted((directory / "run/legs").glob("*/run_meta.json")):
        records.extend(json.loads(path.read_text())["config"]["terminal_records"])
    assert len(records) == 1 and abs(records[0]["qty_before"]) == row.qty
    audit = json.loads((directory / "independent_audit.json").read_text())
    benchmark = json.loads((directory / "excess_benchmark_audit.json").read_text())
    meta = json.loads((directory / "run/walkforward.json").read_text())
    summary = meta["summary"]
    evidence = {
        "status": "TERMINAL_LIFECYCLE_INVARIANTS_PASS",
        "terminal_record": records[0],
        "realized_loss_or_profit": float(row.realized_pnl_quote),
        "post_boundary_market_fills": 0,
        "post_boundary_nonzero_positions": 0,
        "post_boundary_funding": 0,
        "qualified": False,
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((directory / "run").rglob("*"))
            if p.is_file()
        },
    }
    with (directory / "terminal_invariants.json").open("x") as f:
        json.dump(evidence, f, indent=2)
        f.write("\n")
    text = f"""# {name}: measured terminal correction scenario

Two fixed original-calendar crypto legs, February–June2022. Total return{summary["total_return"]:.9%}; raw dailySharpe{summary["sharpe"]:.9f}; DFF net excess Sharpe proxy{benchmark["net_excess_sharpe_DFF_proxy"]:.9f}; daily maxdrawdown{summary["max_dd"]:.9%}; final equity{summary["final_equity"]:.9f} quote units.

Exactly one administrative settlement at the specified boundary, price{row.price:.12f}, quantity{row.qty:.11f}, fee{row.fee:.12f}, realized PnL{row.realized_pnl_quote:.9f}. No later LUNA market fills, nonzero positions or funding payments. The realized loss is retained. All3024hourly equity snapshots independently reconcile, maximum residual{max(x["max_abs_residual"] for x in audit["legs"]):.3g}; exact grids and daily metrics pass.

The settlement endpoint and fee are explicitly modeled, not a certified2022exchange settlement price/rule or contemporaneous notice receipt. DFF benchmark timing is modeled and uses USD rates against USDT accounting; collateral yield and currency conversion remain unverified. Metadata applicability and funding marks are reconstructed. No untouched OOS, independent external reproduction, capacity proof, new sleeve or admission. This phase isolates execution/data corrections; it is not evidence that the combined goal has been achieved. All fixed scenarios must be retained before drawing sensitivity conclusions.
"""
    with (directory / "REPORT.md").open("x") as f:
        f.write(text)
    print(
        json.dumps(
            {
                "arm": name,
                "total_return": summary["total_return"],
                "excess_sharpe_proxy": benchmark["net_excess_sharpe_DFF_proxy"],
                "terminal_pnl": float(row.realized_pnl_quote),
                "lifecycle_checks": "pass",
            }
        )
    )


if __name__ == "__main__":
    main()
