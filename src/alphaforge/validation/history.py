"""Recover the exact bytes a sealed record bound, from this repository's git history.

A sealed result binds its inputs by sha256. Inputs such as ``configs/base.yaml`` or ``uv.lock``
move on legitimately after the seal, and a re-verification that demands the CURRENT bytes then
fails forever even though nothing about the sealed record is wrong. The check here is as strict
and narrower: the bound bytes must exist, byte for byte, at the same path in a commit of this
repository. The claimed hash comes from inside the content-hashed seal, so it cannot be chosen
after the fact without breaking the seal.

Re-verification only. Creating a NEW seal must still bind the current bytes.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)


def recover_bound_bytes(repo: Path, relative: str, sha256_hex: str) -> tuple[str, int] | None:
    """``(commit, size)`` of the newest commit whose ``relative`` has exactly those bytes.

    ``None`` when no commit holds them at that path, or when ``repo`` has no git history (a
    clean shallow checkout cannot prove it). The size lets a re-verification rebuild the sealed
    binding row byte for byte.
    """
    log = _git(repo, "log", "--format=%H", "--", relative)
    if log.returncode != 0:
        return None
    for commit in log.stdout.decode().split():
        blob = _git(repo, "show", f"{commit}:{relative}")
        if blob.returncode == 0 and hashlib.sha256(blob.stdout).hexdigest() == sha256_hex:
            return commit, len(blob.stdout)
    return None


def recover_bound_commit(repo: Path, relative: str, sha256_hex: str) -> str | None:
    """The newest commit whose ``relative`` has exactly the bytes ``sha256_hex``, else ``None``."""
    found = recover_bound_bytes(repo, relative, sha256_hex)
    return found[0] if found else None
