#!/usr/bin/env python3
"""Parse frozen Item 703 documents with a parser hash sealed before evaluation."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_repurchase_item703_manifest import content_hash_valid
from collect_repurchase_issuance_companyfacts import file_sha256
from collect_repurchase_item703_documents import (
    COLLECTOR_VERSION,
)
from collect_repurchase_item703_documents import (
    OUT_DIR as DOCUMENT_PARTS,
)
from collect_repurchase_item703_documents import (
    RESULT as DOCUMENT_RESULT,
)
from collect_repurchase_item703_documents import (
    parts_lineage as document_parts_lineage,
)
from seal_repurchase_item703_labels import OUT as LABEL_SEAL

OUT_DIR: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/item703/parser_parts"
)
RESULT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/item703/parser_result.json"
)
PARSER_VERSION: Final = "repurchase-item703-table-parser-v2"
MONTH_PATTERN: Final = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\b",
    re.IGNORECASE,
)
DATE_PATTERN: Final = re.compile(r"\b(?:0?[1-9]|1[0-2])[/\-.](?:0?[1-9]|[12]\d|3[01])\b")
PARSE_COLUMNS: Final = (
    "cik",
    "accession",
    "filing_year",
    "form",
    "parser_version",
    "source_raw_sha256",
    "table_count",
    "candidate_table_count",
    "has_item703_table",
    "month_rows",
    "has_total_row",
    "tender_offer_mention",
    "candidate_table_sha256",
    "error",
)


def normalize(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split()).strip().lower()


class TableExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.tables: list[list[list[str]]] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.all_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.table = []
        elif self.depth == 1 and tag == "tr":
            self.row = []
        elif self.depth == 1 and tag in {"td", "th"} and self.row is not None:
            self.cell = []
        elif self.depth == 1 and tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data: str) -> None:
        self.all_text.append(data)
        if self.depth == 1 and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.depth == 1 and tag in {"td", "th"} and self.cell is not None:
            if self.row is not None:
                self.row.append(" ".join(self.cell))
            self.cell = None
        elif self.depth == 1 and tag == "tr" and self.row is not None:
            if any(normalize(cell) for cell in self.row):
                assert self.table is not None
                self.table.append(self.row)
            self.row = None
            self.cell = None
        elif tag == "table" and self.depth:
            if self.depth == 1 and self.table:
                self.tables.append(self.table)
                self.table = None
            self.depth -= 1


def is_item703_candidate(rows: list[list[str]]) -> bool:
    text = normalize(" ".join(cell for row in rows for cell in row))
    return (
        "total number of shares" in text
        and "average price paid" in text
        and ("publicly announced" in text or "plans or programs" in text)
    )


def row_shape(rows: list[list[str]]) -> tuple[int, bool]:
    month_rows = 0
    has_total = False
    for row in rows:
        text = normalize(" ".join(row))
        first = normalize(row[0]) if row else ""
        if MONTH_PATTERN.search(text) or DATE_PATTERN.search(first):
            month_rows += 1
        if first == "total" or first.startswith("total "):
            has_total = True
    return month_rows, has_total


def parse_html(raw: bytes) -> dict[str, Any]:
    extractor = TableExtractor()
    extractor.feed(raw.decode("utf-8", errors="replace"))
    candidates = [table for table in extractor.tables if is_item703_candidate(table)]
    month_rows = 0
    has_total = False
    hashes = []
    for table in candidates:
        rows, total = row_shape(table)
        month_rows = max(month_rows, rows)
        has_total = has_total or total
        canonical = json.dumps(table, ensure_ascii=False, separators=(",", ":")).encode()
        hashes.append(hashlib.sha256(canonical).hexdigest())
    return {
        "table_count": len(extractor.tables),
        "candidate_table_count": len(candidates),
        "has_item703_table": bool(candidates),
        "month_rows": month_rows,
        "has_total_row": has_total,
        "tender_offer_mention": "tender offer"
        in normalize(" ".join(extractor.all_text)),
        "candidate_table_sha256": hashlib.sha256("|".join(hashes).encode()).hexdigest()
        if hashes
        else None,
    }


def require_seals(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    documents = json.loads(Path(args.documents_result).read_text())
    label_seal = json.loads(Path(args.label_seal).read_text())
    part_count, part_hash = document_parts_lineage(Path(args.document_parts))
    parser_hash = file_sha256(Path(__file__))
    if (
        documents.get("schema")
        != "canli.feasibility.repurchase-issuance-item703-documents.v1"
        or documents.get("collector_version") != COLLECTOR_VERSION
        or documents.get("complete") is not True
        or documents.get("part_count") != part_count
        or documents.get("parts_sha256") != part_hash
        or not content_hash_valid(documents)
    ):
        raise RuntimeError("Item 703 document collection is stale or incomplete")
    if (
        label_seal.get("schema")
        != "canli.feasibility.repurchase-issuance-item703-label-seal.v1"
        or label_seal.get("complete") is not True
        or label_seal.get("source_documents_parts_sha256") != part_hash
        or label_seal.get("parser_source_sha256") != parser_hash
        or label_seal.get("return_data_opened") is not False
        or label_seal.get("return_hypotheses_spent") != 0
        or not content_hash_valid(label_seal)
    ):
        raise RuntimeError("blind label seal is stale or parser source changed after sealing")
    return documents, label_seal


def current_documents(directory: Path) -> pd.DataFrame:
    frames = []
    for number, path in enumerate(sorted(directory.glob("status-*.parquet"))):
        frame = pd.read_parquet(path)
        frame["part_number"] = number
        frames.append(frame)
    if not frames:
        raise RuntimeError("no Item 703 document parts found")
    frame = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["accession", "part_number"])
        .drop_duplicates("accession", keep="last")
    )
    return frame[
        frame["collector_version"].eq(COLLECTOR_VERSION) & frame["error"].isna()
    ]


def parse_document(row: dict[str, Any]) -> dict[str, Any]:
    base = {key: row[key] for key in ("cik", "accession", "filing_year", "form")}
    base["parser_version"] = PARSER_VERSION
    base["source_raw_sha256"] = row["raw_sha256"]
    try:
        raw = gzip.decompress(Path(row["raw_cache_path"]).read_bytes())
        if hashlib.sha256(raw).hexdigest() != row["raw_sha256"]:
            raise ValueError("raw document hash mismatch")
        return {**base, **parse_html(raw), "error": None}
    except Exception as error:
        return {
            **base,
            "table_count": 0,
            "candidate_table_count": 0,
            "has_item703_table": False,
            "month_rows": 0,
            "has_total_row": False,
            "tender_offer_mention": False,
            "candidate_table_sha256": None,
            "error": str(error),
        }


def run(args: argparse.Namespace) -> dict[str, Any]:
    documents, label_seal = require_seals(args)
    out_dir = Path(args.out_dir)
    if any(out_dir.glob("parse-*.parquet")) or Path(args.result).exists():
        raise FileExistsError("parser outputs are immutable; refusing to overwrite")
    source = current_documents(Path(args.document_parts))
    rows = [parse_document(row) for row in source.to_dict("records")]
    out_dir.mkdir(parents=True, exist_ok=True)
    part = out_dir / "parse-00000.parquet"
    pd.DataFrame(rows, columns=PARSE_COLUMNS).to_parquet(part, index=False, compression="zstd")
    errors = sum(row["error"] is not None for row in rows)
    payload: dict[str, Any] = {
        "schema": "canli.feasibility.repurchase-issuance-item703-parser.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "frozen_parser_before_blind_label_evaluation",
        "parser_version": PARSER_VERSION,
        "parser_source_sha256": file_sha256(Path(__file__)),
        "source_documents_parts_sha256": documents["parts_sha256"],
        "source_label_seal_hash": label_seal["content_hash"],
        "parsed_documents": len(rows),
        "parse_errors": errors,
        "parse_part_sha256": file_sha256(part),
        "labels_opened": False,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "complete": len(rows) == documents["expected_documents"] and errors == 0,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    result_path = Path(args.result)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-parts", default=str(DOCUMENT_PARTS))
    parser.add_argument("--documents-result", default=str(DOCUMENT_RESULT))
    parser.add_argument("--label-seal", default=str(LABEL_SEAL))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--result", default=str(RESULT))
    result = run(parser.parse_args())
    print(json.dumps(result, indent=2))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
