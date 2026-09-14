"""A mismatched reviewed annual total must not authorize an exclusion."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "qqq_review", ROOT / "scripts/adjudicate_qqq_extra_distributions.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "field,value",
    [
        ("reported_distribution_per_share", "0.42"),
        ("suspect_ex_date", "2010-06-18"),
        ("suspect_cash", "0.08"),
    ],
)
def test_bad_review_refuses_exclusion(tmp_path, monkeypatch, field, value):
    notes = json.loads((module.OUT / "annual_report_review.json").read_text())
    notes[0][field] = value
    (tmp_path / "annual_report_review.json").write_text(json.dumps(notes))
    monkeypatch.setattr(module, "OUT", tmp_path)
    with pytest.raises(AssertionError):
        module.main()
    assert not (tmp_path / "revised_actions_v2.parquet").exists()
