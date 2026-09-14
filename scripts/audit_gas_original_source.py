"""Audit alternative original-stock inputs without opening market data or returns."""

import gzip
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "evidence/gas-original-source-audit-20260913"


def main():
    raw = PROD / "data/raw/natural_gas_storage_weather"
    manifest = (
        PROD
        / "artifacts/feasibility/natural_gas_storage_weather/eia_wayback_capture_manifest.parquet"
    )
    files = [raw / "revisions.xls", manifest, OUT / "protocol.json", Path(__file__)]
    original = pd.read_excel(raw / "revisions.xls", sheet_name="original_data", header=1)
    original["Week ending"] = pd.to_datetime(original["Week ending"])
    assert not original["Week ending"].duplicated().any()
    stock = original.set_index("Week ending")["Total Lower 48"]
    captures = pd.read_parquet(manifest)
    assert captures.error.isna().all()
    for row in captures.itertuples():
        path = raw / "wayback_wngsr" / (row.timestamp + ".csv.gz")
        assert hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest() == row.raw_sha256
        files.append(path)
    captures["period_end"] = pd.to_datetime(captures.period_end)
    captures["original_total"] = captures.period_end.map(stock)
    captures["previous_original_total"] = (captures.period_end - pd.Timedelta(days=7)).map(stock)
    assert captures[["original_total", "previous_original_total"]].notna().all().all()
    captures["stock_difference"] = captures.reported_total_bcf - captures.original_total
    captures["prior_stock_difference"] = (
        captures.reported_prior_total_bcf - captures.previous_original_total
    )
    captures["naive_original_change"] = captures.original_total - captures.previous_original_total
    captures["change_difference"] = (
        captures.reported_net_change_bcf - captures.naive_original_change
    )
    captures.to_csv(OUT / "all_capture_comparisons.csv", index=False)
    subset = original[original["Week ending"].between("2017-01-06", "2025-12-31")]
    result = {
        "workbook_periods": len(subset),
        "capture_rows": len(captures),
        "unique_capture_periods": captures.period_end.nunique(),
        "stock_mismatch_rows": int((captures.stock_difference != 0).sum()),
        "prior_stock_mismatch_rows": int((captures.prior_stock_difference != 0).sum()),
        "net_change_mismatch_rows": int((captures.change_difference != 0).sum()),
        "workbook_columns": original.columns.tolist(),
        "timestamp_fields_present": False,
        "new_return_identities": 0,
        "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "source_sha256"}, indent=2))
    print(
        captures.loc[
            captures.change_difference != 0,
            ["period_end", "reported_net_change_bcf", "naive_original_change", "change_difference"],
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
