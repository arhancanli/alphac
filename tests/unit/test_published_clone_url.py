"""The clone URL we publish must name the repository that actually exists.

WHY THIS EXISTS. /verify shipped on 2026-08-22 telling readers to
`git clone https://github.com/arhancanli/alphaforge.git`. That repository does not exist — it
returns 404 — and the real public remote is `alphac`. It was on the one page whose entire subject
is that our instructions work, which is the worst possible place for a broken one: a reader spends
their single attempt on it and concludes the record is fake rather than the page stale.

WHY THE EXISTING GUARD COULD NOT CATCH IT. The site verifier checks that every INTERNAL link
resolves to a built page and that every named download is published. The clone URL is neither —
it is an external URL, and nothing on the site side can know which repository is the right one.
The truth lives here, in the repo's own remote, so the check lives here too.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.workspace_evidence

BUILD_VERIFY = Path.home() / "meridian" / "scripts" / "build-verify.mjs"


def _origin() -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_the_published_clone_url_is_this_repository() -> None:
    source = BUILD_VERIFY.read_text()
    published = re.findall(r'const CLONE_URL = "([^"]+)"', source)
    assert len(published) == 1, (
        "build-verify.mjs no longer declares exactly one CLONE_URL, so this test is checking "
        f"nothing: found {published}"
    )
    assert published[0] == _origin(), (
        f"the site publishes a clone URL of {published[0]} and this repository's origin is "
        f"{_origin()} — a reader following the published instruction would not reach the code"
    )


def test_the_directory_the_instruction_cds_into_matches_the_url() -> None:
    """`git clone …/alphac.git` lands in `alphac/`. Naming a different directory breaks step two.

    Separate from the URL check on purpose: the first version of this page had a correct-looking
    pair where BOTH halves named a repository that did not exist, so agreement between them is not
    evidence that either is right — each has to be pinned to something real.
    """
    source = BUILD_VERIFY.read_text()
    url = re.findall(r'const CLONE_URL = "([^"]+)"', source)[0]
    expected_dir = url.rsplit("/", 1)[-1].removesuffix(".git")
    assert re.search(rf"\bcd {re.escape(expected_dir)}\b", source), (
        f"the published instruction clones {url} but does not cd into {expected_dir}"
    )
