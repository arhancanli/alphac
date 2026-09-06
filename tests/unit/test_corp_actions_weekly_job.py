"""Regression: corporate actions run WEEKLY, in their own job, and never inside a trading tick.

Why this test exists (2026-08-02). Two failures, one on each side of the same knob, bracket this:

* Corp-actions ON inside the daily tick: ``ingest-equities`` defaults to ``--corp-actions``, a
  per-ticker pass over every instrument id in the lake (17,937 today, two vendor REST calls each).
  On the vendor's free tier that walled at 5 req/min and the tick launched 2026-07-21T05:00Z did
  not return until 2026-08-01T00:56Z — 10.8 days for ONE rebalance, because the walk-forward and
  the broker step sit BELOW the data phase in ``scripts/alphamax_tick.sh``.
* Corp-actions OFF everywhere: a split announced after ~2026-07 is never ingested, and a reverse
  split marked at raw prices is precisely the ALIT bug — a fabricated -4.95% day, -1.45% of real
  loss leaked into the record, and a falsely tripped -10% drawdown brake that halved the book for
  a week.

The resolution is structural, not a tuning choice: the daily tick keeps ``--no-corp-actions``
(trading must never block on a vendor) and ``scripts/corp_actions_weekly.sh`` runs the pass on its
own weekly systemd timer. Both halves are load-bearing, so both are pinned here — and pinned on the
RUNNING command, not on a comment:

* :func:`test_weekly_script_runs_the_corp_actions_path` and
  :func:`test_daily_tick_still_disables_the_corp_actions_path` read the two real scripts.
* :func:`test_weekly_argv_actually_ingests_corporate_actions` replays the weekly script's EXACT
  argv through the real CLI and asserts split rows land in the lake.
* :func:`test_daily_tick_argv_never_reaches_the_corp_actions_path` replays the daily tick's EXACT
  argv with the per-ticker reference factory booby-trapped, so re-enabling the fan-out on the
  trading path fails here.
* :func:`test_weekly_job_contains_no_trading_step` and
  :func:`test_no_trading_tick_invokes_the_weekly_job` pin the separation itself: the vendor crawl
  has nothing sequenced behind it and nothing sequences it behind a trade.
* :func:`test_weekly_job_never_writes_the_api_key_to_a_log` pins the two things the first live run
  of this script exposed: the vendor request lines carry the API key, and a redactor in a pipeline
  silently swallows the ingest's exit status unless ``pipefail`` is set.
"""

from __future__ import annotations

import re
import shlex
from datetime import date
from pathlib import Path

import pyarrow.dataset as ds
import pytest
from test_polygon_flatfiles import FakeFlatFilesClient, csv_row
from typer.testing import CliRunner

from alphaforge.cli import data_cmds
from alphaforge.cli.data_cmds import data_app
from alphaforge.data.sources.polygon_flatfiles import PolygonFlatFilesSource

REPO = Path(__file__).resolve().parents[2]
WEEKLY = REPO / "scripts" / "corp_actions_weekly.sh"
DAILY_TICK = REPO / "scripts" / "alphamax_tick.sh"
UNIT_SERVICE = REPO / "deploy" / "systemd" / "alphaforge-corpactions.service"
UNIT_TIMER = REPO / "deploy" / "systemd" / "alphaforge-corpactions.timer"

# Deterministic stand-ins for each script's ``$(date -u ...)`` shell variables, so the argv the
# scripts really run can be replayed against seeded fixture days.
_WEEKLY_VARS = {"TODAY": "2024-01-05"}
_DAILY_VARS = {"INGEST_START": "2024-01-01", "TOMORROW": "2024-01-05"}

runner = CliRunner()


# --------------------------------------------------------------------- argv extraction helpers


def _ingest_command(script: Path) -> str:
    """The script's ``af data ingest-equities`` invocation, line-continuations joined."""
    lines = script.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") or "af data ingest-equities" not in line:
            continue
        chunk, j = line, i
        while chunk.rstrip().endswith("\\"):
            chunk = chunk.rstrip()[:-1]
            j += 1
            chunk += " " + lines[j]
        return chunk
    raise AssertionError(f"no 'af data ingest-equities' invocation found in {script}")


#: Shell tokens that end the command proper — everything from here on is plumbing (pipes,
#: redirects, the non-fatal ``|| echo`` fallback), not argv.
_END_OF_ARGV = re.compile(r"^(\|\|?|&&|;|\d*>>?|\d*>&\d*)$")


def _ingest_argv(script: Path, shell_vars: dict[str, str]) -> list[str]:
    """That invocation as CLI argv: shell vars substituted, pipes/redirects/``|| …`` dropped."""
    cmd = _ingest_command(script)
    cmd = cmd[cmd.index("af data ingest-equities") + len("af data ") :]
    for name, value in shell_vars.items():
        cmd = cmd.replace(f'"${{{name}}}"', value).replace(f"${{{name}}}", value)
    argv: list[str] = []
    for token in shlex.split(cmd):
        if _END_OF_ARGV.match(token):
            break
        argv.append(token)
    assert not [a for a in argv if "$" in a], f"unsubstituted shell var in argv: {argv}"
    return argv


def _weekly_argv() -> list[str]:
    return _ingest_argv(WEEKLY, _WEEKLY_VARS)


def _daily_argv() -> list[str]:
    return _ingest_argv(DAILY_TICK, _DAILY_VARS)


# ----------------------------------------------------------------------------------- fixtures


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


def _seed_lake_with_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populate the tmp lake's ``ohlcv_1d`` ids — the id set the corp-actions pass walks."""
    _seeded_flatfiles(monkeypatch)
    result = runner.invoke(
        data_app,
        [
            "ingest-equities",
            "--start",
            "2024-01-01",
            "--until",
            "2024-01-05",
            "--profile",
            "equity",
            "--no-corp-actions",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "ok=3" in result.output, result.output


def _fake_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reference adapter over canned splits/dividends (no httpx): AAPL 1:4, MSFT 1:10 reverse."""
    from test_polygon_source import FakeClient, dividend_row, split_row

    from alphaforge.data.sources.polygon_source import PolygonEquitiesSource

    ref_client = FakeClient(
        splits={
            "AAPL": [split_row("2024-06-07", split_from=1, split_to=4)],
            "MSFT": [split_row("2024-06-14", split_from=10, split_to=1)],
        },
        dividends={"AAPL": [dividend_row("2024-02-09", cash_amount=0.24)]},
    )
    monkeypatch.setattr(
        data_cmds, "_build_equities_reference", lambda: PolygonEquitiesSource(client=ref_client)
    )


def _booby_trap_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make constructing the PER-TICKER reference source an unmistakable failure."""

    def _boom() -> object:
        raise AssertionError("per-ticker reference source constructed on the live tick path")

    monkeypatch.setattr(data_cmds, "_build_equities_reference", _boom)


# --------------------------------------------------------------------- the two scripts, as text


def test_weekly_script_runs_the_corp_actions_path() -> None:
    argv = _weekly_argv()
    assert argv[0] == "ingest-equities", argv  # argv is relative to the `af data` sub-app
    assert "--corp-actions" in argv, (
        "the weekly job is the ONLY place splits/dividends are ingested; without this flag a "
        f"new split is never seen and the ALIT phantom-mark bug returns; argv={argv}"
    )
    assert "--no-corp-actions" not in argv, argv
    # Same profile as the live sleeve, or the actions land in a lake nothing trades off.
    assert argv[argv.index("--profile") + 1] == "equity", argv
    # Bar window is deliberately EMPTY (start == until => available_sessions() returns []), so this
    # job is corp-actions ONLY and can never compete with the daily tick for bar ingest work.
    assert argv[argv.index("--start") + 1] == argv[argv.index("--until") + 1], argv


def test_daily_tick_still_disables_the_corp_actions_path() -> None:
    """The other half of the fix: moving the pass out is only safe if it stays out."""
    argv = _daily_argv()
    assert argv[0] == "ingest-equities", argv
    assert "--no-corp-actions" in argv, (
        "the daily trading tick must never run the per-ticker splits/dividends pass "
        f"(10.8 days measured for one rebalance); argv={argv}"
    )
    assert "--corp-actions" not in argv, argv


def test_weekly_job_is_watchdogged_and_single_runner() -> None:
    text = WEEKLY.read_text()
    assert re.search(r"^CA_WATCHDOG_S=(\d+)", text, re.M), "CA_WATCHDOG_S must be defined"
    assert 'pkill -TERM -f "ingest-equities.*--corp-actions"' in text
    assert 'sleep "${CA_WATCHDOG_S}"' in text
    assert 'LOCK="var/locks/corp_actions_weekly.lock"' in text, "single-runner lock required"
    assert "var/log/corp_actions_weekly.log" in text, "the pass must be logged"
    # Non-fatal posture: a vendor failure logs and exits clean, it never wedges the unit.
    assert "WARN: corp-actions ingest returned non-zero" in text


def test_weekly_job_never_writes_the_api_key_to_a_log() -> None:
    """The transcript must be redacted, and the redactor must not swallow a failed ingest.

    The corp-actions path is httpx-based and the shared logging config logs every request line at
    INFO **with its query string**, which carries ``apiKey=<live Polygon key>``. A ~36,000-call
    weekly pass would otherwise write the credential to disk 36,000 times. The transcript is
    therefore piped through a redactor — and because a pipeline's exit status is its LAST stage,
    ``setopt pipefail`` is what keeps the non-fatal WARN branch reachable when the ingest fails
    (verified: without it, ``(exit 3) | sed`` reports success).
    """
    text = WEEKLY.read_text()
    redact = re.search(r"^REDACT='([^']+)'", text, re.M)
    assert redact, "the transcript must be piped through an apiKey redactor"
    assert '| sed -E "${REDACT}"' in text, "the redactor must be applied to the ingest output"
    assert re.search(r"^setopt pipefail", text, re.M), (
        "without pipefail the redactor's exit status masks a failed ingest and the WARN branch "
        "never fires — a silent green log is how the sleeve went dark for 11 days"
    )
    # The substitution really redacts a key-shaped query parameter.
    body = re.match(r"s/(.+)/(.+)/g$", redact.group(1))
    assert body, redact.group(1)
    pattern, replacement = body.group(1), body.group(2)
    sample = "GET /v3/reference/splits?ticker=AAPL&apiKey=V678RGw3lvpxfhBMzH01lvClpog9Am_p HTTP/1.1"
    scrubbed = re.sub(pattern, replacement, sample)
    assert "V678RGw3" not in scrubbed, scrubbed
    assert "apiKey=REDACTED" in scrubbed, scrubbed


def test_weekly_watchdog_cannot_reach_the_daily_tick() -> None:
    """The watchdog's pkill pattern must not match the trading tick's ingest command line.

    ``pkill -f`` matches an ERE against the whole command line. A loose pattern (e.g. plain
    ``data ingest-equities``) would let this job's 6-hour watchdog terminate the daily tick's bar
    ingest if the two ever overlapped — reintroducing by the back door exactly the coupling this
    split-out job removes.
    """
    text = WEEKLY.read_text()
    pattern = re.search(r'pkill -TERM -f "([^"]+)"', text).group(1)  # type: ignore[union-attr]
    weekly_cmdline = "uv run af data " + " ".join(_weekly_argv())
    daily_cmdline = "uv run af data " + " ".join(_daily_argv())
    assert re.search(pattern, weekly_cmdline), (pattern, weekly_cmdline)
    assert not re.search(pattern, daily_cmdline), (
        f"watchdog pattern {pattern!r} also matches the DAILY tick's ingest "
        f"({daily_cmdline!r}) — it could kill the trading tick's data phase"
    )


def test_weekly_job_contains_no_trading_step() -> None:
    """Nothing may be sequenced behind the vendor crawl — that ordering is what caused the stall."""
    text = WEEKLY.read_text()
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    for forbidden in (
        "live_cycle.py",
        "research walkforward",
        "paper_trading_state.py",
        "mf_gauntlet.py",
        "vercel",
    ):
        assert forbidden not in body, (
            f"{forbidden!r} must not run in the weekly corp-actions job: a trading or publish "
            "step below a multi-hour vendor crawl is the exact failure this job was split out of"
        )


def test_no_trading_tick_invokes_the_weekly_job() -> None:
    """...and symmetrically, no tick may call this job inline and inherit its runtime."""
    scripts = sorted((REPO / "scripts").glob("*.sh"))
    assert len(scripts) >= 10, (
        f"only {len(scripts)} shell scripts found — the glob has stopped matching and every "
        "assertion below it would pass without checking anything"
    )
    for script in scripts:
        if script == WEEKLY:
            continue
        assert "corp_actions_weekly" not in script.read_text(), (
            f"{script.name} invokes the weekly corp-actions job inline — it must stay on its own "
            "timer so no trading path can ever block on the vendor"
        )


# ------------------------------------------------------------------------------ the systemd pair


def test_weekly_systemd_units_are_weekly_and_persistent() -> None:
    service = UNIT_SERVICE.read_text()
    timer = UNIT_TIMER.read_text()

    assert "ExecStart=" in service and "scripts/corp_actions_weekly.sh" in service, service
    assert "Type=oneshot" in service, service
    assert "Persistent=true" in timer, "a skipped week is a week of un-ingested splits"

    oncalendar = re.search(r"^OnCalendar=(.+)$", timer, re.M)
    assert oncalendar, timer
    assert (
        oncalendar.group(1)
        .strip()
        .startswith(("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "weekly"))
    ), f"the corp-actions timer must be WEEKLY, got OnCalendar={oncalendar.group(1)!r}"

    # systemd must not pre-empt the script's own bounded shutdown.
    watchdog_s = int(re.search(r"^CA_WATCHDOG_S=(\d+)", WEEKLY.read_text(), re.M).group(1))  # type: ignore[union-attr]
    timeout_s = int(re.search(r"^TimeoutStartSec=(\d+)", service, re.M).group(1))  # type: ignore[union-attr]
    assert timeout_s > watchdog_s, (
        f"TimeoutStartSec={timeout_s}s must exceed the script watchdog {watchdog_s}s"
    )


# --------------------------------------------------------------------------- the running CLI path


def test_weekly_argv_actually_ingests_corporate_actions(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The weekly script's EXACT argv must reach the corp-actions pass and write split rows."""
    _seed_lake_with_bars(monkeypatch)
    _fake_reference(monkeypatch)

    result = runner.invoke(data_app, _weekly_argv())

    assert result.exit_code == 0, result.output
    # the bar phase did nothing (empty window) — this job is corp-actions only
    assert "ok=0 failed=0 skipped=0 rows=0" in result.output, result.output
    # ...and the corp-actions phase walked both seeded ids and wrote their actions
    assert "corporate-actions: instruments=2" in result.output, result.output
    written = re.search(r"corporate-actions: instruments=2 actions=(\d+)", result.output)
    assert written and int(written.group(1)) >= 3, result.output

    # The rows are really in the lake, including the reverse split that caused the ALIT bug.
    table = ds.dataset(repo / "lake" / "corporate_actions", format="parquet").to_table()
    ratios = table.column("ratio").to_pylist()
    assert 0.1 in ratios, f"the 10:1 reverse split did not land: {ratios}"


def test_daily_tick_argv_never_reaches_the_corp_actions_path(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control on the other side: the tick's argv must not construct the per-ticker source."""
    _seeded_flatfiles(monkeypatch)
    _booby_trap_reference(monkeypatch)

    result = runner.invoke(data_app, _daily_argv())

    assert result.exit_code == 0, result.output
    assert "per-ticker reference source constructed" not in result.output
    assert "corporate-actions:" not in result.output
    assert "ok=3" in result.output  # the bulk bar path still ingested every seeded session


def test_weekly_argv_without_the_flag_would_ingest_nothing(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: strip ``--corp-actions`` from the weekly argv and the job becomes a no-op.

    Proves the assertions above have teeth — the flag, not some incidental side effect, is what
    makes this job the thing that keeps splits in the lake.
    """
    _seed_lake_with_bars(monkeypatch)
    _booby_trap_reference(monkeypatch)
    argv = [a if a != "--corp-actions" else "--no-corp-actions" for a in _weekly_argv()]

    result = runner.invoke(data_app, argv)

    assert result.exit_code == 0, result.output
    assert "corporate-actions:" not in result.output
    assert not (repo / "lake" / "corporate_actions").exists(), "no actions should have been written"
