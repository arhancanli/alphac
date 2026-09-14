"""Compare within-bar price ratios with retained adjusted history; no repairs."""

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-full-price-panel-20260912"
LAKE = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2/lake_mf/ohlcv_1d"


def main():
    source = OUT / "quality_review.parquet"
    bindings = {}
    records = []
    for row in pd.read_parquet(source).itertuples():
        date = pd.Timestamp(row.session_ms, unit="ms", tz="UTC")
        path = LAKE / f"instrument_id=XUSE:CASH:{row.symbol}USD/year={date.year}/data.parquet"
        data = pd.read_parquet(path)
        bindings[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        selected = data[pd.to_datetime(data.ts_open, utc=True) == date]
        assert len(selected) == 1
        archived = selected.iloc[0]
        result = {
            "symbol": row.symbol,
            "date": str(date.date()),
            "zero_volume": bool(row.zero_volume),
        }
        for field in ["open", "high", "low"]:
            # The archived feed multiplies all same-day OHLC by one adjustment
            # factor. Within-day ratios cancel it; no raw-price parity claim.
            direct = float(getattr(row, "raw_" + field)) / float(row.raw_close)
            prior = float(archived[field]) / float(archived.close)
            result[field + "_ratio_difference_bps"] = (direct / prior - 1) * 10000
        result["max_ratio_difference_bps"] = max(
            abs(result[f + "_ratio_difference_bps"]) for f in ["open", "high", "low"]
        )
        result["review_class"] = (
            "ZERO_VOLUME_UNRESOLVED"
            if row.zero_volume
            else "CROSS_SOURCE_DISAGREEMENT"
            if result["max_ratio_difference_bps"] > 10
            else "EXTREME_WITH_SIMILAR_ARCHIVED_RATIOS"
        )
        records.append(result)
    for path in [Path(__file__), source]:
        bindings[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    pd.DataFrame(records).to_parquet(OUT / "extreme_cross_source_review.parquet", index=False)
    (OUT / "extreme_review.json").write_text(
        json.dumps(
            {
                "method": "within-session OHL/close; 10bp descriptive discrepancy triage",
                "limitation": "agreement does not prove tape correctness; no automatic correction",
                "bindings": bindings,
                "records": records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(
        pd.DataFrame(records)[
            ["symbol", "date", "max_ratio_difference_bps", "review_class"]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
