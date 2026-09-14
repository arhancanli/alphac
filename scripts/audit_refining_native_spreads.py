"""Inventory native spread legs and audit a fixed two-instrument route, without returns."""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import databento as db
import numpy as np
import pandas as pd

from alphaforge.validation.refining_spread_legs import exposure, latest_legs

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/refining-native-spreads-20260912"
PRIOR = ROOT / "evidence/refining-synchronization-20260912-v3"
SOURCE = ROOT / "evidence/sleeve-frontier-20260912/refining_sample"
SCALE = 1_000_000_000


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def quality(q, decision, size, tick):
    if q is None:
        return "no_prior_quote"
    recv, event = int(q.ts_recv.value), int(q.ts_event.value)
    if not 0 <= event <= recv <= decision:
        return "clock_order"
    if max(decision - recv, decision - event) > SCALE:
        return "stale"
    if not int(q.flags) & 128 or int(q.flags) & (8 | 4 | 32):
        return "feed_state"
    bid, ask = int(q.bid_px_00), int(q.ask_px_00)
    if bid == 2**63 - 1 or ask == 2**63 - 1 or bid > ask:
        return "invalid_book"
    if tick <= 0 or tick == 2**63 - 1 or bid % tick or ask % tick:
        return "invalid_tick"
    if min(int(q.bid_sz_00), int(q.ask_sz_00)) < size:
        return "insufficient_size"
    return "accepted"


def main():
    for seal_path in [PRIOR / "closure.json", SOURCE.parent / "closure.json"]:
        for path, expected in json.loads(seal_path.read_text())["files"].items():
            assert digest(ROOT / path) == expected, path
    OUT.mkdir(exist_ok=False)
    mapping = json.loads((PRIOR / "contract_mapping.json").read_text())
    protocol = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "scope": "native spread metadata and quote feasibility only; no returns",
        "prior_observation": "C1 definition samples inspected; quote coverage not yet measured",
        "selection": (
            "same outright identities and maturity as prior audit; exact signed 1:1 pair legs"
        ),
        "recipe": "2 gasoline-crude spreads plus 1 heating-oil-crude spread; two separate orders",
        "criteria": (
            "600 one-second decisions; max event/receive age 1s; skew 250ms; "
            "F_LAST and no bad flags; two-way sizes 2 and 1; >=90% each date"
        ),
        "anomalous_sides": "never repair using spread name; block route",
        "price_policy": "check fixed raw tick only; no dollar cost without multiplier validation",
        "bindings": {
            str(p.relative_to(ROOT)): digest(p)
            for p in [
                PRIOR / "closure.json",
                Path(__file__),
                ROOT / "src/alphaforge/validation/refining_spread_legs.py",
            ]
        },
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    summaries, inventory, grids = [], {}, []
    for date, outright in mapping.items():
        start = int(pd.Timestamp(date + "T18:00:00Z").value)
        defs = (
            db.DBNStore.from_file(SOURCE / f"{date}-definition.dbn.zst")
            .to_df(price_type="fixed")
            .reset_index()
        )
        spreads = defs[
            (defs.instrument_class == "S") & (defs.ts_recv <= pd.Timestamp(start, tz="UTC"))
        ]
        target = {
            (c["publisher_id"], c["instrument_id"]): ratio
            for c, ratio in [(outright["CL"], -3), (outright["RB"], 2), (outright["HO"], 1)]
        }
        candidates = {"RB": [], "HO": []}
        counts, matches, anomalies, all_entries = Counter(), [], [], []
        for (pub, ident), group in spreads.groupby(["publisher_id", "instrument_id"], sort=True):
            records = [
                {
                    "recv_ns": int(r.ts_recv.value),
                    "event_ns": int(r.ts_event.value),
                    "publisher_id": int(pub),
                    "instrument_id": int(ident),
                    "raw_symbol": str(r.raw_symbol),
                    "leg_count": int(r.leg_count),
                    "leg_index": int(r.leg_index),
                    "action": str(r.security_update_action),
                    "leg_instrument_id": int(r.leg_instrument_id),
                    "leg_side": str(r.leg_side),
                    "numerator": int(r.leg_ratio_qty_numerator),
                    "denominator": int(r.leg_ratio_qty_denominator),
                }
                for r in group.itertuples()
            ]
            try:
                legs = latest_legs(records, start)
                vector = exposure(legs)
            except ValueError as e:
                counts[str(e)] += 1
                continue
            counts["complete_spread_definitions"] += 1
            entry = {
                "publisher_id": int(pub),
                "instrument_id": int(ident),
                "symbol": legs[0]["raw_symbol"],
                "legs": legs,
                "exposure": {f"{p}:{i}": str(v) for (p, i), v in vector.items()},
            }
            all_entries.append(entry)
            if vector == target or vector == {k: -v for k, v in target.items()}:
                matches.append(entry)
            for product in ("RB", "HO"):
                pair = {
                    (outright["CL"]["publisher_id"], outright["CL"]["instrument_id"]): -1,
                    (outright[product]["publisher_id"], outright[product]["instrument_id"]): 1,
                }
                if set(vector) != set(pair):
                    continue
                if vector != pair:
                    anomalies.append(
                        dict(entry, intended_product=product, reason="signed_exposure_mismatch")
                    )
                    continue
                latest = group[
                    (group.ts_recv.astype("int64") == legs[0]["recv_ns"])
                    & (group.ts_event.astype("int64") == legs[0]["event_ns"])
                ]
                if latest.min_price_increment.nunique() != 1:
                    counts["inconsistent_tick"] += 1
                    continue
                entry = dict(entry, tick_fixed=int(latest.iloc[0].min_price_increment))
                candidates[product].append(entry)
        inventory[date] = {
            "all_complete_spreads": all_entries,
            "exact_single_recipe_matches": matches,
            "pair_candidates": candidates,
            "exposure_anomalies": anomalies,
            "counts": dict(counts),
        }
        summary = {
            "date": date,
            "counts": dict(counts),
            "exact_single_recipe_matches": len(matches),
            "pair_candidate_counts": {p: len(x) for p, x in candidates.items()},
            "exposure_anomalies": len(anomalies),
            "route_metadata_valid": False,
            "passes_coverage": False,
        }
        if any(len(candidates[p]) != 1 for p in candidates):
            summary["blocked_reason"] = "missing_or_ambiguous_signed_pair"
            summaries.append(summary)
            continue
        selected = {p: candidates[p][0] for p in candidates}
        changed = defs[
            (defs.ts_recv > pd.Timestamp(start, tz="UTC"))
            & (defs.ts_recv < pd.Timestamp(start + 600 * SCALE, tz="UTC"))
        ]
        if any(
            (
                (changed.publisher_id == c["publisher_id"])
                & (changed.instrument_id == c["instrument_id"])
            ).any()
            for c in selected.values()
        ):
            raise ValueError("Selected native spread definition changed in window")
        summary["route_metadata_valid"] = True
        summary["selected"] = {p: c["symbol"] for p, c in selected.items()}
        quotes = (
            db.DBNStore.from_file(SOURCE / f"{date}-mbp-1.dbn.zst")
            .to_df(price_type="fixed")
            .reset_index()
        )
        streams, times = {}, {}
        summary["raw_flags"] = {}
        for p, c in selected.items():
            subset = quotes[
                (quotes.publisher_id == c["publisher_id"])
                & (quotes.instrument_id == c["instrument_id"])
            ]
            streams[p] = list(subset.itertuples())
            times[p] = np.array([r.ts_recv.value for r in streams[p]], dtype=np.int64)
            assert np.all(times[p][1:] >= times[p][:-1])
            summary["raw_flags"][p] = dict(Counter(int(r.flags) for r in streams[p]))
        reasons = Counter()
        for decision in range(start, start + 600 * SCALE, SCALE):
            record = {"date": date, "decision_ns": decision, "components": {}}
            current = {}
            for p, c in selected.items():
                index = int(np.searchsorted(times[p], decision, side="right")) - 1
                q = None if index < 0 else streams[p][index]
                current[p] = q
                record["components"][p] = {
                    "reason": quality(q, decision, 2 if p == "RB" else 1, c["tick_fixed"]),
                    "recv_ns": None if q is None else int(q.ts_recv.value),
                    "event_ns": None if q is None else int(q.ts_event.value),
                }
            failures = [
                p + ":" + c["reason"]
                for p, c in record["components"].items()
                if c["reason"] != "accepted"
            ]
            if failures:
                reason = failures[0]
            else:
                skew = abs(current["RB"].ts_recv.value - current["HO"].ts_recv.value)
                reason = "accepted" if skew <= 250_000_000 else "cross_spread_skew"
            record["reason"] = reason
            reasons[reason] += 1
            grids.append(record)
        summary.update(
            decisions=600,
            accepted=reasons["accepted"],
            coverage=reasons["accepted"] / 600,
            passes_coverage=reasons["accepted"] / 600 >= 0.9,
            reasons=dict(reasons),
        )
        summaries.append(summary)
    result = {
        "samples": summaries,
        "hypothesis_union": 240,
        "strategy_returns_computed": False,
        "execution_cost_model_complete": False,
        "new_data_purchases": 0,
    }
    for name, value in [
        ("inventory.json", inventory),
        ("grid.json", grids),
        ("result.json", result),
    ]:
        (OUT / name).write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
