from __future__ import annotations

from pathlib import Path
from runpy import run_path
from types import SimpleNamespace

import pandas as pd
import pytest

MODULE = run_path(
    str(Path(__file__).parents[2] / "scripts" / "seal_repurchase_item703_labels.py")
)
parse_bool = MODULE["parse_bool"]
run = MODULE["run"]
validate_labels = MODULE["validate_labels"]


def sample() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cik": 1,
                "accession": "a",
                "filing_year": 2020,
                "form": "10-K",
                "document_url": "https://example.test/a",
            },
            {
                "cik": 2,
                "accession": "b",
                "filing_year": 2021,
                "form": "10-Q",
                "document_url": "https://example.test/b",
            },
        ]
    )


def labels() -> pd.DataFrame:
    frame = sample()
    frame["has_item703_table"] = ["true", "false"]
    frame["expected_month_rows"] = [3, 0]
    frame["expected_total_row"] = ["1", "0"]
    frame["label_notes"] = ["quarter", "absent"]
    return frame


def test_labels_are_exact_complete_and_typed() -> None:
    result = validate_labels(labels(), sample())

    assert result["has_item703_table"].tolist() == [True, False]
    assert result["expected_month_rows"].tolist() == [3, 0]
    assert result["expected_total_row"].tolist() == [True, False]


def test_absent_table_cannot_claim_rows() -> None:
    frame = labels()
    frame.loc[1, "expected_month_rows"] = 1

    with pytest.raises(ValueError, match="without Item 703"):
        validate_labels(frame, sample())


def test_boolean_labels_fail_closed() -> None:
    with pytest.raises(ValueError, match="must be true/false"):
        parse_bool("yes", "field")


def test_labels_cannot_be_sealed_after_parser_output(tmp_path: Path) -> None:
    parser_result = tmp_path / "parser.json"
    parser_result.write_text("{}")
    args = SimpleNamespace(
        out=tmp_path / "seal.json",
        parse_parts=tmp_path / "parts",
        parser_result=parser_result,
    )

    with pytest.raises(RuntimeError, match="after parser output"):
        run(args)
