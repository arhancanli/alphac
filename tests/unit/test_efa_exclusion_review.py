"""Wrong fiscal total or split basis cannot authorize an event exclusion."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "efa_review", ROOT / "scripts/adjudicate_efa_extra_distribution.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "field,value",
    [
        ("reported_distribution", "0.68"),
        ("split_ratio", "2"),
        ("suspect_ex_date", "2003-12-22"),
        ("split_effective_date", "2005-06-10"),
    ],
)
def test_wrong_review_refuses_exclusion(tmp_path, monkeypatch, field, value):
    note = json.loads((module.OUT / "filing_review.json").read_text())
    note[field] = value
    (tmp_path / "filing_review.json").write_text(json.dumps(note))
    monkeypatch.setattr(module, "OUT", tmp_path)
    with pytest.raises(AssertionError):
        module.main()
    assert not (tmp_path / "revised_actions_v3.parquet").exists()
