from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).parents[2]
RESULT = REPO / "artifacts" / "audit" / "sharadar_zero_dividend.json"


def test_zero_dividend_audit_is_hash_bound_and_forbids_imputation() -> None:
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    content_hash = payload.pop("content_hash")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    assert content_hash == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert payload["decision"] == "QUARANTINE_REQUIRED_NO_AUTOMATIC_REPAIR"
    assert payload["hypotheses_spent"] == 0
    assert payload["return_data_opened"] is False
    assert payload["source_defect"]["raw_archive_nonpositive_dividend_rows"] == 11
    assert payload["source_defect"]["raw_hdb_nonpositive_dividend_rows"] == 1
    assert payload["source_defect"]["lake_nonpositive_dividend_rows"] == 1
    assert payload["gates"]["issuer_declared_positive_underlying_dividend"] is True
    assert payload["gates"]["net_usd_cash_per_ads_established_from_primary_evidence"] is False
    assert payload["gates"]["automatic_amount_or_date_imputation_permitted"] is False
