"""A published sleeve number must track its artifact, and a KILLED sleeve must not
read as validated.

WHAT WENT WRONG, which this exists to stop repeating. AlphaVintage was deployed on 2026-08-10 at a
quarter of the book on a verdict of ADD (net Sharpe 0.3403, Newey-West t 1.82). On 2026-08-16 its
probe was re-run with a calendar correction retaining zero-exposure sessions: net Sharpe 0.2298,
NW t 1.267, pre-registered check `b_nw_t_ge_1p5` FALSE, and
`artifacts/probe/cpi_surprise_size/result.json` recorded **verdict: KILLED**.

The published figures never moved, because they were HARD-CODED literals in
`scripts/paper_trading_state.py`. For three days canlicapital.com described a killed candidate as a
validated 25%-weight live sleeve, and nothing in the repo could notice: the retraction blocklist
only catches a claim once someone has already decided to retract it, and no test bound a published
number to the artifact it came from.

These tests bind them. They are deliberately narrow -- they assert only what an artifact actually
states -- because a test that re-derives the number would just be a second implementation that can
drift the same way.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STATE_SCRIPT = REPO / "scripts" / "paper_trading_state.py"

#: Published sleeve -> the artifact that is the SOURCE OF TRUTH for its headline Sharpe.
#: Only sleeves whose artifact carries an unambiguous scalar net Sharpe are listed; adding a
#: sleeve here is how you opt it into this guarantee.
SLEEVE_ARTIFACTS = {
    "alphavintage": REPO / "artifacts" / "probe" / "cpi_surprise_size" / "result.json",
}

#: Keys an artifact may use for the figure that should be published.
_SHARPE_KEYS = ("net_sharpe", "sharpe", "net_sharpe_ann")
#: Keys whose presence means the artifact itself has superseded a figure.
_SUPERSEDED_MARKERS = ("_superseded", "superseded")


def _artifact(path: Path) -> dict:
    if not path.exists():
        pytest.skip(f"artifact absent: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("sleeve,artifact_path", sorted(SLEEVE_ARTIFACTS.items()))
def test_published_sharpe_is_not_a_superseded_value(sleeve: str, artifact_path: Path) -> None:
    """The site must not publish a number the artifact itself labels superseded.

    This is the exact failure: 0.338207 lived in the artifact under
    `active_day_net_sharpe_superseded` while 0.34 was published as the sleeve's Sharpe.
    """
    art = _artifact(artifact_path)
    superseded = [
        float(v)
        for k, v in art.items()
        if any(m in k for m in _SUPERSEDED_MARKERS) and isinstance(v, (int, float))
    ]
    if not superseded:
        pytest.skip(f"{sleeve}: artifact declares no superseded figure")

    text = STATE_SCRIPT.read_text(encoding="utf-8")
    for bad in superseded:
        # Published to 2dp is how the site renders it; that is the form that must not appear
        # as an assertion. It may still appear inside a correction, so require the retraction
        # vocabulary nearby rather than banning the digits outright.
        rendered = f"{bad:.2f}"
        for idx in _find_all(text, f'"standalone_sharpe": {rendered}'):
            window = text[max(0, idx - 900) : idx + 900]
            assert _has_retraction_language(window), (
                f"{sleeve}: publishes standalone_sharpe {rendered}, which the artifact records as "
                f"a SUPERSEDED value, with no retraction stated beside it"
            )


@pytest.mark.parametrize("sleeve,artifact_path", sorted(SLEEVE_ARTIFACTS.items()))
def test_a_killed_sleeve_is_disclosed_as_killed(sleeve: str, artifact_path: Path) -> None:
    """A sleeve whose own artifact says KILLED may still be held, but must not read as validated.

    This does NOT assert the sleeve is withdrawn -- that is an allocation decision. It asserts the
    published copy tells the reader the verdict, so nobody has to open the repo to learn it.
    """
    art = _artifact(artifact_path)
    verdict = str(art.get("verdict", "")).upper()
    if verdict != "KILLED":
        pytest.skip(f"{sleeve}: artifact verdict is {verdict or 'absent'}, not KILLED")

    text = STATE_SCRIPT.read_text(encoding="utf-8")
    assert "KILLED" in text, (
        f"{sleeve}: its artifact records verdict KILLED and the published state never says so. "
        f"A killed candidate carrying live weight must disclose that, whatever the allocation "
        f"decision turns out to be."
    )


@pytest.mark.parametrize("sleeve,artifact_path", sorted(SLEEVE_ARTIFACTS.items()))
def test_failed_preregistered_checks_are_disclosed(sleeve: str, artifact_path: Path) -> None:
    """If a pre-registered check is FALSE, the published copy must not imply it passed."""
    art = _artifact(artifact_path)
    checks = art.get("checks")
    if not isinstance(checks, dict):
        pytest.skip(f"{sleeve}: artifact has no checks block")
    failed = [k for k, v in checks.items() if v is False]
    if not failed:
        pytest.skip(f"{sleeve}: all pre-registered checks passed")

    text = STATE_SCRIPT.read_text(encoding="utf-8")
    assert _has_retraction_language(text), (
        f"{sleeve}: pre-registered checks {failed} are FALSE and the published state contains no "
        f"withdrawal, correction or failure language anywhere"
    )


def test_this_check_can_fail() -> None:
    """A check that cannot fail is worse than no check.

    Proves the guarantee has teeth: a synthetic artifact declaring a superseded figure and a
    KILLED verdict must be detected as such by the same predicates the tests above use.
    """
    art = {"net_sharpe": 0.1, "active_day_net_sharpe_superseded": 0.99, "verdict": "KILLED",
           "checks": {"b_nw_t_ge_1p5": False}}
    superseded = [v for k, v in art.items() if "superseded" in k and isinstance(v, (int, float))]
    assert superseded == [0.99]
    assert str(art["verdict"]).upper() == "KILLED"
    assert [k for k, v in art["checks"].items() if v is False] == ["b_nw_t_ge_1p5"]
    assert not _has_retraction_language("a page with no correction vocabulary at all")
    assert _has_retraction_language("CORRECTION 2026-08-19 — those numbers are WITHDRAWN")


def test_every_listed_artifact_exists() -> None:
    """A mapping that silently points at nothing makes every case above vacuously skip."""
    missing = [s for s, p in SLEEVE_ARTIFACTS.items() if not p.exists()]
    assert not missing, f"SLEEVE_ARTIFACTS points at absent files: {missing}"


def _find_all(haystack: str, needle: str) -> list[int]:
    out, i = [], haystack.find(needle)
    while i != -1:
        out.append(i)
        i = haystack.find(needle, i + 1)
    return out


def _has_retraction_language(window: str) -> bool:
    return any(
        w in window
        for w in ("WITHDRAWN", "withdraw", "CORRECTION", "superseded", "KILLED",
                  "we published", "we said")
    )
