from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from alphaforge.environment_archive import resolve_environment_binding


@pytest.fixture
def archive(tmp_path: Path) -> tuple[Path, str, Path]:
    historical = b"original locked research dependencies\n"
    digest = hashlib.sha256(historical).hexdigest()
    path = tmp_path / "research/environments" / digest / "uv.lock.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(historical)
    (tmp_path / "uv.lock").write_text("patched active dependencies\n")
    return tmp_path, digest, path


def test_archive_is_explicit_and_does_not_establish_active_environment(archive):
    root, digest, path = archive
    binding = resolve_environment_binding(root, "uv.lock", digest)
    assert binding.status == "HISTORICAL_ARCHIVE_ONLY"
    assert binding.resolved_path == path.relative_to(root).as_posix()
    assert binding.active_sha256 != digest
    with pytest.raises(ValueError, match="active environment binding mismatch"):
        resolve_environment_binding(root, "uv.lock", digest, allow_archive=False)
    (root / "uv.lock").write_bytes(path.read_bytes())
    assert (
        resolve_environment_binding(root, "uv.lock", digest, allow_archive=False).status
        == "ACTIVE_FILE_MATCH"
    )


@pytest.mark.parametrize("mutation", ["missing", "corrupt", "symlink", "parent_symlink"])
def test_invalid_archives_are_rejected(archive, mutation):
    root, digest, path = archive
    if mutation == "missing":
        path.unlink()
    elif mutation == "corrupt":
        path.write_text("different dependencies")
    elif mutation == "symlink":
        saved = root / "saved"
        path.rename(saved)
        path.symlink_to(saved)
    else:
        saved = root / "saved-directory"
        path.parent.rename(saved)
        path.parent.symlink_to(saved, target_is_directory=True)
    with pytest.raises(ValueError, match=r"missing or corrupt|symlink"):
        resolve_environment_binding(root, "uv.lock", digest)


def test_arbitrary_paths_code_drift_and_project_drift_cannot_use_lock_archive(archive):
    root, digest, _ = archive
    for name in ["../uv.lock", "/uv.lock", "src/code.py", "pyproject.toml"]:
        with pytest.raises(ValueError):
            resolve_environment_binding(root, name, digest)
    with pytest.raises(ValueError, match="invalid environment digest"):
        resolve_environment_binding(root, "uv.lock", "../escape")


def test_active_symlink_cannot_hide_a_changed_execution_environment(archive):
    root, digest, path = archive
    (root / "uv.lock").unlink()
    (root / "uv.lock").symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        resolve_environment_binding(root, "uv.lock", digest)
