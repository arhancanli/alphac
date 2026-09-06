"""The health monitor must run under the interpreter launchd actually starts it with.

2026-09-06: ``check_crypto_rebalance`` (added the day before) called ``dt.UTC``, an
attribute that exists from Python 3.11. ``com.accapital.health.plist`` starts the monitor
with ``/usr/bin/python3``, which on this machine is 3.9. The 03:10 run raised
``AttributeError`` inside ``check_loops()`` before writing a status, sending an alert, or
touching the Supabase keep-alive, so the night's monitoring simply did not happen. The
suite could not see it: every test here loads ``health_check.py`` under the project venv
(3.12), where the attribute exists.

Two guards. The first executes the module and the check that broke under the interpreter
the plist names, so any construct that interpreter lacks (attribute, syntax, stdlib
module) fails here before it fails at 03:10. The second is a static scan for the exact
attribute, so CI (which has no plist) still catches the known class.
"""

from __future__ import annotations

import ast
import json
import plistlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
HEALTH_PY = _ROOT / "scripts" / "health_check.py"
PLIST = Path.home() / "Library" / "LaunchAgents" / "com.accapital.health.plist"


def _launchd_interpreter() -> str:
    if not PLIST.exists():
        pytest.skip(f"{PLIST} absent: not the machine that runs the monitor")
    with PLIST.open("rb") as fh:
        args = plistlib.load(fh)["ProgramArguments"]
    assert args[1] == str(HEALTH_PY), args
    return args[0]


_CHILD = textwrap.dedent(
    """
    import importlib.util, json, sqlite3, sys
    spec = importlib.util.spec_from_file_location("hc_under_launchd", sys.argv[1])
    hc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hc)
    db = sys.argv[2]
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE cycles (cycle_ts INTEGER PRIMARY KEY, started_ms INTEGER, "
        "finished_ms INTEGER, status TEXT, detail TEXT)"
    )
    now = int(hc.NOW.timestamp() * 1000)
    hour = 3_600_000
    last_book = now - 37 * 24 * hour
    rows = [(ts, "ok", "hold: no target change") for ts in range(now - 40 * 24 * hour, now, hour)]
    rows = [r for r in rows if r[0] != last_book]
    rows.append((last_book, "ok", "orders=15 filled=15 partial=0 rejected=0 skipped_replay=0"))
    failed = last_book + 5 * 168 * hour  # two days ago, on the weekly grid
    rows = [r for r in rows if r[0] != failed]
    rows.append((failed, "failed", "KeyError: instrument unknown"))
    con.executemany("INSERT INTO cycles VALUES (?, ?, ?, ?, ?)",
                    [(ts, ts, ts + 1000, st, d) for ts, st, d in rows])
    con.commit(); con.close()
    hc.CRYPTO_DB = db
    hc.RESULTS = []
    hc.check_crypto_rebalance()
    print(json.dumps({"python": sys.version.split()[0],
                      "ids": sorted(r["id"] for r in hc.RESULTS),
                      "statuses": {r["id"]: r["status"] for r in hc.RESULTS}}))
    """
)


def test_the_check_that_broke_runs_under_the_launchd_interpreter(tmp_path: Path) -> None:
    interpreter = _launchd_interpreter()
    proc = subprocess.run(
        [interpreter, "-c", _CHILD, str(HEALTH_PY), str(tmp_path / "crypto.sqlite")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, (
        f"health_check.py does not run under {interpreter} (the interpreter launchd starts "
        f"it with)\n--- stderr ---\n{proc.stderr[-2000:]}"
    )
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["ids"] == ["C6f-crypto-rebalance", "C6g-crypto-failed-cycles"], out
    assert out["statuses"]["C6f-crypto-rebalance"] == "FAIL", out
    assert out["statuses"]["C6g-crypto-failed-cycles"] == "FAIL", out


def test_the_launchd_interpreter_is_older_than_the_venv_so_the_guard_has_teeth() -> None:
    """If the plist ever points at the venv, the first test proves nothing new; say so."""
    interpreter = _launchd_interpreter()
    proc = subprocess.run(
        [interpreter, "-c", "import sys; print(sys.version_info[:2])"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    launchd_version = tuple(int(x) for x in proc.stdout.strip("() \n").split(", "))
    assert launchd_version <= sys.version_info[:2], (launchd_version, sys.version_info[:2])


def test_no_datetime_utc_attribute_in_health_check() -> None:
    """``datetime.UTC`` is 3.11+. The monitor's own convention is ``dt.timezone.utc``."""
    tree = ast.parse(HEALTH_PY.read_text(), filename=str(HEALTH_PY))
    hits = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "UTC"
        and isinstance(node.value, ast.Name)
        and node.value.id in {"dt", "datetime"}
    ]
    assert hits == [], f"datetime.UTC used at lines {hits}; use dt.timezone.utc (3.9-safe)"
