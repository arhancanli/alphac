#!/usr/bin/env python3
"""Audit merger-arbitrage timeline metadata using only cached official SEC submissions JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd

CACHE: Final = Path("data/raw/sec_10k_narrative/submissions")
OUT: Final = Path("artifacts/feasibility/merger_arbitrage")
START: Final = pd.Timestamp("2016-01-01")
END: Final = pd.Timestamp("2025-12-31")
TARGET_FORMS: Final = {"DEFM14A", "SC 14D9"}
COUNT_FORMS: Final = TARGET_FORMS | {"SC TO-T"}


def archive_url(cik: int, accession: str, primary_document: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/"
        f"{accession.replace('-', '')}/{primary_document}"
    )


def records(payload: dict, cik: int) -> list[dict]:
    source = payload.get("filings", {}).get("recent", payload)
    required = [
        "accessionNumber",
        "filingDate",
        "acceptanceDateTime",
        "form",
        "items",
        "primaryDocument",
    ]
    if any(field not in source for field in required):
        return []
    sizes = {len(source[field]) for field in required}
    if len(sizes) != 1:
        raise ValueError(f"inconsistent cached submissions columns for CIK {cik}: {sizes}")
    out = []
    for values in zip(*(source[field] for field in required), strict=True):
        accession, filing_date, accepted, form, items, document = values
        out.append(
            {
                "cik": cik,
                "accession": str(accession),
                "filing_date": str(filing_date),
                "acceptance_datetime": str(accepted),
                "form": str(form),
                "items": str(items),
                "primary_document": str(document),
                "source_url": archive_url(cik, str(accession), str(document)),
            }
        )
    return out


def read_cache(cache: Path) -> pd.DataFrame:
    rows: list[dict] = []
    for path in sorted(cache.glob("*.json")):
        payload = json.loads(path.read_text())
        name = path.name
        cik_text = name[3:13] if name.startswith("CIK") else ""
        if not cik_text.isdigit():
            continue
        rows.extend(records(payload, int(cik_text)))
    frame = pd.DataFrame(rows).drop_duplicates(["cik", "accession"], keep="last")
    frame["filing_ts"] = pd.to_datetime(frame["filing_date"], errors="coerce")
    return frame[frame["filing_ts"].between(START, END)].copy()


def prior_announcement(anchor: pd.Series, issuer: pd.DataFrame) -> pd.Series | None:
    accepted = pd.Timestamp(anchor["acceptance_datetime"])
    candidates = issuer[
        issuer["form"].eq("8-K")
        & issuer["items"].str.split(",").apply(lambda values: "1.01" in values)
    ].copy()
    candidates["accepted"] = pd.to_datetime(candidates["acceptance_datetime"], utc=True)
    candidates = candidates[
        candidates["accepted"].le(accepted)
        & candidates["accepted"].ge(accepted - pd.Timedelta(days=60))
    ]
    return candidates.sort_values("accepted").iloc[-1] if len(candidates) else None


def later_outcome(anchor: pd.Series, issuer: pd.DataFrame) -> pd.Series | None:
    accepted = pd.Timestamp(anchor["acceptance_datetime"])
    candidates = issuer[issuer["form"].eq("8-K")].copy()
    candidates["accepted"] = pd.to_datetime(candidates["acceptance_datetime"], utc=True)
    candidates["outcome_item"] = candidates["items"].str.split(",").apply(
        lambda values: "2.01" in values or "1.02" in values
    )
    candidates = candidates[
        candidates["outcome_item"]
        & candidates["accepted"].ge(accepted)
        & candidates["accepted"].le(accepted + pd.Timedelta(days=540))
    ]
    return candidates.sort_values("accepted").iloc[0] if len(candidates) else None


def deterministic_sample(anchors: pd.DataFrame, per_cell: int = 10) -> pd.DataFrame:
    frame = anchors.copy()
    frame["year"] = pd.to_datetime(frame["filing_date"]).dt.year
    frame["sample_rank"] = frame.apply(
        lambda row: hashlib.sha256(
            f"{row['form']}|{int(row['cik'])}|{row['accession']}".encode()
        ).hexdigest(),
        axis=1,
    )
    return (
        frame.sort_values(["year", "form", "sample_rank"])
        .groupby(["year", "form"], group_keys=False)
        .head(per_cell)
        .reset_index(drop=True)
    )


def run(args: argparse.Namespace) -> dict:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    filings = read_cache(Path(args.cache))
    counted = filings[filings["form"].isin(COUNT_FORMS)].copy()
    anchors = counted[counted["form"].isin(TARGET_FORMS)].copy()
    linked: list[dict] = []
    grouped = dict(iter(filings.groupby("cik", sort=False)))
    for anchor in anchors.to_dict("records"):
        series = pd.Series(anchor)
        issuer = grouped[int(anchor["cik"])]
        announcement = prior_announcement(series, issuer)
        outcome = later_outcome(series, issuer)
        linked.append(
            {
                **anchor,
                "prior_8k_accession": (
                    announcement["accession"] if announcement is not None else None
                ),
                "prior_8k_acceptance": (
                    announcement["acceptance_datetime"] if announcement is not None else None
                ),
                "later_outcome_accession": outcome["accession"] if outcome is not None else None,
                "later_outcome_acceptance": (
                    outcome["acceptance_datetime"] if outcome is not None else None
                ),
            }
        )
    timeline = pd.DataFrame(linked)
    timeline.to_parquet(out / "target_anchor_timeline.parquet", index=False)
    deterministic_sample(timeline, args.sample_per_cell).to_csv(
        out / "locked_document_sample.csv", index=False
    )
    counts = counted.assign(year=pd.to_datetime(counted["filing_date"]).dt.year).groupby(
        ["year", "form"]
    ).size()
    target_years = timeline.assign(year=pd.to_datetime(timeline["filing_date"]).dt.year).groupby(
        "year"
    ).size()
    lineage = [
        "cik",
        "accession",
        "form",
        "filing_date",
        "acceptance_datetime",
        "primary_document",
        "source_url",
    ]
    prior_rate = float(timeline["prior_8k_accession"].notna().mean()) if len(timeline) else 0.0
    outcome_rate = (
        float(timeline["later_outcome_accession"].notna().mean()) if len(timeline) else 0.0
    )
    gates = {
        "lineage_complete": bool(len(timeline) and not timeline[lineage].isna().any().any()),
        "prior_item101_8k_rate_gte_0_80": prior_rate >= 0.80,
        "later_item201_or_102_8k_rate_gte_0_70": outcome_rate >= 0.70,
        "every_year_has_at_least_20_target_anchors": all(
            int(target_years.get(year, 0)) >= 20 for year in range(2016, 2026)
        ),
    }
    result = {
        "schema": "canli.feasibility.merger-arbitrage-metadata.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_metadata_feasibility_no_documents_no_returns",
        "hypothesis_identities_spent": 0,
        "period": {"start": str(START.date()), "end": str(END.date())},
        "filings_scanned": len(filings),
        "target_anchors": len(timeline),
        "unique_target_ciks": int(timeline["cik"].nunique()) if len(timeline) else 0,
        "counts_by_year_form": {
            f"{year}|{form}": int(value) for (year, form), value in counts.items()
        },
        "prior_item101_8k_rate": prior_rate,
        "later_item201_or_102_8k_rate": outcome_rate,
        "target_anchors_by_year": {
            str(year): int(target_years.get(year, 0)) for year in range(2016, 2026)
        },
        "locked_document_sample_rows": len(
            deterministic_sample(timeline, args.sample_per_cell)
        ),
        "gates": gates,
        "decision": "PASS_TO_DOCUMENT_FEASIBILITY" if all(gates.values()) else "DATA_GATED",
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default=str(CACHE))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--sample-per-cell", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
