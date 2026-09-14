import pytest
from audit_merger_headers import parse_header


def header(extra=""):
    return (
        "<ACCESSION-NUMBER>0000000001-10-000001\n"
        "<ACCEPTANCE-DATETIME>20100104123000\n<TYPE>SC 14D9\n" + extra
    )


def test_roles_are_separate_and_do_not_infer_target():
    r = parse_header(
        header(
            "<SUBJECT-COMPANY>\n<CIK>000001\n</SUBJECT-COMPANY>\n"
            "<FILED-BY>\n<CIK>000002\n</FILED-BY>"
        )
    )
    assert r["roles"]["SUBJECT-COMPANY"] == [1]
    assert r["roles"]["FILED-BY"] == [2]
    assert r["acceptance_utc_verified"] is False
    assert "target_cik" not in r


def test_duplicate_or_bad_clock_rejected():
    with pytest.raises(ValueError):
        parse_header(header("<ACCEPTANCE-DATETIME>20100104123000\n"))
    with pytest.raises(ValueError):
        parse_header(header().replace("20100104123000", "20100230123000"))
