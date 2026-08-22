"""The system map must be what the repository currently is, not what it was.

WHY. A hand-written map is accurate on the day it is written and quietly wrong afterwards, which is
worse than no map: a reader trusts it and is misled. So the map is generated, and this pins the
committed copy to a fresh render.

MARKED workspace_evidence deliberately. The map includes the launchd agents installed on THIS
machine, which a CI runner does not have, so a fresh render there would legitimately differ. The
guard belongs where the machine is.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "system_map", REPO / "scripts" / "build_system_map.py"
)
assert _spec is not None and _spec.loader is not None
system_map = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = system_map
_spec.loader.exec_module(system_map)

pytestmark = pytest.mark.workspace_evidence


def test_the_committed_map_is_what_the_repository_is_now() -> None:
    committed = system_map.OUTPUT.read_text()
    fresh = system_map.render()
    assert committed == fresh, (
        "docs/design/SYSTEM_MAP.md no longer describes this repository. Regenerate it with "
        "`.venv/bin/python scripts/build_system_map.py`, or run scripts/install_hooks.sh once so "
        "the pre-commit hook does it for you. Do not edit the file by hand — it is generated."
    )


def test_the_render_is_deterministic() -> None:
    """Two renders must be identical, or the guard above would fail at random.

    The first version included a file count per data directory, and the collectors write into
    those every day: the committed map would have gone stale on its own within the hour, which is
    exactly the nuisance that trains a reader to ignore a real failure.
    """
    assert system_map.render() == system_map.render()


def test_the_map_describes_a_repository_of_the_expected_size() -> None:
    """Floors, because a render over an empty repository would satisfy equality perfectly."""
    fresh = system_map.render()
    assert len(fresh.splitlines()) > 200, "the map is too short to be describing this repository"
    sections = (
        "## What runs on a timer",
        "## The pipelines",
        "## Contracts",
        "## Scripts by kind",
    )
    for expected in sections:
        assert expected in fresh, f"the map has lost its {expected!r} section"


def test_every_script_states_what_it_is() -> None:
    """A script with no docstring shows up in the map as having none; none should.

    This is the map earning its keep: it makes an undocumented script visible instead of absent.
    """
    missing = [
        p.name
        for p in sorted((REPO / "scripts").glob("*.py"))
        if system_map._docstring_first_line(p) == "_(no docstring)_"
    ]
    assert missing == [], f"these scripts do not say what they are for: {missing}"
