"""Read-only inventory of explicit local price/action roots for the 17 ETFs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "evidence/alphatrend-raw-inventory-20260912"


def main():
    OUT.mkdir(exist_ok=False)
    prior = ROOT / "evidence/alphatrend-history-bridge-20260912/protocol.json"
    symbols = json.loads(prior.read_text())["symbols"]
    roots = [
        PROD / "data/lake",
        PROD / "data/lake_sharadar",
        PROD / "data/lake_mf",
        PROD / "data/reproduction/alphamax_k30_dn_63_polygon_reacquired_20260824/data/lake",
    ]
    rows, bindings = [], {}
    for lake in roots:
        for symbol in symbols:
            for dataset in ["ohlcv_1d", "corporate_actions"]:
                paths = sorted((lake / dataset).glob(f"instrument_id=*:{symbol}USD/**/*.parquet"))
                row = {
                    "lake": str(lake),
                    "symbol": symbol,
                    "dataset": dataset,
                    "files": len(paths),
                    "rows": 0,
                    "source_semantics_verified": False,
                }
                if paths:
                    frame = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
                    row["rows"] = len(frame)
                    column = "ts_open" if dataset == "ohlcv_1d" else "ex_date"
                    if len(frame) and column in frame:
                        stamps = pd.to_datetime(frame[column], utc=True)
                        row.update(first=str(stamps.min()), last=str(stamps.max()))
                    for p in paths:
                        bindings[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
                rows.append(row)
    for p in [Path(__file__), prior]:
        bindings[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    result = {
        "scope": "EXPLICIT_ROOTS_READ_ONLY_INVENTORY_NOT_COMPLETENESS_CERTIFICATE",
        "roots": [str(p) for p in roots],
        "rows": rows,
        "bindings": bindings,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
    }
    (OUT / "inventory.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps([r for r in rows if r["files"] and "/lake_mf" not in r["lake"]], indent=2))


if __name__ == "__main__":
    main()
