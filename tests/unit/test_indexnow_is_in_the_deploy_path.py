"""Both deploy paths must announce what they published, from one shared implementation.

WHY THIS EXISTS. 99 URLs were submitted to IndexNow once, by hand. Everything published after that
— 27 further pages, including every measurement page and the verification instructions — would
have waited for a crawler to rediscover the sitemap on its own. A push channel that runs only when
somebody remembers is not a push channel.

WHY IT CHECKS FOR ONE SHARED IMPLEMENTATION RATHER THAN JUST FOR THE CALL. This repo has been bitten
twice by identical logic living in two hand-mirrored places: the retracted-claim gate that the
hourly job ran and the nightly one did not, and the glassbox copy list where one host received a
paper the other did not. Both of those looked correct in every file anyone opened. So the test
requires the shared file to exist, both callers to source it, and NEITHER caller to carry its own
copy of the submission.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib" / "indexnow.sh"
DEPLOY_PATHS = (
    REPO / "scripts" / "live_deploy_hourly.sh",
    REPO / "scripts" / "live_publish.sh",
)


def test_the_shared_helper_exists_and_defines_both_halves() -> None:
    source = LIB.read_text()
    assert "indexnow_submit()" in source
    # The half that makes a non-fatal failure loud. Without it, a run of failures is invisible.
    assert "indexnow_warn_if_stale()" in source


@pytest.mark.parametrize("script", DEPLOY_PATHS, ids=lambda p: p.name)
def test_every_deploy_path_submits_and_reports_staleness(script: Path) -> None:
    source = script.read_text()
    assert re.search(r"^\s*\.\s+\S*scripts/lib/indexnow\.sh", source, re.MULTILINE), (
        f"{script.name} does not SOURCE the shared helper — note that the path also appears in a "
        "comment here, so a plain substring check would pass with the directive deleted"
    )
    assert "indexnow_submit" in source, (
        f"{script.name} deploys without announcing what it published"
    )
    assert "indexnow_warn_if_stale" in source, (
        f"{script.name} would let a run of failed submissions pass unreported"
    )


@pytest.mark.parametrize("script", DEPLOY_PATHS, ids=lambda p: p.name)
def test_no_deploy_path_carries_its_own_copy_of_the_submission(script: Path) -> None:
    """Two copies is one copy too many, and this repo has the scar tissue to prove it."""
    source = script.read_text()
    assert "api.indexnow.org" not in source, (
        f"{script.name} posts to IndexNow directly instead of calling the shared helper"
    )
    assert "npm run" not in source or "indexnow" not in source.split("npm run")[1][:40], (
        f"{script.name} invokes the submitter itself rather than through the shared helper"
    )


@pytest.mark.parametrize("script", DEPLOY_PATHS, ids=lambda p: p.name)
def test_submission_is_gated_on_the_landing_deploy_succeeding(script: Path) -> None:
    """Announcing URLs after a failed deploy advertises pages that may not be there."""
    source = script.read_text()
    assert re.search(r"LANDING_OK=\$\?", source), (
        f"{script.name} does not capture whether the landing deploy succeeded"
    )
    guarded = re.search(r'if \[ "\$LANDING_OK" = "0" \]; then\s*\n\s*indexnow_submit', source)
    assert guarded, f"{script.name} submits without checking the landing deploy succeeded"


def test_the_submission_is_bounded() -> None:
    """Every external call in this repo is bounded; an unbounded one hung for 28 hours once."""
    assert re.search(r"run_bounded \d+ npm run", LIB.read_text()), (
        "the IndexNow call is not bounded, and it reaches a third-party API over the network"
    )


def test_a_failure_never_fails_the_deploy_but_is_always_recorded() -> None:
    """Loud, not fatal — and the marker is what stops 'not fatal' from meaning 'not noticed'."""
    source = LIB.read_text()
    assert "return 0" in source.split("indexnow_submit()")[1].split("\n}")[0], (
        "indexnow_submit can fail its caller; a third-party notification must not fail a publish"
    )
    body = source.split("indexnow_submit()")[1].split("\n}")[0]
    assert body.count("INDEXNOW_MARKER") >= 2, (
        "the marker is not written on every attempt, so 'when did this last work' would need "
        "the log"
    )
    assert "FAILED" in body, "a failed submission is not recorded as failed"
