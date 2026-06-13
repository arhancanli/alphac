"""Unit tests for alphaforge.risk.killswitch — sentinel-file lifecycle.

All paths under tmp_path; engagement is decided by file EXISTENCE alone (a
zero-byte external ``touch`` must engage), content is audit-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from alphaforge.risk import KillSwitch


class TestKillSwitch:
    def test_lifecycle(self, tmp_path: Path) -> None:
        sentinel = tmp_path / "var" / "KILL"
        ks = KillSwitch(sentinel)
        assert ks.path == sentinel
        assert not ks.engaged()

        ks.engage("dd_tier2")
        assert ks.engaged()
        assert sentinel.exists()

        ks.disengage()
        assert not ks.engaged()
        assert not sentinel.exists()

    def test_engage_writes_audit_line(self, tmp_path: Path) -> None:
        ks = KillSwitch(tmp_path / "KILL")
        ks.engage("reconciliation divergence")
        content = (tmp_path / "KILL").read_text(encoding="utf-8")
        assert "reason=reconciliation divergence" in content
        assert f"pid={os.getpid()}" in content
        assert "ts=" in content

    def test_double_engage_preserves_first_cause(self, tmp_path: Path) -> None:
        ks = KillSwitch(tmp_path / "KILL")
        ks.engage("first")
        ks.engage("second")
        lines = (tmp_path / "KILL").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert "reason=first" in lines[0]
        assert "reason=second" in lines[1]

    def test_external_touch_engages(self, tmp_path: Path) -> None:
        # Ops contract: `touch var/KILL` from any shell halts the loop —
        # a zero-byte file with no content must count as engaged.
        sentinel = tmp_path / "KILL"
        ks = KillSwitch(sentinel)
        sentinel.touch()
        assert ks.engaged()

    def test_disengage_idempotent(self, tmp_path: Path) -> None:
        ks = KillSwitch(tmp_path / "KILL")
        ks.disengage()  # nothing to remove; must not raise
        assert not ks.engaged()

    def test_engage_creates_parent_dirs(self, tmp_path: Path) -> None:
        ks = KillSwitch(tmp_path / "deep" / "nested" / "KILL")
        ks.engage("manual")
        assert ks.engaged()
