from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).parents[2]
RESULT = REPO / "artifacts" / "analysis" / "bond_etf_nav_reachability" / "result.json"


def test_bond_etf_nav_is_not_misclassified_as_parser_work() -> None:
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    content_hash = payload.pop("content_hash")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    assert content_hash == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert payload["decision"] == "PUBLIC_ENGINEERING_CANNOT_CLOSE_LOCKED_GATES"
    assert payload["verdict"] == "PAID_ARCHIVAL_AND_EXECUTABLE_DATA_REQUIRED"
    assert payload["hypotheses_spent"] == 0
    assert payload["market_records_opened"] == 0
    assert payload["engineering_reachability"][
        "parser_or_crawler_can_create_missing_history"
    ] is False
    assert all(
        row["historical_holdings_snapshots"] == 1
        and row["required_historical_holdings_snapshots"] == 120
        for row in payload["measured_public_record"]["funds"].values()
    )
