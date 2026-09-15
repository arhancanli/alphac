#!/usr/bin/env python3
"""Collect crypto forced-liquidation events FORWARD: a record no venue archives.

WHY THIS EXISTS. `crypto_liquidation_pressure` is an atlas family with no point-in-time record
anywhere (scripts/atlas_reachability_screen.py marks it NO_PIT; docs/design/AUTONOMOUS_BACKLOG.md):
venues stream forced liquidations in real time and offer no public history, so a missed hour can
never be recovered. The admission contract needs three years of it before the family can be tested
at all. Every day this does not run is a day the family can never have.

SO THIS MAKES NO CLAIM AND RUNS NO TEST. It accumulates like collect_venues.py and keeps its rules:
  * every row carries `available_at_ms`, the instant this process read it from the socket; research
    must condition on it, never on the venue's own event time, or it reads the future;
  * rows are partitioned by the venue's event date (UTC), so a late delivery lands with its day;
  * part files are written atomically (temporary name, then rename): a crash can lose at most the
    unflushed buffer, never corrupt a written file;
  * one venue failing never takes the other down.

WHAT A GAP LOOKS LIKE. These feeds are silent when nothing is liquidated, so silence is not a gap,
and a disconnected stream records nothing that could be mistaken for calm. Every connection attempt
is written to `_sessions/<venue>.jsonl`: when it opened, when the venue acknowledged the
subscription, when the last message arrived, when and why it closed. A study keeps only the time
inside acknowledged sessions.

WHAT EACH VENUE GIVES (checked against the venues' documentation on 2026-09-15):
  * Bybit `allLiquidation.{symbol}` is COMPLETE: every liquidation on the subscribed symbols. The
    collector subscribes every USDT perpetual and records the list in each session.
  * Binance `!forceOrder@arr` is SAMPLED: at most one order per symbol per second. Its counts and
    volumes are lower bounds; every row says so in `sampling_class`.
  * OKX is parsed but NOT collected by default: its API agreement limits market data to personal,
    non-commercial use without written consent, and this project publishes research.

    /opt/alphaforge/.venv/bin/python collect_liquidations.py
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os
import signal
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
import pandas as pd

OUT = Path(os.environ.get("AF_LIQUIDATIONS_OUT", "/opt/alphaforge/data/lake_liquidations"))
UA = {"User-Agent": "alphaforge-research/1.0"}
FLUSH_SECONDS = 60.0
FLUSH_ROWS = 5_000
RECONNECT_DELAYS: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
# Binance closes every stream connection at 24 hours. Rotating first keeps the close ours, with a
# recorded reason, rather than the venue's.
MAX_SESSION_SECONDS = 23 * 3600.0
CONNECT_TIMEOUT_SECONDS = 30.0
RECEIVE_POLL_SECONDS = 5.0
STOP_GRACE_SECONDS = 20.0
BYBIT_TOPICS_PER_MESSAGE = 10
BYBIT_MAX_ARGS_CHARACTERS = 21_000
SAMPLED = "sampled"
COMPLETE = "complete"

Row = dict[str, Any]
Parser = Callable[[Any, int, str], list[Row]]
Subscriptions = Callable[[aiohttp.ClientSession], Awaitable[tuple[list[str], list[str], bool]]]


def now_ms() -> int:
    return int(time.time() * 1000)


def _raw(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _row(
    venue: str,
    sampling_class: str,
    *,
    symbol: str,
    side: str,
    price: float,
    quantity: float,
    quantity_unit: str,
    event_ts_ms: int,
    push_ts_ms: int | None,
    available_at_ms: int,
    session_id: str,
    raw: Any,
) -> Row:
    return {
        "venue": venue,
        "sampling_class": sampling_class,
        "symbol": symbol,
        "side": side.lower(),
        "price": price,
        "quantity": quantity,
        "quantity_unit": quantity_unit,
        "event_ts_ms": event_ts_ms,
        "push_ts_ms": push_ts_ms,
        "available_at_ms": available_at_ms,
        "session_id": session_id,
        "raw": _raw(raw),
    }


# ----------------------------------------------------------------------------- payload parsers
def parse_binance(message: Any, available_at_ms: int, session_id: str) -> list[Row]:
    """USD-M futures `!forceOrder@arr`: one sampled liquidation order per event."""
    if not isinstance(message, dict) or message.get("e") != "forceOrder":
        return []
    order = message["o"]
    average = float(order.get("ap") or 0.0)
    filled = float(order.get("z") or 0.0)
    return [
        _row(
            "binance",
            SAMPLED,
            symbol=str(order["s"]),
            side=str(order["S"]),
            price=average if average > 0.0 else float(order["p"]),
            quantity=filled if filled > 0.0 else float(order["q"]),
            quantity_unit="base",
            event_ts_ms=int(order["T"]),
            push_ts_ms=int(message["E"]) if "E" in message else None,
            available_at_ms=available_at_ms,
            session_id=session_id,
            raw=message,
        )
    ]


def parse_bybit(message: Any, available_at_ms: int, session_id: str) -> list[Row]:
    """v5 linear `allLiquidation.{symbol}`: every liquidation, a list per push."""
    if not isinstance(message, dict) or not str(message.get("topic", "")).startswith(
        "allLiquidation."
    ):
        return []
    pushed = int(message["ts"]) if "ts" in message else None
    return [
        _row(
            "bybit",
            COMPLETE,
            symbol=str(item["s"]),
            side=str(item["S"]),
            price=float(item["p"]),
            quantity=float(item["v"]),
            quantity_unit="base",
            event_ts_ms=int(item["T"]),
            push_ts_ms=pushed,
            available_at_ms=available_at_ms,
            session_id=session_id,
            raw=item,
        )
        for item in message.get("data") or []
    ]


def parse_okx(message: Any, available_at_ms: int, session_id: str) -> list[Row]:
    """v5 public `liquidation-orders` (SWAP). `sz` is in contracts, not base units."""
    arg = message.get("arg") if isinstance(message, dict) else None
    if not isinstance(arg, dict) or arg.get("channel") != "liquidation-orders":
        return []
    return [
        _row(
            "okx",
            SAMPLED,
            symbol=str(instrument["instId"]),
            side=str(detail["side"]),
            price=float(detail["bkPx"]),
            quantity=float(detail["sz"]),
            quantity_unit="contracts",
            event_ts_ms=int(detail["ts"]),
            push_ts_ms=None,
            available_at_ms=available_at_ms,
            session_id=session_id,
            raw={"instId": instrument["instId"], **detail},
        )
        for instrument in message.get("data") or []
        for detail in instrument.get("details") or []
    ]


def bybit_acknowledged(message: Any) -> bool:
    return (
        isinstance(message, dict)
        and message.get("op") == "subscribe"
        and bool(message.get("success"))
    )


def okx_acknowledged(message: Any) -> bool:
    return isinstance(message, dict) and message.get("event") == "subscribe"


def never_acknowledged(message: Any) -> bool:
    return False


# ------------------------------------------------------------------------------ subscriptions
async def binance_subscriptions(http: aiohttp.ClientSession) -> tuple[list[str], list[str], bool]:
    """The stream name in the URL covers every symbol; nothing to send."""
    return [], ["*"], False


async def okx_subscriptions(http: aiohttp.ClientSession) -> tuple[list[str], list[str], bool]:
    message = {"op": "subscribe", "args": [{"channel": "liquidation-orders", "instType": "SWAP"}]}
    return [json.dumps(message)], ["SWAP:*"], False


async def bybit_subscriptions(http: aiohttp.ClientSession) -> tuple[list[str], list[str], bool]:
    """Every USDT perpetual, most liquid first. If the venue's documented argument limit would be
    exceeded the least liquid symbols are left out and the session says so (`truncated`)."""
    url = "https://api.bybit.com/v5/market/tickers?category=linear"
    async with http.get(url, timeout=aiohttp.ClientTimeout(total=25)) as response:
        payload = await response.json(content_type=None)
    tickers = [
        row
        for row in ((payload or {}).get("result") or {}).get("list") or []
        if str(row.get("symbol", "")).endswith("USDT")
    ]
    tickers.sort(key=lambda row: float(row.get("turnover24h") or 0.0), reverse=True)
    symbols: list[str] = []
    characters = 0
    truncated = False
    for row in tickers:
        topic = f"allLiquidation.{row['symbol']}"
        cost = len(json.dumps(topic)) + 1
        if characters + cost > BYBIT_MAX_ARGS_CHARACTERS:
            truncated = True
            break
        symbols.append(str(row["symbol"]))
        characters += cost
    if not symbols:
        raise RuntimeError("bybit tickers returned no USDT linear symbols")
    topics = [f"allLiquidation.{symbol}" for symbol in symbols]
    messages = [
        json.dumps({"op": "subscribe", "args": topics[start : start + BYBIT_TOPICS_PER_MESSAGE]})
        for start in range(0, len(topics), BYBIT_TOPICS_PER_MESSAGE)
    ]
    return messages, symbols, truncated


@dataclass(frozen=True)
class Venue:
    name: str
    url: str
    sampling_class: str
    completeness: str
    parse: Parser
    subscriptions: Subscriptions
    acknowledged: Callable[[Any], bool] = never_acknowledged
    app_ping: str | None = None
    app_ping_every_seconds: float = 20.0


BINANCE = Venue(
    name="binance",
    url="wss://fstream.binance.com/market/ws/!forceOrder@arr",
    sampling_class=SAMPLED,
    completeness="SAMPLED: at most one liquidation order per symbol per second",
    parse=parse_binance,
    subscriptions=binance_subscriptions,
)
BYBIT = Venue(
    name="bybit",
    url="wss://stream.bybit.com/v5/public/linear",
    sampling_class=COMPLETE,
    completeness="COMPLETE_FOR_SUBSCRIBED_SYMBOLS: allLiquidation pushes every liquidation",
    parse=parse_bybit,
    subscriptions=bybit_subscriptions,
    acknowledged=bybit_acknowledged,
    app_ping=json.dumps({"op": "ping"}),
    app_ping_every_seconds=20.0,
)
# Parsed and tested, but not in VENUES: the OKX API agreement limits market data to personal,
# non-commercial use without written consent. Add it only after consent is recorded in
# config/data_source_rights_policy.json.
OKX = Venue(
    name="okx",
    url="wss://ws.okx.com:8443/ws/v5/public",
    sampling_class=SAMPLED,
    completeness="SAMPLED: at most one liquidation order per contract per second (unverified)",
    parse=parse_okx,
    subscriptions=okx_subscriptions,
    acknowledged=okx_acknowledged,
    app_ping="ping",
    app_ping_every_seconds=25.0,
)
VENUES: tuple[Venue, ...] = (BYBIT, BINANCE)


# ----------------------------------------------------------------------------------- storage
class PartitionWriter:
    """Buffers rows and writes them as atomic part files under <root>/<venue>/<event date>/."""

    def __init__(self, root: Path, venue: str) -> None:
        self._directory = root / venue
        self._buffer: list[Row] = []
        self._sequence = 0

    @property
    def pending(self) -> int:
        return len(self._buffer)

    def add(self, rows: Sequence[Row]) -> None:
        self._buffer.extend(rows)

    def flush(self) -> int:
        if not self._buffer:
            return 0
        frame = pd.DataFrame(self._buffer)
        self._buffer = []
        days = pd.to_datetime(frame["event_ts_ms"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
        written = 0
        for day, part in frame.groupby(days):
            directory = self._directory / str(day)
            directory.mkdir(parents=True, exist_ok=True)
            self._sequence += 1
            name = f"part-{now_ms()}-{os.getpid()}-{self._sequence:06d}.parquet"
            temporary = directory / f".{name}.tmp"
            part.to_parquet(temporary, index=False)
            os.replace(temporary, directory / name)
            written += len(part)
        return written


class SessionLog:
    """Append-only, fsynced record of every connection attempt: the collector's own gap map."""

    def __init__(self, root: Path, venue: str) -> None:
        self._path = root / "_sessions" / f"{venue}.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


# ---------------------------------------------------------------------------------- the loop
async def _receive(
    venue: Venue,
    ws: aiohttp.ClientWebSocketResponse,
    stop: asyncio.Event,
    writer: PartitionWriter,
    session_id: str,
    state: dict[str, Any],
    *,
    max_session_seconds: float,
    flush_seconds: float,
    receive_poll_seconds: float,
) -> str:
    started = time.monotonic()
    last_flush = started
    last_ping = started
    while True:
        if stop.is_set():
            return "stopped"
        now = time.monotonic()
        if now - started >= max_session_seconds:
            return "scheduled_rotation"
        # Pings go out on a schedule, not only when the feed is quiet: a venue that drops idle
        # clients counts our pings, not its own pushes.
        if venue.app_ping is not None and now - last_ping >= venue.app_ping_every_seconds:
            await ws.send_str(venue.app_ping)
            last_ping = now
        try:
            message: aiohttp.WSMessage | None = await ws.receive(timeout=receive_poll_seconds)
        except TimeoutError:
            message = None
        if message is not None:
            if message.type == aiohttp.WSMsgType.TEXT:
                received = now_ms()
                state["messages"] += 1
                state["last_message_at_ms"] = received
                if message.data != "pong":
                    try:
                        payload = json.loads(message.data)
                        if state["acknowledged_at_ms"] is None and venue.acknowledged(payload):
                            state["acknowledged_at_ms"] = received
                        rows = venue.parse(payload, received, session_id)
                    except (ValueError, KeyError, TypeError):
                        state["parse_errors"] += 1
                        rows = []
                    if rows:
                        writer.add(rows)
                        state["rows"] += len(rows)
            elif message.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                return f"closed_by_venue: code {ws.close_code}"
            elif message.type == aiohttp.WSMsgType.ERROR:
                return f"websocket_error: {ws.exception()}"
        now = time.monotonic()
        if now - last_flush >= flush_seconds or writer.pending >= FLUSH_ROWS:
            writer.flush()
            last_flush = now


async def run_venue(
    venue: Venue,
    http: aiohttp.ClientSession,
    stop: asyncio.Event,
    root: Path,
    *,
    reconnect_delays: Sequence[float] = RECONNECT_DELAYS,
    max_session_seconds: float = MAX_SESSION_SECONDS,
    flush_seconds: float = FLUSH_SECONDS,
    receive_poll_seconds: float = RECEIVE_POLL_SECONDS,
) -> None:
    writer = PartitionWriter(root, venue.name)
    sessions = SessionLog(root, venue.name)
    failures = 0
    while not stop.is_set():
        attempt_at = now_ms()
        session_id = f"{venue.name}-{attempt_at}-{os.getpid()}"
        state: dict[str, Any] = {
            "messages": 0,
            "rows": 0,
            "parse_errors": 0,
            "acknowledged_at_ms": None,
            "last_message_at_ms": None,
        }
        opened_at: int | None = None
        reason = "connect_failed"
        try:
            messages, symbols, truncated = await asyncio.wait_for(
                venue.subscriptions(http), timeout=CONNECT_TIMEOUT_SECONDS
            )
            # No protocol-level heartbeat: Bybit and OKX do not answer PING frames and would be
            # dropped for it. Binance pings us, and autoping answers.
            ws = await asyncio.wait_for(
                http.ws_connect(venue.url, heartbeat=None, autoping=True),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
            async with ws:
                for text in messages:
                    await ws.send_str(text)
                opened_at = now_ms()
                sessions.write(
                    {
                        "event": "open",
                        "session_id": session_id,
                        "venue": venue.name,
                        "url": venue.url,
                        "sampling_class": venue.sampling_class,
                        "completeness": venue.completeness,
                        "symbols": symbols,
                        "truncated": truncated,
                        "opened_at_ms": opened_at,
                    }
                )
                failures = 0
                reason = await _receive(
                    venue,
                    ws,
                    stop,
                    writer,
                    session_id,
                    state,
                    max_session_seconds=max_session_seconds,
                    flush_seconds=flush_seconds,
                    receive_poll_seconds=receive_poll_seconds,
                )
        except asyncio.CancelledError:
            reason = "cancelled"
            raise
        except Exception as error:  # a venue failing must never take the other down
            stage = reason if opened_at is None else "session_error"
            reason = f"{stage}: {type(error).__name__}: {str(error)[:160]}"
        finally:
            writer.flush()
            sessions.write(
                {
                    "event": "close",
                    "session_id": session_id,
                    "venue": venue.name,
                    "attempted_at_ms": attempt_at,
                    "opened_at_ms": opened_at,
                    "closed_at_ms": now_ms(),
                    "reason": reason,
                    **state,
                }
            )
        if stop.is_set():
            break
        delay = reconnect_delays[min(failures, len(reconnect_delays) - 1)]
        failures += 1
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)


async def collect(
    venues: Sequence[Venue],
    root: Path,
    *,
    stop: asyncio.Event | None = None,
    grace_seconds: float = STOP_GRACE_SECONDS,
) -> int:
    """Run every venue until stopped. A venue task that ends on its own is a defect: the process
    exits non-zero so systemd restarts it, and the restart is a recorded gap."""
    if stop is None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=20.0, sock_read=None)
    async with aiohttp.ClientSession(headers=UA, timeout=timeout) as http:
        tasks = [asyncio.create_task(run_venue(venue, http, stop, root)) for venue in venues]
        stopped = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({stopped, *tasks}, return_when=asyncio.FIRST_COMPLETED)
        ended_early = [task for task in done if task is not stopped]
        stop.set()
        _, pending = await asyncio.wait(tasks, timeout=grace_seconds)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        stopped.cancel()
    return 1 if ended_early else 0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC)
    print(f"=== liquidation collector start {started:%Y-%m-%dT%H:%M:%SZ} out={OUT} ===", flush=True)
    code = asyncio.run(collect(VENUES, OUT))
    stopped = dt.datetime.now(dt.UTC)
    print(
        f"=== liquidation collector stop {stopped:%Y-%m-%dT%H:%M:%SZ} code={code} ===", flush=True
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
