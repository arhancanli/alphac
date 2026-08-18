from __future__ import annotations

import gzip
import importlib.util
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[2] / "scripts" / "audit_customer_supplier_propagation_feasibility.py"
)
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location(
    "audit_customer_supplier_propagation_feasibility", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_prefilter_requires_customer_and_ten_percent_in_same_neighborhood() -> None:
    assert MODULE.is_concentration_candidate(
        b"<p>Apple Inc. accounted for 14% of our revenue and was our largest customer.</p>"
    )
    assert not MODULE.is_concentration_candidate(b"<p>We have many customers around the world.</p>")
    assert not MODULE.is_concentration_candidate(b"customer" + b"x" * 500 + b"10 percent")


def test_strict_extractor_keeps_named_customer_and_rejects_anonymous_label() -> None:
    named = MODULE.strict_name_candidates("Apple Inc accounted for 14% of consolidated revenue.")
    anonymous = MODULE.strict_name_candidates(
        "Customer A accounted for 22% of consolidated revenue."
    )
    assert named == [{"name": "Apple Inc", "percent": 14.0, "pattern_id": 1}]
    assert anonymous == []


def test_windows_require_customer_context() -> None:
    text = (
        "Apple was 12% of revenue and our largest customer. "
        + "unrelated " * 20
        + "Tax was 10% of expense."
    )
    windows = MODULE.concentration_windows(text, radius=45)
    assert len(windows) == 1
    assert "customer" in windows[0]


def test_document_path_matches_frozen_cache_identity(tmp_path: Path) -> None:
    path = MODULE.document_path(1234, "0000001234-24-000001", tmp_path)
    assert path.name == "1234_0000001234-24-000001.html.gz"
    path.write_bytes(gzip.compress(b"filing", mtime=0))
    assert gzip.decompress(path.read_bytes()) == b"filing"
