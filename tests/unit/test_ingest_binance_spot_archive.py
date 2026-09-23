"""Spot klines land in their own lake, stamped spot, with archive gaps recorded and resumable."""

from __future__ import annotations

import importlib.util
import io
import json
import zipfile
from pathlib import Path

import httpx
import pyarrow.dataset as ds

from alphaforge.core.types import MarketType
from alphaforge.data.sources.vision import BinanceVisionClient
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.writer import LakeWriter

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "ingest_binance_spot_archive_under_test", ROOT / "scripts" / "ingest_binance_spot_archive.py"
)
assert _spec and _spec.loader
ingest_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest_mod)

H1 = 3_600_000
JAN_2021 = 1_609_459_200_000


def _zip(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.csv", csv_text)
    return buf.getvalue()


def _row(ts: int) -> str:
    return f"{ts},100,101,99,100.5,10,{ts + H1 - 1},1000,42,5,500,0"


def _spot_client(requests: list[str]) -> BinanceVisionClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("-2021-01.zip"):
            return httpx.Response(
                200, content=_zip("\n".join(_row(JAN_2021 + i * H1) for i in range(3)))
            )
        return httpx.Response(404)  # 2021-02 absent from the archive

    return BinanceVisionClient(
        http=httpx.Client(transport=httpx.MockTransport(handler)), market=MarketType.SPOT
    )


def test_spot_rows_land_in_their_own_lake_with_gaps_recorded_and_resume(tmp_path: Path) -> None:
    lake = tmp_path / "lake_spot"
    progress = lake / "_ingest" / "progress.json"
    requests: list[str] = []
    counts = ingest_mod.ingest(
        ["BTCUSDT"],
        [(2021, 1), (2021, 2)],
        spot=_spot_client(requests),
        writer=LakeWriter(LakePaths(lake)),
        progress_path=progress,
    )
    assert counts == {"written": 1, "rows": 3, "gaps": 1, "skipped": 0}
    assert all(path.startswith("/data/spot/monthly/klines/BTCUSDT/") for path in requests)

    rows = ds.dataset(lake / "ohlcv", format="parquet", partitioning="hive").to_table()
    assert set(rows.column("instrument_id").to_pylist()) == {"BINANCE:SPOT:BTCUSDT"}
    assert rows.num_rows == 3
    recorded = json.loads(progress.read_text())
    assert recorded["done"]["BTCUSDT"] == ["2021-01"]
    assert recorded["gaps"]["BTCUSDT"] == ["2021-02"]

    again: list[str] = []
    counts = ingest_mod.ingest(
        ["BTCUSDT"],
        [(2021, 1), (2021, 2)],
        spot=_spot_client(again),
        writer=LakeWriter(LakePaths(lake)),
        progress_path=progress,
    )
    assert counts == {"written": 0, "rows": 0, "gaps": 0, "skipped": 2}
    assert again == []


def test_the_spot_lake_is_not_the_main_lake() -> None:
    assert ingest_mod.LAKE == ROOT / "data" / "lake_spot"
    assert ingest_mod.months("2020-11", "2021-02") == [(2020, 11), (2020, 12), (2021, 1), (2021, 2)]
