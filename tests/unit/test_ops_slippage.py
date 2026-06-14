"""Unit tests for :mod:`alphaforge.ops.slippage` (offline, tmp_path only).

Covers: hand-seeded fills -> exact summary stats (mean/median/p90/p99 to 1e-9);
side-normalized adverse-positive sign taken straight from the stored audit column;
book_exhausted counted overall and per-instrument; per-instrument breakdown sorted
by id; an empty/young store -> fully zeroed summary; a store with no fills table at
all -> zeroed; the render_text table shape for both populated and empty stores. A
real :class:`TradingStore` is seeded in a tmp_path file; no network, no ./var.
"""

from __future__ import annotations

from pathlib import Path

from alphaforge.core.types import Fill, Liquidity, OrderRequest, OrderType, Side
from alphaforge.live.store import FillAudit, TradingStore
from alphaforge.ops.slippage import SlippageReport

T0 = 1_700_000_000_000
BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"
TOL = 1e-9


def _seed_fill(
    store: TradingStore,
    *,
    coid: str,
    instrument_id: str,
    slippage_bps: float,
    book_exhausted: bool = False,
    side: Side = Side.BUY,
    qty: float = 1.0,
    price: float = 100.0,
) -> None:
    """Record an intent and a fully-audited fill for it on ``store``."""
    req = OrderRequest(
        client_order_id=coid,
        instrument_id=instrument_id,
        side=side,
        qty=qty,
        order_type=OrderType.MARKET,
        decision_ts=T0,
        decision_price=price,
        reason="test",
    )
    store.record_intent(req, T0, now=T0)
    fill = Fill(
        client_order_id=coid,
        instrument_id=instrument_id,
        side=side,
        qty=qty,
        price=price,
        fee_quote=0.05,
        liquidity=Liquidity.TAKER,
        ts=T0 + 1,
    )
    audit = FillAudit(
        walked_price=price,
        modeled_price=price,
        slippage_bps=slippage_bps,
        book_exhausted=book_exhausted,
    )
    store.mark_filled(fill, now=T0 + 1, audit=audit)


def test_empty_store_zeroed_summary(tmp_path: Path) -> None:
    db = tmp_path / "trading.sqlite"
    with TradingStore(db):
        pass  # creates schema, no fills
    summary = SlippageReport.from_store(db).summary()
    assert summary.n_fills == 0
    assert summary.mean_bps == 0.0
    assert summary.median_bps == 0.0
    assert summary.p90_bps == 0.0
    assert summary.p99_bps == 0.0
    assert summary.n_book_exhausted == 0
    assert summary.per_instrument == ()


def test_no_fills_table_reads_as_empty(tmp_path: Path) -> None:
    """A brand-new SQLite file with no ``fills`` table yields a zeroed summary, not an error."""
    db = tmp_path / "fresh.sqlite"
    import sqlite3

    sqlite3.connect(db).close()  # empty db, no schema
    summary = SlippageReport.from_store(db).summary()
    assert summary.n_fills == 0
    assert summary.per_instrument == ()


def test_empty_render_text(tmp_path: Path) -> None:
    db = tmp_path / "trading.sqlite"
    with TradingStore(db):
        pass
    text = SlippageReport.from_store(db).render_text()
    assert "no audited fills yet" in text


def test_exact_summary_stats(tmp_path: Path) -> None:
    """Hand-seeded slippage_bps -> exact mean/median/p90/p99 (linear-interp percentiles)."""
    db = tmp_path / "trading.sqlite"
    # 10 values; ascending: -2,-1,0,1,2,3,4,5,6,7  (mix of favorable and adverse)
    values = [3.0, -2.0, 5.0, 0.0, 1.0, -1.0, 6.0, 2.0, 7.0, 4.0]
    with TradingStore(db) as store:
        for i, v in enumerate(values):
            _seed_fill(store, coid=f"af-{i}", instrument_id=BTC, slippage_bps=v)
    summary = SlippageReport.from_store(db).summary()

    assert summary.n_fills == 10
    # mean = (sum -2..7) / 10 = 25/10 = 2.5
    assert abs(summary.mean_bps - 2.5) < TOL
    # sorted: [-2,-1,0,1,2,3,4,5,6,7]; n=10 -> pos = q*(n-1) = q*9
    # median q=0.5 -> pos 4.5 -> interp between idx4(2) and idx5(3) = 2.5
    assert abs(summary.median_bps - 2.5) < TOL
    # p90 q=0.9 -> pos 8.1 -> interp idx8(6),idx9(7): 6 + 0.1*1 = 6.1
    assert abs(summary.p90_bps - 6.1) < TOL
    # p99 q=0.99 -> pos 8.91 -> interp idx8(6),idx9(7): 6 + 0.91 = 6.91
    assert abs(summary.p99_bps - 6.91) < TOL


def test_single_fill_percentiles_are_the_value(tmp_path: Path) -> None:
    db = tmp_path / "trading.sqlite"
    with TradingStore(db) as store:
        _seed_fill(store, coid="af-0", instrument_id=BTC, slippage_bps=3.5)
    summary = SlippageReport.from_store(db).summary()
    assert summary.n_fills == 1
    assert summary.mean_bps == 3.5
    assert summary.median_bps == 3.5
    assert summary.p90_bps == 3.5
    assert summary.p99_bps == 3.5


def test_book_exhausted_counted(tmp_path: Path) -> None:
    db = tmp_path / "trading.sqlite"
    with TradingStore(db) as store:
        _seed_fill(store, coid="af-0", instrument_id=BTC, slippage_bps=1.0, book_exhausted=True)
        _seed_fill(store, coid="af-1", instrument_id=BTC, slippage_bps=2.0, book_exhausted=False)
        _seed_fill(store, coid="af-2", instrument_id=BTC, slippage_bps=3.0, book_exhausted=True)
    summary = SlippageReport.from_store(db).summary()
    assert summary.n_book_exhausted == 2


def test_adverse_sign_taken_from_audit_column(tmp_path: Path) -> None:
    """A SELL fill stores an already adverse-signed slippage; the report passes it through."""
    db = tmp_path / "trading.sqlite"
    with TradingStore(db) as store:
        # adverse-positive for a SELL is stored on the audit column directly
        _seed_fill(store, coid="af-s", instrument_id=BTC, slippage_bps=4.2, side=Side.SELL, qty=1.0)
    summary = SlippageReport.from_store(db).summary()
    assert abs(summary.mean_bps - 4.2) < TOL


def test_per_instrument_breakdown_sorted(tmp_path: Path) -> None:
    db = tmp_path / "trading.sqlite"
    with TradingStore(db) as store:
        _seed_fill(store, coid="e0", instrument_id=ETH, slippage_bps=10.0)
        _seed_fill(store, coid="e1", instrument_id=ETH, slippage_bps=20.0, book_exhausted=True)
        _seed_fill(store, coid="b0", instrument_id=BTC, slippage_bps=1.0)
    summary = SlippageReport.from_store(db).summary()

    ids = [r.instrument_id for r in summary.per_instrument]
    assert ids == [BTC, ETH]  # sorted
    btc = summary.per_instrument[0]
    eth = summary.per_instrument[1]
    assert btc.n_fills == 1 and abs(btc.mean_bps - 1.0) < TOL and btc.n_book_exhausted == 0
    assert eth.n_fills == 2 and abs(eth.mean_bps - 15.0) < TOL and eth.n_book_exhausted == 1
    # overall mean = (1 + 10 + 20)/3
    assert abs(summary.mean_bps - (31.0 / 3.0)) < TOL


def test_recovered_fill_without_audit_is_excluded(tmp_path: Path) -> None:
    """A fill recorded WITHOUT walked-book audit has no modeled-vs-realized signal -> skipped."""
    db = tmp_path / "trading.sqlite"
    with TradingStore(db) as store:
        # audited fill
        _seed_fill(store, coid="af-0", instrument_id=BTC, slippage_bps=5.0)
        # un-audited fill (e.g. a recovered broker fill): audit=None
        req = OrderRequest(
            client_order_id="af-1",
            instrument_id=BTC,
            side=Side.BUY,
            qty=1.0,
            order_type=OrderType.MARKET,
            decision_ts=T0,
            decision_price=100.0,
            reason="recovered",
        )
        store.record_intent(req, T0, now=T0)
        store.mark_filled(
            Fill(
                client_order_id="af-1",
                instrument_id=BTC,
                side=Side.BUY,
                qty=1.0,
                price=100.0,
                fee_quote=0.05,
                liquidity=Liquidity.TAKER,
                ts=T0 + 2,
            ),
            now=T0 + 2,
            audit=None,
        )
    summary = SlippageReport.from_store(db).summary()
    assert summary.n_fills == 1  # only the audited fill
    assert abs(summary.mean_bps - 5.0) < TOL


def test_render_text_populated_table(tmp_path: Path) -> None:
    db = tmp_path / "trading.sqlite"
    with TradingStore(db) as store:
        _seed_fill(store, coid="b0", instrument_id=BTC, slippage_bps=1.0)
        _seed_fill(store, coid="e0", instrument_id=ETH, slippage_bps=2.0, book_exhausted=True)
    text = SlippageReport.from_store(db).render_text()
    assert "overall: n=2" in text
    assert "instrument" in text
    assert BTC in text
    assert ETH in text
    assert "book_exhausted=1" in text
