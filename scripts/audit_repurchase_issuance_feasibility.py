#!/usr/bin/env python3
"""Combine every frozen no-return gate for repurchase/issuance feasibility."""

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
from audit_repurchase_issuance_companyfacts import OUT as COMPANYFACTS_AUDIT
from audit_repurchase_issuance_companyfacts import wilson_lower
from audit_repurchase_issuance_semantics import OUT as SEMANTICS_AUDIT
from audit_repurchase_item703_extraction import OUT as ITEM703_AUDIT
from build_repurchase_item703_manifest import MANIFEST as ITEM703_MANIFEST
from build_repurchase_item703_manifest import RESULT as ITEM703_MANIFEST_RESULT
from build_repurchase_item703_manifest import content_hash_valid
from collect_repurchase_issuance_companyfacts import (
    OUT_DIR as FACTS_DIR,
)
from collect_repurchase_issuance_companyfacts import (
    PARSER_VERSION as FACTS_PARSER_VERSION,
)
from collect_repurchase_issuance_companyfacts import file_sha256
from collect_repurchase_issuance_companyfacts import parts_lineage as facts_parts_lineage
from collect_repurchase_issuance_submissions import (
    OUT_DIR as SUBMISSIONS_DIR,
)
from collect_repurchase_issuance_submissions import (
    PARSER_VERSION as SUBMISSIONS_PARSER_VERSION,
)
from collect_repurchase_issuance_submissions import (
    parts_lineage as submissions_parts_lineage,
)
from parse_repurchase_item703_documents import OUT_DIR as PARSE_PARTS
from parse_repurchase_item703_documents import PARSER_VERSION as ITEM703_PARSER_VERSION
from parse_repurchase_item703_documents import RESULT as ITEM703_PARSER_RESULT

OUT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/final_feasibility_audit.json"
)


def require_audit(path: Path, schema: str) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"required audit is missing: {path}")
    payload = json.loads(path.read_text())
    if (
        payload.get("schema") != schema
        or payload.get("return_data_opened") is not False
        or payload.get("return_hypotheses_spent") != 0
        or not content_hash_valid(payload)
    ):
        raise RuntimeError(f"required audit is stale or not return-sealed: {path}")
    return payload


def load_current_parts(directory: Path, pattern: str, version: str) -> pd.DataFrame:
    frames = [pd.read_parquet(path) for path in sorted(directory.glob(pattern))]
    if not frames:
        raise RuntimeError(f"no parts match {directory / pattern}")
    frame = pd.concat(frames, ignore_index=True)
    return frame[frame["parser_version"].eq(version)].drop_duplicates()


def issuer_year(frame: pd.DataFrame, date_column: str = "report_date") -> pd.Series:
    return (
        frame["cik"].astype(int).astype(str)
        + "|"
        + pd.to_datetime(frame[date_column], errors="coerce")
        .dt.year.astype("Int64")
        .astype(str)
    )


def combined_coverage(
    facts: pd.DataFrame,
    filings: pd.DataFrame,
    document_sample: pd.DataFrame,
    predictions: pd.DataFrame,
) -> dict[str, Any]:
    filing_map = filings[
        ["cik", "accession", "report_date", "acceptance_datetime"]
    ].drop_duplicates(["cik", "accession"])
    sample = document_sample[["cik", "accession"]].merge(
        filing_map,
        on=["cik", "accession"],
        how="left",
        validate="one_to_one",
    )
    sample = sample[
        sample["report_date"].notna() & sample["acceptance_datetime"].notna()
    ].copy()
    sample["issuer_year"] = issuer_year(sample)
    denominator = set(sample["issuer_year"])

    joined_facts = facts.merge(
        filing_map[["cik", "accession", "report_date"]],
        on=["cik", "accession"],
        how="inner",
        validate="many_to_one",
    )
    joined_facts["issuer_year"] = issuer_year(joined_facts)
    direct_repurchase = set(
        joined_facts.loc[
            joined_facts["tag_family"].isin({"repurchase_cash", "repurchase_shares"}),
            "issuer_year",
        ]
    ) & denominator
    direct_issuance = set(
        joined_facts.loc[
            joined_facts["tag_family"].isin({"issuance_cash", "issuance_shares"}),
            "issuer_year",
        ]
    ) & denominator

    predicted = predictions[
        predictions["parser_version"].eq(ITEM703_PARSER_VERSION)
        & predictions["error"].isna()
    ][["cik", "accession", "has_item703_table", "tender_offer_mention"]]
    predicted = predicted.merge(
        sample[["cik", "accession", "issuer_year"]],
        on=["cik", "accession"],
        how="inner",
        validate="one_to_one",
    )
    item703 = set(predicted.loc[predicted["has_item703_table"], "issuer_year"])
    repurchase = direct_repurchase | item703
    total = len(denominator)
    return {
        "sample_documents": len(sample),
        "sample_issuer_years": total,
        "direct_repurchase_issuer_years": len(direct_repurchase),
        "item703_issuer_years": len(item703),
        "combined_repurchase_issuer_years": len(repurchase),
        "combined_repurchase_coverage": len(repurchase) / total if total else 0.0,
        "combined_repurchase_wilson_95_lower": wilson_lower(len(repurchase), total),
        "direct_issuance_issuer_years": len(direct_issuance),
        "conservative_issuance_coverage": len(direct_issuance) / total if total else 0.0,
        "conservative_issuance_wilson_95_lower": wilson_lower(
            len(direct_issuance), total
        ),
        "tender_offer_mentions": int(predicted["tender_offer_mention"].sum()),
        "missing_sample_metadata": len(document_sample) - len(sample),
    }


def decision_for_gates(gates: dict[str, bool]) -> str:
    governance = (
        gates.get("return_data_unopened", False)
        and gates.get("return_hypotheses_unspent", False)
    )
    if not governance:
        return "REJECT_GOVERNANCE"
    return "PASS_TO_RETURN_PREREGISTRATION" if all(gates.values()) else "DATA_GATED"


def run(args: argparse.Namespace) -> dict[str, Any]:
    companyfacts = require_audit(
        Path(args.companyfacts_audit),
        "canli.feasibility.repurchase-issuance-companyfacts-audit.v1",
    )
    semantics = require_audit(
        Path(args.semantics_audit),
        "canli.feasibility.repurchase-issuance-semantics-audit.v1",
    )
    item703 = require_audit(
        Path(args.item703_audit),
        "canli.feasibility.repurchase-issuance-item703-audit.v1",
    )
    item703_manifest = require_audit(
        Path(args.item703_manifest_result),
        "canli.feasibility.repurchase-issuance-item703-manifest.v1",
    )
    parser_result = require_audit(
        Path(args.item703_parser_result),
        "canli.feasibility.repurchase-issuance-item703-parser.v1",
    )
    facts_count, facts_hash = facts_parts_lineage(Path(args.facts_dir))
    submissions_count, submissions_hash = submissions_parts_lineage(
        Path(args.submissions_dir)
    )
    parse_paths = sorted(Path(args.parse_parts).glob("parse-*.parquet"))
    if (
        facts_count <= 0
        or submissions_count <= 0
        or facts_hash != semantics["facts_parts_sha256"]
        or submissions_hash != semantics["submissions_parts_sha256"]
        or facts_hash != companyfacts["facts_parts_sha256"]
        or submissions_hash != companyfacts["submissions_parts_sha256"]
    ):
        raise RuntimeError("current Company Facts or Submissions parts differ from audit seals")
    if (
        item703_manifest.get("document_manifest_sha256")
        != file_sha256(Path(args.item703_manifest))
        or item703_manifest.get("source_submissions_hash") != submissions_hash
        or item703.get("source_item703_manifest_hash")
        != item703_manifest.get("content_hash")
        or len(parse_paths) != 1
        or parser_result.get("parse_part_sha256") != file_sha256(parse_paths[0])
        or item703.get("source_parser_hash") != parser_result.get("content_hash")
    ):
        raise RuntimeError("current Item 703 artifacts differ from their sealed audit chain")
    if len(
        {
            companyfacts["source_manifest_hash"],
            semantics["source_manifest_hash"],
        }
    ) != 1:
        raise RuntimeError("Company Facts and semantics audits do not share one manifest")
    facts = load_current_parts(
        Path(args.facts_dir), "facts-*.parquet", FACTS_PARSER_VERSION
    )
    filings = load_current_parts(
        Path(args.submissions_dir), "filings-*.parquet", SUBMISSIONS_PARSER_VERSION
    )
    predictions = load_current_parts(
        Path(args.parse_parts), "parse-*.parquet", ITEM703_PARSER_VERSION
    )
    document_sample = pd.read_parquet(args.item703_manifest)
    coverage = combined_coverage(facts, filings, document_sample, predictions)
    gates = {
        "raw_hash_and_accession_lineage": coverage["missing_sample_metadata"] == 0,
        "accession_join_rate_gte_0_95": companyfacts["gates"][
            "accession_join_rate_gte_0_95"
        ],
        "repurchase_coverage_gte_0_70": coverage["combined_repurchase_coverage"]
        >= 0.70,
        "repurchase_wilson_lower_gte_0_65": coverage[
            "combined_repurchase_wilson_95_lower"
        ]
        >= 0.65,
        "issuance_coverage_gte_0_60": coverage["conservative_issuance_coverage"]
        >= 0.60,
        "issuance_wilson_lower_gte_0_55": coverage[
            "conservative_issuance_wilson_95_lower"
        ]
        >= 0.55,
        "item703_precision_gte_0_85": item703["gates"]["precision_gte_0_85"],
        "item703_recall_gte_0_80": item703["gates"]["recall_gte_0_80"],
        "context_complete_rate_gte_0_95": companyfacts["gates"][
            "context_complete_rate_gte_0_95"
        ],
        "amendment_replay_slice_invariant": semantics["gates"][
            "amendment_replay_slice_invariant"
        ],
        "quarterization_fail_closed": semantics["gates"][
            "quarterization_accounts_for_every_eligible_fact"
        ]
        and semantics["gates"]["quarterization_zero_imputations"],
        "contamination_categories_explicit": semantics["gates"][
            "contamination_categories_explicit"
        ],
        "return_data_unopened": True,
        "return_hypotheses_unspent": True,
    }
    decision = decision_for_gates(gates)
    payload: dict[str, Any] = {
        "schema": "canli.feasibility.repurchase-issuance-final-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "combined_no_return_feasibility_decision",
        "protocol": "docs/design/FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md",
        "source_companyfacts_audit_hash": companyfacts["content_hash"],
        "source_semantics_audit_hash": semantics["content_hash"],
        "source_item703_audit_hash": item703["content_hash"],
        "coverage": coverage,
        "gates": gates,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "decision": decision,
        "claim_boundary": (
            "Only PASS_TO_RETURN_PREREGISTRATION permits one separately sealed return identity; "
            "it never admits a sleeve or chooses sign, horizon, universe, threshold, or weight."
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--companyfacts-audit", default=str(COMPANYFACTS_AUDIT))
    parser.add_argument("--semantics-audit", default=str(SEMANTICS_AUDIT))
    parser.add_argument("--item703-audit", default=str(ITEM703_AUDIT))
    parser.add_argument("--facts-dir", default=str(FACTS_DIR))
    parser.add_argument("--submissions-dir", default=str(SUBMISSIONS_DIR))
    parser.add_argument("--item703-manifest", default=str(ITEM703_MANIFEST))
    parser.add_argument(
        "--item703-manifest-result", default=str(ITEM703_MANIFEST_RESULT)
    )
    parser.add_argument("--parse-parts", default=str(PARSE_PARTS))
    parser.add_argument("--item703-parser-result", default=str(ITEM703_PARSER_RESULT))
    parser.add_argument("--out", default=str(OUT))
    result = run(parser.parse_args())
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "PASS_TO_RETURN_PREREGISTRATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
