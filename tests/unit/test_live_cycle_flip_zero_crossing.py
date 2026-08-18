"""Regression: the live order path may NEVER emit a lone order that crosses zero (2026-08-02).

The flip-split fix (tests/unit/test_live_cycle_execution.py) turned a sign-reversing target into a
close leg plus an open leg, because Alpaca rejects one oversized order across zero
(``insufficient qty available for order``). An adversarial verifier found the residual hole: the
$1 minimum-order dust gate ran BEFORE the split, so whenever the CURRENT position was worth less
than the gate the close leg was dropped and the OPEN leg went out on its own -- which is again a
single order crossing zero, exactly what the broker rejects. Two reproductions:

  (a) cur=+0.02, tgt=-100          -> a lone SELL 100 over a $0.54 long;
  (b) cur=+0.5,  tgt=-10, whole_only -> the close truncates to 0 whole shares, lone SELL 10.

Every test drives the RUNNING path: the pure builder ``_delta_orders`` is the one ``main()`` calls,
and the end-to-end cases execute the real ``main()`` against a fake broker + a fake walk-forward
leg, asserting on the orders that actually reach the broker.

The invariant is checked mechanically by ``_replay`` below: applying the emitted orders in order to
the current position, no SINGLE order may take it from one sign to the other.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from alphaforge.core.types import AccountState, OrderType, Position, Side
from alphaforge.execution.broker import BrokerAck, OrderBook

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "live_cycle.py"


def _load_live_cycle() -> Any:
    spec = importlib.util.spec_from_file_location("live_cycle_zero_crossing_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["live_cycle_zero_crossing_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


MOD = _load_live_cycle()
CYCLE = 1_754_100_000_000


def _iid(sym: str) -> str:
    return f"XUSE:CASH:{sym}USD"


def _sym(instrument_id: str) -> str:
    return instrument_id.split(":")[-1].removesuffix("USD")


# --------------------------------------------------------------------------- the invariant


def _replay(orders: list[Any], cur: float) -> None:
    """Assert that no SINGLE order in ``orders`` crosses zero from the position it acts on.

    Reaching the other side of zero is legal only across TWO orders (close, then open): after the
    close the position is exactly flat, so the open starts from 0 and crosses nothing.
    """
    pos = cur
    for i, o in enumerate(orders):
        signed = o.qty if o.side is Side.BUY else -o.qty
        nxt = pos + signed
        assert pos * nxt >= 0.0, (
            f"order #{i} ({o.side.name} {o.qty}) takes the position {pos:+.4f} -> {nxt:+.4f}, a "
            "single order across zero — the broker rejects it ('insufficient qty available')"
        )
        pos = nxt


def _build(cur: float, tgt: float, *, mid: float = 27.0, sym: str = "DBA",
           market_orders: bool = False, whole_only: bool = False,
           skips: list[str] | None = None) -> list[Any]:
    orders = MOD._delta_orders(
        profile="managed_futures", cycle_ms=CYCLE, instrument_id=_iid(sym), symbol=sym,
        cur_shares=cur, tgt_shares=tgt, mid=mid, market_orders=market_orders,
        whole_only=whole_only, skips=skips,
    )
    _replay(orders, cur)  # the invariant holds for EVERY case this helper builds
    return orders


# --------------------------------------------------------------------------- (a) dust-sized current


def test_dust_sized_current_position_still_gets_a_close_leg_not_a_lone_short() -> None:
    """(a) cur=+0.02 -> tgt=-100: the $0.54 long is below the $1 dust gate, but dropping its close
    leg left a LONE SELL 100 crossing zero. The close leg is now exempt from the dust gate."""
    skips: list[str] = []
    orders = _build(0.02, -100.0, skips=skips)

    assert len(orders) == 2, "the dust-sized long must still be closed before the short is opened"
    close, open_ = orders
    assert (close.side, close.qty) == (Side.SELL, 0.02)
    assert close.reduce_only is True and close.reason == "managed_futures-flip-close"
    assert (open_.side, open_.qty) == (Side.SELL, 100.0)
    assert open_.reason == "managed_futures-flip-open"
    assert orders != [open_], "the lone zero-crossing SELL 100 is the bug"
    assert skips == [], "this flip is fully executable — nothing to disclose"
    # idempotent, prefix-compatible ids (cancel-stale filters on the '<profile>-' prefix)
    assert close.client_order_id == f"managed_futures-{CYCLE}-DBA-close"
    assert open_.client_order_id == f"managed_futures-{CYCLE}-DBA-open"


def test_dust_sized_current_short_gets_a_close_leg_before_the_long_is_opened() -> None:
    """The mirror image: a $0.54 short must be covered before a 100-share long is opened."""
    orders = _build(-0.02, 100.0)
    assert [(o.side, o.qty) for o in orders] == [(Side.BUY, 0.02), (Side.BUY, 100.0)]
    assert orders[0].reduce_only is True


def test_small_flip_over_a_dust_long_is_two_legs() -> None:
    """The same hole at a smaller open size (cur=+0.02 -> tgt=-2): still never one order."""
    orders = _build(0.02, -2.0)
    assert [(o.side, o.qty) for o in orders] == [(Side.SELL, 0.02), (Side.SELL, 2.0)]


# --------------------------------------------------------------------------- (b) unclosable close


def test_fractional_holding_of_a_non_fractionable_name_skips_the_whole_flip() -> None:
    """(b) cur=+0.5 -> tgt=-10 on a whole-share-only name: the close leg truncates to 0 shares, so
    it is genuinely unfillable. Sending the open leg alone is a guaranteed reject — the flip is
    withheld and disclosed instead."""
    skips: list[str] = []
    orders = _build(0.5, -10.0, sym="SIDU", mid=14.83, whole_only=True, skips=skips)

    assert orders == [], "no order at all beats a lone SELL 10 the broker will reject"
    assert len(skips) == 1
    assert "cannot be flattened" in skips[0] and "cross zero" in skips[0]


def test_partial_close_on_a_non_fractionable_name_keeps_the_close_and_withholds_the_open() -> None:
    """cur=+5.5 whole-share-only: the close can only flatten 5 shares, so an open on top of the
    0.5 residual would STILL cross zero. Keep the de-risking close, withhold the open, disclose."""
    skips: list[str] = []
    orders = _build(5.5, -10.0, sym="SIDU", mid=14.83, whole_only=True, skips=skips)

    assert [(o.side, o.qty) for o in orders] == [(Side.SELL, 5.0)]
    assert orders[0].reduce_only is True
    assert len(skips) == 1 and "open leg withheld" in skips[0]


def test_skips_argument_is_optional() -> None:
    """The builder stays usable without the disclosure list (no crash, same orders)."""
    assert _build(0.5, -10.0, sym="SIDU", mid=14.83, whole_only=True) == []


# --------------------------------------------------------------------------- unchanged behaviour


def test_ordinary_flip_is_unchanged() -> None:
    """+166 -> -180 is still close(166) then open(180), same ids/sides/qtys/prices/reasons."""
    skips: list[str] = []
    orders = _build(166.0, -180.0, skips=skips)

    assert len(orders) == 2
    close, open_ = orders
    assert (close.side, close.qty) == (Side.SELL, 166.0)
    assert (open_.side, open_.qty) == (Side.SELL, 180.0)
    assert close.reduce_only is True and open_.reduce_only is False
    assert close.reason == "managed_futures-flip-close"
    assert open_.reason == "managed_futures-flip-open"
    assert close.client_order_id == f"managed_futures-{CYCLE}-DBA-close"
    assert open_.client_order_id == f"managed_futures-{CYCLE}-DBA-open"
    assert close.decision_price == round(27.0 * (1 - MOD._LIMIT_BUFFER), 2)
    assert open_.decision_price == round(27.0 * (1 - MOD._LIMIT_BUFFER), 2)
    assert skips == []


def test_ordinary_flip_short_to_long_is_unchanged_and_keeps_whole_share_short_rules() -> None:
    assert ([(o.side, o.qty) for o in _build(-166.0, 163.65)]
            == [(Side.BUY, 166.0), (Side.BUY, 163.65)])
    assert [(o.side, o.qty) for o in _build(10.5, -7.0)] == [(Side.SELL, 10.5), (Side.SELL, 7.0)]


@pytest.mark.parametrize(
    ("cur", "tgt"),
    [
        (0.0, 47.0),        # open from flat
        (0.0, -47.0),       # open a short from flat
        (41.81, 41.87),     # same-side add
        (11.26, 11.16),     # same-side trim
        (93.0, 0.0),        # close to flat
        (-87.0, -86.0),     # short trim
        (-87.0, -93.0),     # short add
        (0.02, 0.9),        # dust-sized current, SAME side -> ordinary one-order resize
    ],
)
def test_same_side_resize_is_still_exactly_one_unchanged_order(cur: float, tgt: float) -> None:
    """The non-flip path must stay byte-identical to the pre-fix executor (legacy arithmetic
    reproduced inline), and it must never consult the disclosure list."""
    mid = 27.19
    skips: list[str] = []
    orders = _build(cur, tgt, mid=mid, skips=skips)

    delta = tgt - cur                       # --- legacy computation, verbatim ---
    if tgt < 0:
        delta = float(int(delta))
    delta = round(delta, 4)
    legacy_side = Side.BUY if delta > 0 else Side.SELL
    legacy_px = (round(mid * (1 + MOD._LIMIT_BUFFER), 2) if legacy_side is Side.BUY
                 else round(mid * (1 - MOD._LIMIT_BUFFER), 2))

    assert len(orders) == 1
    o = orders[0]
    assert o.client_order_id == f"managed_futures-{CYCLE}-DBA"  # NO suffix on the non-flip path
    assert o.side is legacy_side
    assert o.qty == abs(delta)
    assert o.decision_price == legacy_px
    assert o.order_type is OrderType.LIMIT
    assert o.reduce_only is False
    assert o.reason == "managed_futures-rebalance"
    assert o.decision_ts == CYCLE
    assert skips == []


def test_dust_net_delta_still_produces_no_order_at_all() -> None:
    """The pre-split dust gate stays: when the NET delta is dust NOTHING is emitted, which cannot
    leave a lone crossing order (for a flip |delta| >= max(|cur|, |tgt|), so both legs are dust)."""
    assert _build(41.81, 41.8101, mid=27.19) == []
    assert _build(0.005, -0.005, mid=27.19) == []


# --------------------------------------------------------------------------- fake broker (e2e)


class _Resp:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, assets: list[dict[str, Any]]) -> None:
        self._assets = assets

    def get(self, url: str, params: dict[str, Any] | None = None) -> _Resp:
        assert url.endswith("/v2/assets")
        return _Resp(self._assets)


class _FakeBroker:
    """Minimal stand-in for AlpacaBroker over the surface live_cycle actually uses."""

    is_paper = True

    def __init__(self, *, equity: float, positions: dict[str, float], prices: dict[str, float],
                 assets: list[dict[str, Any]] | None = None) -> None:
        self._equity = equity
        self._positions = positions
        self._prices = prices
        self.submitted: list[Any] = []
        self._base = "https://paper-api.alpaca.markets"
        self._client = _Client(assets) if assets is not None else None

    def open_orders(self) -> list[Any]:
        return []

    def cancel(self, client_order_id: str) -> bool:  # pragma: no cover - no stale orders here
        return True

    def account(self) -> AccountState:
        return AccountState(
            equity_quote=self._equity, cash_quote=self._equity,
            positions=tuple(
                Position(instrument_id=i, qty=q, avg_entry_price=self._prices[_sym(i)],
                         opened_ts=CYCLE)
                for i, q in self._positions.items()
            ),
            ts=CYCLE,
        )

    def order_book(self, instrument_id: str, *, depth: int = 50) -> OrderBook:
        px = self._prices[_sym(instrument_id)]
        return OrderBook(instrument_id=instrument_id, bids=((px * 0.999, 100.0),),
                         asks=((px * 1.001, 100.0),), ts=CYCLE)

    def last_trade(self, instrument_id: str) -> float:
        return self._prices[_sym(instrument_id)]

    def submit(self, order: Any) -> BrokerAck:
        self.submitted.append(order)
        return BrokerAck(accepted=True, client_order_id=order.client_order_id,
                         broker_order_id=f"srv-{len(self.submitted)}")

    def portfolio_history(self, *, period: str = "all", timeframe: str = "1D") -> list[Any]:
        return [(CYCLE - 86_400_000, self._equity)]

    def close(self) -> None:
        return None


def _asset(symbol: str, *, shortable: bool = True, fractionable: bool = True) -> dict[str, Any]:
    return {"symbol": symbol, "shortable": shortable, "fractionable": fractionable,
            "tradable": True, "class": "us_equity"}


def _write_leg(root: Path, wf: str, weights: dict[str, float], ts: int = CYCLE) -> None:
    leg = root / "artifacts" / "walkforward" / wf / "legs" / "leg_00"
    leg.mkdir(parents=True, exist_ok=True)
    iids = [_iid(s) for s in weights]
    pq.write_table(
        pa.table({
            "ts": pa.array([ts] * len(iids), type=pa.int64()),
            "instrument_id": pa.array(iids, type=pa.string()),
            "qty": pa.array([1.0] * len(iids), type=pa.float64()),
            "mark": pa.array([10.0] * len(iids), type=pa.float64()),
            "weight": pa.array(list(weights.values()), type=pa.float64()),
            "unreal_pnl": pa.array([0.0] * len(iids), type=pa.float64()),
        }),
        leg / "positions.parquet",
    )


def _run_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broker: _FakeBroker,
               weights: dict[str, float], *, profile: str = "managed_futures") -> int:
    """Drive the REAL main() end to end against ``broker`` (no network, nothing real submitted)."""
    _write_leg(tmp_path, "mf_live_fwd" if profile == "managed_futures" else "equity_live_fwd",
               weights)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AF_PATHS__VAR_DIR", str(tmp_path / "var"))
    import alphaforge.execution.alpaca_broker as ab

    monkeypatch.setattr(ab, "AlpacaBroker", lambda **kw: broker)
    # A REAL mapping, not {}: the account guard must stay exercised here. See the note on
    # _fake_account_map in test_live_cycle_execution.py — an unmapped profile used to fall through
    # to AlphaTrend's live account.
    env = tmp_path / f"alpaca_{profile}.env"
    env.write_text(
        "APCA_API_KEY_ID=test-key\nAPCA_API_SECRET_KEY=test-secret\n"
        "APCA_API_BASE_URL=https://paper-api.alpaca.markets\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(MOD, "_ACCOUNT_ENV", {profile: env})
    return int(MOD.main(["--profile", profile]))


def _rows(db: Path, table: str) -> list[tuple[Any, ...]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        con.close()


# --------------------------------------------------------------------------- end-to-end


def test_running_path_never_submits_a_lone_crossing_order_over_a_dust_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) end to end: holding 0.02 DBA ($0.54) with a SHORT target submits close+open."""
    broker = _FakeBroker(
        equity=100_000.0,
        positions={_iid("DBA"): 0.02, _iid("SPY"): 4.0},
        prices={"DBA": 27.19, "SPY": 744.62},
        assets=[_asset("DBA"), _asset("SPY")],
    )
    rc = _run_cycle(tmp_path, monkeypatch, broker, {"DBA": -0.044, "SPY": 0.030})
    assert rc == 0

    dba = [o for o in broker.submitted if _sym(o.instrument_id) == "DBA"]
    assert len(dba) == 2, "the lone zero-crossing SELL is the reproduced bug"
    assert dba[0].side is Side.SELL and dba[0].qty == 0.02 and dba[0].reduce_only is True
    assert dba[1].side is Side.SELL and dba[1].qty > 100.0
    _replay(dba, 0.02)
    # the rest of the book is a single ordinary order, unchanged
    spy = [o for o in broker.submitted if _sym(o.instrument_id) == "SPY"]
    assert len(spy) == 1 and spy[0].client_order_id.endswith("-SPY")


def test_running_path_withholds_the_flip_when_the_close_leg_is_unfillable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """(b) end to end: 0.5 shares of a NON-FRACTIONABLE name with a short target submits NOTHING
    for that name (the close truncates to 0), discloses the skip and audits it. The rest of the
    book still trades."""
    broker = _FakeBroker(
        equity=100_000.0,
        positions={_iid("SIDU"): 0.5},
        prices={"SIDU": 14.83, "SPY": 744.62},
        assets=[_asset("SIDU", fractionable=False), _asset("SPY")],
    )
    rc = _run_cycle(tmp_path, monkeypatch, broker, {"SIDU": -0.020, "SPY": 0.030})
    assert rc == 0

    assert [_sym(o.instrument_id) for o in broker.submitted] == ["SPY"], (
        "a lone SELL over an unclosable fractional holding must never be submitted"
    )
    out = capsys.readouterr().out
    assert "SIDU" in out and "DISCLOSED SKIP (unclosable flip)" in out
    rejects = _rows(tmp_path / "var" / "trading_managed_futures.sqlite", "order_rejects")
    assert [(r[3], r[4]) for r in rejects] == [(_iid("SIDU"), "precheck_unclosable_flip")]
    assert "cannot be flattened" in rejects[0][5]


def test_running_path_ordinary_flip_and_resize_still_unchanged_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shipped behaviour the fix must preserve: a full-size flip is still close+open and a
    same-side resize is still exactly one order."""
    broker = _FakeBroker(
        equity=100_000.0,
        positions={_iid("DBA"): -166.0, _iid("SPY"): 4.0},
        prices={"DBA": 27.19, "SPY": 744.62},
        assets=[_asset("DBA"), _asset("SPY")],
    )
    rc = _run_cycle(tmp_path, monkeypatch, broker, {"DBA": 0.044, "SPY": 0.030})
    assert rc == 0

    dba = [o for o in broker.submitted if _sym(o.instrument_id) == "DBA"]
    assert [(o.side, o.qty) for o in dba] == [(Side.BUY, 166.0), (Side.BUY, 161.8242)]
    _replay(dba, -166.0)
    spy = [o for o in broker.submitted if _sym(o.instrument_id) == "SPY"]
    assert len(spy) == 1 and spy[0].reason == "managed_futures-rebalance"
    assert not _rows(tmp_path / "var" / "trading_managed_futures.sqlite", "order_rejects")
