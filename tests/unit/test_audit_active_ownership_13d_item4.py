from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "audit_active_ownership_13d_item4.py"
SPEC = importlib.util.spec_from_file_location("audit_active_ownership_13d_item4", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_exact_primary_document_ignores_amendment_and_exhibit() -> None:
    raw = b"""<DOCUMENT>
<TYPE>SC 13D
<FILENAME>primary.htm
<TEXT><html>primary</html></TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-99.1
<FILENAME>letter.htm
<TEXT>letter</TEXT>
</DOCUMENT>"""
    assert MODULE.exact_primary_documents(raw, "SC 13D") == [
        ("primary.htm", b"<html>primary</html>")
    ]


def test_extract_item4_rejects_toc_and_keeps_real_section() -> None:
    text = (
        "Item 4. Purpose of Transaction\nItem 5. Interest in Securities\n"
        "Item 4. Purpose of Transaction\nThe Reporting Person delivered a letter to the Board. "
        + "specific action " * 60
        + "\nItem 5. Interest in Securities"
    )
    section = MODULE.extract_item4(text)
    assert section is not None
    assert "delivered a letter" in section


def test_active_classifier_excludes_generic_optional_boilerplate() -> None:
    generic = (
        "The Reporting Person may from time to time consider proposing changes to the Board."
    )
    active = "The Reporting Person delivered a letter to the Board proposing a strategic review."
    assert MODULE.active_sentences(generic) == []
    assert MODULE.active_sentences(active) == [active]


def test_percentage_candidates_are_bounded_and_deduplicated() -> None:
    text = "The Reporting Person beneficially owns 7.5%. Aggregate percentage 7.500%."
    assert MODULE.percentage_candidates(text) == [7.5]
