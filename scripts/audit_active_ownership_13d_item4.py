#!/usr/bin/env python3
"""Audit a frozen Schedule 13D Item 4 corpus without loading prices or returns."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_active_ownership_13d_metadata import read_or_fetch
from audit_sec_filing_text_feasibility import (
    FLAGS,
    PREFIX,
    _span,
    html_to_text,
    sha256_bytes,
    sha256_text,
)
from build_sec_10k_manifest import SecClient

SOURCE: Final = Path(
    "artifacts/feasibility/active_ownership_13d_schema_v2/header_audit.parquet"
)
OUT: Final = Path("artifacts/feasibility/active_ownership_13d_item4")
RAW: Final = Path("data/raw/sec_active_ownership_13d/submissions")
PROTOCOL: Final = "docs/design/FEASIBILITY_ACTIVE_OWNERSHIP_13D_ITEM4.md"
PARSER_VERSION: Final = "sec-13d-item4-v1"
DOCUMENT_PATTERN: Final = re.compile(
    rb"<DOCUMENT>\s*<TYPE>\s*([^\r\n]+).*?<FILENAME>\s*([^\r\n]+).*?"
    rb"<TEXT>(.*?)</TEXT>\s*</DOCUMENT>",
    re.I | re.S,
)
ITEM4_START: Final = (
    re.compile(PREFIX + r"item\s+4\s*[.\-:\u2013\u2014]*\s*purpose\s+of\s+transaction\b", FLAGS),
)
ITEM4_END: Final = (
    re.compile(PREFIX + r"item\s+5\s*[.\-:\u2013\u2014]*\s*interest\s+in\s+securities\b", FLAGS),
)
SENTENCE_PATTERN: Final = re.compile(r"[^.!?\n]+(?:[.!?]|$)")
ACTIVE_PATTERNS: Final = (
    re.compile(r"(?i)\b(?:nominate|nominated|appoint|appointed)\b[^.]{0,120}\b(?:director|board)"),
    re.compile(r"(?i)\bseek(?:s|ing)?\b[^.]{0,80}\bboard\s+representation\b"),
    re.compile(r"(?i)\b(?:delivered|sent|submitted)\b[^.]{0,100}\b(?:letter|proposal)\b"),
    re.compile(
        r"(?i)\b(?:demand|demands|demanded|urge|urges|urged)\b[^.]{0,140}"
        r"\b(?:strategic|sale|capital|buyback|dividend|governance|board)\b"
    ),
    re.compile(r"(?i)\bagreement\b[^.]{0,120}\bboard\s+seat\b"),
    re.compile(
        r"(?i)\bintend(?:s|ed)?\s+to\b[^.]{0,100}\b(?:engage|discuss|seek|propose)\b"
        r"[^.]{0,120}\b(?:management|board|strategic|sale|capital|governance)\b"
    ),
)
BOILERPLATE: Final = re.compile(
    r"(?i)\b(?:may|might|could|reserves?\s+the\s+right\s+to)\b[^.]{0,120}"
    r"\b(?:future|from\s+time\s+to\s+time|consider|review)\b"
)
PERCENT_PATTERN: Final = re.compile(
    r"(?i)(?:beneficial(?:ly)?\s+(?:own|owned|ownership)|aggregate\s+percentage|"
    r"percent\s+of\s+class)[^%\n]{0,120}?([0-9]{1,3}(?:\.[0-9]{1,3})?)\s*%"
)


def locked_sample(frame: pd.DataFrame, per_year: int = 10) -> pd.DataFrame:
    eligible = frame[
        frame["error"].isna()
        & frame["acceptance_datetime"].notna()
        & frame["subject_cik"].notna()
        & frame["filed_by_cik"].notna()
        & frame["ticker_match_count"].eq(1)
    ].copy()
    eligible["document_rank"] = eligible.apply(
        lambda row: hashlib.sha256(f"{int(row['year'])}|{row['accession']}".encode()).hexdigest(),
        axis=1,
    )
    sample = (
        eligible.sort_values(["year", "document_rank", "accession"])
        .groupby("year", group_keys=False)
        .head(per_year)
        .reset_index(drop=True)
    )
    counts = sample.groupby("year").size()
    if len(sample) != 160 or not counts.eq(10).all():
        raise RuntimeError(f"locked Item 4 sample incomplete: {counts.to_dict()}")
    return sample


def exact_primary_documents(raw: bytes, form: str) -> list[tuple[str, bytes]]:
    matches: list[tuple[str, bytes]] = []
    for match in DOCUMENT_PATTERN.finditer(raw):
        document_type = match.group(1).decode("latin-1", errors="replace").strip()
        filename = match.group(2).decode("latin-1", errors="replace").strip()
        if document_type == form:
            matches.append((filename, match.group(3)))
    return matches


def extract_item4(text: str) -> str | None:
    return cast(str | None, _span(text, ITEM4_START, ITEM4_END, minimum_words=50))


def active_sentences(section: str) -> list[str]:
    sentences: list[str] = []
    for match in SENTENCE_PATTERN.finditer(section):
        sentence = re.sub(r"\s+", " ", match.group(0)).strip()
        if BOILERPLATE.search(sentence):
            continue
        if any(pattern.search(sentence) for pattern in ACTIVE_PATTERNS):
            sentences.append(sentence)
    return sentences


def percentage_candidates(text: str) -> list[float]:
    return sorted(
        {
            round(float(match.group(1)), 3)
            for match in PERCENT_PATTERN.finditer(text)
            if 0 < float(match.group(1)) <= 100
        }
    )


def build_labels(sample: pd.DataFrame, path: Path) -> None:
    if path.exists():
        return
    selected = sample.groupby("year", group_keys=False).head(3).copy()
    labels = selected[
        ["year", "accession", "subject_cik", "filed_by_cik", "ticker", "submission_url"]
    ].copy()
    labels["human_specific_active_intent"] = ""
    labels["human_representative_sentence"] = ""
    labels["human_aggregate_ownership_pct_or_unresolved"] = ""
    labels["human_notes"] = ""
    labels.to_csv(path, index=False)


def score_labels(rows: pd.DataFrame, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"complete": False, "labeled": 0, "required": 48}
    labels = pd.read_csv(path, dtype=str, keep_default_na=False)
    valid_binary = labels["human_specific_active_intent"].isin(["true", "false"])
    required_text = labels["human_representative_sentence"].ne("")
    required_pct = labels["human_aggregate_ownership_pct_or_unresolved"].ne("")
    complete = valid_binary & required_text & required_pct
    if not complete.all():
        return {"complete": False, "labeled": int(complete.sum()), "required": len(labels)}
    merged = labels.merge(
        rows[["accession", "specific_active_intent", "ownership_pct_candidates"]],
        on="accession",
        validate="one_to_one",
    )
    truth = merged["human_specific_active_intent"].eq("true")
    prediction = merged["specific_active_intent"].astype(bool)
    true_positive = int((truth & prediction).sum())
    precision = true_positive / int(prediction.sum()) if prediction.any() else 0.0
    recall = true_positive / int(truth.sum()) if truth.any() else 0.0
    human_ownership = merged["human_aggregate_ownership_pct_or_unresolved"].map(
        lambda value: str(value).strip().lower()
    )

    def ownership_matches(row: pd.Series) -> bool:
        candidates = [float(value) for value in row["ownership_pct_candidates"]]
        human = str(row["human_aggregate_ownership_pct_or_unresolved"]).strip().lower()
        if len(candidates) != 1:
            return human == "unresolved"
        try:
            return float(human) == candidates[0]
        except ValueError:
            return False

    valid_ownership = human_ownership.eq("unresolved") | pd.to_numeric(
        human_ownership, errors="coerce"
    ).notna()
    if not bool(valid_ownership.all()):
        return {
            "complete": False,
            "labeled": int(valid_ownership.sum()),
            "required": len(merged),
            "error": "ownership labels must be a plain number or unresolved",
        }
    ownership_exact_rate = float(merged.apply(ownership_matches, axis=1).mean())
    return {
        "complete": True,
        "labeled": len(merged),
        "required": len(merged),
        "positive_precision": precision,
        "positive_recall": recall,
        "ownership_exact_rate": ownership_exact_rate,
        "ownership_machine_rule": "sole_candidate_else_unresolved",
    }


def validate_import_receipt(labels_path: Path, receipt_path: Path) -> None:
    if not receipt_path.is_file():
        raise ValueError("completed human labels lack a sealed import receipt")
    receipt = cast(dict[str, Any], json.loads(receipt_path.read_text()))
    body = {key: value for key, value in receipt.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    expected_hash = "sha256:" + hashlib.sha256(encoded).hexdigest()
    if receipt.get("content_hash") != expected_hash:
        raise ValueError("human-label import receipt content hash mismatch")
    if receipt.get("canonical_labels_after_sha256") != hashlib.sha256(
        labels_path.read_bytes()
    ).hexdigest():
        raise ValueError("completed human labels do not match the sealed import receipt")
    if receipt.get("rows_imported") != 48 or receipt.get("prediction_blind_attested") is not True:
        raise ValueError("human-label import receipt does not prove the governed blind review")
    return_boundary_broken = (
        receipt.get("return_hypotheses_spent") != 0
        or receipt.get("return_data_opened") is not False
    )
    if return_boundary_broken:
        raise ValueError("human-label import receipt violates the no-return boundary")


def run(args: argparse.Namespace) -> dict[str, Any]:
    sample = locked_sample(pd.read_parquet(args.source), args.sample_per_year)
    sample["submission_url"] = sample["index_filename"].map(
        lambda path: f"https://www.sec.gov/Archives/{path}"
    )
    out = Path(args.out)
    raw_dir = Path(args.raw)
    out.mkdir(parents=True, exist_ok=True)
    sample.to_csv(out / "locked_document_sample.csv", index=False)
    labels_path = out / "frozen_human_labels.csv"
    build_labels(sample, labels_path)

    client = SecClient(raw_dir / "network_metadata_cache")
    rows: list[dict[str, Any]] = []
    try:
        for index, raw_record in enumerate(sample.to_dict("records"), 1):
            record = cast(dict[str, Any], raw_record)
            accession = str(record["accession"])
            cache = raw_dir / f"{accession}.txt.gz"
            try:
                raw, cached = read_or_fetch(
                    client, str(record["submission_url"]), cache, args.uncached_delay
                )
                primary = exact_primary_documents(raw, str(record["form"]))
                if len(primary) != 1:
                    raise ValueError(
                        f"expected one exact-form primary document, found {len(primary)}"
                    )
                filename, body = primary[0]
                text = html_to_text(body)
                section = extract_item4(text)
                matches = active_sentences(section or "")
                rows.append(
                    {
                        **record,
                        "parser_version": PARSER_VERSION,
                        "submission_cache_path": str(cache),
                        "submission_sha256": sha256_bytes(raw),
                        "submission_bytes": len(raw),
                        "submission_from_cache": cached,
                        "primary_document": filename,
                        "primary_document_count": len(primary),
                        "primary_document_sha256": sha256_bytes(body),
                        "document_words": len(text.split()),
                        "item4_extracted": section is not None,
                        "item4_words": len(section.split()) if section else 0,
                        "item4_sha256": sha256_text(section) if section else None,
                        "specific_active_intent": bool(matches),
                        "active_sentences": matches,
                        "ownership_pct_candidates": percentage_candidates(text),
                        "item4_text": section,
                        "error": None,
                    }
                )
            except Exception as error:
                rows.append({**record, "error": str(error), "item4_extracted": False})
            if index % 20 == 0 or index == len(sample):
                print(f"13D Item 4 submissions {index}/{len(sample)}", flush=True)
    finally:
        client.close()

    frame = pd.DataFrame(rows)
    frame.to_parquet(out / "document_audit.parquet", index=False, compression="zstd")
    successful = frame["error"].isna()
    extracted = successful & frame["item4_extracted"].fillna(False)
    extracted_frame = frame[extracted]
    positive_rate = (
        float(extracted_frame["specific_active_intent"].mean()) if len(extracted_frame) else 0.0
    )
    gates = {
        "submissions_160_of_160": int(successful.sum()) == len(sample) == 160,
        "exact_primary_document_rate_gte_0_98": (
            float(frame["primary_document_count"].eq(1).mean()) >= 0.98
            if "primary_document_count" in frame
            else False
        ),
        "item4_extraction_rate_gte_0_90": float(extracted.mean()) >= 0.90,
        "every_positive_has_source_sentence": bool(
            extracted_frame.loc[
                extracted_frame["specific_active_intent"], "active_sentences"
            ].map(bool).all()
        ),
        "positive_class_rate_between_0_10_and_0_90": 0.10 <= positive_rate <= 0.90,
    }
    accuracy = score_labels(frame, labels_path)
    if accuracy.get("complete"):
        try:
            validate_import_receipt(labels_path, out / "human_label_import_receipt.json")
        except ValueError as error:
            accuracy = {
                "complete": False,
                "labeled": accuracy.get("labeled", 0),
                "required": accuracy.get("required", 48),
                "error": str(error),
            }
    machine_pass = all(gates.values())
    accuracy_pass = bool(
        accuracy.get("complete")
        and accuracy.get("positive_precision", 0) >= 0.95
        and accuracy.get("positive_recall", 0) >= 0.80
        and accuracy.get("ownership_exact_rate", 0) is not None
        and accuracy.get("ownership_exact_rate", 0) >= 0.90
    )
    decision = (
        "PASS_TO_RETURN_PREREGISTRATION"
        if machine_pass and accuracy_pass
        else "HUMAN_AUDIT_REQUIRED"
        if machine_pass and not accuracy.get("complete")
        else "DATA_GATED"
    )
    result = {
        "schema": "canli.feasibility.active-ownership-13d-item4.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_document_feasibility_no_prices_no_returns",
        "protocol": PROTOCOL,
        "hypothesis_identities_spent": 0,
        "sample_rows": len(frame),
        "successful_submissions": int(successful.sum()),
        "item4_extracted": int(extracted.sum()),
        "item4_extraction_rate": float(extracted.mean()),
        "specific_active_intent": int(
            extracted_frame["specific_active_intent"].sum()
        ) if len(extracted_frame) else 0,
        "specific_active_intent_rate": positive_rate,
        "gates": gates,
        "human_accuracy_audit": accuracy,
        "decision": decision,
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SOURCE))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--raw", default=str(RAW))
    parser.add_argument("--sample-per-year", type=int, default=10)
    parser.add_argument("--uncached-delay", type=float, default=0.8)
    run(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
