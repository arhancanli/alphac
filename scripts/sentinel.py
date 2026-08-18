#!/usr/bin/env python3
"""Read-only, 24/7 operational sentinel for the AlphaForge VPS.

The sentinel observes the artifacts the system actually consumes.  It never imports a broker,
places an order, changes a timer, edits signed history, heals state, or calls an external service.
Its only optional write is an atomic JSON status file under ``var/sentinel``; failures exit 2 so
systemd/journald can page or retain evidence independently of any trading process.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
HOURLY_WARN_H = 1.75
HOURLY_FAIL_H = 3.0
DAILY_WARN_H = 30.0
DAILY_FAIL_H = 54.0


def _age_hours(epoch_ms: int, now: dt.datetime) -> float:
    return (now.timestamp() * 1000.0 - epoch_ms) / 3_600_000.0


def _status_for_age(age: float | None, warn_h: float, fail_h: float) -> str:
    if age is None or age < 0 or age > fail_h:
        return "FAIL"
    return "PASS" if age <= warn_h else "WARN"


def _sqlite_row(path: Path, query: str) -> tuple[Any, ...] | None:
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    try:
        return con.execute(query).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _latest_file(directory: Path, pattern: str) -> Path | None:
    files = [p for p in directory.glob(pattern) if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _timer_active(name: str) -> tuple[bool, str]:
    proc = subprocess.run(
        ["systemctl", "is-active", name], capture_output=True, text=True, timeout=5, check=False
    )
    observed = (proc.stdout or proc.stderr).strip() or f"exit={proc.returncode}"
    return proc.returncode == 0 and observed == "active", observed


def _check(
    check_id: str,
    status: str,
    observed: str,
    expected: str,
    *,
    evidence: str = "",
) -> dict[str, str]:
    return {
        "id": check_id,
        "status": status,
        "observed": observed,
        "expected": expected,
        "evidence": evidence,
    }


def collect(root: Path, *, now: dt.datetime | None = None) -> dict[str, Any]:
    """Collect one read-only sentinel snapshot."""
    now = now or dt.datetime.now(dt.UTC)
    checks: list[dict[str, str]] = []

    for timer in (
        "af-trade.timer",
        "af-collect.timer",
        "af-ingest.timer",
        "af-venues.timer",
        "af-deribit.timer",
    ):
        active, observed = _timer_active(timer)
        checks.append(_check(f"timer:{timer}", "PASS" if active else "FAIL", observed, "active"))

    trading_db = root / "var" / "trading_crypto_perp.sqlite"
    row = _sqlite_row(
        trading_db,
        "SELECT cycle_ts,status FROM cycles ORDER BY cycle_ts DESC LIMIT 1",
    )
    if row and isinstance(row[0], int | float):
        cycle_age = _age_hours(int(row[0]), now)
        checks.append(
            _check(
                "crypto-cycle-freshness",
                _status_for_age(cycle_age, HOURLY_WARN_H, HOURLY_FAIL_H),
                f"{cycle_age:.2f}h",
                f"<={HOURLY_WARN_H}h",
                evidence=str(trading_db),
            )
        )
        checks.append(
            _check(
                "crypto-cycle-status",
                "PASS" if row[1] == "ok" else "FAIL",
                str(row[1]),
                "ok",
                evidence=str(trading_db),
            )
        )
    else:
        checks.append(
            _check("crypto-cycle-freshness", "FAIL", "unreadable/empty", "recent cycle")
        )

    maker_db = root / "var" / "maker_shadow.sqlite"
    maker = _sqlite_row(maker_db, "SELECT MAX(ts) FROM quotes WHERE method_version >= 2")
    maker_ts = maker[0] if maker else None
    maker_age = _age_hours(int(maker_ts), now) if isinstance(maker_ts, int | float) else None
    checks.append(
        _check(
            "maker-shadow-freshness",
            _status_for_age(maker_age, HOURLY_WARN_H, HOURLY_FAIL_H),
            f"{maker_age:.2f}h" if maker_age is not None else "unreadable/empty",
            f"<={HOURLY_WARN_H}h",
            evidence=str(maker_db),
        )
    )

    deribit = _latest_file(root / "data" / "deribit" / "snapshots", "snap_*.jsonl")
    deribit_age = (
        (now.timestamp() - deribit.stat().st_mtime) / 3600.0 if deribit is not None else None
    )
    checks.append(
        _check(
            "deribit-freshness",
            _status_for_age(deribit_age, DAILY_WARN_H, DAILY_FAIL_H),
            f"{deribit_age:.2f}h" if deribit_age is not None else "no snapshots",
            f"<={DAILY_WARN_H}h",
            evidence=str(deribit or ""),
        )
    )

    disk = shutil.disk_usage(root)
    free_pct = disk.free / disk.total * 100.0
    free_gib = disk.free / 1024**3
    disk_status = "FAIL" if free_pct < 5 or free_gib < 2 else "WARN" if free_pct < 10 else "PASS"
    checks.append(
        _check(
            "disk-headroom",
            disk_status,
            f"{free_gib:.1f} GiB / {free_pct:.1f}% free",
            ">=10% and >=2 GiB",
            evidence=str(root),
        )
    )

    kill = root / "var" / "KILL"
    checks.append(
        _check(
            "kill-switch",
            "WARN" if kill.exists() else "PASS",
            "ENGAGED" if kill.exists() else "clear",
            "clear or intentionally engaged",
            evidence=str(kill),
        )
    )

    counts = {
        status.lower(): sum(c["status"] == status for c in checks)
        for status in ("PASS", "WARN", "FAIL")
    }
    overall = "FAIL" if counts["fail"] else "WARN" if counts["warn"] else "PASS"
    return {
        "schema": "alphaforge.sentinel.v1",
        "generated_at": now.isoformat(),
        "root": str(root),
        "overall": overall,
        "counts": counts,
        "checks": checks,
        "mutations_permitted": ["own_status_file"],
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    payload = collect(args.root.resolve())
    if args.json_out:
        _write_atomic(args.json_out, payload)
    print(json.dumps(payload, separators=(",", ":")))
    return 2 if payload["overall"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
