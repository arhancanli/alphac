"""Independent raw-record and exact-integer checks of the sealed-policy audit."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import databento as db
import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/refining-synchronization-20260912-v3"


def main():
    result = json.loads((OUT / "result.json").read_text())
    mapping = json.loads((OUT / "contract_mapping.json").read_text())
    for suffix in ("", "-v2"):
        prior = ROOT / ("evidence/refining-synchronization-20260912" + suffix)
        for name in ("result.json", "contract_mapping.json"):
            assert json.loads((prior / name).read_text()) == json.loads((OUT / name).read_text())
    for suffix in ("", "-v2", "-v3"):
        prior = ROOT / ("evidence/refining-synchronization-20260912" + suffix)
        for path, digest in json.loads((prior / "protocol.json").read_text())["bindings"].items():
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    grid = pq.read_table(OUT / "grid_audit.parquet").to_pylist()
    assert len(grid) == 1800
    flags = {}
    timestamp_checks = 0
    accepted_checks = 0
    for sample in result["samples"]:
        date = sample["date"]
        frame = (
            db.DBNStore.from_file(
                ROOT / "evidence/sleeve-frontier-20260912/refining_sample" / f"{date}-mbp-1.dbn.zst"
            )
            .to_df(price_type="fixed")
            .reset_index()
        )
        selected = {}
        flags[date] = {}
        for root, contract in mapping[date].items():
            subset = frame.loc[
                (frame.instrument_id == contract["instrument_id"])
                & (frame.publisher_id == contract["publisher_id"])
            ]
            selected[root] = list(subset.itertuples())
            flags[date][root] = dict(Counter(int(q.flags) for q in selected[root]))
        times = {
            root: np.array([q.ts_recv.value for q in rows], dtype=np.int64)
            for root, rows in selected.items()
        }
        rows = [row for row in grid if row["date"] == date]
        assert len(rows) == 600
        assert Counter(row["reason"] for row in rows) == sample["reasons"]
        assert sum(row["valid"] for row in rows) == sample["accepted_count"]
        for row in rows:
            quotes = {}
            for root, records in selected.items():
                index = int(np.searchsorted(times[root], row["decision_ns"], side="right")) - 1
                quote = None if index < 0 else records[index]
                quotes[root] = quote
                for suffix in ("recv", "event"):
                    exact = None if quote is None else int(getattr(quote, "ts_" + suffix).value)
                    assert row[root + "_" + suffix + "_ns"] == exact
                    timestamp_checks += 1
            if not row["valid"]:
                assert row["roundtrip_width_fixed_usd"] is None
                continue
            for q in quotes.values():
                assert q is not None
                assert int(q.flags) & 128 and not int(q.flags) & (8 | 4 | 32)
                assert 0 <= q.ts_event.value <= q.ts_recv.value <= row["decision_ns"]
                assert row["decision_ns"] - q.ts_event.value <= 1_000_000_000
                assert row["decision_ns"] - q.ts_recv.value <= 1_000_000_000
            buy = (
                -3000 * int(quotes["CL"].bid_px_00)
                + 84000 * int(quotes["RB"].ask_px_00)
                + 42000 * int(quotes["HO"].ask_px_00)
            )
            sell = (
                -3000 * int(quotes["CL"].ask_px_00)
                + 84000 * int(quotes["RB"].bid_px_00)
                + 42000 * int(quotes["HO"].bid_px_00)
            )
            assert (buy, sell, buy - sell) == tuple(
                row[k]
                for k in (
                    "buy_recipe_fixed_usd",
                    "sell_recipe_fixed_usd",
                    "roundtrip_width_fixed_usd",
                )
            )
            size = min(
                min(int(q.bid_sz_00), int(q.ask_sz_00)) // ratio
                for q, ratio in ((quotes["CL"], 3), (quotes["RB"], 2), (quotes["HO"], 1))
            )
            assert row["displayed_two_way_recipes"] == size >= 1
            skew = max(q.ts_recv.value for q in quotes.values()) - min(
                q.ts_recv.value for q in quotes.values()
            )
            assert row["cross_leg_skew_ns"] == skew <= 250_000_000
            accepted_checks += 1
    assert accepted_checks == 32
    assert all(flag & 8 for counts in flags["2015-01-15"].values() for flag in counts)
    verified = {
        "grid_rows": len(grid),
        "exact_nullable_timestamp_checks": timestamp_checks,
        "independent_accepted_quote_checks": accepted_checks,
        "result_and_mapping_equal_all_three_versions": True,
        "all_three_protocol_source_bindings_verified": True,
        "selected_raw_flags_by_date_root": flags,
    }
    (OUT / "independent_verification.json").write_text(json.dumps(verified, indent=2) + "\n")
    print(json.dumps(verified, indent=2))


if __name__ == "__main__":
    main()
