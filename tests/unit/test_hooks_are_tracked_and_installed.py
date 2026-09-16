"""The pre-commit hook must live in the repository, not only in one working copy.

WHY. `.git/hooks` is not tracked, so a hook that exists only there exists for exactly one clone and
silently does not exist for anybody else — including for whoever inherits this machine. The hooks
live in `scripts/hooks/` where they are reviewable and versioned, and `core.hooksPath` points at
them.

This does NOT assert the hook is installed in this clone, because that is a local setting a fresh
checkout will not have. It asserts the hook is present, executable, and does the thing it claims —
so the fix for a fresh checkout is one documented command rather than a mystery.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "scripts" / "hooks" / "pre-commit"
INSTALLER = REPO / "scripts" / "install_hooks.sh"


def test_the_hook_is_tracked_and_executable() -> None:
    assert HOOK.is_file(), "the pre-commit hook is not in the repository"
    assert os.access(HOOK, os.X_OK), f"{HOOK} is not executable, so git would ignore it"
    assert INSTALLER.is_file() and os.access(INSTALLER, os.X_OK), (
        "there is no installer, so a fresh checkout has no way to enable the hook"
    )


def test_the_hook_regenerates_the_artifact_it_exists_for() -> None:
    """Naming the script is not evidence it runs it."""
    body = HOOK.read_text()
    assert "export_lint_debt_contract.py" in body
    # It must be CONDITIONAL on Python being part of the commit: a docs-only commit should not pay
    # for a ruff pass over the repository, and a hook that is slow on every commit gets disabled.
    assert "--cached --name-only" in body
    assert r"\.py$" in body


def test_the_map_is_regenerated_only_where_its_inputs_exist() -> None:
    """A worktree renders a DIFFERENT map, and staging it reverts the publisher tree's.

    The map counts the engineering contracts under artifacts/ and the lake directories under
    data/, both gitignored. On 2026-09-16 a commit put the publisher-rendered map in main and the
    very next commit from a scratch worktree, which has neither directory, silently replaced it
    with one claiming 3 contracts and 0 lakes — reverting the fix and re-failing the guard on the
    only machine that can satisfy it.
    """
    body = HOOK.read_text()
    assert '[ -d "$REPO/artifacts" ] && [ -d "$REPO/data" ]' in body
    # Decided before the lint-debt exporter runs, because that exporter creates artifacts/ itself.
    assert body.index("MACHINE_INPUTS_PRESENT=no") < body.index("export_lint_debt_contract.py")
    assert "system map NOT regenerated" in body


def test_the_installer_points_git_at_the_tracked_hooks() -> None:
    assert "core.hooksPath" in INSTALLER.read_text()


def test_the_hook_runs_clean_on_a_commit_with_no_python() -> None:
    """A hook that errors on an ordinary commit is a hook somebody will delete."""
    result = subprocess.run(["sh", str(HOOK)], cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, (
        f"the pre-commit hook exited {result.returncode} with nothing staged: {result.stderr}"
    )
