from __future__ import annotations

import hashlib
import json
from pathlib import Path
from runpy import run_path

import pandas as pd

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "build_repurchase_item703_manifest.py"
    )
)
accession_url = MODULE["accession_url"]
balanced_quotas = MODULE["balanced_quotas"]
content_hash_valid = MODULE["content_hash_valid"]
locked_sample = MODULE["locked_sample"]


def filings() -> pd.DataFrame:
    rows = []
    for year in (2020, 2021):
        for index in range(5):
            rows.append(
                {
                    "cik": year * 10 + index,
                    "accession": f"{year:010d}-20-{index:06d}",
                    "form": "10-K" if index != 4 else "10-K/A",
                    "filing_date": f"{year}-03-01",
                    "report_date": f"{year - 1}-12-31",
                    "acceptance_datetime": f"{year}-03-01T12:00:00Z",
                    "primary_document": f"doc{index}.htm",
                    "parser_version": "x",
                }
            )
    return pd.DataFrame(rows)


def test_balanced_quotas_are_exact_and_deterministic() -> None:
    assert balanced_quotas((2020, 2021, 2022), 8) == {2020: 3, 2021: 3, 2022: 2}
    assert sum(balanced_quotas(tuple(range(2013, 2026)), 240).values()) == 240
    assert sum(balanced_quotas(tuple(range(2013, 2026)), 60).values()) == 60


def test_locked_sample_excludes_amendments_and_balances_years() -> None:
    frame = filings()
    first = locked_sample(
        frame, years=(2020, 2021), total=6, seed="sealed"
    )
    second = locked_sample(
        frame.sample(frac=1, random_state=9),
        years=(2020, 2021),
        total=6,
        seed="sealed",
    )

    assert first["accession"].tolist() == second["accession"].tolist()
    assert first.groupby("filing_year").size().to_dict() == {2020: 3, 2021: 3}
    assert set(first["form"]) == {"10-K"}
    assert first["accession"].nunique() == 6


def test_accession_url_uses_unhyphenated_directory() -> None:
    assert accession_url(123, "0000000123-20-000001", "doc.htm") == (
        "https://www.sec.gov/Archives/edgar/data/123/000000012320000001/doc.htm"
    )


def test_content_hash_validation_rejects_mutation() -> None:
    payload = {"complete": True}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    assert content_hash_valid(payload) is True
    payload["complete"] = False
    assert content_hash_valid(payload) is False
