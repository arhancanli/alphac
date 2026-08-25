"""Both public domains must deploy from one immutable publication snapshot."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "scripts/lib/site_snapshot.sh"
DEPLOY_PATHS = (
    REPO / "scripts/live_deploy_hourly.sh",
    REPO / "scripts/live_publish.sh",
)


def _project(root: Path, name: str) -> Path:
    project = root / name
    (project / ".vercel").mkdir(parents=True)
    (project / ".vercel/project.json").write_text('{"projectId":"test"}\n')
    (project / "public/glassbox").mkdir(parents=True)
    (project / "public/glassbox/evidence.json").write_text('{"status":"PASS"}\n')
    for excluded in ("artifacts", "node_modules", "dist", ".next", ".git", ".bak"):
        (project / excluded).mkdir()
        (project / excluded / "ignored.txt").write_text(excluded)
    (project / ".vercel/ignored.txt").write_text("derived")
    return project


@pytest.mark.parametrize("shell", ["zsh", "bash"])
def test_snapshot_is_executable_and_copies_only_deployable_sources(
    shell: str, tmp_path: Path
) -> None:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is unavailable")
    landing = _project(tmp_path, "landing")
    application = _project(tmp_path, "application")
    snapshot_parent = tmp_path / "canli-publish.test"
    environment = os.environ | {
        "SITE_LANDING_SOURCE": str(landing),
        "SITE_APP_SOURCE": str(application),
    }
    command = (
        f'. "{HELPER}"; site_snapshot_create "{snapshot_parent}"; '
        'printf "%s\\n%s\\n" "$SITE_SNAPSHOT_ROOT" "$SITE_SNAPSHOT_HASH"'
    )
    result = subprocess.run(
        [shell, "-c", command], capture_output=True, text=True, env=environment, check=False
    )
    assert result.returncode == 0, result.stderr or result.stdout
    lines = result.stdout.strip().splitlines()
    snapshot_root = Path(lines[-2])
    assert len(lines[-1]) == 64
    for name in ("meridian", "meridian-app"):
        copied = snapshot_root / name
        assert (copied / "public/glassbox/evidence.json").exists()
        assert (copied / ".vercel/project.json").exists()
        assert not (copied / ".vercel/ignored.txt").exists()
        for excluded in ("artifacts", "node_modules", "dist", ".next", ".git", ".bak"):
            assert not (copied / excluded).exists()


def test_source_hash_tracks_served_files_but_not_unserved_root_receipts(tmp_path: Path) -> None:
    landing = _project(tmp_path, "landing")
    application = _project(tmp_path, "application")
    environment = os.environ | {
        "SITE_LANDING_SOURCE": str(landing),
        "SITE_APP_SOURCE": str(application),
    }

    def digest() -> str:
        result = subprocess.run(
            ["zsh", "-c", f'. "{HELPER}"; site_source_hash'],
            capture_output=True,
            text=True,
            env=environment,
            check=True,
        )
        return result.stdout.strip()

    original = digest()
    (landing / "artifacts/ignored.txt").write_text("changed receipt")
    assert digest() == original
    (landing / "public/glassbox/evidence.json").write_text('{"status":"FAIL_CLOSED"}\n')
    assert digest() != original


@pytest.mark.parametrize("script", DEPLOY_PATHS, ids=lambda path: path.name)
def test_every_production_path_deploys_and_announces_the_frozen_snapshot(script: Path) -> None:
    source = script.read_text()
    assert "scripts/lib/site_snapshot.sh" in source
    assert 'site_snapshot_create "$SNAPSHOT_TEMP"' in source
    assert 'deploy_prod "$SITE_SNAPSHOT_ROOT/meridian"' in source
    assert 'deploy_prod "$SITE_SNAPSHOT_ROOT/meridian-app"' in source
    assert 'indexnow_submit "$SITE_SNAPSHOT_ROOT/meridian"' in source
    assert 'deploy_prod "$HOME/meridian"' not in source
    assert 'deploy_prod "$HOME/meridian-app"' not in source


def test_cleanup_refuses_broad_or_unexpected_targets(tmp_path: Path) -> None:
    unexpected = tmp_path / "keep-me"
    unexpected.mkdir()
    result = subprocess.run(
        ["zsh", "-c", f'. "{HELPER}"; site_snapshot_cleanup "{unexpected}"'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert unexpected.exists()
