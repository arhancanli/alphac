"""Account for the sealed AlphaTrend simulation without rerunning or selecting a strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def attribute_leg(fills, positions, equity, config):
    """Flat-start cash equity leg: realized plus terminal unrealized, less fees.

    Execution friction is embedded in fill prices. Borrow stays at book level because
    this artifact has no instrument-level borrow journal. No gross-alpha claim.
    """
    if equity.empty or equity.ts.duplicated().any() or not equity.ts.is_monotonic_increasing:
        raise ValueError("Invalid equity timeline")
    if positions.duplicated(["ts", "instrument_id"]).any():
        raise ValueError("Duplicate position snapshot")
    for frame, fields in [
        (fills, ["realized_pnl_quote", "fee", "notional"]),
        (positions, ["unreal_pnl", "weight"]),
        (equity, ["equity"]),
    ]:
        if not np.isfinite(frame[fields].to_numpy(dtype=float)).all():
            raise ValueError("Non-finite accounting input")
    terminal = positions.loc[positions.ts == equity.ts.iloc[-1]]
    instruments = sorted(set(fills.instrument_id) | set(positions.instrument_id))
    rows = []
    for iid in instruments:
        f = fills.loc[fills.instrument_id == iid]
        p = positions.loc[positions.instrument_id == iid]
        unreal = float(terminal.loc[terminal.instrument_id == iid, "unreal_pnl"].sum())
        realized = float(f.realized_pnl_quote.sum())
        fees = float(f.fee.sum())
        rows.append(
            {
                "instrument_id": iid,
                "realized": realized,
                "terminal_unrealized": unreal,
                "commission": fees,
                "pnl_after_commission_before_borrow": realized + unreal - fees,
                "notional": float(f.notional.sum()),
                "fills": len(f),
                "abs_weight_session_sum": float(p.weight.abs().sum()),
                "short_weight_session_sum": float(-p.loc[p.weight < 0, "weight"].sum()),
            }
        )
    borrow = float(config["borrow_total"])
    financing = float(config["financing_cashflow_total"])
    actions = float(config["corporate_action_cashflow_total"])
    expected = (
        sum(r["pnl_after_commission_before_borrow"] for r in rows) + borrow + financing + actions
    )
    actual = float(equity.equity.iloc[-1]) - float(config["initial_cash"])
    residual = actual - expected
    if abs(residual) > 1e-6:
        raise ValueError(f"Unreconciled leg: {residual}")
    return {
        "instruments": rows,
        "borrow_cashflow": borrow,
        "financing_cashflow": financing,
        "corporate_action_cashflow": actions,
        "equity_change": actual,
        "reconciliation_residual": residual,
        "equity_observations": len(equity),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = (
        args.source_root / "artifacts/publication/alphatrend_upstream_replay_manifest.json"
    )
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    body = {k: v for k, v in manifest.items() if k != "content_hash"}
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if manifest["content_hash"] != f"sha256:{digest}":
        raise ValueError("Manifest content hash mismatch")
    verified = 0
    for section in ("private_input_snapshot", "private_reference_output"):
        snapshot = manifest[section]
        for record in snapshot["records"]:
            path = args.source_root / snapshot["path"] / record["path"]
            data = path.read_bytes()
            if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError(f"Sealed input/output drift: {path}")
            verified += 1
    root = args.source_root / manifest["private_reference_output"]["path"]
    wf = json.loads((root / "walkforward.json").read_text())
    totals = {}
    legs = []
    for leg in sorted((root / "legs").iterdir()):
        config = json.loads((leg / "run_meta.json").read_text())["config"]
        if not pd.read_parquet(leg / "funding.parquet").empty:
            raise ValueError("Funding attribution requires a separate contract")
        frames = [
            pd.read_parquet(leg / f"{kind}.parquet") for kind in ("fills", "positions", "equity")
        ]
        result = attribute_leg(*frames, config)
        result["leg"] = leg.name
        result["start_ts"] = int(frames[2].ts.iloc[0])
        result["end_ts"] = int(frames[2].ts.iloc[-1])
        legs.append(result)
        for row in result["instruments"]:
            target = totals.setdefault(
                row["instrument_id"], {k: 0 for k in row if k != "instrument_id"}
            )
            for key in target:
                target[key] += row[key]
    table = [dict(instrument_id=iid, **row) for iid, row in totals.items()]
    table.sort(key=lambda r: r["pnl_after_commission_before_borrow"])
    root_equity = pd.read_parquet(root / "equity.parquet")
    delta = float(root_equity.equity.iloc[-1] - root_equity.equity.iloc[0])
    leg_delta = sum(r["equity_change"] for r in legs)
    if abs(delta - leg_delta) > 1e-6:
        raise ValueError("Leg stitching failed to reconcile")
    total_exposure = sum(r["abs_weight_session_sum"] for r in table)
    for row in table:
        row["gross_exposure_share"] = row["abs_weight_session_sum"] / total_exposure
    result = {
        "schema": "alphac.alphatrend-baseline-attribution.v1",
        "claim_boundary": "Sealed simulation accounting; no new strategy return trial",
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "verified_files": verified,
        "baseline_summary": wf["summary"],
        "instruments": table,
        "legs": legs,
        "total_equity_change": delta,
        "total_borrow_cashflow": sum(r["borrow_cashflow"] for r in legs),
        "max_leg_residual": max(abs(r["reconciliation_residual"]) for r in legs),
        "unavailable": [
            "independent horizon PnL from a blended book",
            "instrument-level borrow cashflows",
            "spread/impact split from execution prices",
        ],
        "trial_status": "No new return trial; 21 archived family identities are not reset",
    }
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "source_manifest.json").write_bytes(raw)
    (args.output / "attribution.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n"
    )
    lines = [
        "# AlphaTrend sealed baseline attribution",
        "",
        f"Verified {verified} sealed input/output files. All {len(legs)} legs reconcile to "
        f"within ${result['max_leg_residual']:.9f}. The stitched equity gain is ${delta:,.2f}.",
        "",
        "Historical simulation, not forward performance. Commission is explicit; spread and "
        "impact are embedded in execution prices. Borrow is reported at book level, not "
        "allocated by an invented rule. Dollar contributions are additive across cash-linked legs.",
        "",
        "| Instrument | PnL after commission, before borrow | Commission | Gross exposure share |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in table:
        lines.append(
            f"| {row['instrument_id']} | ${row['pnl_after_commission_before_borrow']:,.2f} | "
            f"${row['commission']:,.2f} | {row['gross_exposure_share']:.1%} |"
        )
    lines += [
        "",
        f"Book-level borrow cashflow: ${result['total_borrow_cashflow']:,.2f}.",
        "",
        "Exposure shares use sums of absolute recorded session weights. These are capital "
        "exposures, not risk contributions. The blended book does not record horizon-level "
        "PnL; attributing its whole PnL separately to 63/126/252 days would double-count.",
        "",
        "Loss rankings are diagnostic and are not an instruction to remove losing assets. "
        "The inspected interval is now research evidence, not an untouched test of a new variant.",
        "",
    ]
    (args.output / "ATTRIBUTION.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "verified_files",
                    "total_equity_change",
                    "total_borrow_cashflow",
                    "max_leg_residual",
                )
            }
        )
    )
    print(json.dumps(table, indent=2))


if __name__ == "__main__":
    main()
