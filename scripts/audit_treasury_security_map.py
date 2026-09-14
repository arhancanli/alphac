"""No-price mapping of issued reference candidates for the sealed event calendar."""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from alphaforge.validation.treasury_security_map import classify, issued_candidate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/treasury-security-map-20260912"
FRONTIER = ROOT / "evidence/sleeve-frontier-20260912"
STATE = ROOT / "artifacts/feasibility/treasury_auction_concession/schedule_state_machine_audit.json"
OLD = Path(
    "/Users/arhancanli/alphaforge/artifacts/feasibility/treasury_auction_concession/events.parquet"
)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    for p, h in json.loads((FRONTIER / "closure.json").read_text())["files"].items():
        assert sha(ROOT / p) == h
    state = json.loads(STATE.read_text())
    assert sha(OLD) == state["source_hashes"]["event_manifest_sha256"]
    # Preserve a local copy of the source-bound metadata only.
    (OUT / "original_events.parquet").write_bytes(OLD.read_bytes())
    protocol = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "scope": "issued reference mapping diagnostic, not on-the-run or settlement confirmation",
        "buckets": ["note_2y", "bill_6m", "note_10y"],
        "policy": "nominal fixed notes, new issue only; bills by 26-Week current auction term",
        "timing": "prior-date announcement and auction; issue <= decision < maturity",
        "selection": "latest issue then latest auction; reject ties",
        "roll_policy": "daily reference candidates only; no trade-roll rule asserted",
        "historical_observability": "current retrospective metadata, not historical archived vintages",
        "bindings": {
            str(p.relative_to(ROOT)): sha(p)
            for p in [
                OUT / "fiscal_identity.json",
                OUT / "original_events.parquet",
                STATE,
                FRONTIER / "treasury_event_sessions.parquet",
                Path(__file__),
                ROOT / "src/alphaforge/validation/treasury_security_map.py",
            ]
        },
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    payload = json.loads((OUT / "fiscal_identity.json").read_text())
    records = payload["data"]
    assert len(records) == int(payload["meta"]["total-count"])
    keys = [(r["auction_date"], r["cusip"]) for r in records]
    assert len(keys) == len(set(keys))
    lookup = dict(zip(keys, records, strict=True))
    old = pd.read_parquet(OUT / "original_events.parquet").set_index("event_identity")
    events, differences = {}, []
    for event in state["events"]:
        identity = event["event_identity"]
        day, cusip = identity.split("|")
        fresh = lookup[(day, cusip)]
        assert classify(fresh) == "note_2y"
        for field in ("issue_date", "maturity_date", "auction_date"):
            before = str(old.loc[identity, field].date())
            if before != fresh[field]:
                differences.append(
                    {"event": identity, "field": field, "old": before, "new": fresh[field]}
                )
        assert fresh["announcemt_date"] == event["announcement_date"]
        events[identity] = fresh
    if differences:
        raise ValueError("Event identity metadata changed")
    sessions = pd.read_parquet(FRONTIER / "treasury_event_sessions.parquet")
    buckets = protocol["buckets"]
    cache, rows, missing = {}, [], []
    for day in sorted(sessions.session.unique()):
        cache[day] = {}
        for bucket in buckets:
            try:
                c = issued_candidate(records, day, bucket)
                cache[day][bucket] = {
                    k: c[k]
                    for k in (
                        "cusip",
                        "announcemt_date",
                        "auction_date",
                        "issue_date",
                        "maturity_date",
                        "reopening",
                    )
                }
            except ValueError as e:
                cache[day][bucket] = None
                missing.append({"session": day, "bucket": bucket, "reason": str(e)})
    for row in sessions.itertuples():
        auction = events[row.event_identity]
        rows.append(
            {
                "session": row.session,
                "event_identity": row.event_identity,
                "phase": row.phase,
                "auction_cusip": auction["cusip"],
                "auction_issue_date": auction["issue_date"],
                "auction_security_issued": auction["issue_date"] <= row.session,
                "references": cache[row.session],
                "tradable_instrument_id": None,
                "settlement_date": None,
                "hedge_weights": None,
            }
        )
    changes = Counter()
    for identity in events:
        for phase in ("pre", "post"):
            group = sorted(
                [r for r in rows if r["event_identity"] == identity and r["phase"] == phase],
                key=lambda r: r["session"],
            )
            for bucket in buckets:
                series = [
                    r["references"][bucket]["cusip"] if r["references"][bucket] else None
                    for r in group
                ]
                changes[bucket] += sum(a != b for a, b in zip(series, series[1:]))
    result = {
        "source_rows": len(records),
        "events_matched": len(events),
        "event_metadata_discrepancies": differences,
        "event_session_rows": len(rows),
        "unique_reference_days": len(cache),
        "missing_reference_candidates": len(missing),
        "bucket_record_counts": dict(Counter(classify(r) or "excluded" for r in records)),
        "tips_rows_explicitly_excluded": sum(
            r["inflation_index_security"] == "Yes" for r in records
        ),
        "post_rows_before_auction_issue": sum(
            r["phase"] == "post" and not r["auction_security_issued"] for r in rows
        ),
        "pre_rows_before_auction_announcement": sum(
            r["phase"] == "pre" and r["session"] < events[r["event_identity"]]["announcemt_date"]
            for r in rows
        ),
        "within_phase_reference_cusip_changes": dict(changes),
        "market_prices_read": False,
        "return_ready": False,
        "hypothesis_union": 240,
        "remaining": [
            "historical reference vintages",
            "on-the-run/WI transition rule",
            "instrument calendars and exact settlement",
            "roll and overlap netting rule",
            "duration hedge weights and financing/borrow/execution evidence",
        ],
    }
    for name, obj in [("mapping.json", rows), ("missing.json", missing), ("result.json", result)]:
        (OUT / name).write_text(json.dumps(obj, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
