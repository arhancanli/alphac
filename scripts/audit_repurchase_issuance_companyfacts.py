#!/usr/bin/env python3
"""Audit Company Facts coverage against SEC periodic-filing denominators, without returns."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_repurchase_issuance_companyfacts import (
    OUT_DIR as FACTS_DIR,
)
from collect_repurchase_issuance_companyfacts import (
    PARSER_VERSION as FACTS_PARSER_VERSION,
)
from collect_repurchase_issuance_companyfacts import (
    RESULT as FACTS_RESULT,
)
from collect_repurchase_issuance_companyfacts import content_hash_valid
from collect_repurchase_issuance_companyfacts import (
    parts_lineage as facts_parts_lineage,
)
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
    parts_lineage as submissions_parts_lineage,
)

OUT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/companyfacts_audit.json"
)
DURATION_TAGS: Final = {
    "PaymentsForRepurchaseOfCommonStock",
    "PaymentsForRepurchaseOfCommonAndPreferredStock",
    "ProceedsFromIssuanceOfCommonStock",
    "ProceedsFromIssuanceOfCommonAndPreferredStock",
    "ProceedsFromIssuanceOfSharesUnderIncentiveAndShareBasedCompensationPlansIncludingStockOptions",
    "ProceedsFromStockOptionsExercised",
    "StockRepurchasedAndRetiredDuringPeriodShares",
    "TreasuryStockSharesAcquired",
    "StockIssuedDuringPeriodSharesNewIssues",
    "StockIssuedDuringPeriodSharesStockOptionsExercised",
    "StockIssuedDuringPeriodSharesAcquisitions",
    "StockIssuedDuringPeriodValueAcquisitions",
    "ShareBasedCompensation",
}


def wilson_lower(successes: int, total: int, z: float = 1.959963984540054) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    denominator = 1 + z**2 / total
    centre = proportion + z**2 / (2 * total)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z**2 / (4 * total**2)
    )
    return (centre - margin) / denominator


def require_collection(
    result_path: Path,
    out_dir: Path,
    *,
    schema: str,
    parser_version: str,
    lineage: Any,
) -> dict[str, Any]:
    if not result_path.exists():
        raise RuntimeError(f"collection result is missing: {result_path}")
    result = json.loads(result_path.read_text())
    part_count, part_hash = lineage(out_dir)
    if (
        result.get("schema") != schema
        or result.get("parser_version") != parser_version
        or result.get("complete") is not True
        or result.get("return_data_opened") is not False
        or result.get("return_hypotheses_spent") != 0
        or result.get("part_files") != part_count
        or result.get("parts_sha256") != part_hash
        or not content_hash_valid(result)
    ):
        raise RuntimeError(f"collection is incomplete, stale, or not return-sealed: {result_path}")
    return result


def load_parts(directory: Path, pattern: str, parser_version: str) -> pd.DataFrame:
    frames = [pd.read_parquet(path) for path in sorted(directory.glob(pattern))]
    if not frames:
        raise RuntimeError(f"no parts match {directory / pattern}")
    frame = pd.concat(frames, ignore_index=True)
    return frame[frame["parser_version"].eq(parser_version)].drop_duplicates()


def coverage_metrics(facts: pd.DataFrame, filings: pd.DataFrame) -> dict[str, Any]:
    filings = filings.copy()
    filings["issuer_year"] = (
        filings["cik"].astype(str)
        + "|"
        + pd.to_datetime(filings["report_date"], errors="coerce")
        .dt.year.astype("Int64")
        .astype(str)
    )
    valid_filings = filings[
        pd.to_datetime(filings["report_date"], errors="coerce").notna()
        & filings["acceptance_datetime"].fillna("").astype(str).ne("")
    ].drop_duplicates(["cik", "accession"])
    issuer_years = set(valid_filings["issuer_year"])

    facts = facts.copy()
    facts["accession_declared"] = facts["accession"].fillna("").astype(str).ne("")
    joined = facts.merge(
        valid_filings[["cik", "accession", "issuer_year"]],
        on=["cik", "accession"],
        how="left",
        validate="many_to_one",
    )
    joined["accession_joined"] = joined["issuer_year"].notna()
    direct_repurchases = set(
        joined.loc[
            joined["tag_family"].isin({"repurchase_cash", "repurchase_shares"})
            & joined["accession_joined"],
            "issuer_year",
        ]
    )
    direct_issuance = set(
        joined.loc[
            joined["tag_family"].isin({"issuance_cash", "issuance_shares"})
            & joined["accession_joined"],
            "issuer_year",
        ]
    )
    duration = joined["tag"].isin(DURATION_TAGS)
    context_complete = (
        joined["unit"].fillna("").astype(str).ne("")
        & joined["end"].fillna("").astype(str).ne("")
        & joined["form"].isin({"10-K", "10-K/A", "10-Q", "10-Q/A"})
        & (~duration | joined["start"].fillna("").astype(str).ne(""))
    )
    total_years = len(issuer_years)
    family_rows = {
        str(family): int(count)
        for family, count in joined["tag_family"].value_counts().sort_index().items()
    }
    family_issuer_years = {
        str(family): int(group.loc[group["accession_joined"], "issuer_year"].nunique())
        for family, group in joined.groupby("tag_family", sort=True)
    }
    declared = int(joined["accession_declared"].sum())
    joined_count = int((joined["accession_declared"] & joined["accession_joined"]).sum())
    return {
        "periodic_filings": len(valid_filings),
        "issuer_years": total_years,
        "relevant_fact_rows": len(joined),
        "tag_family_rows": family_rows,
        "tag_family_issuer_years": family_issuer_years,
        "accession_declared_rows": declared,
        "accession_joined_rows": joined_count,
        "accession_join_rate": joined_count / declared if declared else 0.0,
        "context_complete_rows": int(context_complete.sum()),
        "context_complete_rate": float(context_complete.mean()) if len(joined) else 0.0,
        "direct_repurchase_issuer_years": len(direct_repurchases),
        "direct_repurchase_coverage": len(direct_repurchases) / total_years
        if total_years
        else 0.0,
        "direct_repurchase_wilson_95_lower": wilson_lower(
            len(direct_repurchases), total_years
        ),
        "direct_issuance_issuer_years": len(direct_issuance),
        "direct_issuance_coverage": len(direct_issuance) / total_years
        if total_years
        else 0.0,
        "direct_issuance_wilson_95_lower": wilson_lower(
            len(direct_issuance), total_years
        ),
        "unjoined_accessions": sorted(
            set(
                joined.loc[
                    joined["accession_declared"] & ~joined["accession_joined"],
                    "accession",
                ].astype(str)
            )
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    facts_dir = Path(args.facts_dir)
    submissions_dir = Path(args.submissions_dir)
    facts_result = require_collection(
        Path(args.facts_result),
        facts_dir,
        schema="canli.feasibility.repurchase-issuance-companyfacts-collection.v1",
        parser_version=FACTS_PARSER_VERSION,
        lineage=facts_parts_lineage,
    )
    submissions_result = require_collection(
        Path(args.submissions_result),
        submissions_dir,
        schema="canli.feasibility.repurchase-issuance-submissions-collection.v1",
        parser_version=SUBMISSIONS_PARSER_VERSION,
        lineage=submissions_parts_lineage,
    )
    if (
        facts_result["source_manifest_hash"]
        != submissions_result["source_manifest_hash"]
        or facts_result["expected_ciks"] != submissions_result["expected_ciks"]
        or submissions_result.get("companyfacts_parser_version")
        != FACTS_PARSER_VERSION
    ):
        raise RuntimeError("Company Facts and Submissions collections do not share one manifest")
    facts = load_parts(facts_dir, "facts-*.parquet", FACTS_PARSER_VERSION)
    filings = load_parts(submissions_dir, "filings-*.parquet", SUBMISSIONS_PARSER_VERSION)
    metrics = coverage_metrics(facts, filings)
    gates = {
        "collections_share_manifest": True,
        "sample_600_ciks": facts_result["expected_ciks"] == 600,
        "accession_join_rate_gte_0_95": metrics["accession_join_rate"] >= 0.95,
        "context_complete_rate_gte_0_95": metrics["context_complete_rate"] >= 0.95,
        "return_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    metadata_pass = all(gates.values())
    payload: dict[str, Any] = {
        "schema": "canli.feasibility.repurchase-issuance-companyfacts-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_xbrl_coverage_no_prices_no_returns",
        "protocol": "docs/design/FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md",
        "claim_boundary": (
            "Direct-tag coverage cannot pass the full family feasibility gate. Item 703 table "
            "precision/recall and contamination reconciliation remain mandatory."
        ),
        "source_manifest_hash": facts_result["source_manifest_hash"],
        "facts_parts_sha256": facts_result["parts_sha256"],
        "submissions_parts_sha256": submissions_result["parts_sha256"],
        "metrics": metrics,
        "custom_extension_inventory": {
            "fact_rows": facts_result.get("custom_fact_rows", 0),
            "tag_count_across_issuers": facts_result.get("custom_tags", 0),
            "mapping_policy": "preserved_in_raw_and_counted_but_never_auto_mapped",
        },
        "gates": gates,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "decision": "ITEM703_AUDIT_REQUIRED" if metadata_pass else "DATA_GATED",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts-dir", default=str(FACTS_DIR))
    parser.add_argument("--facts-result", default=str(FACTS_RESULT))
    parser.add_argument("--submissions-dir", default=str(SUBMISSIONS_DIR))
    parser.add_argument("--submissions-result", default=str(SUBMISSIONS_RESULT))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    payload = run(args)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
