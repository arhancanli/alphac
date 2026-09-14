"""Fixed sub-dollar raw-data sample; no forecasts, positions or strategy returns."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import databento as db
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/sleeve-frontier-20260912"


def main():
    estimate_path = OUT / "refining_data_estimate.json"
    estimate = json.loads(estimate_path.read_text())
    if not estimate["complete_estimate"] or not estimate["all_nine_root_windows_nonempty"]:
        raise ValueError("Complete positive metadata sample required")
    jobs = [r for r in estimate["requests"] if r["endpoint"] == "metadata.get_cost"]
    if len(jobs) != 6 or not 0 <= sum(r["value"] for r in jobs) <= 1:
        raise ValueError("Sample estimate exceeds one-dollar cap")
    protocol = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "purpose": "contract and quote feasibility only",
        "estimate_sha256": hashlib.sha256(estimate_path.read_bytes()).hexdigest(),
        "estimate_cap_usd": 1.0,
        "estimated_cost_usd": sum(r["value"] for r in jobs),
        "jobs": [r["parameters"] for r in jobs],
        "selection": (
            "2015-01-15 early history; 2020-04-20 known negative-oil stress; "
            "2025-07-15 recent history. Fixed before data download."
        ),
        "strategy_returns_allowed": False,
        "new_hypotheses": 0,
    }
    with (OUT / "refining_sample_protocol.json").open("x") as f:
        json.dump(protocol, f, indent=2)
    key = dotenv_values(Path.home() / ".config/alphaforge/databento.env")["DATABENTO_API_KEY"]
    client = db.Historical(key)
    directory = OUT / "refining_sample"
    directory.mkdir(exist_ok=False)
    receipts = []
    for job in jobs:
        params = dict(job["parameters"])
        params["symbols"] = params["symbols"].split(",")
        name = params["start"][:10] + "-" + params["schema"] + ".dbn.zst"
        path = directory / name
        capture = client.timeseries.get_range(**params, path=path)
        frame = capture.to_df().reset_index()
        # Schema/identity inventory only; retain raw data but emit no quote prices.
        receipt = {
            "parameters": params,
            "received_at": datetime.now(UTC).isoformat(),
            "file": name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
            "rows": len(frame),
            "columns": list(frame.columns),
            "instrument_ids": int(frame.instrument_id.nunique()),
        }
        if params["schema"] == "definition":
            receipt["instrument_classes"] = sorted(str(x) for x in frame.instrument_class.unique())
            receipt["currencies"] = sorted(str(x) for x in frame.currency.unique())
            receipt["raw_symbol_examples"] = sorted(str(x) for x in frame.raw_symbol.unique())[:12]
        else:
            receipt["missing_bid_or_ask_rows"] = int(
                frame[["bid_px_00", "ask_px_00"]].isna().any(axis=1).sum()
            )
            receipt["crossed_quote_rows"] = int((frame.bid_px_00 > frame.ask_px_00).sum())
            receipt["empty_bid_or_ask_size_rows"] = int(
                ((frame.bid_sz_00 == 0) | (frame.ask_sz_00 == 0)).sum()
            )
        receipts.append(receipt)
        (directory / (name + ".receipt.json")).write_text(json.dumps(receipt, indent=2) + "\n")
        print(name, len(frame), "records", flush=True)
    (OUT / "refining_capture.json").write_text(
        json.dumps(
            {
                "requests": receipts,
                "estimated_cost_usd": protocol["estimated_cost_usd"],
                "billed_cost_verified": False,
                "strategy_returns_computed": False,
                "hypothesis_union": 240,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
