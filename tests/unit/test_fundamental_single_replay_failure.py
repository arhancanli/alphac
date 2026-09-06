from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).parents[2]
RESULT = (
    REPO
    / "artifacts"
    / "probe"
    / "fundamental_single_replays"
    / "1d2924f28fe31a9a"
    / "replay_failure.json"
)


def test_failed_replay_is_hash_bound_and_carries_no_performance_claim() -> None:
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    content_hash = payload.pop("content_hash")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    assert content_hash == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert payload["status"] == "FAILED_CLOSED"
    assert payload["packet_status"] == "INCOMPLETE"
    assert payload["failure"]["invalid_row_count_entire_sharadar_lake"] == 1
    assert payload["failure"]["offending_row"]["instrument_id"] == "XUSE:CASH:HDBUSD"
    assert payload["failure"]["offending_row"]["cash_amount"] == 0.0
    assert not any(payload["evidence"]["replay_outputs_present"].values())
    assert "Sharpe" in payload["claim_boundary"]
