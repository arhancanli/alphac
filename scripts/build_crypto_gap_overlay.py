"""Build isolated archival repairs, preserving every existing bar verbatim."""

import csv
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
SOURCE = ROOT / "evidence/crypto-gap-archives-20260913"
OUT = ROOT / "evidence/crypto-gap-overlay-20260913"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    manifest = json.loads(
        (ROOT / "evidence/crypto-2022-input-grid-20260913/manifest.json").read_text()
    )
    receipts = json.loads((SOURCE / "result.json").read_text())
    patches = {}
    lineage = []
    observed = pd.Timestamp(datetime.now(UTC)).as_unit("ms")
    for receipt in receipts:
        required = set(receipt.get("recovered_timestamps", []))
        if not required:
            continue
        iid = receipt["instrument"]
        key = iid.rsplit(":", 1)[1] + "-" + receipt["day"]
        path = SOURCE / (key + ".zip")
        assert (
            sha(path) == receipt["sha256"] == (SOURCE / (key + ".CHECKSUM")).read_text().split()[0]
        )
        with zipfile.ZipFile(path) as z:
            assert len(z.namelist()) == 1
            rows = csv.reader(io.StringIO(z.read(z.namelist()[0]).decode()))
            seen = set()
            for row in rows:
                if not row or not row[0].isdigit() or int(row[0]) not in required:
                    continue
                ts = int(row[0])
                assert ts not in seen
                seen.add(ts)
                assert int(row[6]) == ts + 3600000 - 1
                item = {
                    "instrument_id": iid,
                    "ts_open": pd.to_datetime(ts, unit="ms", utc=True),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "quote_volume": float(row[7]),
                    "n_trades": int(row[8]),
                    "quality_flags": 0,
                    "ingested_at": observed,
                }
                assert (
                    0
                    < item["low"]
                    <= min(item["open"], item["close"])
                    <= max(item["open"], item["close"])
                    <= item["high"]
                )
                assert item["volume"] >= 0 and item["quote_volume"] >= 0 and item["n_trades"] >= 0
                patches.setdefault(iid, []).append(item)
                lineage.append(
                    {
                        "instrument_id": iid,
                        "ts_open_ms": ts,
                        "archive": str(path.relative_to(ROOT)),
                        "archive_sha256": receipt["sha256"],
                        "retrieval_receipt": key + ".receipt.json",
                    }
                )
            assert seen == required
    results = []
    for iid, items in patches.items():
        source = PROD / "data/lake/ohlcv" / f"instrument_id={iid}" / "year=2022/data.parquet"
        expected = manifest["source_sha256"][str(source)]
        assert sha(source) == expected
        schema = pq.ParquetFile(source).schema_arrow
        original = pd.read_parquet(source)
        additions = pd.DataFrame(items)
        assert not additions.ts_open.duplicated().any()
        assert not original.ts_open.isin(additions.ts_open).any()
        # Cast all added values to the existing source schema; preserve ingestion as current.
        added = pa.Table.from_pandas(additions, schema=schema, preserve_index=False).to_pandas()
        merged = (
            pd.concat([original, added], ignore_index=True)
            .sort_values("ts_open")
            .reset_index(drop=True)
        )
        retained = merged[~merged.ts_open.isin(added.ts_open)].reset_index(drop=True)
        pd.testing.assert_frame_equal(
            retained, original.sort_values("ts_open").reset_index(drop=True)
        )
        assert not merged.ts_open.duplicated().any()
        target = OUT / "lake/ohlcv" / f"instrument_id={iid}" / "year=2022/data.parquet"
        target.parent.mkdir(parents=True)
        pq.write_table(pa.Table.from_pandas(merged, schema=schema, preserve_index=False), target)
        replay = pd.read_parquet(target)
        pd.testing.assert_frame_equal(replay, merged)
        assert sha(source) == expected
        results.append(
            {
                "instrument": iid,
                "added": len(added),
                "source_path": str(source),
                "source_sha256": expected,
                "output_path": str(target.relative_to(ROOT)),
                "output_sha256": sha(target),
                "original_rows_unchanged": True,
            }
        )
    assert sum(r["added"] for r in results) == 360
    (OUT / "bar_lineage.json").write_text(json.dumps(lineage, indent=2) + "\n")
    (OUT / "result.json").write_text(
        json.dumps(
            {
                "repairs": results,
                "production_unchanged": True,
                "full_lake": False,
                "returns_measured": False,
                "limitations": "Four patched yearly partitions only; "
                "funding, membership, contract status and settlement not supplied. "
                "No historical availability guarantee.",
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
