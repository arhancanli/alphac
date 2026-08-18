from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[2]
    / "scripts"
    / "audit_active_ownership_13d_item4_v3.py"
)
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("audit_active_ownership_13d_item4_v3", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_sequence_one_resolves_multiple_exact_form_documents() -> None:
    raw = b"""
<DOCUMENT><TYPE>SC 13D
<SEQUENCE>2
<FILENAME>duplicate.htm
<TEXT>duplicate</TEXT></DOCUMENT>
<DOCUMENT><TYPE>SC 13D
<SEQUENCE>1
<FILENAME>primary.htm
<TEXT>primary</TEXT></DOCUMENT>
"""
    assert MODULE.exact_primary_documents_v3(raw, "SC 13D") == [
        ("primary.htm", b"primary")
    ]


def test_structured_parser_unwraps_edgar_xml_envelope() -> None:
    raw = b"""<XML>
<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13D">
  <formData><item4><transactionPurpose>Seek two board seats and discuss strategic alternatives.
  This paragraph contains enough source words to remain a meaningful Item 4 disclosure for the
  unchanged minimum-length extraction contract used by the production parser.</transactionPurpose>
  </item4></formData>
</edgarSubmission>
</XML>"""
    text = MODULE.structured_item_text_v3(raw)
    assert text is not None
    assert "Seek two board seats" in text
    assert text.startswith("Item 4. Purpose of Transaction")


def test_non_xml_document_falls_back() -> None:
    assert MODULE.structured_item_text_v3(b"<html>legacy filing</html>") is None
