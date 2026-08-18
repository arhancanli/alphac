from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "audit_active_ownership_13d_item4_v2.py"
SPEC = importlib.util.spec_from_file_location("audit_active_ownership_13d_item4_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_legacy_heading_variants_extract() -> None:
    for heading in (
        "ITEM 4. PURPOSE OF THE TRANSACTION",
        "ITEM 4. PURPOSE OF TRANSACTIONS",
        "4. Purpose of the Transaction",
    ):
        text = f"{heading}\n" + "purpose " * 60 + "\n5. Interest in Securities of the Issuer"
        assert MODULE.extract_item4_v2(text) is not None


def test_structured_xml_injects_semantic_item_boundaries() -> None:
    raw = b"""<?xml version="1.0"?>
<edgarSubmission><formData><item4><transactionPurpose>""" + b"active purpose " * 60 + b"""
</transactionPurpose></item4><item5><ownership>7.5</ownership></item5></formData></edgarSubmission>"""
    text = MODULE.schema_aware_text(raw)
    assert "Item 4. Purpose of Transaction" in text
    assert MODULE.extract_item4_v2(text) is not None


def test_malformed_xml_falls_back_without_crashing() -> None:
    assert MODULE.structured_item_text(b"<?xml broken") is None
