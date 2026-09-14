from pathlib import Path

import pytest

from alphaforge.validation.wasde_vintages import extract_tables

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/wasde"


def august():
    return (FIXTURES / "2024-08-12.txt").read_text()


def test_current_columns_match_published_values_and_keep_units():
    rows = extract_tables(august())
    latest = {r["crop"]: r for r in rows if r["crop_year"] == "2024/25"}
    assert len(rows) == 9
    assert [latest[c]["values"]["ending_stocks"] for c in ("wheat", "corn", "soybeans")] == [
        828,
        2073,
        560,
    ]
    assert all(r["source_column_index"] == 3 for r in latest.values())
    assert all(r["units"] == "million_bushels" for r in rows)
    assert latest["wheat"]["stocks_to_use"] == pytest.approx(828 / 1961)


def test_may_missing_comparison_does_not_replace_new_forecast():
    rows = extract_tables((FIXTURES / "2024-05-10.txt").read_text())
    wheat = next(r for r in rows if r["crop"] == "wheat" and r["crop_year"] == "2024/25")
    assert wheat["values"]["ending_stocks"] == 766
    assert wheat["source_column_index"] == 3


@pytest.mark.parametrize(
    "old,new,error",
    [
        ("Million Bushels", "Million Metric Tons", "units"),
        ("856           828", "856            NA", "missing selected"),
        ("856           828", "856           999", "balance mismatch"),
        ("856           828", "856          8?28", "numeric columns"),
        ("856           828", "856        12 828", "numeric columns"),
    ],
)
def test_malformed_data_is_rejected(old, new, error):
    text = august()
    assert old in text
    with pytest.raises(ValueError, match=error):
        extract_tables(text.replace(old, new, 1))


def test_conflicting_report_identity_rejected():
    with pytest.raises(ValueError, match="report number"):
        extract_tables(august() + "\nWASDE - 999 - 11")


def test_duplicate_table_rejected():
    with pytest.raises(ValueError, match="ambiguous wheat table"):
        extract_tables(august() + "\nU.S. Wheat Supply and Use")
