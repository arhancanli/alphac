from pathlib import Path

import pytest

from alphaforge.validation.wasde_xml import extract_xml

RAW = (Path(__file__).resolve().parents[1] / "fixtures/wasde/2015-01-selected.xml").read_bytes()


def test_xml_thousands_separators_and_current_column():
    rows = extract_xml(RAW, "January 2015")
    wheat = next(r for r in rows if r["crop"] == "wheat" and r["crop_year"] == "2014/15")
    assert len(rows) == 9
    assert wheat["values"]["production"] == 2026
    assert wheat["source_column_index"] == 3


def test_wrong_vintage_rejected():
    with pytest.raises(ValueError, match="month or identity"):
        extract_xml(RAW, "February 2015")


def test_unknown_units_rejected():
    with pytest.raises(ValueError, match="units"):
        extract_xml(RAW.replace(b"Million Bushels", b"Million Pounds"), "January 2015")


def test_malformed_thousands_separator_rejected():
    assert b"2,026" in RAW
    with pytest.raises(ValueError, match="numeric syntax"):
        extract_xml(RAW.replace(b"2,026", b"20,26"), "January 2015")


@pytest.mark.parametrize(
    "raw", [b"<!DOCTYPE Report><Report/>", b"<Report>\x00</Report>", b'<!ENTITY test "x"><Report/>']
)
def test_unsafe_xml_rejected(raw):
    with pytest.raises(ValueError, match="unsafe"):
        extract_xml(raw, "January 2015")
