from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts" / "build_sec_10k_manifest.py"
SPEC = importlib.util.spec_from_file_location("build_sec_10k_manifest", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def payload(forms: list[str]) -> dict:
    n = len(forms)
    return {
        "accessionNumber": [f"0000000001-2{i}-00000{i}" for i in range(n)],
        "filingDate": ["2020-03-01"] * n,
        "reportDate": ["2019-12-31"] * n,
        "acceptanceDateTime": [f"2020-03-01T12:00:0{i}.000Z" for i in range(n)],
        "form": forms,
        "primaryDocument": [f"doc{i}.htm" for i in range(n)],
    }


def test_filing_frame_accepts_recent_and_historical_shapes() -> None:
    historical = payload(["10-K", "8-K"])
    recent = {"filings": {"recent": historical}}
    pd.testing.assert_frame_equal(MODULE.filing_frame(historical), MODULE.filing_frame(recent))


def test_filing_frame_rejects_inconsistent_sec_columns() -> None:
    malformed = payload(["10-K"])
    malformed["primaryDocument"] = []
    try:
        MODULE.filing_frame(malformed)
    except ValueError as error:
        assert "inconsistent lengths" in str(error)
    else:  # pragma: no cover
        raise AssertionError("malformed SEC payload must fail")


def test_accession_urls_are_immutable_archive_paths() -> None:
    index_url, document_url = MODULE.accession_urls(
        1031296, "0001031296-25-000006", "fe-20241231.htm"
    )
    root = "https://www.sec.gov/Archives/edgar/data/1031296/000103129625000006"
    assert index_url == f"{root}/0001031296-25-000006-index.html"
    assert document_url == f"{root}/fe-20241231.htm"


def test_manifest_contract_excludes_amendments_and_out_of_range() -> None:
    class FakeClient:
        def json(self, name: str) -> dict:
            assert name == "CIK0000000001.json"
            data = payload(["10-K", "10-K/A", "10-K"])
            data["filingDate"][-1] = "2004-12-31"
            return {"filings": {"recent": data, "files": []}}

    frame, pages = MODULE.company_filings(FakeClient(), 1)
    assert pages == 0
    assert frame["form"].tolist() == ["10-K"]
    assert frame["filingDate"].tolist() == ["2020-03-01"]
