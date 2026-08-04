"""AlpacaBroker — a real :class:`~alphaforge.execution.broker.Broker` over Alpaca's REST API.

This is what turns the equity / managed-futures-ETF sleeves from walk-forward SIMULATIONS into a
genuine broker-executed paper record (the red-team's #1 gap). It implements the same synchronous
Broker surface the live loop programs against, so the loop never knows it is talking to Alpaca
rather than the PaperBroker. Built on httpx (already a dep) — no Alpaca SDK.

Paper vs live is the base URL alone (``APCA_API_BASE_URL`` = https://paper-api.alpaca.markets for
paper). Credentials come from ~/.config/alphaforge/alpaca.env (chmod 600), never hard-coded.

Idempotency (the crash-recovery backbone): Alpaca natively dedupes on ``client_order_id`` — a
duplicate submit returns 422 'client_order_id must be unique'. :meth:`submit` catches that, fetches
the existing order, and returns its ack verbatim, so a crash between submit and persist can never
double-order. ``fetch_order`` queries by client_order_id, so the recovery path can re-discover a
fill that landed during a crash window.

Equity ids map ``XUSE:CASH:SPYUSD`` <-> Alpaca ``SPY``. Paper commissions are $0 (fee_quote=0).
Order books for equities are top-of-book (Alpaca's latest NBBO quote) — a single bid/ask level,
enough for the loop's reference/slippage logging (real fills come from Alpaca, not a walked book).
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any, Final

import httpx

from alphaforge.core.symbols import EQUITY_MIC, SymbolMapper
from alphaforge.core.time import Ms, now_ms
from alphaforge.core.types import (
    AccountState,
    Fill,
    Liquidity,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
)
from alphaforge.execution.broker import Broker, BrokerAck, OpenOrder, OrderBook

_ENV_PATH: Final[Path] = Path.home() / ".config" / "alphaforge" / "alpaca.env"

# Alpaca order-status string -> our OrderStatus.
_STATUS: Final[dict[str, OrderStatus]] = {
    "new": OrderStatus.NEW, "accepted": OrderStatus.NEW, "pending_new": OrderStatus.NEW,
    "accepted_for_bidding": OrderStatus.NEW, "held": OrderStatus.NEW,
    "partially_filled": OrderStatus.PARTIAL,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED, "expired": OrderStatus.CANCELED,
    "done_for_day": OrderStatus.CANCELED, "replaced": OrderStatus.CANCELED,
    "pending_cancel": OrderStatus.PARTIAL, "pending_replace": OrderStatus.PARTIAL,
    "stopped": OrderStatus.CANCELED, "suspended": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
}


def _load_env(path: Path = _ENV_PATH) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    # env vars override the file (so a deploy can inject them)
    for k in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL", "APCA_DATA_URL"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _ts(rfc3339: str | None) -> Ms:
    """Parse an Alpaca RFC3339 timestamp to epoch-ms UTC; 0 if absent."""
    if not rfc3339:
        return 0
    s = rfc3339.replace("Z", "+00:00")
    return int(dt.datetime.fromisoformat(s).timestamp() * 1000)


def _symbol(instrument_id: str) -> str:
    """XUSE:CASH:SPYUSD -> SPY (the Alpaca ticker)."""
    tail = instrument_id.split(":")[-1]
    return tail.removesuffix("USD")


def _instrument_id(symbol: str) -> str:
    """SPY -> XUSE:CASH:SPYUSD."""
    return SymbolMapper.equity_instrument_id(EQUITY_MIC, symbol.upper())


class AlpacaBroker(Broker):
    """Real broker over Alpaca's REST API (paper by base-URL). Synchronous, httpx-backed."""

    def __init__(self, *, env: dict[str, str] | None = None, env_path: Path | None = None,
                 timeout: float = 25.0) -> None:
        # env_path selects WHICH account (each sleeve trades its own Alpaca paper account for clean,
        # un-commingled per-sleeve equity history); default is the shared alpaca.env.
        env = env if env is not None else _load_env(env_path or _ENV_PATH)
        key = env.get("APCA_API_KEY_ID", "")
        sec = env.get("APCA_API_SECRET_KEY", "")
        if not key or not sec:
            raise ValueError(
                f"Alpaca credentials missing (set APCA_API_KEY_ID / APCA_API_SECRET_KEY in {_ENV_PATH})"  # noqa: E501
            )
        self._base = env.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
        self._data = env.get("APCA_DATA_URL", "https://data.alpaca.markets").rstrip("/")
        self.is_paper = "paper" in self._base
        self._h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
        self._client = httpx.Client(timeout=timeout, headers=self._h)

    # ------------------------------------------------------------------ http
    def _get(self, url: str, **kw: Any) -> httpx.Response:
        return self._client.get(url, **kw)

    def _order_json(self, j: dict[str, Any]) -> dict[str, Any]:
        return j

    # ------------------------------------------------------------------ submit
    def submit(self, order: OrderRequest) -> BrokerAck:
        symbol = _symbol(order.instrument_id)
        body: dict[str, Any] = {
            "symbol": symbol,
            "qty": str(abs(order.qty)),
            "side": "buy" if order.side is Side.BUY else "sell",
            "type": "market" if order.order_type is OrderType.MARKET else "limit",
            "time_in_force": "day",
            "client_order_id": order.client_order_id,
        }
        if order.order_type is OrderType.LIMIT:
            body["limit_price"] = str(order.decision_price)
        r = self._client.post(f"{self._base}/v2/orders", json=body)
        if r.status_code in (200, 201):
            j = r.json()
            return BrokerAck(accepted=True, client_order_id=order.client_order_id,
                             broker_order_id=str(j["id"]))
        # idempotency: a duplicate client_order_id -> fetch the existing order, return its ack
        if r.status_code == 422 and "client_order_id" in r.text.lower():
            existing = self._raw_by_client_id(order.client_order_id)
            if existing is not None:
                return BrokerAck(accepted=True, client_order_id=order.client_order_id,
                                 broker_order_id=str(existing["id"]))
        # ordinary business rejection -> accepted=False (do NOT raise)
        return BrokerAck(accepted=False, client_order_id=order.client_order_id,
                         broker_order_id=None, reason=f"HTTP {r.status_code}: {r.text[:160]}")

    # ------------------------------------------------------------------ cancel
    def cancel(self, client_order_id: str) -> bool:
        raw = self._raw_by_client_id(client_order_id)
        if raw is None:
            return False
        r = self._client.delete(f"{self._base}/v2/orders/{raw['id']}")
        return r.status_code in (200, 204)

    # ------------------------------------------------------------------ fetch_order
    def fetch_order(self, client_order_id: str) -> Fill | None:
        raw = self._raw_by_client_id(client_order_id)
        if raw is None or raw.get("status") != "filled":
            return None
        filled_qty = float(raw.get("filled_qty") or 0.0)
        price = float(raw.get("filled_avg_price") or 0.0)
        if filled_qty <= 0.0 or price <= 0.0:
            return None
        return Fill(
            client_order_id=client_order_id,
            instrument_id=_instrument_id(raw["symbol"]),
            side=Side.BUY if raw["side"] == "buy" else Side.SELL,
            qty=filled_qty,
            price=price,
            fee_quote=0.0,  # Alpaca commission-free
            liquidity=Liquidity.TAKER,
            ts=_ts(raw.get("filled_at")),
        )

    def _raw_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        r = self._get(f"{self._base}/v2/orders:by_client_order_id",
                      params={"client_order_id": client_order_id})
        if r.status_code == 200:
            return r.json()
        return None

    # ------------------------------------------------------------------ open_orders
    def open_orders(self) -> list[OpenOrder]:
        r = self._get(f"{self._base}/v2/orders", params={"status": "open", "limit": 500})
        r.raise_for_status()
        out: list[OpenOrder] = []
        for o in r.json():
            qty = float(o.get("qty") or 0.0)
            if qty <= 0.0:
                continue
            out.append(OpenOrder(
                client_order_id=o["client_order_id"],
                broker_order_id=str(o["id"]),
                instrument_id=_instrument_id(o["symbol"]),
                side=Side.BUY if o["side"] == "buy" else Side.SELL,
                qty=qty,
                filled_qty=float(o.get("filled_qty") or 0.0),
                status=_STATUS.get(o.get("status", ""), OrderStatus.NEW),
            ))
        return out

    # ------------------------------------------------------------------ positions
    def positions(self) -> list[Position]:
        r = self._get(f"{self._base}/v2/positions")
        r.raise_for_status()
        out: list[Position] = []
        for p in r.json():
            qty = float(p["qty"])  # Alpaca returns a SIGNED qty (negative for shorts)
            if qty == 0.0:
                continue
            out.append(Position(
                instrument_id=_instrument_id(p["symbol"]),
                qty=qty,
                avg_entry_price=float(p.get("avg_entry_price") or 0.0),
                opened_ts=now_ms(),  # Alpaca's positions endpoint carries no open time
            ))
        return out

    # ------------------------------------------------------------------ account
    def account(self) -> AccountState:
        r = self._get(f"{self._base}/v2/account")
        r.raise_for_status()
        a = r.json()
        return AccountState(
            equity_quote=float(a.get("equity") or 0.0),
            cash_quote=float(a.get("cash") or 0.0),
            positions=tuple(self.positions()),
            ts=now_ms(),
        )

    # ------------------------------------------------------------------ order_book
    def order_book(self, instrument_id: str, *, depth: int = 50) -> OrderBook:
        """Top-of-book from Alpaca's latest NBBO quote (equities have no free L2)."""
        symbol = _symbol(instrument_id)
        r = self._get(f"{self._data}/v2/stocks/{symbol}/quotes/latest")
        r.raise_for_status()
        q = r.json().get("quote", {})
        bid_p, bid_s = float(q.get("bp") or 0.0), float(q.get("bs") or 0.0)
        ask_p, ask_s = float(q.get("ap") or 0.0), float(q.get("as") or 0.0)
        bids = ((bid_p, bid_s),) if bid_p > 0.0 and bid_s > 0.0 else ()
        asks = ((ask_p, ask_s),) if ask_p > 0.0 and ask_s > 0.0 else ()
        return OrderBook(instrument_id=instrument_id, bids=bids, asks=asks, ts=_ts(q.get("t")))

    # ------------------------------------------------------------------ portfolio_history
    def portfolio_history(
        self, *, period: str = "all", timeframe: str = "1D"
    ) -> list[tuple[Ms, float]]:
        """Alpaca's OWN marked-to-market account-equity series — the authoritative realized curve.

        Returns [(epoch_ms, equity)], nulls (pre-funding points) dropped. This is the broker's own
        view of account value over time, so it captures fills + marks without us snapshotting.
        NOTE: account-level, so it is a single sleeve's curve only while that sleeve is the sole
        occupant of the account. A second live sleeve sharing it would commingle; per-sleeve
        isolation (separate Alpaca accounts/keys) is required first.
        """
        r = self._get(f"{self._base}/v2/account/portfolio/history",
                      params={"period": period, "timeframe": timeframe, "extended_hours": "false"})
        r.raise_for_status()
        j = r.json()
        ts = j.get("timestamp") or []
        eq = j.get("equity") or []
        return [(int(t) * 1000, float(e))
                for t, e in zip(ts, eq, strict=False) if e is not None and e > 0.0]

    def last_trade(self, instrument_id: str) -> float:
        """Last trade price — a sizing fallback when there is no two-sided quote (market closed).
        Good enough to size shares; the order still fills at the next open at the live price."""
        symbol = _symbol(instrument_id)
        r = self._get(f"{self._data}/v2/stocks/{symbol}/trades/latest")
        r.raise_for_status()
        return float(r.json().get("trade", {}).get("p") or 0.0)

    def close(self) -> None:
        self._client.close()
