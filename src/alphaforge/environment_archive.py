"""Verify historical lock bytes without installing them or claiming a new replay."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EnvironmentBinding:
    original_path: str
    resolved_path: str
    sha256: str
    active_sha256: str | None
    status: str

    def receipt(self) -> dict[str, str | None]:
        return {
            "original_path": self.original_path,
            "resolved_path": self.resolved_path,
            "sha256": self.sha256,
            "active_sha256": self.active_sha256,
            "status": self.status,
        }


def _regular_path(root: Path, relative: str) -> Path:
    path = root / relative
    for candidate in (path, *path.parents):
        if candidate == root:
            break
        if candidate.is_symlink():
            raise ValueError(f"environment binding contains a symlink: {relative}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"environment binding escapes repository: {relative}")
    return path


def resolve_environment_binding(
    root: Path, relative: str, expected: str, *, allow_archive: bool = True
) -> EnvironmentBinding:
    """Resolve only declared project/lock inputs; archives never authorize execution.

    The archive path is derived from the already-bound digest, not an arbitrary
    path supplied by a manifest. Source-code bindings never use this resolver.
    """
    if relative not in {"uv.lock", "pyproject.toml"}:
        raise ValueError(f"unsupported environment binding: {relative}")
    if not isinstance(expected, str) or re.fullmatch(r"[a-f0-9]{64}", expected) is None:
        raise ValueError("invalid environment digest")
    root = root.resolve()
    active = _regular_path(root, relative)
    active_hash = hashlib.sha256(active.read_bytes()).hexdigest() if active.is_file() else None
    if active_hash == expected:
        return EnvironmentBinding(relative, relative, expected, active_hash, "ACTIVE_FILE_MATCH")
    # Only uv.lock has an archival policy. A changed project definition remains a hard failure.
    if not allow_archive or relative != "uv.lock":
        raise ValueError(f"active environment binding mismatch: {relative}")
    archived = f"research/environments/{expected}/uv.lock.txt"
    path = _regular_path(root, archived)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"historical environment archive missing or corrupt: {archived}")
    return EnvironmentBinding(relative, archived, expected, active_hash, "HISTORICAL_ARCHIVE_ONLY")
