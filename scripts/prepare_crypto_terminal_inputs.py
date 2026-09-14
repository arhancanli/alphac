"""Copy retained crypto inputs without computing signals or returns."""

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "evidence/crypto-terminal-inputs-20260913"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    config_path = PROD / "artifacts/walkforward/crypto_carry_wk/walkforward.json"
    config = json.loads(config_path.read_text())["config"]
    ids = config["instrument_ids"]
    records = []
    for iid in ids:
        for table in ["ohlcv", "funding", "universe_membership"]:
            base = PROD / "data/lake" / table / f"instrument_id={iid}"
            for source in sorted(base.glob("year=*/data.parquet")):
                year = int(source.parent.name.split("=")[1])
                if table != "universe_membership" and year not in [2020, 2021, 2022]:
                    continue
                relative = source.relative_to(PROD / "data/lake")
                original_hash = sha(source)
                patched = ROOT / "evidence/crypto-gap-overlay-20260913/lake" / relative
                selected = patched if patched.exists() else source
                destination = OUT / "lake" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                selected_hash = sha(selected)
                shutil.copyfile(selected, destination)
                assert sha(destination) == selected_hash
                assert sha(source) == original_hash
                records.append(
                    {
                        "source": str(source),
                        "original_sha256": original_hash,
                        "selected_source": str(selected),
                        "snapshot": str(destination.relative_to(OUT)),
                        "sha256": selected_hash,
                        "bytes": destination.stat().st_size,
                        "overlay_used": selected == patched,
                    }
                )
    fields = [
        "instrument_id",
        "asset_class",
        "market_type",
        "base",
        "quote",
        "tick_size",
        "lot_size",
        "min_qty",
        "min_notional",
        "contract_multiplier",
        "can_short",
        "maker_fee_bps",
        "taker_fee_bps",
        "funding_interval_hours",
        "listed_ts",
        "delisted_ts",
        "valid_from_ms",
        "valid_to_ms",
    ]
    # Only instrument metadata, never account, authentication or execution tables.
    with sqlite3.connect(f"file:{PROD / 'var/ops.sqlite'}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in ids)
        query = (
            f"SELECT {','.join(fields)} FROM instruments_v "
            f"WHERE instrument_id IN ({placeholders}) ORDER BY instrument_id, valid_from_ms"
        )
        metadata = [dict(row) for row in db.execute(query, ids)]
    assert {row["instrument_id"] for row in metadata} == set(ids)
    (OUT / "instrument_versions.json").write_text(json.dumps(metadata, indent=2) + "\n")
    extras = [
        config_path,
        ROOT / "configs/base.yaml",
        ROOT / "evidence/luna-terminal-market-records-20260913/analysis.json",
        ROOT / "evidence/crypto-gap-overlay-20260913/luna_status_evidence.json",
    ]
    bindings = []
    for i, source in enumerate(extras):
        destination = OUT / "references" / f"{i}_{source.name}"
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, destination)
        assert sha(source) == sha(destination)
        bindings.append(
            {
                "source": str(source),
                "snapshot": str(destination.relative_to(OUT)),
                "sha256": sha(destination),
            }
        )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "2020-2022 price/funding plus retained membership partitions for fixed 58 IDs",
        "instrument_ids": ids,
        "partitions": records,
        "references": bindings,
        "metadata_sha256": sha(OUT / "instrument_versions.json"),
        "metadata_versions": len(metadata),
        "signals_or_returns_computed": False,
        "historical_availability_certified": False,
        "total_bytes": sum(row["bytes"] for row in records),
        "overlay_partitions": sum(row["overlay_used"] for row in records),
    }
    (OUT / "input_manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {k: report[k] for k in ["total_bytes", "metadata_versions", "overlay_partitions"]}
        )
    )
    print(f"Copied and verified {len(records)} partitions; no historical returns computed.")


if __name__ == "__main__":
    main()
