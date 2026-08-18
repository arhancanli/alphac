#!/usr/bin/env python3
"""Run the locked schema-aware Item 4 parser v2 on the unchanged corpus."""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_active_ownership_13d_item4 as v1
from audit_sec_filing_text_feasibility import FLAGS, PREFIX, _span, html_to_text

OUT: Final = Path("artifacts/feasibility/active_ownership_13d_item4_v2")
PROTOCOL: Final = "docs/design/FEASIBILITY_ACTIVE_OWNERSHIP_13D_ITEM4_V2.md"
ITEM4_START: Final = (
    re.compile(
        PREFIX
        + r"(?:item\s+)?4\s*[.\-:\u2013\u2014]*\s*purpose\s+of\s+(?:the\s+)?transactions?\b",
        FLAGS,
    ),
)
ITEM4_END: Final = (
    re.compile(
        PREFIX
        + r"(?:item\s+)?5\s*[.\-:\u2013\u2014]*\s*interest\s+in\s+securities"
        + r"(?:\s+of\s+the\s+issuer)?\b",
        FLAGS,
    ),
)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def structured_item_text(raw: bytes) -> str | None:
    stripped = raw.lstrip()
    if not stripped.startswith(b"<?xml"):
        return None
    try:
        root = ET.fromstring(raw.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return None
    item4 = next((element for element in root.iter() if local_name(element.tag) == "item4"), None)
    if item4 is None:
        return None
    purpose = next(
        (
            element
            for element in item4.iter()
            if local_name(element.tag) == "transactionPurpose"
        ),
        None,
    )
    if purpose is None:
        return None
    content = " ".join(text.strip() for text in purpose.itertext() if text.strip())
    return f"Item 4. Purpose of Transaction\n{content}\nItem 5. Interest in Securities"


def schema_aware_text(raw: bytes) -> str:
    return structured_item_text(raw) or html_to_text(raw)


def extract_item4_v2(text: str) -> str | None:
    return _span(text, ITEM4_START, ITEM4_END, minimum_words=50)


def run(args: argparse.Namespace) -> dict:
    v1.PARSER_VERSION = "sec-13d-item4-v2"
    v1.PROTOCOL = PROTOCOL
    v1.html_to_text = schema_aware_text
    v1.extract_item4 = extract_item4_v2
    result = v1.run(args)
    result["schema"] = "canli.feasibility.active-ownership-13d-item4.v2"
    result["protocol"] = PROTOCOL
    result_path = Path(args.out) / "result.json"
    import json

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

