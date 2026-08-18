from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts" / "audit_active_ownership_13d_schema_v2.py"
SPEC = importlib.util.spec_from_file_location("audit_active_ownership_13d_schema_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parse_index_accepts_both_exact_initial_forms() -> None:
    raw = b"""CIK|Company Name|Form Type|Date Filed|Filename
10|A|SC 13D|2024-01-01|edgar/data/10/0000000010-24-000001.txt
11|B|SCHEDULE 13D|2025-01-01|edgar/data/11/0000000011-25-000001.txt
12|C|SCHEDULE 13D/A|2025-01-02|edgar/data/12/0000000012-25-000001.txt
"""
    rows = MODULE.parse_index(raw, 2025, 1)
    assert [row["form"] for row in rows] == ["SC 13D", "SCHEDULE 13D"]


def test_accession_table_preserves_association_set() -> None:
    rows = pd.DataFrame(
        [
            {
                "year": 2025,
                "quarter": 1,
                "associated_cik": cik,
                "index_company_name": str(cik),
                "form": "SCHEDULE 13D",
                "filing_date": "2025-01-01",
                "accession": "a",
                "index_filename": "edgar/data/1/a.txt",
                "archive_cik": 1,
            }
            for cik in (1, 2)
        ]
    )
    result = MODULE.accession_table(rows)
    assert result.iloc[0]["associated_ciks"] == [1, 2]
    assert result.iloc[0]["association_count"] == 2


def test_wilson_lower_is_conservative() -> None:
    lower = MODULE.wilson_lower(320, 800)
    assert 0.36 < lower < 0.40
    assert MODULE.wilson_lower(0, 0) == 0.0


def test_native_gate_scalar_is_json_serializable() -> None:
    gate = bool(pd.Series([True, True]).all())
    assert json.loads(json.dumps({"gate": gate})) == {"gate": True}


def test_locked_sample_is_50_per_year() -> None:
    frame = pd.DataFrame(
        [
            {"year": year, "accession": f"{year}-{index:04d}"}
            for year in (2024, 2025)
            for index in range(80)
        ]
    )
    sample = MODULE.locked_sample(frame)
    assert len(sample) == 100
    assert sample.groupby("year").size().eq(50).all()
