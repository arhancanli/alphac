from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts/audit_repurchase_issuance_overlap.py"
SPEC = importlib.util.spec_from_file_location("audit_repurchase_issuance_overlap", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_prior_issuance_trials_are_counted_without_opening_new_returns(tmp_path: Path) -> None:
    ledger = tmp_path / "experiments.jsonl"
    rows = [
        {
            "config_hash": f"hash-{number}",
            "sharpe_ann": sharpe,
            "n_obs": 500,
            "config": {
                "alpha_names": ["eq_net_issuance"],
                "start": number,
                "end": 9,
                "instrument_ids": [f"asset-{number}"],
                "allocator": "rank",
                "rebalance_bars": 63,
            },
        }
        for number, sharpe in ((1, None), (2, -0.3))
    ]
    ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    records = MODULE.issuance_records([ledger])

    assert len(records) == 2
    assert {record["config_hash"] for record in records} == {"hash-1", "hash-2"}
    assert all("sharpe_ann" in record for record in records)


def test_production_overlap_is_same_family_and_cannot_count_as_new_sleeve() -> None:
    result = MODULE.audit_overlap(list(MODULE.ROOT.glob("var*/experiments.jsonl")))

    assert result["classification"] == "SAME_ECONOMIC_FAMILY_DISTINCT_MEASUREMENT"
    assert result["return_data_opened_by_this_audit"] is False
    assert result["return_hypotheses_spent_by_this_audit"] == 0
    assert result["prior_trial_account"]["distinct_config_hashes"] >= 3
    assert result["governance"]["required_family_trial_floor"] >= 4
    assert result["governance"]["may_count_toward_ten_new_independent_sleeves"] is False
    assert result["governance"]["fresh_standalone_trial_budget"] is False
