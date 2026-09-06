from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_publication_bibliographies.py"
REGISTRY = ROOT / "config" / "external_publication_registry.json"
CACHE = ROOT / "artifacts" / "research" / "publication_reference_metadata.json"


def _module():
    spec = importlib.util.spec_from_file_location("publication_bibliographies", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_cache_is_complete_and_content_hash_bound() -> None:
    module = _module()
    registry = json.loads(REGISTRY.read_text())
    cache = json.loads(CACHE.read_text())
    required = module._all_required_dois(registry)

    module._validate_cache(cache, required)
    assert len(required) == len(cache["records"]) == 29
    assert cache["unresolved_references"] == []
    assert "10.1016/j.econlet.2019.03.028" in cache["records"]
    assert "10.1016/j.econlet.2020.109060" not in cache["records"]
    assert cache["records"]["10.1093/rof/rfs019"]["title"] == (
        "The Fundamentals of Commodity Futures Returns"
    )


def test_every_generic_sleeve_has_a_complete_normalized_bibliography() -> None:
    registry = json.loads(REGISTRY.read_text())
    generic = [
        item for item in registry["sleeves"] if item["key"] != "alphavintage_macro_surprise"
    ]
    assert len(generic) == 15

    for item in generic:
        out = (ROOT / item["bundle_manifest"]).parent
        references = json.loads((out / "references.json").read_text())
        bibtex = (out / "references.bib").read_text()

        assert references["status"] == "COMPLETE_NORMALIZED_BIBLIOGRAPHY"
        assert references["unresolved_references"] == []
        assert references["reference_count"] == len(references["references"])
        assert references["reference_count"] >= 1
        assert bibtex.count("@article{") + bibtex.count("@techreport{") + bibtex.count(
            "@online{"
        ) == references["reference_count"]
