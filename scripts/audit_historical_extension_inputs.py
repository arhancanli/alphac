"""Inventory timestamp coverage and membership metadata, without strategy returns."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "evidence/historical-extension-inputs-20260913"


def main():
    records, configurations, memberships = [], {}, []
    for sleeve, tables in [
        ("k30_dn_63", [("ohlcv_1d", "ts_open")]),
        ("crypto_carry_wk", [("ohlcv", "ts_open"), ("funding", "ts_funding")]),
    ]:
        p = PROD / "artifacts/walkforward" / sleeve / "walkforward.json"
        config = json.loads(p.read_text())["config"]
        configurations[sleeve] = {
            "config": config,
            "path": str(p),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for iid in config["instrument_ids"]:
            for table, timestamp in tables:
                parts = sorted(
                    (PROD / "data/lake" / table / f"instrument_id={iid}").glob("year=*/*.parquet")
                )
                lows, highs, rows = [], [], 0
                for path in parts:
                    parquet = pq.ParquetFile(path)
                    index = parquet.schema.names.index(timestamp)
                    for j in range(parquet.metadata.num_row_groups):
                        group = parquet.metadata.row_group(j)
                        stats = group.column(index).statistics
                        assert stats is not None and stats.has_min_max
                        lows.append(
                            int(pd.Timestamp(stats.min).value // 1000000)
                            if isinstance(stats.min, datetime)
                            else int(stats.min)
                        )
                        highs.append(
                            int(pd.Timestamp(stats.max).value // 1000000)
                            if isinstance(stats.max, datetime)
                            else int(stats.max)
                        )
                        rows += group.num_rows
                records.append(
                    {
                        "sleeve": sleeve,
                        "instrument": iid,
                        "table": table,
                        "files": len(parts),
                        "rows": rows,
                        "first_ms": min(lows) if lows else None,
                        "last_ms": max(highs) if highs else None,
                    }
                )
            parts = sorted(
                (PROD / "data/lake/universe_membership" / f"instrument_id={iid}").glob(
                    "year=*/*.parquet"
                )
            )
            for path in parts:
                data = pd.read_parquet(path)
                for row in data.to_dict("records"):
                    memberships.append(
                        {
                            "sleeve": sleeve,
                            "path": str(path),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            **row,
                        }
                    )
    frame = pd.DataFrame(records)
    frame["first_date"] = pd.to_datetime(frame.first_ms, unit="ms")
    frame["last_date"] = pd.to_datetime(frame.last_ms, unit="ms")
    frame.to_csv(OUT / "coverage.csv", index=False)
    pd.DataFrame(memberships).to_parquet(OUT / "membership_rows.parquet", index=False)
    summary = []
    for (sleeve, table), g in frame.groupby(["sleeve", "table"]):
        summary.append(
            {
                "sleeve": sleeve,
                "table": table,
                "instruments": len(g),
                "with_files": int((g.files > 0).sum()),
                "begins_by_2019_01_01": int((g.first_date <= pd.Timestamp("2019-01-01")).sum()),
                "begins_by_2021_01_01": int((g.first_date <= pd.Timestamp("2021-01-01")).sum()),
                "earliest": str(g.first_date.min()),
                "latest_instrument_start": str(g.first_date.max()),
            }
        )
    (OUT / "result.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "configs": configurations,
                "limits": "Current-lake footer timestamp bounds only. "
                "No internal gap, availability, survivorship, price adjustment "
                "or raw-payload certification. No new returns.",
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(summary, indent=2))
    m = pd.DataFrame(memberships)
    print("membership reasons", m.reason.value_counts().to_dict())
    print("membership earliest", pd.to_datetime(m.effective_from.min(), unit="ms"))


if __name__ == "__main__":
    main()
