"""Regression: the LIVE AlphaMax tick's data phase must never fan out per-ticker.

Why this test exists (2026-08-01). ``scripts/alphamax_tick.sh`` used to run
``af data ingest-equities`` with its DEFAULT ``--corp-actions``, which walks every instrument
id present in the lake (17,541 keys) and issues two vendor REST calls each. On a free-tier key
(5 req/min) that is ~35,000 calls of mostly HTTP 429: the tick launched 2026-07-21T05:00Z did
not return until 2026-08-01T00:56Z. The walk-forward and the broker step sit BELOW the data
phase in the tick, so AlphaMax rebalanced once in 11 days — the sleeve looked dark while a
grinder held its lock.

The fix is a flag on the RUNNING command, so this pins the RUNNING command:

* :func:`test_tick_ingest_command_disables_per_ticker_corp_actions` reads the real tick script
  and asserts the live invocation still carries ``--no-corp-actions`` (and its watchdog).
* :func:`test_tick_argv_never_builds_per_ticker_reference_source` feeds THOSE EXACT ARGV back
  through the real CLI with the per-ticker reference factory booby-trapped, so re-enabling the
  fan-out anywhere on that path fails here.
* :func:`test_control_corp_actions_argv_does_build_reference_source` is the control: the same
  argv with ``--corp-actions`` DOES trip the booby trap, proving the guard can actually see the
  regression it claims to block.

Bars are unaffected: they come from the BULK day-agg path (one object per session, every ticker
inside it), which has no per-ticker fan-out.
"""

from __future__ import annotations

import re
import shlex
from datetime import date
from pathlib import Path

import pytest
from test_polygon_flatfiles import FakeFlatFilesClient, csv_row
from typer.testing import CliRunner

from alphaforge.cli import data_cmds
from alphaforge.cli.data_cmds import data_app
from alphaforge.data.sources.polygon_flatfiles import PolygonFlatFilesSource

TICK = Path(__file__).resolve().parents[2] / "scripts" / "alphamax_tick.sh"

# Deterministic stand-ins for the tick's ``$(date -u ...)`` shell variables, so the argv the
# tick really runs can be replayed against seeded fixture days.
_SHELL_VARS = {"INGEST_START": "2024-01-01", "TOMORROW": "2024-01-05"}

runner = CliRunner()


def _tick_ingest_command() -> str:
    """The tick's ``af data ingest-equities`` invocation, line-continuations joined."""
    lines = TICK.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") or "af data ingest-equities" not in line:
            continue
        chunk, j = line, i
        while chunk.rstrip().endswith("\\"):
            chunk = chunk.rstrip()[:-1]
            j += 1
            chunk += " " + lines[j]
        return chunk
    raise AssertionError(f"no 'af data ingest-equities' invocation found in {TICK}")


def _tick_ingest_argv() -> list[str]:
    """That invocation as CLI argv: shell vars substituted, ``|| echo …`` fallback dropped."""
    cmd = _tick_ingest_command().split("||")[0]
    cmd = cmd[cmd.index("af data ingest-equities") + len("af data ") :]
    for name, value in _SHELL_VARS.items():
        cmd = cmd.replace(f'"${{{name}}}"', value).replace(f"${{{name}}}", value)
    argv = shlex.split(cmd)
    assert not [a for a in argv if "$" in a], f"unsubstituted shell var in tick argv: {argv}"
    return argv


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point lake + var dirs at tmp via env overrides (env layer wins over YAML profiles)."""
    for key, sub in (("AF_PATHS__LAKE_DIR", "lake"), ("AF_PATHS__VAR_DIR", "var")):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(key, str(tmp_path / sub))
    return tmp_path


def _seeded_flatfiles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bulk day-agg source over an in-memory fake (no boto3, no S3, no network)."""
    client = FakeFlatFilesClient()
    for d in (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)):
        client.put_day(d, [csv_row(t, d) for t in ("AAPL", "MSFT")])
    monkeypatch.setattr(
        data_cmds, "_build_flatfiles_source", lambda: PolygonFlatFilesSource(client=client)
    )


def _booby_trap_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make constructing the PER-TICKER reference source an unmistakable failure."""

    def _boom() -> object:
        raise AssertionError("per-ticker reference source constructed on the live tick path")

    monkeypatch.setattr(data_cmds, "_build_equities_reference", _boom)


# ------------------------------------------------------------------ the tick script itself


def test_tick_ingest_command_disables_per_ticker_corp_actions() -> None:
    argv = _tick_ingest_argv()
    assert argv[0] == "ingest-equities", argv  # argv is relative to the `af data` sub-app
    assert "--no-corp-actions" in argv, (
        "the live tick must not run the per-ticker splits/dividends pass "
        f"(~35k rate-limited calls, 10.8 days measured); argv={argv}"
    )
    assert "--corp-actions" not in argv, argv
    # live and research must keep reading the same profile — the sleeve's traded universe
    assert argv[argv.index("--profile") + 1] == "equity", argv


def test_tick_data_phase_is_watchdogged() -> None:
    """An unbounded data phase is what buried the trading steps; the cap must stay."""
    text = TICK.read_text()
    assert re.search(r"^DATA_WATCHDOG_S=\d+", text, re.M), "DATA_WATCHDOG_S must be defined"
    assert 'pkill -TERM -f "data ingest-equities"' in text
    assert 'sleep "${DATA_WATCHDOG_S}"' in text
    # ... and the phase must not be able to abort the tick before the broker step runs.
    assert "WARN: equity bar ingest returned non-zero" in text


# ------------------------------------------------------------------ the running CLI path


def test_tick_argv_never_builds_per_ticker_reference_source(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seeded_flatfiles(monkeypatch)
    _booby_trap_reference(monkeypatch)

    result = runner.invoke(data_app, _tick_ingest_argv())

    assert result.exit_code == 0, result.output
    assert "per-ticker reference source constructed" not in result.output
    assert "corporate-actions:" not in result.output
    assert "ok=3" in result.output  # the bulk bar path still ingested every seeded session


def test_control_corp_actions_argv_does_build_reference_source(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: with the fan-out re-enabled the trap fires, so the guard above has teeth."""
    _seeded_flatfiles(monkeypatch)
    _booby_trap_reference(monkeypatch)
    argv = [a if a != "--no-corp-actions" else "--corp-actions" for a in _tick_ingest_argv()]

    result = runner.invoke(data_app, argv)

    assert result.exit_code != 0
    assert isinstance(result.exception, AssertionError)
    assert "per-ticker reference source constructed" in str(result.exception)
