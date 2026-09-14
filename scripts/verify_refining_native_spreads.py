"""Verify raw timestamps, accepted snapshots and lifecycle without audit helpers."""

import hashlib
import json
from collections import Counter
from pathlib import Path

import databento as db
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/refining-native-spreads-20260912"
SOURCE = ROOT / "evidence/sleeve-frontier-20260912/refining_sample"


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    for path, expected in protocol["bindings"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
    inv = json.loads((OUT / "inventory.json").read_text())
    result = json.loads((OUT / "result.json").read_text())
    grid = json.loads((OUT / "grid.json").read_text())
    accepted, timestamps, lifecycle = 0, 0, []
    for sample in result["samples"]:
        date = sample["date"]
        if not sample["route_metadata_valid"]:
            assert not any(r["date"] == date for r in grid)
            continue
        start = pd.Timestamp(date + "T18:00:00Z")
        defs = (
            db.DBNStore.from_file(SOURCE / f"{date}-definition.dbn.zst")
            .to_df(price_type="fixed")
            .reset_index()
        )
        raw = (
            db.DBNStore.from_file(SOURCE / f"{date}-mbp-1.dbn.zst")
            .to_df(price_type="fixed")
            .reset_index()
        )
        streams, clocks, ticks = {}, {}, {}
        for product in ("RB", "HO"):
            c = inv[date]["pair_candidates"][product][0]
            d = defs[
                (defs.publisher_id == c["publisher_id"])
                & (defs.instrument_id == c["instrument_id"])
                & (defs.ts_recv <= start)
            ]
            d = d[d.ts_recv == d.ts_recv.max()]
            assert all(d.currency == "USD")
            assert all(d.activation <= start)
            assert all(d.expiration > start + pd.Timedelta(days=10))
            lifecycle.append(
                {
                    "date": date,
                    "symbol": c["symbol"],
                    "currency": "USD",
                    "activation": str(d.iloc[0].activation),
                    "expiration": str(d.iloc[0].expiration),
                    "first_notice_verified": False,
                }
            )
            q = raw[
                (raw.publisher_id == c["publisher_id"]) & (raw.instrument_id == c["instrument_id"])
            ]
            streams[product] = list(q.itertuples())
            clocks[product] = np.array([x.ts_recv.value for x in streams[product]], dtype=np.int64)
            ticks[product] = c["tick_fixed"]
        rows = [r for r in grid if r["date"] == date]
        assert len(rows) == 600
        assert [r["decision_ns"] for r in rows] == list(
            range(start.value, start.value + 600 * 10**9, 10**9)
        )
        assert dict(Counter(r["reason"] for r in rows)) == sample["reasons"]
        for row in rows:
            qs = []
            for product in ("RB", "HO"):
                i = int(np.searchsorted(clocks[product], row["decision_ns"], side="right")) - 1
                q = None if i < 0 else streams[product][i]
                component = row["components"][product]
                assert component["recv_ns"] == (None if q is None else q.ts_recv.value)
                assert component["event_ns"] == (None if q is None else q.ts_event.value)
                timestamps += 2
                if row["reason"] != "accepted":
                    continue
                assert q is not None
                assert 0 <= q.ts_event.value <= q.ts_recv.value <= row["decision_ns"]
                assert row["decision_ns"] - q.ts_event.value <= 10**9
                assert row["decision_ns"] - q.ts_recv.value <= 10**9
                assert int(q.flags) & 128 and not int(q.flags) & 44
                assert int(q.bid_px_00) != 2**63 - 1 and int(q.ask_px_00) != 2**63 - 1
                assert q.bid_px_00 <= q.ask_px_00
                assert min(q.bid_sz_00, q.ask_sz_00) >= (2 if product == "RB" else 1)
                assert q.bid_px_00 % ticks[product] == q.ask_px_00 % ticks[product] == 0
                qs.append(q)
            if row["reason"] == "accepted":
                assert abs(qs[0].ts_recv.value - qs[1].ts_recv.value) <= 250_000_000
                accepted += 1
    assert accepted == 147 and timestamps == 4800
    verification = {
        "accepted_snapshots_independently_verified": accepted,
        "exact_nullable_timestamps_verified": timestamps,
        "lifecycle_checks": lifecycle,
        "protocol_bindings_verified": True,
    }
    (OUT / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
