from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).parents[2] / "scripts" / "audit_merger_metadata_feasibility.py"
SPEC = importlib.util.spec_from_file_location("audit_merger_metadata_feasibility", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def filing(accession: str, accepted: str, form: str, items: str) -> dict:
    return {
        "cik": 1,
        "accession": accession,
        "filing_date": accepted[:10],
        "acceptance_datetime": accepted,
        "form": form,
        "items": items,
        "primary_document": "doc.htm",
        "source_url": "https://www.sec.gov/doc.htm",
    }


def test_timeline_uses_latest_prior_announcement_and_first_later_outcome() -> None:
    issuer = pd.DataFrame(
        [
            filing("old", "2020-01-01T12:00:00Z", "8-K", "1.01,9.01"),
            filing("announcement", "2020-02-01T12:00:00Z", "8-K", "1.01,9.01"),
            filing("anchor", "2020-02-20T12:00:00Z", "DEFM14A", ""),
            filing("outcome", "2020-04-01T12:00:00Z", "8-K", "2.01,9.01"),
            filing("later", "2020-05-01T12:00:00Z", "8-K", "1.02"),
        ]
    )
    anchor = issuer[issuer["accession"].eq("anchor")].iloc[0]
    assert MODULE.prior_announcement(anchor, issuer)["accession"] == "announcement"
    assert MODULE.later_outcome(anchor, issuer)["accession"] == "outcome"


def test_prior_window_never_expands_past_60_days() -> None:
    issuer = pd.DataFrame(
        [
            filing("old", "2020-01-01T12:00:00Z", "8-K", "1.01"),
            filing("anchor", "2020-04-01T12:00:00Z", "SC 14D9", ""),
        ]
    )
    assert MODULE.prior_announcement(issuer.iloc[1], issuer) is None


def test_sample_is_deterministic_and_bounded_per_cell() -> None:
    rows = []
    for index in range(30):
        row = filing(str(index), "2020-03-01T12:00:00Z", "DEFM14A", "")
        row["cik"] = index + 1
        rows.append(row)
    frame = pd.DataFrame(rows)
    left = MODULE.deterministic_sample(frame, 10)
    right = MODULE.deterministic_sample(frame.sample(frac=1, random_state=7), 10)
    assert left["accession"].tolist() == right["accession"].tolist()
    assert len(left) == 10
