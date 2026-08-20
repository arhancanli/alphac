"""The signed-chain fact on the public page must not label entries as days.

WHAT WENT WRONG. `transparency_log.json` gains an entry on every PUBLISH, and the tick publishes
hourly, so the entry count runs roughly 8x the number of calendar dates the record covers.
`js/open.js` bound `entry_count` to a slot that `open.html` labelled "days", under the heading
"Signed chain". The live page therefore read "371 days" while the chain spanned 47 dates and the
published live book was 13 days old — an ~8x overstatement of how long the signed record had been
running, on the one page whose whole argument is "don't trust us, verify us".

It also got worse on its own. Nothing tied the label to the data, so every hour the tick ran, the
number the site displayed as "days" grew by one. It had already been recorded once at 239.

WHY THESE ASSERTIONS. Checking that `distinct_days` exists in the JSON would not have caught it —
the defect was never in the data, it was in which field the page chose and what word sat beside
it. So these read the SITE, and pin the pairing rather than the presence.

Marked workspace_evidence: the sibling site workspace is not present in a CI checkout.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SITE = REPO.parent / "meridian"
OPEN_HTML = SITE / "open.html"
OPEN_JS = SITE / "js" / "open.js"
PUBLISHED = SITE / "public" / "glassbox" / "transparency_log.json"

#: `<span data-tx="NAME">…</span>` followed by whatever word the page prints next to it.
_FACT = re.compile(r'<span data-tx="(?P<hook>[A-Za-z]+)">[^<]*</span>\s*(?P<unit>[A-Za-z]+)')

pytestmark = pytest.mark.workspace_evidence


def _fact_units(html: str) -> dict[str, str]:
    """Map each rendered hook to the bare word printed immediately after it."""
    return {m.group("hook"): m.group("unit").lower() for m in _FACT.finditer(html)}


def _require(path: Path) -> str:
    assert path.exists(), (
        f"{path} is missing, so this guard would pass without checking anything. If the site moved,"
        " RETARGET this test rather than deleting it."
    )
    return path.read_text(encoding="utf-8")


def test_the_entry_count_is_never_the_number_labelled_days() -> None:
    units = _fact_units(_require(OPEN_HTML))
    assert units, (
        "no data-tx facts found in open.html — the scan matched nothing, so it proves nothing"
    )
    assert units.get("entries") != "days", (
        'open.html prints the entry count followed by the word "days". The chain gains an entry '
        "per publish, not per day, so this overstates the length of the signed record by however "
        "many times a day the tick runs."
    )


def test_the_page_renders_a_distinct_day_count_at_all() -> None:
    html = _require(OPEN_HTML)
    js = _require(OPEN_JS)
    assert 'data-tx="days"' in html, "open.html no longer has a slot for the true day count"
    assert re.search(r'setHook\(\s*"tx"\s*,\s*"days"', js), (
        "open.js never fills the days slot, so the page would render a literal placeholder"
    )
    assert "distinct_days" in js, (
        "open.js does not read distinct_days; if it went back to deriving days from entry_count "
        "the original defect is back under a different name"
    )


def test_the_two_numbers_really_are_different_in_the_published_bundle() -> None:
    """If they were equal the distinction would be academic. They are not: prove it on real data."""
    d = json.loads(_require(PUBLISHED))
    entries, days = d["entry_count"], d["distinct_days"]
    assert days <= entries, f"more distinct dates ({days}) than entries ({entries}) is impossible"
    assert days < entries, (
        "entry_count equals distinct_days in the published chain. That makes the mislabel harmless "
        "TODAY and invisible tomorrow — check why the tick stopped appending more than once a day."
    )


def test_the_label_check_can_fail() -> None:
    """A guard that cannot fail is worse than no guard."""
    bad = '<span data-tx="entries">--</span> days &middot; head'
    good = '<span data-tx="days">--</span> days &middot; <span data-tx="entries">--</span> entries'
    assert _fact_units(bad).get("entries") == "days"
    assert _fact_units(good).get("entries") == "entries"
    assert _fact_units(good).get("days") == "days"
