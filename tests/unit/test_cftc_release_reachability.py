from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).parents[2]
RESULT = REPO / "artifacts" / "analysis" / "cftc_release_reachability" / "result.json"


def test_cftc_release_gate_is_measured_unreachable_without_returns() -> None:
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    content_hash = payload.pop("content_hash")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    assert content_hash == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert payload["decision"] == "UNREACHABLE_AS_PREREGISTERED"
    assert payload["hypotheses_spent"] == 0
    assert payload["return_data_opened"] is False
    assert payload["measured_ceiling"]["row_weighted_exact_lineage_ceiling"] < 0.10
    assert payload["protocol_gate"]["required_rate"] == 0.95
    assert payload["work_authorization"]["build_fixed_contract_mapping_now"] is False
    assert payload["lineage"]["classification"] == "RETIRED_KILLED"
