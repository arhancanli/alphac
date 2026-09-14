"""Fixed maturity and quote synchronization audit on the already acquired sample."""

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import databento as db
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from alphaforge.validation.refining_quote_sync import (
    ROOTS,
    SCALE,
    Contract,
    Quote,
    QuoteTimeline,
    quote_indication,
    select_month,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evidence/sleeve-frontier-20260912"
OUT = ROOT / "evidence/refining-synchronization-20260912-v2"
DATES = ("2015-01-15", "2020-04-20", "2025-07-15")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    seal = json.loads((SOURCE / "closure.json").read_text())
    for path, digest in seal["files"].items():
        if sha(ROOT / path) != digest:
            raise ValueError(f"Sealed input changed: {path}")
    OUT.mkdir(exist_ok=False)
    protocol = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "dates": DATES,
        "contract_selection": "nearest common full maturity from prior-known definitions only",
        "expiry_buffer_calendar_days": 10,
        "first_notice_verified": False,
        "decision_grid": "18:00:00 through 18:09:59 UTC each date, one second",
        "max_age_ns": SCALE,
        "max_cross_leg_skew_ns": 250_000_000,
        "minimum_two_way_recipes": 1,
        "minimum_accepted_grid_fraction_each_date": 0.90,
        "quote_policy": (
            "latest raw record by receive time, including invalid states; no last-good substitution"
        ),
        "flags": "require F_LAST; reject BAD_TS_RECV, MAYBE_BAD_BOOK, SNAPSHOT",
        "price_units": "raw DBN fixed-point dollars / 1e9; never multiply display_factor again",
        "scope": "quote indication only, not fills, not positions, not strategy returns",
        "bindings": {
            str(p.relative_to(ROOT)): sha(p)
            for p in [
                SOURCE / "closure.json",
                Path(__file__),
                ROOT / "src/alphaforge/validation/refining_quote_sync.py",
            ]
        },
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    results = []
    all_rows = []
    mapping = {}
    for date in DATES:
        start = pd.Timestamp(date + "T18:00:00Z")
        end = pd.Timestamp(date + "T18:10:00Z")
        definitions = (
            db.DBNStore.from_file(SOURCE / "refining_sample" / f"{date}-definition.dbn.zst")
            .to_df(price_type="fixed")
            .reset_index()
        )
        known = (
            definitions.loc[definitions.ts_recv <= start]
            .sort_values("ts_recv", kind="stable")
            .groupby(["publisher_id", "instrument_id"])
            .tail(1)
        )
        contracts = []
        excluded = Counter()
        for row in known.itertuples():
            match = re.fullmatch(r"(CL|RB|HO)[FGHJKMNQUVXZ][0-9]{1,4}", str(row.raw_symbol))
            if row.instrument_class != "F" or not match:
                continue
            if str(row.security_update_action) == "D":
                excluded["deleted_definition"] += 1
                continue
            if pd.isna(row.activation) or pd.isna(row.expiration):
                excluded["undefined_activation_or_expiration"] += 1
                continue
            if int(row.unit_of_measure_qty) % SCALE:
                excluded["fractional_contract_quantity"] += 1
                continue
            c = Contract(
                match[1],
                str(row.raw_symbol),
                int(row.publisher_id),
                int(row.instrument_id),
                int(row.maturity_year),
                int(row.maturity_month),
                int(row.ts_recv.value),
                int(row.activation.value),
                int(row.expiration.value),
                str(row.currency),
                str(row.unit_of_measure),
                int(row.unit_of_measure_qty) // SCALE,
                int(row.min_price_increment),
            )
            try:
                c.validate(as_of_ns=int(start.value), expiry_buffer_ns=10 * 86400 * SCALE)
            except ValueError as e:
                excluded[str(e)] += 1
                continue
            contracts.append(c)
        selected = select_month(
            contracts, as_of_ns=int(start.value), expiry_buffer_ns=10 * 86400 * SCALE
        )
        mapping[date] = {r: asdict(c) for r, c in selected.items()}
        selected_ids = {(c.publisher_id, c.instrument_id) for c in selected.values()}
        changes = definitions.loc[(definitions.ts_recv > start) & (definitions.ts_recv < end)]
        if any(
            (int(r.publisher_id), int(r.instrument_id)) in selected_ids
            for r in changes.itertuples()
        ):
            raise ValueError("Selected definition changes inside sample")
        # Contract choice above is complete before any quote values are loaded.
        store = db.DBNStore.from_file(SOURCE / "refining_sample" / f"{date}-mbp-1.dbn.zst")
        frame = store.to_df(price_type="fixed").reset_index()
        timelines = {}
        scale_checks = 0
        for product, c in selected.items():
            rows = frame.loc[
                (frame.publisher_id == c.publisher_id) & (frame.instrument_id == c.instrument_id)
            ]
            timeline = []
            for row in rows.itertuples():
                timeline.append(
                    Quote(
                        int(row.publisher_id),
                        int(row.instrument_id),
                        int(row.ts_recv.value),
                        int(row.ts_event.value),
                        int(row.flags),
                        int(row.bid_px_00),
                        int(row.ask_px_00),
                        int(row.bid_sz_00),
                        int(row.ask_sz_00),
                    )
                )
            timelines[product] = QuoteTimeline(timeline)
        # Cross-check all selected finite raw quote fields against SDK dollar decoding.
        floating = store.to_df().reset_index()
        mask = frame.instrument_id.isin([c.instrument_id for c in selected.values()])
        for field in ["bid_px_00", "ask_px_00"]:
            good = mask & (frame[field] != 2**63 - 1)
            np.testing.assert_allclose(
                frame.loc[good, field].to_numpy() / SCALE,
                floating.loc[good, field].to_numpy(),
                rtol=1e-14,
                atol=1e-12,
            )
            scale_checks += int(good.sum())
        rows = []
        for decision in range(int(start.value), int(end.value), SCALE):
            q = {r: timelines[r].at(decision) for r in ROOTS}
            indication = quote_indication(
                selected, q, decision_ns=decision, max_age_ns=SCALE, max_skew_ns=250_000_000
            )
            record = {"date": date, "decision_ns": decision, **indication}
            for product, item in q.items():
                record[product + "_recv_ns"] = None if item is None else item.recv_ns
                record[product + "_event_ns"] = None if item is None else item.event_ns
            rows.append(record)
        accepted = [x for x in rows if x["valid"]]
        widths = [x["roundtrip_width_fixed_usd"] / SCALE for x in accepted]
        results.append(
            {
                "date": date,
                "selected_symbols": {r: c.raw_symbol for r, c in selected.items()},
                "maturity": f"{selected['CL'].year:04d}-{selected['CL'].month:02d}",
                "decision_count": len(rows),
                "accepted_count": len(accepted),
                "accepted_fraction": len(accepted) / len(rows),
                "passes_fixed_coverage": len(accepted) / len(rows) >= 0.90,
                "reasons": dict(Counter(x["reason"] for x in rows)),
                "median_quoted_roundtrip_width_usd": float(np.median(widths)) if widths else None,
                "p95_quoted_roundtrip_width_usd": float(np.quantile(widths, 0.95))
                if widths
                else None,
                "min_displayed_two_way_recipes": min(
                    x["displayed_two_way_recipes"] for x in accepted
                )
                if accepted
                else 0,
                "raw_to_sdk_price_checks": scale_checks,
                "definition_exclusions": dict(excluded),
            }
        )
        all_rows.extend(rows)
    # Arrow infers nullable integers directly from Python records. A DataFrame
    # would first coerce missing nanosecond timestamps to lossy float64.
    pq.write_table(pa.Table.from_pylist(all_rows), OUT / "grid_audit.parquet")
    (OUT / "contract_mapping.json").write_text(json.dumps(mapping, indent=2) + "\n")
    result = {
        "samples": results,
        "all_samples_pass": all(x["passes_fixed_coverage"] for x in results),
        "execution_cost_model_complete": False,
        "strategy_returns_computed": False,
        "hypothesis_union": 240,
        "limitations": [
            "feed receive times are not local strategy observation times",
            "no legging or latency fills",
            "no depth beyond best price",
            "fees, margin, first-notice and market status unverified",
            "only three ten-minute windows; no full-history inference",
        ],
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
