"""Schema and quote quality audit only; never build a spread return series."""

import hashlib
import json
from pathlib import Path

import databento as db
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/sleeve-frontier-20260912"


def main():
    capture = json.loads((OUT / "refining_capture.json").read_text())
    for receipt in capture["requests"]:
        path = OUT / "refining_sample" / receipt["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt["sha256"]:
            raise ValueError("Capture changed")
    results = []
    for date in ["2015-01-15", "2020-04-20", "2025-07-15"]:
        defs = (
            db.DBNStore.from_file(OUT / "refining_sample" / f"{date}-definition.dbn.zst")
            .to_df()
            .reset_index()
        )
        quotes = (
            db.DBNStore.from_file(OUT / "refining_sample" / f"{date}-mbp-1.dbn.zst")
            .to_df()
            .reset_index()
        )
        start = pd.Timestamp(date + "T18:00:00Z")
        end = pd.Timestamp(date + "T18:10:00Z")
        known = (
            defs.loc[defs.ts_recv <= start]
            .sort_values("ts_recv")
            .groupby("instrument_id")
            .tail(1)
            .set_index("instrument_id")
        )
        # Conservatively exclude any instrument with definition changes inside the sample.
        changed = set(defs.loc[(defs.ts_recv > start) & (defs.ts_recv < end), "instrument_id"])
        symbols = quotes.instrument_id.map(known.raw_symbol)
        classes = quotes.instrument_id.map(known.instrument_class)
        outright = (
            (classes == "F")
            & symbols.fillna("").str.fullmatch(r"(CL|RB|HO)[FGHJKMNQUVXZ][0-9]{1,4}")
            & ~quotes.instrument_id.isin(changed)
        )
        valid = (
            np.isfinite(quotes.bid_px_00)
            & np.isfinite(quotes.ask_px_00)
            & (quotes.bid_px_00 <= quotes.ask_px_00)
            & (quotes.bid_sz_00 > 0)
            & (quotes.ask_sz_00 > 0)
        )
        root = symbols.fillna("").str.extract(r"^(CL|RB|HO)")[0]
        by_root = {}
        suffixes = {}
        for product in ["CL", "RB", "HO"]:
            mask = outright & (root == product)
            good = mask & valid
            matched = sorted(set(symbols.loc[good]))
            suffixes[product] = {s[len(product) :] for s in matched}
            ids = set(quotes.loc[mask, "instrument_id"])
            fields = {}
            for field in ["currency", "unit_of_measure", "unit_of_measure_qty", "display_factor"]:
                fields[field] = sorted({str(x) for x in known.loc[known.index.isin(ids), field]})
            by_root[product] = {
                "outright_quote_rows": int(mask.sum()),
                "valid_two_sided_rows": int(good.sum()),
                "invalid_two_sided_rows": int((mask & ~valid).sum()),
                "outright_contracts_with_valid_quotes": len(matched),
                "definition_fields": fields,
            }
        common = sorted(set.intersection(*suffixes.values()))
        results.append(
            {
                "date": date,
                "total_quote_rows": len(quotes),
                "prior_definition_missing_rows": int(symbols.isna().sum()),
                "non_outright_or_changed_definition_rows": int((~outright).sum()),
                "definition_changed_in_window_instruments": len(changed),
                "products": by_root,
                "common_raw_contract_suffixes": common,
                "has_three_leg_outright_coverage": bool(common),
            }
        )
    result = {
        "samples": results,
        "stage": "PASS_TO_CONTRACT_MONTH_AND_SYNCHRONIZATION_AUDIT"
        if all(x["has_three_leg_outright_coverage"] for x in results)
        else "DATA_GATED",
        "same_suffix_does_not_prove_synchronized_executable_quotes": True,
        "historical_spec_changes_not_resolved": True,
        "margin_and_roll_model_not_resolved": True,
        "alpha_evidence": False,
        "strategy_returns_computed": False,
        "hypothesis_union": 240,
    }
    (OUT / "refining_quote_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
