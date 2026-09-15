"""The forward liquidation collector: payload parsers, atomic day partitions, and the session
record that makes a disconnect a visible gap instead of a quiet market."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import aiohttp
import pandas as pd
from aiohttp import web
from aiohttp.test_utils import TestServer

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "vps" / "collect_liquidations.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("collect_liquidations", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve the script's postponed annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


collector = _load()


def _sessions(root: Path, venue: str) -> list[dict[str, Any]]:
    path = root / "_sessions" / f"{venue}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _rows(root: Path, venue: str) -> pd.DataFrame:
    parts = sorted((root / venue).rglob("*.parquet"))
    if not parts:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(part) for part in parts], ignore_index=True)


async def _fixed(http: aiohttp.ClientSession) -> tuple[list[str], list[str], bool]:
    return [], ["BTCUSDT"], False


def _venue(url: str, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "name": "bybit",
        "url": url,
        "sampling_class": collector.COMPLETE,
        "completeness": "TEST",
        "parse": collector.parse_bybit,
        "subscriptions": _fixed,
        "acknowledged": collector.bybit_acknowledged,
        "app_ping": None,
        "app_ping_every_seconds": 20.0,
    }
    fields.update(overrides)
    return collector.Venue(**fields)


async def _serve(
    handler: Callable[[web.Request], Awaitable[web.WebSocketResponse]],
) -> TestServer:
    app = web.Application()
    app.router.add_get("/ws", handler)
    server = TestServer(app)
    await server.start_server()
    return server


async def _stop_when(stop: asyncio.Event, condition: Callable[[], bool]) -> None:
    for _ in range(500):
        if condition():
            break
        await asyncio.sleep(0.01)
    stop.set()


def test_binance_parser_marks_rows_sampled_and_prefers_the_fill() -> None:
    message = {
        "e": "forceOrder",
        "E": 1789500000100,
        "o": {
            "s": "BTCUSDT",
            "S": "SELL",
            "q": "0.014",
            "p": "59000",
            "ap": "59120.5",
            "z": "0.010",
            "T": 1789500000050,
        },
    }
    [row] = collector.parse_binance(message, 1789500000200, "s1")
    assert row["sampling_class"] == "sampled"
    assert row["symbol"] == "BTCUSDT" and row["side"] == "sell"
    assert row["price"] == 59120.5 and row["quantity"] == 0.010
    assert row["event_ts_ms"] == 1789500000050 and row["push_ts_ms"] == 1789500000100
    assert row["available_at_ms"] == 1789500000200
    assert json.loads(row["raw"])["o"]["s"] == "BTCUSDT"
    assert collector.parse_binance({"e": "aggTrade"}, 1, "s1") == []


def test_bybit_parser_marks_rows_complete_and_keeps_every_item() -> None:
    message = {
        "topic": "allLiquidation.ETHUSDT",
        "ts": 1789500000500,
        "data": [
            {"T": 1789500000000, "s": "ETHUSDT", "S": "Buy", "v": "1.5", "p": "2500.1"},
            {"T": 1789500000400, "s": "ETHUSDT", "S": "Sell", "v": "0.2", "p": "2499.9"},
        ],
    }
    rows = collector.parse_bybit(message, 1789500000900, "s2")
    assert [row["side"] for row in rows] == ["buy", "sell"]
    assert [row["quantity"] for row in rows] == [1.5, 0.2]
    assert {row["sampling_class"] for row in rows} == {"complete"}
    assert {row["push_ts_ms"] for row in rows} == {1789500000500}
    assert collector.parse_bybit({"op": "pong"}, 1, "s2") == []


def test_okx_parser_records_contract_units_and_okx_is_not_collected_by_default() -> None:
    message = {
        "arg": {"channel": "liquidation-orders", "instType": "SWAP"},
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "details": [
                    {"side": "buy", "bkPx": "60010.2", "sz": "3", "ts": "1789500000000"},
                ],
            }
        ],
    }
    [row] = collector.parse_okx(message, 1789500000500, "s3")
    assert row["symbol"] == "BTC-USDT-SWAP" and row["quantity_unit"] == "contracts"
    assert row["quantity"] == 3.0 and row["price"] == 60010.2
    assert collector.parse_okx({"event": "subscribe"}, 1, "s3") == []
    assert "okx" not in {venue.name for venue in collector.VENUES}


def test_writer_partitions_by_event_day_and_never_leaves_a_partial_file(tmp_path: Path) -> None:
    writer = collector.PartitionWriter(tmp_path, "bybit")
    late_on_day_one = 1789516799000  # 2026-09-15T23:59:59Z
    early_on_day_two = 1789516801000  # 2026-09-16T00:00:01Z
    base = {"venue": "bybit", "symbol": "BTCUSDT", "price": 1.0, "quantity": 1.0, "raw": "{}"}
    writer.add(
        [{**base, "event_ts_ms": late_on_day_one}, {**base, "event_ts_ms": early_on_day_two}]
    )
    assert writer.flush() == 2 and writer.pending == 0
    writer.add([{**base, "event_ts_ms": early_on_day_two + 1}])
    assert writer.flush() == 1
    days = sorted(path.name for path in (tmp_path / "bybit").iterdir())
    assert days == ["2026-09-15", "2026-09-16"]
    assert len(list((tmp_path / "bybit" / "2026-09-16").glob("*.parquet"))) == 2
    assert not list(tmp_path.rglob("*.tmp"))
    assert len(_rows(tmp_path, "bybit")) == 3


def test_a_dropped_connection_is_a_closed_session_and_the_collector_reconnects(
    tmp_path: Path,
) -> None:
    connections = 0

    async def handler(request: web.Request) -> web.WebSocketResponse:
        nonlocal connections
        connections += 1
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str(json.dumps({"op": "subscribe", "success": True}))
        if connections == 1:
            event = {"T": 1789500000000, "s": "BTCUSDT", "S": "Sell", "v": "0.5", "p": "60000"}
            await ws.send_str(json.dumps({"topic": "allLiquidation.BTCUSDT", "data": [event]}))
        await ws.close()
        return ws

    async def scenario() -> None:
        server = await _serve(handler)
        stop = asyncio.Event()
        path = tmp_path / "_sessions" / "bybit.jsonl"

        def two_closes() -> bool:
            return path.exists() and path.read_text().count('"event": "close"') >= 2

        async with aiohttp.ClientSession() as http:
            await asyncio.gather(
                collector.run_venue(
                    _venue(str(server.make_url("/ws"))),
                    http,
                    stop,
                    tmp_path,
                    reconnect_delays=(0.02,),
                    flush_seconds=0.0,
                    receive_poll_seconds=0.05,
                ),
                _stop_when(stop, two_closes),
            )
        await server.close()

    asyncio.run(scenario())
    records = _sessions(tmp_path, "bybit")
    closes = [record for record in records if record["event"] == "close"]
    assert records[0]["event"] == "open" and records[0]["sampling_class"] == "complete"
    assert len(closes) >= 2 and connections >= 2
    first = closes[0]
    assert first["reason"].startswith("closed_by_venue") and first["rows"] == 1
    assert first["opened_at_ms"] <= first["acknowledged_at_ms"] <= first["closed_at_ms"]
    assert first["last_message_at_ms"] is not None
    frame = _rows(tmp_path, "bybit")
    assert len(frame) == 1 and frame["session_id"].iloc[0] == first["session_id"]
    assert frame["available_at_ms"].iloc[0] >= first["opened_at_ms"]


def test_pings_go_out_on_schedule_while_the_feed_is_busy(tmp_path: Path) -> None:
    received: list[str] = []

    async def handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        async def push() -> None:
            event = {"T": 1789500000000, "s": "BTCUSDT", "S": "Sell", "v": "0.5", "p": "60000"}
            while not ws.closed:
                await ws.send_str(json.dumps({"topic": "allLiquidation.BTCUSDT", "data": [event]}))
                await asyncio.sleep(0.01)

        pusher = asyncio.create_task(push())
        async for message in ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                received.append(message.data)
        pusher.cancel()
        return ws

    async def scenario() -> None:
        server = await _serve(handler)
        stop = asyncio.Event()
        venue = _venue(str(server.make_url("/ws")), app_ping="ping", app_ping_every_seconds=0.1)
        async with aiohttp.ClientSession() as http:
            await asyncio.gather(
                collector.run_venue(venue, http, stop, tmp_path, receive_poll_seconds=0.02),
                _stop_when(stop, lambda: received.count("ping") >= 3),
            )
        await server.close()

    asyncio.run(scenario())
    assert received.count("ping") >= 3
    assert _sessions(tmp_path, "bybit")[-1]["reason"] == "stopped"


def test_stop_ends_a_quiet_session_promptly_and_records_it(tmp_path: Path) -> None:
    async def handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for _message in ws:
            pass
        return ws

    elapsed = 0.0

    async def scenario() -> None:
        nonlocal elapsed
        server = await _serve(handler)
        stop = asyncio.Event()
        path = tmp_path / "_sessions" / "bybit.jsonl"
        async with aiohttp.ClientSession() as http:
            task = asyncio.create_task(
                collector.run_venue(
                    _venue(str(server.make_url("/ws"))),
                    http,
                    stop,
                    tmp_path,
                    receive_poll_seconds=0.05,
                )
            )
            await _stop_when(stop, lambda: path.exists())
            started = time.monotonic()
            await asyncio.wait_for(task, timeout=5)
            elapsed = time.monotonic() - started
        await server.close()

    asyncio.run(scenario())
    assert elapsed < 1.0
    close = _sessions(tmp_path, "bybit")[-1]
    assert close["event"] == "close" and close["reason"] == "stopped"


def test_collect_cancels_a_venue_stuck_before_it_connects(tmp_path: Path) -> None:
    async def never(http: aiohttp.ClientSession) -> tuple[list[str], list[str], bool]:
        await asyncio.sleep(3600)
        return [], [], False

    async def scenario() -> int:
        stop = asyncio.Event()
        venue = _venue("ws://127.0.0.1:9/ws", subscriptions=never)
        asyncio.get_running_loop().call_later(0.05, stop.set)
        return int(await collector.collect([venue], tmp_path, stop=stop, grace_seconds=0.1))

    started = time.monotonic()
    assert asyncio.run(scenario()) == 0
    assert time.monotonic() - started < 2.0
    close = _sessions(tmp_path, "bybit")[-1]
    assert close["event"] == "close" and close["reason"] == "cancelled"
    assert close["opened_at_ms"] is None


def test_an_unreachable_venue_is_recorded_as_an_attempt_that_never_opened(tmp_path: Path) -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        path = tmp_path / "_sessions" / "bybit.jsonl"
        async with aiohttp.ClientSession() as http:
            await asyncio.gather(
                collector.run_venue(
                    _venue("ws://127.0.0.1:9/ws"), http, stop, tmp_path, reconnect_delays=(0.02,)
                ),
                _stop_when(stop, lambda: path.exists() and '"event": "close"' in path.read_text()),
            )

    asyncio.run(scenario())
    first = _sessions(tmp_path, "bybit")[0]
    assert first["event"] == "close" and first["opened_at_ms"] is None
    assert first["reason"].startswith("connect_failed") and first["rows"] == 0
    assert not (tmp_path / "bybit").exists()
