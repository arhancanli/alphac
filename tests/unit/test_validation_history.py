"""A sealed record's bound bytes are recoverable from git history even after the file moved on.

Sealed results bind the exact bytes of their inputs (configs/base.yaml, uv.lock, ...). Those files
legitimately change later (the drawdown brake's activation on 2026-09-15 rewrote base.yaml), and a
re-verification that demands CURRENT bytes then fails forever: thirteen suite failures on
2026-09-23 were of this class. The honest check is narrower and just as strict: the exact bytes the
seal names must still exist at that path in a commit of this repository.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from alphaforge.validation.history import recover_bound_commit


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def _commit(repo: Path, rel: str, text: str) -> str:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", f"write {rel}")
    return _git(repo, "rev-parse", "HEAD")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_bytes_that_moved_on_are_found_in_the_commit_that_held_them(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    first = _commit(repo, "configs/base.yaml", "source: file\n")
    _commit(repo, "configs/base.yaml", "source: https\n")
    assert recover_bound_commit(repo, "configs/base.yaml", _sha("source: file\n")) == first


def test_bytes_never_committed_at_that_path_are_not_found(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "configs/base.yaml", "source: https\n")
    _commit(repo, "other.yaml", "source: file\n")
    # The bytes exist in the repository, but never at this path: not a match.
    assert recover_bound_commit(repo, "configs/base.yaml", _sha("source: file\n")) is None
    assert recover_bound_commit(repo, "configs/base.yaml", "0" * 64) is None


def test_a_directory_without_git_history_recovers_nothing(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    assert recover_bound_commit(tmp_path, "a.txt", _sha("x")) is None


def test_the_recovered_size_is_the_size_of_the_bound_bytes(tmp_path: Path) -> None:
    from alphaforge.validation.history import recover_bound_bytes

    repo = _repo(tmp_path)
    first = _commit(repo, "uv.lock", "a" * 17)
    _commit(repo, "uv.lock", "b" * 5)
    assert recover_bound_bytes(repo, "uv.lock", _sha("a" * 17)) == (first, 17)
