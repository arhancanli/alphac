#!/usr/bin/env python3
"""Build sealed, year-balanced Item 703 document and label samples without returns."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_repurchase_issuance_companyfacts import (
    PARSER_VERSION as COMPANYFACTS_PARSER_VERSION,
)
from collect_repurchase_issuance_companyfacts import file_sha256
from collect_repurchase_issuance_submissions import (
    OUT_DIR as SUBMISSIONS_DIR,
)
from collect_repurchase_issuance_submissions import (
    PARSER_VERSION as SUBMISSIONS_PARSER_VERSION,
)
from collect_repurchase_issuance_submissions import (
    RESULT as SUBMISSIONS_RESULT,
)
from collect_repurchase_issuance_submissions import (
    parts_lineage,
)

OUT_DIR: Final = Path("artifacts/feasibility/repurchase_issuance_flow/item703")
MANIFEST: Final = OUT_DIR / "document_sample.parquet"
LABEL_SAMPLE: Final = OUT_DIR / "label_sample.parquet"
LABEL_TEMPLATE: Final = OUT_DIR / "labels.csv"
RESULT: Final = OUT_DIR / "manifest_result.json"
DOCUMENT_SAMPLE_SIZE: Final = 240
LABEL_SAMPLE_SIZE: Final = 60
YEARS: Final = tuple(range(2013, 2026))
DOCUMENT_SEED: Final = "repurchase_issuance_item703_document_v1"
LABEL_SEED: Final = "repurchase_issuance_item703_label_v1"


def content_hash_valid(payload: dict[str, Any]) -> bool:
    claimed = payload.get("content_hash")
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return claimed == f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def balanced_quotas(years: tuple[int, ...], total: int) -> dict[int, int]:
    if not years or total < len(years):
        raise ValueError("balanced sample requires at least one row per year")
    base, remainder = divmod(total, len(years))
    return {
        year: base + (1 if index < remainder else 0)
        for index, year in enumerate(years)
    }


def accession_url(cik: int, accession: str, primary_document: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{primary_document}"
    )


def locked_sample(
    filings: pd.DataFrame,
    *,
    years: tuple[int, ...],
    total: int,
    seed: str,
) -> pd.DataFrame:
    frame = filings[
        filings["form"].isin({"10-K", "10-Q"})
        & filings["primary_document"].fillna("").astype(str).ne("")
    ].copy()
    frame["filing_year"] = pd.to_datetime(
        frame["filing_date"], errors="coerce"
    ).dt.year
    frame = frame[frame["filing_year"].isin(years)].drop_duplicates("accession")
    frame["sample_rank"] = frame["accession"].map(
        lambda accession: hashlib.sha256(f"{seed}|{accession}".encode()).hexdigest()
    )
    quotas = balanced_quotas(years, total)
    selections: list[pd.DataFrame] = []
    for year in years:
        annual = frame[frame["filing_year"].eq(year)].sort_values(
            ["sample_rank", "accession"]
        )
        if len(annual) < quotas[year]:
            raise ValueError(
                f"year {year} has {len(annual)} eligible filings, needs {quotas[year]}"
            )
        selections.append(annual.head(quotas[year]))
    sample = pd.concat(selections, ignore_index=True).sort_values(
        ["filing_year", "sample_rank", "accession"]
    )
    sample["document_url"] = sample.apply(
        lambda row: accession_url(
            int(row["cik"]), str(row["accession"]), str(row["primary_document"])
        ),
        axis=1,
    )
    return sample.reset_index(drop=True)


def require_submissions(result_path: Path, directory: Path) -> dict[str, Any]:
    if not result_path.exists():
        raise RuntimeError("completed Submissions collection result is required")
    result = json.loads(result_path.read_text())
    count, digest = parts_lineage(directory)
    if (
        result.get("schema")
        != "canli.feasibility.repurchase-issuance-submissions-collection.v1"
        or result.get("parser_version") != SUBMISSIONS_PARSER_VERSION
        or result.get("companyfacts_parser_version") != COMPANYFACTS_PARSER_VERSION
        or result.get("complete") is not True
        or result.get("return_data_opened") is not False
        or result.get("return_hypotheses_spent") != 0
        or result.get("part_files") != count
        or result.get("parts_sha256") != digest
        or not content_hash_valid(result)
    ):
        raise RuntimeError("Submissions collection is incomplete, stale, or unsealed")
    return result


def load_filings(directory: Path) -> pd.DataFrame:
    frames = [pd.read_parquet(path) for path in sorted(directory.glob("filings-*.parquet"))]
    if not frames:
        raise RuntimeError("no periodic-filing parts are available")
    return (
        pd.concat(frames, ignore_index=True)
        .loc[lambda frame: frame["parser_version"].eq(SUBMISSIONS_PARSER_VERSION)]
        .drop_duplicates(["cik", "accession", "form"])
    )


def write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    submissions_dir = Path(args.submissions_dir)
    submissions = require_submissions(Path(args.submissions_result), submissions_dir)
    filings = load_filings(submissions_dir)
    documents = locked_sample(
        filings,
        years=YEARS,
        total=args.document_sample_size,
        seed=DOCUMENT_SEED,
    )
    labels = locked_sample(
        documents,
        years=YEARS,
        total=args.label_sample_size,
        seed=LABEL_SEED,
    )
    manifest = Path(args.manifest)
    label_sample = Path(args.label_sample)
    write_parquet_atomic(documents, manifest)
    write_parquet_atomic(labels, label_sample)
    template = labels[["cik", "accession", "filing_year", "form", "document_url"]].copy()
    template["has_item703_table"] = ""
    template["expected_month_rows"] = ""
    template["expected_total_row"] = ""
    template["label_notes"] = ""
    label_template = Path(args.label_template)
    label_template.parent.mkdir(parents=True, exist_ok=True)
    template.to_csv(label_template, index=False)
    result = {
        "schema": "canli.feasibility.repurchase-issuance-item703-manifest.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "item703_samples_no_documents_no_returns",
        "protocol": "docs/design/FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md",
        "source_submissions_hash": submissions["parts_sha256"],
        "document_seed": DOCUMENT_SEED,
        "document_sample_size": len(documents),
        "document_year_counts": {
            str(year): int(documents["filing_year"].eq(year).sum()) for year in YEARS
        },
        "document_manifest_sha256": file_sha256(manifest),
        "label_seed": LABEL_SEED,
        "label_sample_size": len(labels),
        "label_year_counts": {
            str(year): int(labels["filing_year"].eq(year).sum()) for year in YEARS
        },
        "label_sample_sha256": file_sha256(label_sample),
        "label_state": "UNLABELED",
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "complete": (
            len(documents) == args.document_sample_size
            and len(labels) == args.label_sample_size
        ),
    }
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    result_path = Path(args.result)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submissions-dir", default=str(SUBMISSIONS_DIR))
    parser.add_argument("--submissions-result", default=str(SUBMISSIONS_RESULT))
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--label-sample", default=str(LABEL_SAMPLE))
    parser.add_argument("--label-template", default=str(LABEL_TEMPLATE))
    parser.add_argument("--result", default=str(RESULT))
    parser.add_argument("--document-sample-size", type=int, default=DOCUMENT_SAMPLE_SIZE)
    parser.add_argument("--label-sample-size", type=int, default=LABEL_SAMPLE_SIZE)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, indent=2))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
