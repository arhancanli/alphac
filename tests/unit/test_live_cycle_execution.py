"""Regression: live execution correctness on the Alpaca sleeves (2026-08-01).

Three defects were observed in the LIVE logs of ``scripts/live_cycle.py`` (the file both
AlphaTrend/managed_futures and AlphaMax/equity execute through):

(a) a position FLIP was sent as ONE oversized order and rejected every cycle --
    ``insufficient qty available for order (requested: 346.4156, available: 166)`` -- so a
    sign change of the target book NEVER executed;
(b) non-shortable names were submitted and rejected every cycle
    (``asset "FXE" cannot be sold short``, HTTP 422), likewise ``is not fractionable`` (403);
(c) the per-profile DB held only an ``equity_curve``: no order/reject audit trail, so an
    execution outage could only be diagnosed by grepping logs.

Every test below drives the RUNNING path: the pure order builder
``_delta_orders`` is the one main() calls, and the end-to-end tests execute the real
``main()`` against a fake broker + a fake walk-forward leg, asserting the orders that reach
the broker and the rows that land in ``var/trading_<profile>.sqlite``.
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
    spec = importlib.util.spec_from_file_location("live_cycle_exec_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["live_cycle_exec_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


MOD = _load_live_cycle()
CYCLE = 1_754_000_000_000


def _iid(sym: str) -> str:
    return f"XUSE:CASH:{sym}USD"


# --------------------------------------------------------------------------- pure builder


def _build(cur: float, tgt: float, *, mid: float = 27.0, sym: str = "DBA",
           market_orders: bool = False, whole_only: bool = False) -> list[Any]:
    return MOD._delta_orders(
        profile="managed_futures", cycle_ms=CYCLE, instrument_id=_iid(sym), symbol=sym,
        cur_shares=cur, tgt_shares=tgt, mid=mid, market_orders=market_orders,
        whole_only=whole_only,
    )


def test_flip_long_to_short_splits_into_close_then_open() -> None:
    """(a) +166 -> -180 is close(166) THEN open(180) -- never one sell of 346."""
    orders = _build(166.0, -180.0)

    assert len(orders) == 2, "a flip must be two orders (flatten, then open the other side)"
    close, open_ = orders
    assert (close.side, close.qty) == (Side.SELL, 166.0)   # flatten the long
    assert (open_.side, open_.qty) == (Side.SELL, 180.0)   # open the short
    assert [o.qty for o in orders] != [346.0], "the rejected one-order form must be gone"
    assert not any(o.qty > 200.0 for o in orders), "no leg may exceed the position it moves"
    # distinct, prefix-compatible ids: idempotency holds and cancel-stale ("<profile>-") sweeps both
    assert close.client_order_id == f"managed_futures-{CYCLE}-DBA-close"
    assert open_.client_order_id == f"managed_futures-{CYCLE}-DBA-open"
    assert len({o.client_order_id for o in orders}) == 2
    assert all(o.client_order_id.startswith("managed_futures-") for o in orders)
    assert close.reduce_only is True and open_.reduce_only is False


def test_flip_short_to_long_splits_and_truncates_whole_share_short_close() -> None:
    """The mirror image: -166 -> +163.65 covers 166, then buys 163.65 (fractional long ok)."""
    orders = _build(-166.0, 163.65)

    assert [(o.side, o.qty) for o in orders] == [(Side.BUY, 166.0), (Side.BUY, 163.65)]
    assert orders[0].reason == "managed_futures-flip-close"
    assert orders[1].reason == "managed_futures-flip-open"


def test_flip_open_leg_keeps_whole_share_short_truncation() -> None:
    """Alpaca forbids fractional shorts: a short open leg stays whole-share."""
    orders = _build(10.5, -7.0)
    assert [(o.side, o.qty) for o in orders] == [(Side.SELL, 10.5), (Side.SELL, 7.0)]
    assert float(int(orders[1].qty)) == orders[1].qty


@pytest.mark.parametrize(
    ("cur", "tgt"),
    [
        (0.0, 47.0),        # open from flat
        (0.0, -47.0),       # open a short from flat
        (41.81, 41.87),     # same-side add (dust-sized but > $1 at mid 27)
        (11.26, 11.16),     # same-side trim
        (93.0, 0.0),        # close to flat
        (-87.0, -86.0),     # short trim
        (-87.0, -93.0),     # short add
    ],
)
def test_non_flip_path_is_exactly_one_order_built_as_before(cur: float, tgt: float) -> None:
    """The NON-FLIP path must be byte-identical to the pre-fix executor: one order, same
    client_order_id, side, qty, limit price and reason (asserted against the legacy arithmetic
    reproduced inline below)."""
    mid = 27.19
    orders = _build(cur, tgt, mid=mid)

    # --- legacy (pre-flip-split) computation, verbatim ---
    delta = tgt - cur
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


def test_dust_delta_still_produces_no_order() -> None:
    assert _build(41.81, 41.8101, mid=27.19) == []


def test_market_order_flag_still_honored_on_both_paths() -> None:
    one = _build(0.0, 47.0, market_orders=True)
    assert one[0].order_type is OrderType.MARKET and one[0].decision_price == 27.0
    two = _build(166.0, -180.0, market_orders=True)
    assert all(o.order_type is OrderType.MARKET and o.decision_price == 27.0 for o in two)


def test_non_fractionable_target_trades_whole_shares_only() -> None:
    orders = _build(0.0, 96.4, sym="SIDU", mid=14.83, whole_only=True)
    assert [(o.side, o.qty) for o in orders] == [(Side.BUY, 96.0)]


# --------------------------------------------------------------------------- fake broker


class _Resp:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self) -> Any:
        return self._payload


class _Client:
    """Stands in for AlpacaBroker's httpx client (the REAL asset-flag lookup path)."""

    def __init__(self, assets: list[dict[str, Any]]) -> None:
        self._assets = assets
        self.calls = 0

    def get(self, url: str, params: dict[str, Any] | None = None) -> _Resp:
        self.calls += 1
        assert url.endswith("/v2/assets")
        return _Resp(self._assets)


class _FakeBroker:
    """Minimal stand-in for AlpacaBroker over the surface live_cycle actually uses."""

    is_paper = True

    def __init__(self, *, equity: float, positions: dict[str, float], prices: dict[str, float],
                 assets: list[dict[str, Any]] | None = None,
                 reject: dict[str, str] | None = None) -> None:
        self._equity = equity
        self._positions = positions
        self._prices = prices
        self._reject = reject or {}
        self.submitted: list[Any] = []
        self._base = "https://paper-api.alpaca.markets"
        self._client = _Client(assets) if assets is not None else None

    # -- construction args are keyword-only in live_cycle; accept and ignore env_path
    def open_orders(self) -> list[Any]:
        return []

    def cancel(self, client_order_id: str) -> bool:  # pragma: no cover - no stale orders here
        return True

    def account(self) -> AccountState:
        return AccountState(
            equity_quote=self._equity, cash_quote=self._equity,
            positions=tuple(
                Position(instrument_id=i, qty=q, avg_entry_price=self._prices[MOD_SYM(i)],
                         opened_ts=CYCLE)
                for i, q in self._positions.items()
            ),
            ts=CYCLE,
        )

    def order_book(self, instrument_id: str, *, depth: int = 50) -> OrderBook:
        px = self._prices[MOD_SYM(instrument_id)]
        return OrderBook(instrument_id=instrument_id, bids=((px * 0.999, 100.0),),
                         asks=((px * 1.001, 100.0),), ts=CYCLE)

    def last_trade(self, instrument_id: str) -> float:
        return self._prices[MOD_SYM(instrument_id)]

    def submit(self, order: Any) -> BrokerAck:
        self.submitted.append(order)
        sym = MOD_SYM(order.instrument_id)
        if sym in self._reject:
            return BrokerAck(accepted=False, client_order_id=order.client_order_id,
                             broker_order_id=None, reason=self._reject[sym])
        return BrokerAck(accepted=True, client_order_id=order.client_order_id,
                         broker_order_id=f"srv-{len(self.submitted)}")

    def portfolio_history(self, *, period: str = "all", timeframe: str = "1D") -> list[Any]:
        return [(CYCLE - 86_400_000, self._equity)]

    def close(self) -> None:
        return None


def MOD_SYM(instrument_id: str) -> str:
    return instrument_id.split(":")[-1].removesuffix("USD")


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
    monkeypatch.setattr(MOD, "_ACCOUNT_ENV", {})
    return int(MOD.main(["--profile", profile]))


def _rows(db: Path, table: str) -> list[tuple[Any, ...]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        con.close()


# --------------------------------------------------------------------------- end-to-end


def test_running_path_flip_submits_two_legs_not_one_oversized_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) end to end: the sleeve holding -166 DBA with a +long target sends close+open."""
    broker = _FakeBroker(
        equity=100_000.0,
        positions={_iid("DBA"): -166.0, _iid("SPY"): 4.0},
        prices={"DBA": 27.19, "SPY": 744.62},
        assets=[_asset("DBA"), _asset("SPY")],
    )
    rc = _run_cycle(tmp_path, monkeypatch, broker, {"DBA": 0.044, "SPY": 0.030})
    assert rc == 0

    dba = [o for o in broker.submitted if MOD_SYM(o.instrument_id) == "DBA"]
    assert len(dba) == 2
    assert [(o.side, o.qty) for o in dba] == [(Side.BUY, 166.0), (Side.BUY, 161.8242)]
    assert not any(o.qty > 330.0 for o in dba), "the single oversized order is what Alpaca rejects"
    # the rest of the book is a single ordinary order, unchanged
    spy = [o for o in broker.submitted if MOD_SYM(o.instrument_id) == "SPY"]
    assert len(spy) == 1 and spy[0].client_order_id.endswith("-SPY")


def test_running_path_drops_non_shortable_short_target_and_keeps_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """(b) FXE (not shortable) is never submitted; UUP/SPY trade normally."""
    broker = _FakeBroker(
        equity=100_000.0,
        positions={},
        prices={"FXE": 106.40, "UUP": 28.12, "SPY": 744.62},
        assets=[_asset("FXE", shortable=False), _asset("UUP"), _asset("SPY")],
    )
    rc = _run_cycle(tmp_path, monkeypatch, broker,
                    {"FXE": -0.050, "UUP": 0.050, "SPY": 0.030})
    assert rc == 0

    submitted = {MOD_SYM(o.instrument_id) for o in broker.submitted}
    assert "FXE" not in submitted, "an unfillable short must never be submitted"
    assert submitted == {"UUP", "SPY"}, "the rest of the book is unaffected"
    out = capsys.readouterr().out
    assert "FXE" in out and "DISCLOSED SKIP" in out and "not shortable" in out
    # and the skip is in the audit trail, not just the log
    rejects = _rows(tmp_path / "var" / "trading_managed_futures.sqlite", "order_rejects")
    assert [r[4] for r in rejects] == ["precheck_not_shortable"]
    assert _iid("FXE") in [r[3] for r in rejects]


def test_running_path_flattens_a_long_whose_target_turns_non_shortable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A short target on a non-shortable name becomes 0 -- an existing long still CLOSES
    (that order is fillable), rather than the whole name being ignored."""
    broker = _FakeBroker(
        equity=100_000.0,
        positions={_iid("FXE"): 25.0},
        prices={"FXE": 106.40, "SPY": 744.62},
        assets=[_asset("FXE", shortable=False), _asset("SPY")],
    )
    rc = _run_cycle(tmp_path, monkeypatch, broker, {"FXE": -0.050, "SPY": 0.030})
    assert rc == 0
    fxe = [o for o in broker.submitted if MOD_SYM(o.instrument_id) == "FXE"]
    assert [(o.side, o.qty) for o in fxe] == [(Side.SELL, 25.0)]  # flatten only, no short


def test_broker_reject_is_a_clean_skip_and_never_aborts_the_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """(b, fallback) with NO asset flags available, a 422/403 is caught, audited and skipped —
    every later name in the book still gets submitted."""
    broker = _FakeBroker(
        equity=100_000.0,
        positions={},
        prices={"BYND": 4.91, "SIDU": 14.83, "ZZZZ": 50.0},
        assets=None,  # no pre-check available -> the submit-time catch path
        reject={
            "BYND": 'HTTP 422: {"code":42210000,"message":"asset \\"BYND\\" cannot be sold short"}',
            "SIDU": 'HTTP 403: {"code":40310000,"message":"asset \\"SIDU\\" is not fractionable"}',
        },
    )
    rc = _run_cycle(tmp_path, monkeypatch, broker,
                    {"BYND": -0.020, "SIDU": 0.020, "ZZZZ": 0.020})
    assert rc == 0
    assert {MOD_SYM(o.instrument_id) for o in broker.submitted} == {"BYND", "SIDU", "ZZZZ"}

    out = capsys.readouterr().out
    assert "DISCLOSED SKIP BYND (not-shortable)" in out
    assert "DISCLOSED SKIP SIDU (not-fractionable)" in out
    assert "submitted 1/3 accepted" in out

    db = tmp_path / "var" / "trading_managed_futures.sqlite"
    rejects = {r[3]: (r[4], r[5]) for r in _rows(db, "order_rejects")}
    assert rejects[_iid("BYND")][0] == "42210000"
    assert "cannot be sold short" in rejects[_iid("BYND")][1]
    assert rejects[_iid("SIDU")][0] == "40310000"
    # the equity curve is still recorded: a reject cannot abort the cycle
    assert _rows(db, "equity_curve")


def test_audit_tables_receive_every_submitted_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(c) orders + order_rejects exist in var/trading_<profile>.sqlite and hold this cycle."""
    broker = _FakeBroker(
        equity=100_000.0,
        positions={_iid("DBA"): -166.0},
        prices={"DBA": 27.19, "SPY": 744.62},
        assets=[_asset("DBA"), _asset("SPY")],
        reject={"SPY": 'HTTP 403: {"code":40310000,"message":"insufficient buying power"}'},
    )
    rc = _run_cycle(tmp_path, monkeypatch, broker, {"DBA": 0.044, "SPY": 0.030})
    assert rc == 0

    db = tmp_path / "var" / "trading_managed_futures.sqlite"
    orders = _rows(db, "orders")
    assert len(orders) == len(broker.submitted) == 3
    by_coid = {r[0]: r for r in orders}
    close = next(r for k, r in by_coid.items() if k.endswith("-DBA-close"))
    open_ = next(r for k, r in by_coid.items() if k.endswith("-DBA-open"))
    assert close[3] == "buy" and close[4] == 166.0 and close[7] == "flip-close" and close[8] == 1
    assert open_[7] == "flip-open" and open_[9] is not None      # broker_order_id recorded
    spy = next(r for k, r in by_coid.items() if k.endswith("-SPY"))
    assert spy[7] == "rebalance" and spy[8] == 0                 # rejected order still audited
    assert all(r[1] > 0 and r[2].startswith("XUSE:") and r[5] > 0 for r in orders)

    rejects = _rows(db, "order_rejects")
    assert len(rejects) == 1
    assert rejects[0][3] == _iid("SPY") and rejects[0][4] == "40310000"
    assert "buying power" in rejects[0][5]


def test_dry_run_submits_nothing_and_writes_no_audit_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _FakeBroker(
        equity=100_000.0, positions={_iid("DBA"): -166.0},
        prices={"DBA": 27.19}, assets=[_asset("DBA")],
    )
    _write_leg(tmp_path, "mf_live_fwd", {"DBA": 0.044})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AF_PATHS__VAR_DIR", str(tmp_path / "var"))
    import alphaforge.execution.alpaca_broker as ab

    monkeypatch.setattr(ab, "AlpacaBroker", lambda **kw: broker)
    monkeypatch.setattr(MOD, "_ACCOUNT_ENV", {})
    assert MOD.main(["--profile", "managed_futures", "--dry-run"]) == 0
    assert broker.submitted == []
    assert not (tmp_path / "var" / "trading_managed_futures.sqlite").exists()


# --------------------------------------------------------------------------- reject parsing


@pytest.mark.parametrize(
    ("reason", "code", "kind"),
    [
        ('HTTP 422: {"code":42210000,"message":"asset \\"FXE\\" cannot be sold short"}',
         "42210000", "not-shortable"),
        ('HTTP 403: {"code":40310000,"message":"asset \\"SLS\\" is not fractionable"}',
         "40310000", "not-fractionable"),
        ('HTTP 403: {"available":"166","code":40310000,"existing_qty":"166",'
         '"message":"insufficient qty available for order (requested: 346.4156, available: 166)"}',
         "40310000", None),
        ("HTTP 500: upstream unavailable", "HTTP 500", None),
    ],
)
def test_reject_parsing_and_classification(reason: str, code: str, kind: str | None) -> None:
    parsed_code, message = MOD._parse_reject(reason)
    assert parsed_code == code
    assert MOD._skip_kind(message) == kind
