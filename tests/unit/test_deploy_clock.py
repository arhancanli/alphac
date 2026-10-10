"""Both deploy paths keep one deploy clock, and mean the same thing by a deploy that landed.

WHY THIS EXISTS. Every production deploy starts the company pages' CDN cache cold, and crawlers
re-rendering those pages were ~88% of the Vercel bill in the 2026-10-09 audit. So the hourly job
deploys only when nothing has landed for 24 h, counted from var/last_web_deploy.hash, and the
nightly publish stamps that same file when its deploy lands: the site deploys once a day, not twice.

A STAMP IS ONLY AS GOOD AS THE SUCCESS IT RECORDS. The nightly publish used to count any printed
URL as success, which the hourly job stopped doing on 2026-09-06 (Vercel prints the URL before it
builds). Once the nightly's success also holds the hourly job back for a day, a false success would
leave a dead build in place for that day. Both jobs therefore decide "landed" with one shared
helper, scripts/lib/deploy_landed.sh, and neither carries its own copy: the same reason
test_indexnow_is_in_the_deploy_path.py gives for the IndexNow submission.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib" / "deploy_landed.sh"
HOURLY = REPO / "scripts" / "live_deploy_hourly.sh"
NIGHTLY = REPO / "scripts" / "live_publish.sh"
DEPLOY_PATHS = (HOURLY, NIGHTLY)
APP_DEPLOY = 'deploy_prod "$SITE_SNAPSHOT_ROOT/meridian-app"'
ANNOUNCE = 'indexnow_submit "$SITE_SNAPSHOT_ROOT/meridian"'


def test_the_hourly_job_deploys_at_most_once_a_day_unless_told_to() -> None:
    source = HOURLY.read_text()
    assert "DEPLOY_MIN_INTERVAL_S=${DEPLOY_MIN_INTERVAL_S:-86400}" in source
    gate, lock = source.index("DEPLOY_MIN_INTERVAL_S="), source.index("deploy_lock_acquire")
    assert gate < lock, "the cost gate must run before the deploy takes the lock"
    assert "var/deploy_now" in source[gate:lock]


def test_a_forced_deploy_stays_requested_until_one_lands() -> None:
    """Clearing the flag before deploying turns one failed forced deploy into a day's wait."""
    source = HOURLY.read_text()
    removals = [m.start() for m in re.finditer(r"rm -f \S*deploy_now", source)]
    assert removals, "the hourly job never clears var/deploy_now"
    assert all(at > source.rindex(APP_DEPLOY) for at in removals), (
        "var/deploy_now is cleared before the deploy lands"
    )


@pytest.mark.parametrize("script", DEPLOY_PATHS, ids=lambda p: p.name)
def test_every_deploy_path_stamps_the_clock_once_both_projects_land(script: Path) -> None:
    source = script.read_text()
    after_app = source.rindex(APP_DEPLOY)
    stamp = re.compile(r'> "[^"]*(\$HASH_FILE|last_web_deploy\.hash)"').search(source, after_app)
    assert stamp, f"{script.name} does not stamp the deploy clock after deploying"
    guard = source[source.rfind("if [", after_app, stamp.start()) : stamp.start()]
    assert ("LANDING_OK" in guard and "APP_OK" in guard) or '"$FAIL" = "0"' in guard, (
        f"{script.name} stamps the clock without checking both deploys landed"
    )
    assert stamp.start() < source.index(ANNOUNCE), (
        f"{script.name} stamps after IndexNow, so a kill during the announcement loses the stamp"
    )


@pytest.mark.parametrize("script", DEPLOY_PATHS, ids=lambda p: p.name)
def test_every_deploy_path_decides_landed_with_the_shared_helper(script: Path) -> None:
    source = script.read_text()
    assert re.search(r"^\.\s+\S*scripts/lib/deploy_landed\.sh", source, re.MULTILINE), (
        f"{script.name} does not source scripts/lib/deploy_landed.sh"
    )
    assert re.search(r'deploy_landed "\$label" "\$url" ', source)
    assert "Build Failed" not in source and "%{http_code}" not in source, (
        f"{script.name} carries its own copy of the check instead of the shared helper"
    )


@pytest.mark.parametrize("shell", ["sh", "zsh", "bash"])
@pytest.mark.parametrize(
    ("url", "output", "status", "landed"),
    [
        ("https://site-abc.vercel.app", "Production: https://site-abc.vercel.app", "200", True),
        ("https://site-abc.vercel.app", 'Error: Command "npm run build" exited 1', "200", False),
        ("https://site-abc.vercel.app", "Build Failed", "200", False),
        ("https://site-abc.vercel.app", "Production: https://site-abc.vercel.app", "404", False),
        ("https://site-abc.vercel.app", "Production: https://site-abc.vercel.app", "000", False),
        ("", "no URL was printed", "200", False),
    ],
    ids=["landed", "command-exited", "build-failed", "answers-404", "no-answer", "no-url"],
)
def test_landed_means_a_clean_build_that_answers_200(
    shell: str, url: str, output: str, status: str, landed: bool, tmp_path: Path
) -> None:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is not installed")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(f"#!/bin/sh\nprintf '%s' '{status}'\n")
    curl.chmod(0o755)
    result = subprocess.run(
        [shell, "-c", f'. "{LIB}"; deploy_landed site "$1" "$2"', "deploy_landed", url, output],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (result.returncode == 0) is landed, result.stdout + result.stderr
