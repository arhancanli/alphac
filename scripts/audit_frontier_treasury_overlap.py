"""No-price audit of overlapping sealed auction-calendar intervals."""

import hashlib
import json
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "artifacts/feasibility/treasury_auction_concession/schedule_state_machine_audit.json"
)
OUT = ROOT / "evidence/sleeve-frontier-20260912"


def main():
    source = json.loads(SOURCE.read_text())
    content_hash = source.pop("content_hash")
    observed = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    if observed != content_hash:
        raise ValueError("Source content hash mismatch")
    cal = xcals.get_calendar("XNYS", start="2012-01-01", end="2026-02-01")
    rows = []
    ids = set()
    for event in source["events"]:
        identity = event["event_identity"]
        if identity in ids:
            raise ValueError("Duplicate event")
        ids.add(identity)
        for phase in ["pre", "post"]:
            entry, exit_ = event.get(phase + "_entry_date"), event.get(phase + "_exit_date")
            if (entry is None) != (exit_ is None):
                raise ValueError("Partial interval")
            if entry is None:
                continue
            start, end = pd.Timestamp(entry), pd.Timestamp(exit_)
            if start >= end or not cal.is_session(start) or not cal.is_session(end):
                raise ValueError("Invalid session boundaries")
            # State held after each close: exit close is excluded, entry close included.
            for session in cal.sessions_in_range(start, end)[:-1]:
                rows.append(
                    {
                        "session": str(session.date()),
                        "event_identity": identity,
                        "phase": phase,
                        "auction_identity_cusip": identity.split("|")[1],
                        "tradable_instrument_id": None,
                    }
                )
    frame = pd.DataFrame(rows)
    if frame.duplicated(["session", "event_identity"]).any():
        raise ValueError("An event has two simultaneous phases")
    groups = frame.groupby("session")
    crowded = groups.size()
    mixed = groups.phase.nunique()
    result = {
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "events": len(ids),
        "event_session_records": len(frame),
        "active_sessions": len(crowded),
        "sessions_with_multiple_events": int((crowded > 1).sum()),
        "maximum_simultaneous_events": int(crowded.max()),
        "sessions_with_pre_and_post_legs": int((mixed > 1).sum()),
        "auction_cusip_is_tradable_cusip": False,
        "scalar_phase_netting_authorized": False,
        "reason": (
            "Auction identity does not bind on-the-run traded CUSIP or hedge legs. "
            "Net only identical tradable instrument and settlement identities after mapping."
        ),
        "return_ready": False,
        "market_prices_read": False,
        "new_hypotheses": 0,
        "hypothesis_union": 240,
    }
    frame.to_parquet(OUT / "treasury_event_sessions.parquet", index=False)
    (OUT / "treasury_overlap.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
