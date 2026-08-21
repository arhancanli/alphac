"""No number in a kill paper may be typed by hand.

The papers are hybrid by construction: the prose is written, the figures are injected. That is
only trustworthy if it is CHECKED, because the failure mode is silent and this project has lived
it -- withdrawn AlphaVintage figures stayed on the site for six days because two hard-coded
literals in a publish script were not connected to the artifact that had changed underneath them.

The invariant here: every numeric token appearing in a rendered paper must be traceable to its
kill-log entry, either as a figure injected through `_figure` or as text inside the entry's own
written fields. A number that is in neither was typed into a template, and a typed number is a
claim nothing can keep honest.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).parents[2]
KILL_LOG = REPO.parent / "meridian" / "public" / "glassbox" / "kill_log.json"

_spec = importlib.util.spec_from_file_location(
    "build_kill_papers", REPO / "scripts" / "build_kill_papers.py"
)
assert _spec is not None and _spec.loader is not None
kill_papers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kill_papers)

# Digit runs, with any thousands separators and decimal point attached.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _entries() -> list[dict[str, Any]]:
    if not KILL_LOG.exists():
        pytest.skip(f"no published kill log at {KILL_LOG}")
    log = json.loads(KILL_LOG.read_text())
    entries = list(log.get("killed_strategies", [])) + list(log.get("screen_stage_kills", []))
    assert entries, "kill log contains no killed candidates; this guard would pass vacuously"
    return entries


def _source_text(entry: dict[str, Any]) -> str:
    """Everything in the entry a number could legitimately have come from."""
    return " ".join(str(value) for value in entry.values())


def _untraceable_numbers(markdown: str, entry: dict[str, Any], injected: list[str]) -> list[str]:
    allowed = set()
    for figure in injected:
        allowed.add(figure)
        allowed.update(_NUMBER.findall(figure))
    source = _source_text(entry)
    return [
        token
        for token in _NUMBER.findall(markdown)
        if token not in allowed and token not in source
    ]


def test_the_generator_produces_a_paper_for_every_killed_candidate() -> None:
    entries = _entries()
    papers = kill_papers.render_kill_papers(json.loads(KILL_LOG.read_text()))
    assert len(papers) == len(entries)
    assert len({e["name"] for e in entries}) == len(papers), (
        "two candidates share a name, so one paper would overwrite the other"
    )


def test_every_number_in_every_paper_traces_to_its_artifact() -> None:
    for entry in _entries():
        markdown, injected = kill_papers.render_kill_paper(entry)
        untraceable = _untraceable_numbers(markdown, entry, injected)
        assert not untraceable, (
            f"{entry['name']}: these numbers appear in the paper but are in neither the injected "
            f"figures nor the entry's own text: {untraceable}. A typed number is a claim nothing "
            "can keep honest."
        )


def test_the_guard_catches_a_hand_typed_number() -> None:
    """A check that cannot fail is worse than no check, so prove this one bites."""
    entry = _entries()[0]
    markdown, injected = kill_papers.render_kill_paper(entry)
    tampered = markdown + "\n\nThe strategy returned 42.7% in its best year.\n"

    untraceable = _untraceable_numbers(tampered, entry, injected)
    assert "42.7" in untraceable


def test_every_paper_carries_its_verdict_and_its_boundary() -> None:
    """A kill published without its limits reads as a stronger claim than the evidence supports."""
    for entry in _entries():
        markdown, _ = kill_papers.render_kill_paper(entry)
        assert str(entry["verdict"]) in markdown
        assert "does not say the underlying economic effect does not exist" in markdown
        assert "raises the deflated-Sharpe hurdle" in markdown, (
            "every kill paper must state that the trial was not free"
        )


def test_no_paper_reuses_the_default_framing_where_a_specific_one_exists() -> None:
    """A framing that silently falls through to the generic text is a paper nobody wrote."""
    generic_only = []
    for entry in _entries():
        markdown, _ = kill_papers.render_kill_paper(entry)
        has_specific = any(
            framing[:60] in markdown
            for framing in list(kill_papers._FAMILY_FRAMING.values())
            + list(kill_papers._STAGE_FRAMING.values())
        )
        if not has_specific:
            generic_only.append(f"{entry['name']} (type={entry.get('type')}, "
                                f"stage={entry.get('stage')})")
    assert not generic_only, (
        "these candidates fell through to the default framing, so their paper says nothing "
        f"specific about what was tested: {generic_only}"
    )
