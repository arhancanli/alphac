from __future__ import annotations

import importlib.util
import json
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


def test_persisted_v3_result_is_hash_bound_and_stops_at_human_audit() -> None:
    result_path = (
        SCRIPT.parents[1]
        / "artifacts"
        / "feasibility"
        / "active_ownership_13d_item4_v3"
        / "result.json"
    )
    result = json.loads(result_path.read_text())
    assert result["decision"] == "HUMAN_AUDIT_REQUIRED"
    assert result["successful_submissions"] == 160
    assert result["item4_extracted"] == 150
    assert result["item4_extraction_rate"] == 0.9375
    assert result["human_accuracy_audit"] == {"complete": False, "labeled": 0, "required": 48}
    assert result["return_data_opened"] is False
    assert result["return_hypotheses_spent"] == 0
    assert result["content_hash"] == MODULE.content_hash(result)
