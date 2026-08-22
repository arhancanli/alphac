"""No published artifact may reach the site with nothing guarding it.

WHY THIS IS A SEPARATE, CHEAP TEST. Building the claim-coverage map runs the whole unit suite, the
reproduce kit and the site verifiers, which is right for a deliberate run and wrong for every
commit. What rots between runs is not the map's numbers — it is the SET: somebody publishes a new
artifact, it lands on both hosts, and nothing at all checks its contents. That question costs
milliseconds.

It also pins the weakest mechanism as weak. An artifact whose only coverage is the host mirror is
one where we verify two copies agree and nothing verifies what they say, and the count of those is
allowed to fall but not to rise.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "claim_coverage", REPO / "scripts" / "build_claim_coverage_map.py"
)
assert _spec is not None and _spec.loader is not None
coverage = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = coverage
_spec.loader.exec_module(coverage)

pytestmark = pytest.mark.workspace_evidence

#: What the map measured when this ceiling was set. It may fall; it may not rise without somebody
#: deciding that a new claim needs no check beyond "both hosts got the same bytes".
MIRROR_ONLY_CEILING = 8


def _rows() -> list[dict[str, object]]:
    guards = coverage._guard_sources()
    rendered = coverage._rendered_artifacts()
    exporter = coverage.EXPORTER.read_text()
    import json

    rows = []
    for path in sorted(coverage.GLASSBOX.glob("*.json")):
        try:
            document = json.loads(path.read_text())
        except (ValueError, OSError):
            document = None
        mechanisms = []
        if any(path.stem in text for text in guards.values()):
            mechanisms.append("NAMED_GUARD")
        if isinstance(document, dict) and "content_hash" in document:
            mechanisms.append("CONTENT_HASH")
        if path.name in coverage.SIGNED:
            mechanisms.append("SIGNATURE")
        if path.stem in rendered:
            mechanisms.append("RENDERED_PAGE")
        if f'"{path.name}"' in exporter:
            mechanisms.append("HOST_MIRROR")
        rows.append({"artifact": path.name, "mechanisms": mechanisms})
    return rows


def test_the_published_set_is_not_empty() -> None:
    """A scan that found no artifacts would make both checks below pass with nothing covered."""
    assert len(_rows()) >= 40


def test_every_published_artifact_has_at_least_one_guard() -> None:
    unguarded = [r["artifact"] for r in _rows() if not r["mechanisms"]]
    assert unguarded == [], (
        f"these artifacts are published and nothing checks them at all: {unguarded}. Split "
        "coverage reads as coverage; no coverage reads the same way from the outside."
    )


def test_the_mirror_only_set_does_not_grow() -> None:
    mirror_only = [r["artifact"] for r in _rows() if r["mechanisms"] == ["HOST_MIRROR"]]
    assert len(mirror_only) <= MIRROR_ONLY_CEILING, (
        f"{len(mirror_only)} artifacts are guarded only by the host mirror, up from "
        f"{MIRROR_ONLY_CEILING}: {mirror_only}. That mechanism verifies two copies agree and "
        "nothing about what they say — if the contents went stale, both hosts would publish the "
        "same wrong thing and every check would pass."
    )


def test_the_guard_sources_actually_loaded() -> None:
    """If no guard source loaded, every artifact would look unguarded and the first test would
    fail loudly — but the mirror-only ceiling would pass, so the floor is pinned here too."""
    assert len(coverage._guard_sources()) >= 50
