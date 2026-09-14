import http.client
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import urllib.error
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import macro_refresh_transport as transport  # noqa: E402
import stage_macro_vintage_refresh as stage  # noqa: E402


def load_seal():
    spec = importlib.util.spec_from_file_location(
        "seal_test", ROOT / "scripts/seal_alphavintage_rtdsm_portable_fetch.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Tests must not connect to the network")

    monkeypatch.setattr(socket.socket, "connect", fail)


def table():
    return pd.DataFrame(
        {
            "obs_period": pd.to_datetime(["2019-01-01", "2019-02-01"]),
            "vintage_date": pd.to_datetime(["2019-03-15", "2019-03-15"]),
            "value": [100.0, float("nan")],
        }
    )


def sealed(tmp_path):
    module = load_seal()
    frame = table()
    lake = tmp_path / "lake"
    lake.mkdir()
    frame.to_parquet(lake / "PCPI_vintage_long.parquet", index=False)
    hashed = module._fetch_module()._table_content_hash(frame)
    doc = {
        "status": "PASS",
        "execution": {"vintage_cutoff_inclusive": "2019-03-15"},
        "source_bindings": {
            "portable_fetcher": {
                "path": "scripts/fetch_rtdsm_cpi_portable.py",
                "sha256": module._sha256(ROOT / "scripts/fetch_rtdsm_cpi_portable.py"),
            }
        },
        "comparisons": [
            {"series": "PCPI", "local_table_content_hash": hashed, "rows_local_at_cutoff": 2}
        ],
        "fresh_source_manifest": {
            "records": [
                {
                    "series": "PCPI",
                    "normalized_table_content_hash": hashed,
                    "rows": 2,
                    "first_observation": "2019-01-01",
                    "last_observation": "2019-02-01",
                }
            ]
        },
    }
    doc["content_hash"] = module._content_hash(doc)
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(doc))
    return module, receipt, lake, frame


@pytest.mark.parametrize(
    "value,passes", [(float("nan"), True), (0.0, False), (101.0, False), (float("inf"), False)]
)
def test_historical_domain_extension(tmp_path, value, passes):
    module, receipt, lake, frame = sealed(tmp_path)
    extension = pd.DataFrame(
        {
            "obs_period": [pd.Timestamp("2019-03-01")],
            "vintage_date": [pd.Timestamp("2019-03-15")],
            "value": [value],
        }
    )
    pd.concat([frame, extension]).to_parquet(lake / "PCPI_vintage_long.parquet", index=False)
    original_receipt = receipt.read_bytes()
    if passes:
        assert module.validate_published(receipt, lake)["status"] == "PASS"
    else:
        with pytest.raises(RuntimeError, match="Populated CPI cell"):
            module.validate_published(receipt, lake)
    assert receipt.read_bytes() == original_receipt


@pytest.mark.parametrize(
    "mutation",
    ["value", "fill_blank", "remove_blank", "duplicate", "missing_date", "tamper_receipt"],
)
def test_receipt_stays_fail_closed(tmp_path, mutation):
    module, receipt, lake, frame = sealed(tmp_path)
    if mutation == "value":
        frame.loc[0, "value"] = 99.0
    if mutation == "fill_blank":
        frame.loc[1, "value"] = 101.0
    if mutation == "remove_blank":
        frame = frame.iloc[:1]
    if mutation == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]])
    if mutation == "missing_date":
        frame.loc[0, "obs_period"] = pd.NaT
    if mutation == "tamper_receipt":
        receipt.write_text(receipt.read_text().replace('"PASS"', '"OTHER"'))
    frame.to_parquet(lake / "PCPI_vintage_long.parquet", index=False)
    with pytest.raises(RuntimeError):
        module.validate_published(receipt, lake)


def make_source(path):
    (path / "tier2_vintage").mkdir(parents=True)
    for name in stage.SERIES:
        table().to_parquet(path / f"tier2_vintage/{name}_vintage_long.parquet", index=False)
    (path / "arrival_log.jsonl").write_text('{"existing":true}\n')
    return path


def candidate_runner(mutation=None):
    def run(args, **kwargs):
        candidate = Path(args[-1])
        for relative in stage.required_files():
            p = candidate / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith(".parquet"):
                table().to_parquet(p, index=False)
            else:
                p.write_bytes(b"fixture workbook: parsing tested separately")
        if mutation == "changed_value":
            d = table()
            d.loc[0, "value"] = 102.0
            d.to_parquet(candidate / "tier2_vintage/PCPI_vintage_long.parquet", index=False)
        if mutation == "empty":
            table().iloc[:0].to_parquet(
                candidate / "tier2_vintage/PCPI_vintage_long.parquet", index=False
            )
        files = {
            str(p.relative_to(candidate)): stage.digest(p)[:16]
            for p in candidate.rglob("*.parquet")
        }
        (candidate / "meta.json").write_text(json.dumps({"files": files}))
        if mutation == "missing":
            (candidate / "tier2_vintage/PCPIX_first_release.parquet").unlink()
        if mutation == "bad_hash":
            files["tier2_vintage/PCPI_vintage_long.parquet"] = "0" * 16
            (candidate / "meta.json").write_text(json.dumps({"files": files}))
        return subprocess.CompletedProcess(args, 0, "fixture only", "")

    return run


@pytest.mark.parametrize("mutation", [None, "changed_value", "empty", "missing", "bad_hash"])
def test_candidate_is_never_promoted(tmp_path, mutation):
    source = make_source(tmp_path / "source")
    before = stage.inventory(source)
    report = stage.stage(source, tmp_path / "candidates", runner=candidate_runner(mutation))
    assert report["status"] == (
        "READY_FOR_REVIEW_NOT_PROMOTED" if mutation is None else "QUARANTINED"
    )
    assert report["source_unchanged"] and not report["production_promoted"]
    assert stage.inventory(source) == before
    assert Path(report["report_path"]).is_file()
    assert not (Path(report["candidate"]) / "arrival_log.jsonl").exists()


@pytest.mark.parametrize("failure", ["disconnect", "timeout", "concurrent"])
def test_failed_build_preserves_last_good_source(tmp_path, failure):
    source = make_source(tmp_path / "source")
    before = stage.inventory(source)

    def run(args, **kwargs):
        (Path(args[-1]) / "partial-download").write_bytes(b"partial")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        if failure == "concurrent":
            (source / "arrival_log.jsonl").write_text("external writer\n")
        return subprocess.CompletedProcess(args, 1, "", "RemoteDisconnected fixture")

    report = stage.stage(source, tmp_path / "candidates", runner=run)
    assert report["status"] == "QUARANTINED" and not report["production_promoted"]
    assert Path(report["candidate"], "partial-download").exists()
    if failure != "concurrent":
        assert stage.inventory(source) == before
    else:
        assert not report["source_unchanged"]


def test_source_cannot_be_candidate_destination(tmp_path):
    source = make_source(tmp_path / "source")
    for destination in [source, source / "nested", tmp_path]:
        with pytest.raises(ValueError):
            stage.stage(source, destination)


def test_historical_comparison_handles_missing_values():
    old = table()
    assert stage.compare_series(old, old)["passes"]
    new = pd.concat(
        [
            old,
            pd.DataFrame(
                {
                    "obs_period": [pd.Timestamp("2019-03-01")],
                    "vintage_date": [pd.Timestamp("2019-03-15")],
                    "value": [float("nan")],
                }
            ),
        ]
    )
    assert stage.compare_series(old, new)["passes"]
    new.iloc[-1, new.columns.get_loc("value")] = 0.0
    assert not stage.compare_series(old, new)["passes"]


@pytest.mark.parametrize("kind", ["disconnect_then_ok", "timeout", "429", "503", "404", "parse"])
def test_retry_is_bounded(monkeypatch, kind):
    calls = []
    sleeps = []
    monkeypatch.setattr(transport.time, "sleep", sleeps.append)

    def open_url(*args, **kwargs):
        calls.append(1)
        if kind == "disconnect_then_ok":
            if len(calls) < 3:
                raise http.client.RemoteDisconnected("fixture")
            return io.BytesIO(b"complete")
        if kind == "timeout":
            raise TimeoutError("fixture")
        if kind == "parse":
            raise ValueError("not a transport error")
        raise urllib.error.HTTPError("https://example.test", int(kind), "fixture", {}, None)

    monkeypatch.setattr(transport.urllib.request, "urlopen", open_url)
    if kind == "disconnect_then_ok":
        assert transport.get("https://example.test") == b"complete"
    else:
        with pytest.raises((TimeoutError, urllib.error.HTTPError, ValueError)):
            transport.get("https://example.test")
    attempts = 1 if kind in ["404", "parse"] else 3
    assert len(calls) == attempts and len(sleeps) == attempts - 1


def test_real_builder_with_archived_workbooks_and_fixture_daily_data(tmp_path, monkeypatch):
    """Exercise real paths/parsers, with network forbidden and no new data acquired."""
    import shutil

    archive_setting = os.environ.get("ALPHAC_MACRO_REPLAY_ARCHIVE")
    if not archive_setting:
        pytest.skip("Optional archived replay: set ALPHAC_MACRO_REPLAY_ARCHIVE")
    archive = Path(archive_setting).resolve()
    assert archive.is_dir(), "Explicit replay archive must exist"
    source = tmp_path / "source"
    (source / "tier2_vintage").mkdir(parents=True)
    for name in stage.SERIES:
        relative = f"tier2_vintage/{name}_vintage_long.parquet"
        shutil.copy2(ROOT / "data/lake_macro_vintage" / relative, source / relative)
    builder = stage.load_builder()
    registry = {entry[0]: entry[1] for entry in builder.TIER2.values()}

    def archived_get(url, timeout=60):
        if "fredgraph.csv" in url:
            return b"DATE,VALUE\n2026-09-01,1.0\n2026-09-02,1.1\n"
        if url.endswith(".xlsx"):
            return (archive / url.rsplit("/", 1)[-1]).read_bytes()
        variable = url.rsplit("/", 1)[-1]
        return f'<a href="/-/media/{registry[variable]}">source fixture</a>'.encode()

    monkeypatch.setattr(transport, "get", archived_get)

    def run(args, **kwargs):
        rc = stage.build_into(Path(args[-1]))
        return subprocess.CompletedProcess(
            args, rc, "Archived workbook integration; daily data synthetic", ""
        )

    report = stage.stage(source, tmp_path / "candidates", runner=run)
    assert report["status"] == "READY_FOR_REVIEW_NOT_PROMOTED", report
    assert report["source_unchanged"] and not report["production_promoted"]
    assert len(report["series"]) == 7
    # Keep the aggregate result, not a manufactured fresh-acquisition claim.
    saved = {
        "status": report["status"],
        "series": report["series"],
        "source_unchanged": report["source_unchanged"],
        "network_used": False,
        "daily_data": "SYNTHETIC_FIXTURE",
        "rtdsm": "ARCHIVED_WORKBOOKS",
        "production_promoted": False,
    }
    (tmp_path / "archived-build-test.json").write_text(json.dumps(saved, indent=2) + "\n")


def test_scheduled_tick_is_staging_only():
    tick = (ROOT / "scripts/macro_vintage_tick.sh").read_text()
    assert "scripts/stage_macro_vintage_refresh.py" in tick
    assert "scripts/refresh_macro_vintage.py" not in tick
    assert "--source-lake" in tick and "--output-parent" in tick
    assert "NOT PROMOTED" in tick


def test_source_inventory_failure_quarantines_candidate(tmp_path, monkeypatch):
    source = make_source(tmp_path / "source")
    original = stage.inventory
    calls = 0

    def inventory(path):
        nonlocal calls
        if path == source:
            calls += 1
            if calls == 2:
                raise FileNotFoundError("Concurrent source removal fixture")
        return original(path)

    monkeypatch.setattr(stage, "inventory", inventory)
    report = stage.stage(source, tmp_path / "candidates", runner=candidate_runner())
    assert report["status"] == "QUARANTINED"
    assert not report["source_unchanged"] and not report["production_promoted"]
    assert "source_inventory_error" in report
    assert Path(report["report_path"]).is_file()
