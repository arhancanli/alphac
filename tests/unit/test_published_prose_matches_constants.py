"""Published PROSE must never contradict the CONSTANT it describes.

On 2026-08-07 `BOOK_WEIGHTS` moved from 40/40/20 to equal thirds. Eight published strings kept
saying "fixed 40/40/20", so the shipped artifact contradicted itself inside a single file: every
sleeve carried `weight: 0.333` while the prose beside it named 40/40/20. It went live and served
that way until an audit caught it.

The root cause is not carelessness, it is architecture: hand-typed prose about a constant is a
SECOND source of truth, and a second source of truth is a defect waiting for someone to change the
first one. `WEIGHTS_PROSE` now derives from `BOOK_WEIGHTS`, and these tests fail if anyone
reintroduces a hand-typed weight description into a published string.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from paper_trading_state import (  # noqa: E402
    BOOK_WEIGHTS,
    WEIGHTS_PROSE,
    _weights_prose,
)

_GEN = _SCRIPTS / "paper_trading_state.py"
#: A literal weight split like "40/40/20" or "50/50" appearing in a PUBLISHED string.
_WEIGHT_LITERAL = re.compile(r"\b\d{2}/\d{2}(?:/\d{2})?\b")


def test_prose_derives_from_the_constant() -> None:
    assert _weights_prose() == WEIGHTS_PROSE
    # "equal quarters" since 2026-08-10, when AlphaVintage became the fourth live sleeve.
    # This literal is pinned deliberately: it is the one place a silent weight change would
    # otherwise slip into published prose without anyone re-reading the words.
    assert WEIGHTS_PROSE == "equal quarters", (
        f"BOOK_WEIGHTS is {BOOK_WEIGHTS}, prose is {WEIGHTS_PROSE!r}"
    )


def test_prose_tracks_a_change_in_the_constant() -> None:
    """The property that actually matters: change the weights, the words change with them."""
    import paper_trading_state as m

    original = dict(m.BOOK_WEIGHTS)
    try:
        m.BOOK_WEIGHTS = {"a": 0.5, "b": 0.3, "c": 0.2}
        assert m._weights_prose() == "50/30/20"
        m.BOOK_WEIGHTS = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
        assert m._weights_prose() == "equal quarters"
    finally:
        m.BOOK_WEIGHTS = original


def test_no_hand_typed_weight_split_survives_in_a_published_string() -> None:
    """Scan the generator for a literal split inside a quoted string that is not a comment.

    Historical weights ARE allowed to appear — the v2 rebaseline disclosure legitimately says the
    book once ran 40/40/20 — so the rule is scoped: a weight literal may not sit in a string that
    also describes the CURRENT book. Those are the strings that go stale on a weight change.
    """
    offenders: list[tuple[int, str]] = []
    in_docstring = False
    for i, line in enumerate(_GEN.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        # Track triple-quoted blocks: a docstring explaining the history of this very bug quotes
        # "fixed 40/40/20" legitimately, and is not a published string.
        ticks = line.count('"""') + line.count("'''")
        if ticks % 2 == 1:
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#"):
            continue  # comments and docstrings may discuss history freely
        if not _WEIGHT_LITERAL.search(line):
            continue
        if '"' not in line and "'" not in line:
            continue
        # Allowed only where the sentence is explicitly about the superseded v2 book.
        if any(k in line for k in ("v2", "previously", "used to", "was really", "had been")):
            continue
        offenders.append((i, stripped[:100]))
    assert not offenders, (
        "hand-typed weight split in a published string describing the CURRENT book:\n  "
        + "\n  ".join(f"line {n}: {t}" for n, t in offenders)
        + "\nUse the derived WEIGHTS_PROSE instead, or scope the sentence to the historical book."
    )
