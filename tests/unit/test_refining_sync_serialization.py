"""Regression coverage for sparse audit fields and exact timestamps."""

import importlib.util
from pathlib import Path

import pyarrow.parquet as pq
import pytest

spec = importlib.util.spec_from_file_location(
    "refining_audit",
    Path(__file__).resolve().parents[2] / "scripts/audit_refining_synchronization_v3.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_sparse_first_row_preserves_later_fields_and_exact_nanoseconds(tmp_path):
    timestamp = 1_750_000_000_123_456_789
    rows = [
        {
            "date": "2025-07-15",
            "decision_ns": timestamp,
            "valid": False,
            "reason": "CL:no_prior_quote",
            "CL_recv_ns": None,
        },
        {
            "date": "2025-07-15",
            "decision_ns": timestamp + 1,
            "valid": True,
            "reason": "accepted",
            "CL_recv_ns": timestamp,
            "buy_recipe_fixed_usd": -123_456_789_012_345,
            "sell_recipe_fixed_usd": -123_499_389_012_345,
            "roundtrip_width_fixed_usd": 42_600_000_000,
            "displayed_two_way_recipes": 2,
            "max_age_ns": 1,
            "cross_leg_skew_ns": 0,
        },
    ]
    table = module.grid_table(rows)
    path = tmp_path / "grid.parquet"
    pq.write_table(table, path)
    decoded = pq.read_table(path).to_pylist()
    for before, after in zip(rows, decoded, strict=True):
        for name, value in before.items():
            assert after[name] == value
    assert decoded[0]["roundtrip_width_fixed_usd"] is None
    assert decoded[1]["CL_recv_ns"] == timestamp


def test_unknown_field_refuses_silent_loss():
    with pytest.raises(ValueError, match="Unrecognized"):
        module.grid_table([{"unregistered_metric": 1}])
