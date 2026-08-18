from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from ingest_insider_transactions import normalize_quarter, quarters


def _archive() -> bytes:
    submission = pd.DataFrame(
        [
            ["A", "01-APR-2026", "4", "1", "Issuer", "AAA", "0"],
            ["B", "01-APR-2026", "4/A", "1", "Issuer", "AAA", "0"],
            ["C", "01-APR-2026", "4", "2", "Other", "BBB", "0"],
        ],
        columns=[
            "ACCESSION_NUMBER",
            "FILING_DATE",
            "DOCUMENT_TYPE",
            "ISSUERCIK",
            "ISSUERNAME",
            "ISSUERTRADINGSYMBOL",
            "AFF10B5ONE",
        ],
    )
    transactions = pd.DataFrame(
        [
            ["A", "1", "Common", "31-MAR-2026", "4", "P", "10", "20", "A", "D"],
            ["A", "2", "Common", "31-MAR-2026", "4", "S", "10", "20", "D", "D"],
            ["B", "3", "Common", "31-MAR-2026", "4", "P", "50", "20", "A", "D"],
            ["C", "4", "Common", "31-MAR-2026", "4", "P", "10", "", "A", "D"],
        ],
        columns=[
            "ACCESSION_NUMBER",
            "NONDERIV_TRANS_SK",
            "SECURITY_TITLE",
            "TRANS_DATE",
            "TRANS_FORM_TYPE",
            "TRANS_CODE",
            "TRANS_SHARES",
            "TRANS_PRICEPERSHARE",
            "TRANS_ACQUIRED_DISP_CD",
            "DIRECT_INDIRECT_OWNERSHIP",
        ],
    )
    owners = pd.DataFrame(
        [
            ["A", "9", "Officer", "Officer", "CEO"],
            ["B", "9", "Officer", "Officer", "CEO"],
            ["C", "8", "Holder", "Ten Percent Owner", ""],
        ],
        columns=[
            "ACCESSION_NUMBER",
            "RPTOWNERCIK",
            "RPTOWNERNAME",
            "RPTOWNER_RELATIONSHIP",
            "RPTOWNER_TITLE",
        ],
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("SUBMISSION.tsv", submission.to_csv(sep="\t", index=False))
        archive.writestr("NONDERIV_TRANS.tsv", transactions.to_csv(sep="\t", index=False))
        archive.writestr("REPORTINGOWNER.tsv", owners.to_csv(sep="\t", index=False))
    return out.getvalue()


def test_normalize_keeps_only_original_officer_director_open_market_purchases() -> None:
    rows, counts = normalize_quarter(_archive())

    assert counts == {"submission_rows": 3, "transaction_rows": 4, "owner_rows": 3}
    assert len(rows) == 1
    assert rows.iloc[0]["accession_number"] == "A"
    assert rows.iloc[0]["purchase_value_usd"] == 200


def test_quarter_range_is_bounded_by_latest_complete_quarter() -> None:
    result = quarters(2025, 2026, 2)
    assert result[0] == (2025, 1)
    assert result[-1] == (2026, 2)
    assert len(result) == 6


def test_pre_2023_archive_without_10b5_flag_is_supported() -> None:
    payload = _archive()
    source = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as incoming, zipfile.ZipFile(source, "w") as outgoing:
        for name in incoming.namelist():
            content = incoming.read(name)
            if name == "SUBMISSION.tsv":
                frame = pd.read_csv(io.BytesIO(content), sep="\t").drop(columns="AFF10B5ONE")
                content = frame.to_csv(sep="\t", index=False).encode()
            outgoing.writestr(name, content)

    rows, _ = normalize_quarter(source.getvalue())
    assert len(rows) == 1
    assert pd.isna(rows.iloc[0]["aff10b5one"])
