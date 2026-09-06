#!/usr/bin/env python3
"""Run the locked Schedule 13D source-schema v3 on the unchanged 160 accessions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Final, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_active_ownership_13d_item4 as v1
import audit_active_ownership_13d_item4_v2 as v2

OUT: Final = Path("artifacts/feasibility/active_ownership_13d_item4_v3")
PROTOCOL: Final = "docs/design/FEASIBILITY_ACTIVE_OWNERSHIP_13D_ITEM4_V3.md"
DOCUMENT_V3_PATTERN: Final = re.compile(
    rb"<DOCUMENT>\s*<TYPE>\s*([^\r\n]+).*?<SEQUENCE>\s*([^\r\n]+).*?"
    rb"<FILENAME>\s*([^\r\n]+).*?<TEXT>(.*?)</TEXT>\s*</DOCUMENT>",
    re.IGNORECASE | re.DOTALL,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def exact_primary_documents_v3(raw: bytes, form: str) -> list[tuple[str, bytes]]:
    matches: list[tuple[str, str, bytes]] = []
    for match in DOCUMENT_V3_PATTERN.finditer(raw):
        document_type = match.group(1).decode("latin-1", errors="replace").strip()
        sequence = match.group(2).decode("latin-1", errors="replace").strip()
        filename = match.group(3).decode("latin-1", errors="replace").strip()
        if document_type == form:
            matches.append((sequence, filename, match.group(4)))
    if len(matches) <= 1:
        return [(filename, body) for _, filename, body in matches]
    primary = [(filename, body) for sequence, filename, body in matches if sequence == "1"]
    return primary if len(primary) == 1 else []


def unwrap_edgar_xml(raw: bytes) -> bytes | None:
    text = raw.decode("utf-8", errors="replace").strip()
    wrapper = re.fullmatch(r"<XML>\s*(<\?xml[\s\S]*</[^>]+>)\s*</XML>", text)
    if wrapper:
        return wrapper.group(1).encode()
    if text.startswith("<?xml"):
        return text.encode()
    return None


def structured_item_text_v3(raw: bytes) -> str | None:
    xml_raw = unwrap_edgar_xml(raw)
    if xml_raw is None:
        return None
    try:
        root = ET.fromstring(xml_raw.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return None
    item4 = next(
        (element for element in root.iter() if v2.local_name(element.tag) == "item4"),
        None,
    )
    if item4 is None:
        return None
    purpose = next(
        (
            element
            for element in item4.iter()
            if v2.local_name(element.tag) == "transactionPurpose"
        ),
        None,
    )
    if purpose is None:
        return None
    content = " ".join(text.strip() for text in purpose.itertext() if text.strip())
    return f"Item 4. Purpose of Transaction\n{content}\nItem 5. Interest in Securities"


def schema_aware_text_v3(raw: bytes) -> str:
    return structured_item_text_v3(raw) or v2.html_to_text(raw)


def run(args: argparse.Namespace) -> dict[str, Any]:
    v1.PARSER_VERSION = "sec-13d-item4-v3"
    v1.PROTOCOL = PROTOCOL
    v1.exact_primary_documents = exact_primary_documents_v3
    v1.html_to_text = schema_aware_text_v3
    v1.extract_item4 = v2.extract_item4_v2
    result = cast(dict[str, Any], v1.run(args))
    result.update(
        {
            "schema": "canli.feasibility.active-ownership-13d-item4.v3",
            "author": "Arhan Canli",
            "protocol": PROTOCOL,
            "source_lineage": {
                "protocol_sha256": sha256_file(Path(PROTOCOL)),
                "locked_sample_sha256": sha256_file(Path(args.source)),
                "document_audit_sha256": sha256_file(Path(args.out) / "document_audit.parquet"),
                "frozen_human_labels_sha256": sha256_file(
                    Path(args.out) / "frozen_human_labels.csv"
                ),
            },
            "market_data_opened": False,
            "return_data_opened": False,
            "return_hypotheses_spent": 0,
            "claim_boundary": (
                "Machine extraction feasibility passed on the frozen corpus. Classification "
                "accuracy, returns, Sharpe, drawdown, correlation, capacity and sleeve admission "
                "remain unproven until their separate gates pass."
            ),
        }
    )
    result["content_hash"] = content_hash(result)
    result_path = Path(args.out) / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(v1.SOURCE))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--raw", default=str(v1.RAW))
    parser.add_argument("--sample-per-year", type=int, default=10)
    parser.add_argument("--uncached-delay", type=float, default=0.8)
    run(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
