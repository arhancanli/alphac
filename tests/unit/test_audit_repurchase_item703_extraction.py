from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "audit_repurchase_item703_extraction.py"
    )
)
classification_metrics = MODULE["classification_metrics"]


def frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    labels = pd.DataFrame(
        [
            {
                "cik": index,
                "accession": str(index),
                "filing_year": 2020,
                "form": "10-K",
                "has_item703_table": index < 4,
                "expected_month_rows": 3 if index < 4 else 0,
                "expected_total_row": index < 4,
            }
            for index in range(6)
        ]
    )
    predictions = labels[
        ["cik", "accession", "filing_year", "form"]
    ].copy()
    predictions["has_item703_table"] = [True, True, True, False, True, False]
    predictions["month_rows"] = [3, 3, 2, 0, 0, 0]
    predictions["has_total_row"] = [True, True, True, False, False, False]
    return labels, predictions


def test_precision_recall_and_shape_metrics_are_explicit() -> None:
    labels, predictions = frames()
    metrics = classification_metrics(labels, predictions)

    assert metrics["true_positive"] == 3
    assert metrics["false_positive"] == 1
    assert metrics["false_negative"] == 1
    assert metrics["true_negative"] == 1
    assert metrics["precision"] == 0.75
    assert metrics["recall"] == 0.75
    assert metrics["positive_month_row_exact_rate"] == 0.5
    assert metrics["positive_total_row_accuracy"] == 0.75


def test_missing_prediction_counts_as_false_negative() -> None:
    labels, predictions = frames()
    predictions = predictions[predictions["accession"].ne("0")]

    metrics = classification_metrics(labels, predictions)

    assert metrics["missing_predictions"] == 1
    assert metrics["false_negative"] == 2


def test_no_predicted_positives_is_fail_closed() -> None:
    labels, predictions = frames()
    predictions["has_item703_table"] = False

    metrics = classification_metrics(labels, predictions)

    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
