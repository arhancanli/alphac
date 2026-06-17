"""CLI tests for ``af data ingest-equities`` (offline, tmp_path only, no network/live lake).

The command is exercised through typer's :class:`CliRunner` against the REAL
:class:`~alphaforge.data.ingest.equities.EquitiesFlatFilesJob` + :class:`LakeWriter` +
:class:`CheckpointStore`, but its two network seams are monkeypatched to fakes:

* ``_build_flatfiles_source`` → a :class:`PolygonFlatFilesSource` backed by the in-memory
  :class:`FakeFlatFilesClient` (synthetic fixture day-aggs CSVs; no boto3, no S3).
* ``_build_equities_reference`` → a :class:`PolygonEquitiesSource` over the
  ``test_polygon_source.FakeClient`` (canned splits/dividends; no httpx).

Paths are steered to ``tmp_path`` via ``AF_PATHS__LAKE_DIR`` / ``AF_PATHS__VAR_DIR`` env
overrides so nothing touches ./data or ./var.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from test_polygon_flatfiles import FakeFlatFilesClient, csv_row
from typer.testing import CliRunner

from alphaforge.cli import data_cmds
from alphaforge.cli.data_cmds import data_app
from alphaforge.data.sources.polygon_flatfiles import PolygonFlatFilesSource

runner = CliRunner()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point lake + var dirs at tmp via env overrides (env layer wins over YAML)."""
    lake = tmp_path / "lake"
    var = tmp_path / "var"
    lake.mkdir(parents=True, exist_ok=True)
    var.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AF_PATHS__LAKE_DIR", str(lake))
    monkeypatch.setenv("AF_PATHS__VAR_DIR", str(var))
    return tmp_path


def _patch_source(monkeypatch: pytest.MonkeyPatch, client: FakeFlatFilesClient) -> None:
    """Replace the flat-files source factory with a fake-client-backed source."""
    monkeypatch.setattr(
        data_cmds,
        "_build_flatfiles_source",
        lambda: PolygonFlatFilesSource(client=client),
    )


def _seed_days(client: FakeFlatFilesClient, days: list[date], tickers: list[str]) -> None:
    for d in days:
        client.put_day(d, [csv_row(t, d) for t in tickers])


# --------------------------------------------------------------------------- happy path


def test_ingest_exit_zero_and_report(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeFlatFilesClient()
    days = [date(2024, 1, 2), date(2024, 1, 3)]
    _seed_days(client, days, ["AAPL", "MSFT"])
    _patch_source(monkeypatch, client)

    result = runner.invoke(
        data_app,
        [
            "ingest-equities",
            "--start",
            "2024-01-01",
            "--until",
            "2024-01-05",
            "--no-corp-actions",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "ingest-equities" in result.output
    assert "ok=2" in result.output
    assert "2024-01-02" in result.output


def test_resume_message_on_second_invocation(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeFlatFilesClient()
    _seed_days(client, [date(2024, 1, 2), date(2024, 1, 3)], ["AAPL"])
    _patch_source(monkeypatch, client)
    args = [
        "ingest-equities",
        "--start",
        "2024-01-01",
        "--until",
        "2024-01-05",
        "--no-corp-actions",
    ]
    first = runner.invoke(data_app, args)
    assert first.exit_code == 0, first.output

    second = runner.invoke(data_app, args)
    assert second.exit_code == 0, second.output
    assert "skipped (already ingested)" in second.output


# --------------------------------------------------------------------------- failure


def test_failed_day_exits_one(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_polygon_flatfiles import make_day_csv_raw

    from alphaforge.data.sources.polygon_flatfiles import day_aggs_key

    client = FakeFlatFilesClient()
    good = date(2024, 1, 2)
    bad = date(2024, 1, 3)
    client.put_day(good, [csv_row("AAPL", good)])
    # malformed body (non-numeric volume) -> SchemaError on that day -> failed, exit 1
    client.put_raw(
        day_aggs_key(bad),
        make_day_csv_raw(
            "ticker,volume,open,close,high,low,window_start,transactions\nAAPL,bad,1,1,1,1,1,1\n"
        ),
    )
    _patch_source(monkeypatch, client)

    result = runner.invoke(
        data_app,
        [
            "ingest-equities",
            "--start",
            "2024-01-01",
            "--until",
            "2024-01-05",
            "--no-corp-actions",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "failed" in result.output


# --------------------------------------------------------------------------- max-tickers warn


def test_max_tickers_warning_emitted(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeFlatFilesClient()
    d = date(2024, 1, 2)
    client.put_day(
        d,
        [
            csv_row("AAPL", d, close=100.0, volume=3_000.0),
            csv_row("MSFT", d, close=100.0, volume=1_000.0),
        ],
    )
    _patch_source(monkeypatch, client)

    result = runner.invoke(
        data_app,
        [
            "ingest-equities",
            "--start",
            "2024-01-01",
            "--until",
            "2024-01-05",
            "--max-tickers",
            "1",
            "--no-corp-actions",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "NON-survivorship-safe" in result.output


# --------------------------------------------------------------------------- missing creds


def test_missing_credentials_exits_one(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No injected source + no env creds -> the source factory raises ConfigError -> exit 1."""
    for var in (
        "POLYGON_S3_ENDPOINT",
        "POLYGON_S3_ACCESS_KEY_ID",
        "POLYGON_S3_SECRET_ACCESS_KEY",
        "POLYGON_S3_BUCKET",
    ):
        monkeypatch.delenv(var, raising=False)
    # Do NOT patch the source factory: the real _build_flatfiles_source() runs and the
    # PolygonFlatFilesSource constructor raises ConfigError with no client and no env.
    result = runner.invoke(
        data_app,
        ["ingest-equities", "--start", "2024-01-01", "--no-corp-actions"],
    )
    assert result.exit_code == 1, result.output
    assert "error:" in result.output


# --------------------------------------------------------------------------- corp-actions step


def test_corp_actions_step_runs(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With --corp-actions (default), the per-instrument splits/dividends pass runs over the
    ids just ingested, using a monkeypatched reference adapter (no httpx)."""
    from test_polygon_source import FakeClient, dividend_row, split_row

    client = FakeFlatFilesClient()
    d = date(2024, 1, 2)
    client.put_day(d, [csv_row("AAPL", d)])
    _patch_source(monkeypatch, client)

    # The reference adapter keys splits/dividends by the vendor ticker. The flat-files id for
    # "AAPL" resolves back to ticker "AAPL" via parse_equity_id, so the reference fetch for
    # that id queries ticker "AAPL".
    ref_client = FakeClient(
        splits={"AAPL": [split_row("2024-06-07", split_from=1, split_to=4)]},
        dividends={"AAPL": [dividend_row("2024-02-09", cash_amount=0.24)]},
    )
    from alphaforge.data.sources.polygon_source import PolygonEquitiesSource

    monkeypatch.setattr(
        data_cmds,
        "_build_equities_reference",
        lambda: PolygonEquitiesSource(client=ref_client),
    )

    result = runner.invoke(
        data_app,
        ["ingest-equities", "--start", "2024-01-01", "--until", "2024-01-05"],
    )
    assert result.exit_code == 0, result.output
    assert "corporate-actions:" in result.output
    assert "instruments=1" in result.output
