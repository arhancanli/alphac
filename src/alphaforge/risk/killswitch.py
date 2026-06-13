"""Kill-switch — a sentinel FILE, deliberately dumb (execDesign §7.3).

Ops contract:
    The switch IS the file. ``touch var/KILL`` from any shell (any SSH
    session, no Python, no DB, no AlphaForge import) engages it; the live
    loop checks :meth:`KillSwitch.engaged` at cycle start and again
    immediately before every order submission, so the system halts on the
    next cycle at the latest (Phase 7 wires the loop). A file survives DB
    corruption, process crashes, and broken venv upgrades — exactly the
    scenarios in which you most need the brake to work.

    Disengaging is intentionally NOT symmetric: :meth:`disengage` exists for
    the CLI ``arm`` flow (typed confirmation + audit row, wired by the
    auditor/Phase 7), and nothing in the trading path ever calls it. The
    machine can stop itself; only a human restarts it.

The file's content (timestamp, pid, reason — appended, never truncated, so a
double-engage preserves the first cause) is for the post-mortem human;
engagement is decided by EXISTENCE alone, so a zero-byte ``touch`` works.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["KillSwitch"]


class KillSwitch:
    """File-existence kill-switch. Pure filesystem, no other state."""

    __slots__ = ("_path",)

    def __init__(self, sentinel_path: Path) -> None:
        self._path = sentinel_path

    @property
    def path(self) -> Path:
        """The sentinel file location (conventionally ``var/KILL``)."""
        return self._path

    def engaged(self) -> bool:
        """True iff the sentinel file exists — the single source of truth."""
        return self._path.exists()

    def engage(self, reason: str) -> None:
        """Engage: write the sentinel with a ``ts=... pid=... reason=...``
        audit line (appended if already engaged — first cause preserved)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(tz=UTC).isoformat()
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(f"ts={ts} pid={os.getpid()} reason={reason}\n")

    def disengage(self) -> None:
        """Remove the sentinel (idempotent). ONLY the audited CLI ``arm``
        flow calls this — never the trading loop (see module docstring)."""
        self._path.unlink(missing_ok=True)
