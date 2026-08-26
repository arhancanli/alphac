"""Regression: every external call on a scheduled path must be KILLABLE.

THE INCIDENT (2026-08-03). `vercel deploy` has no timeout of its own. One hung deploy held the
hourly tick's single-runner lock for 28 HOURS and blocked ALL trading — a cosmetic web publish
stopping the critical path.

THE SUBTLE PART, which is why these tests exist rather than a code review. The obvious fix (kill
the child by PID) DOES NOT WORK for a captured command like::

    url=$(run_bounded 600 vercel deploy --prod --yes | grep -oE 'https://...')

`vercel` spawns grandchildren. Killing only the direct child leaves them alive holding the write
end of the capture pipe, so the command substitution keeps blocking and the hang survives the
"fix". ``run_bounded`` therefore starts the child as its own process-group leader and kills the
whole GROUP. ``test_hang_with_grandchild_is_killed`` is the test that distinguishes the two
implementations — it fails against the naive PID-only version.

The second bug these pin: the first fix pattern-killed ``vercel deploy`` from live_tick's
watchdog, but the hourly tick (:05) and the nightly publish (02:10) overlap by schedule, so a
broad pkill would kill the OTHER job's deploy mid-upload. Hence group-kill by pid (can only ever
hit our own child) plus a shared lock, not pattern matching.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "bounded.sh"

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh-only helper")


def run_zsh(body: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["zsh", "-c", f". {LIB}\n{body}"],
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def test_library_parses() -> None:
    assert subprocess.run(["zsh", "-n", str(LIB)], check=False).returncode == 0


def test_output_and_exit_code_pass_through() -> None:
    """A bounded call must behave exactly like the unbounded one on the happy path."""
    r = run_zsh('run_bounded 30 /bin/echo hello-world; echo "rc=$?"')
    assert "hello-world" in r.stdout
    assert "rc=0" in r.stdout
    r = run_zsh('run_bounded 30 /bin/sh -c "exit 7"; echo "rc=$?"')
    assert "rc=7" in r.stdout, "a real failure must still be reported to the caller"


def test_capture_through_command_substitution() -> None:
    """The live call sites capture stdout — backgrounding must not break that."""
    r = run_zsh(
        'u=$(run_bounded 30 /bin/echo "https://x-1.vercel.app" 2>&1 | tail -1); '
        'echo "got:$u"'
    )
    assert "got:https://x-1.vercel.app" in r.stdout


def test_hang_with_grandchild_is_killed() -> None:
    """THE decisive test: a hung tree must not outlive its cap, and the capture must return.

    `sh -c 'sleep 600; echo x'` does not exec — it forks a grandchild, reproducing the vercel
    shape. A PID-only watchdog leaves that grandchild holding the pipe and this test times out.
    """
    t0 = time.monotonic()
    r = run_zsh(
        'u=$(run_bounded 3 /bin/sh -c "sleep 600; echo never" 2>&1); '
        'echo "after:[$u]"',
        timeout=45,
    )
    elapsed = time.monotonic() - t0
    assert "after:[]" in r.stdout, "capture did not return — a grandchild still holds the pipe"
    assert elapsed < 60, (
        f"hang outlived its 3s cap ({elapsed:.1f}s) — watchdog did not kill the tree. The failure "
        "this guards against is the full 600s sleep, so anything under a minute means the tree "
        "was killed; the bound is loose on purpose because the suite runs in parallel."
    )


def test_a_missing_command_says_which_command() -> None:
    """A failure that cannot be read is a failure that cannot be fixed.

    perl's exec failure is silent, so a missing binary produced exit 127 and not one byte of
    output — every caller logged an empty error tail and had to guess. Found while checking
    whether the IndexNow submission survives launchd's minimal PATH: it reported SUBMISSION FAILED
    followed by a blank line. Same defect class as the deploy that piped vercel's output into grep
    and discarded the reason for a 23-hour outage.
    """
    result = subprocess.run(
        ["zsh", "-c", f". {LIB}; run_bounded 5 definitely_not_a_command_xyz"],
        capture_output=True,
        text=True,
        cwd=LIB.parents[2],
    )
    assert result.returncode == 127, f"expected 127 for a missing command, got {result.returncode}"
    combined = result.stdout + result.stderr
    assert "definitely_not_a_command_xyz" in combined, (
        f"run_bounded did not say which command it could not run: {combined!r}"
    )
    assert "cannot exec" in combined


def test_a_command_that_exists_still_passes_its_output_through() -> None:
    """The half that would break if the diagnostic were added carelessly."""
    result = subprocess.run(
        ["sh", "-c", f". {LIB}; run_bounded 5 echo hello-from-bounded"],
        capture_output=True,
        text=True,
        cwd=LIB.parents[2],
    )
    assert result.returncode == 0
    assert "hello-from-bounded" in result.stdout


def test_hang_leaves_no_orphan() -> None:
    run_zsh('run_bounded 2 /bin/sh -c "sleep 407; echo never" >/dev/null 2>&1', timeout=45)
    time.sleep(1)
    left = subprocess.run(["pgrep", "-f", "sleep 407"], capture_output=True, text=True, check=False)
    assert left.returncode != 0, f"orphaned process survived the watchdog: {left.stdout!r}"


def test_deploy_lock_is_mutually_exclusive(tmp_path: Path) -> None:
    """The hourly deploy and the nightly publish must never deploy concurrently."""
    r = run_zsh(
        f'DEPLOY_LOCK="{tmp_path}/d.lock"\n'
        'deploy_lock_acquire && echo A1 || echo A1-blocked\n'
        'deploy_lock_acquire && echo A2 || echo A2-blocked\n'
        'deploy_lock_release\n'
        'deploy_lock_acquire && echo A3 || echo A3-blocked\n'
    )
    assert "A1\n" in r.stdout
    assert "A2-blocked" in r.stdout, "two jobs held the deploy lock at once"
    assert "A3\n" in r.stdout, "lock was not released"


def test_deploy_lock_steals_a_dead_holder(tmp_path: Path) -> None:
    """A SIGKILL'd deploy cannot clean up; a permanently stuck lock would freeze the site."""
    lock = tmp_path / "d.lock"
    lock.mkdir()
    old = time.time() - 3600
    import os
    os.utime(lock, (old, old))
    r = run_zsh(f'DEPLOY_LOCK="{lock}"\ndeploy_lock_acquire && echo STOLE || echo STUCK')
    assert "STOLE" in r.stdout, "a stale lock was never reclaimed — the site would stop updating"
