import hashlib
from dataclasses import replace

import pytest
from test_backtest_engine import make_instrument

from alphaforge.backtest.terminal_ledger import TerminalEvent, TerminalLedger
from alphaforge.core.types import Fill, Liquidity, Side


def setup(tmp_path, **overrides):
    inst = make_instrument("BINANCE:PERP:BTCUSDT")
    source = tmp_path / "source.json"
    source.write_text('{"basis":"synthetic unit test only"}')
    values = {
        "instrument_id": inst.instrument_id,
        "effective_ts": 100,
        "price": 10.0,
        "fee_fraction": 0.01,
        "basis": "modeled",
        "source_path": source,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    values.update(overrides)
    event = TerminalEvent(**values)
    ledger = TerminalLedger(1000.0, {inst.instrument_id: inst}, events=[event], allow_modeled=True)
    fill = Fill(
        client_order_id="entry",
        instrument_id=inst.instrument_id,
        side=Side.BUY,
        qty=2.0,
        price=100.0,
        fee_quote=1.0,
        liquidity=Liquidity.TAKER,
        ts=10,
    )
    return ledger, event, fill, inst


@pytest.mark.parametrize("side,expected", [(Side.BUY, 818.8), (Side.SELL, 1178.8)])
def test_settlement_preserves_signed_profit_loss_and_explicit_fees(tmp_path, side, expected):
    ledger, event, fill, _ = setup(tmp_path)
    ledger.apply_fill(replace(fill, side=side))
    assert ledger.settle_at(event.instrument_id, 100)
    assert not ledger.positions()
    assert ledger.mark({}, 100).equity_quote == pytest.approx(expected)
    assert not ledger.settle_at(event.instrument_id, 100)
    assert len(ledger.terminal_records) == 1
    for ts in [99, 100, 101]:
        with pytest.raises(ValueError, match="terminated"):
            ledger.apply_fill(replace(fill, ts=ts))


def test_missing_boundary_cannot_be_skipped_or_priced_at_last_mark(tmp_path):
    ledger, event, fill, _ = setup(tmp_path)
    ledger.apply_fill(fill)
    with pytest.raises(ValueError, match="boundary"):
        ledger.mark({event.instrument_id: 999.0}, 101)
    with pytest.raises(ValueError, match="exact"):
        ledger.settle_at(event.instrument_id, 101)
    assert ledger.positions()[event.instrument_id].qty == 2.0


def test_source_tampering_fails_before_cash_or_position_changes(tmp_path):
    ledger, event, fill, _ = setup(tmp_path)
    ledger.apply_fill(fill)
    event.source_path.write_text("tampered")
    with pytest.raises(ValueError, match="hash"):
        ledger.settle_at(event.instrument_id, 100)
    assert ledger.positions()[event.instrument_id].qty == 2.0
    assert not ledger.terminal_records


def test_modeled_price_requires_explicit_opt_in_and_flat_contract_stays_closed(tmp_path):
    ledger, event, fill, inst = setup(tmp_path)
    with pytest.raises(ValueError, match="opt-in"):
        TerminalLedger(1000.0, {inst.instrument_id: inst}, events=[event])
    assert ledger.settle_at(event.instrument_id, 100)
    assert ledger.mark({}, 100).equity_quote == 1000.0
    with pytest.raises(ValueError):
        ledger.apply_fill(replace(fill, ts=100))


@pytest.mark.parametrize("price", [float("nan"), float("inf"), 0.0, -1.0])
def test_invalid_settlement_price_rejected(tmp_path, price):
    with pytest.raises(ValueError, match="price"):
        setup(tmp_path, price=price)


def test_funding_cannot_cross_unprocessed_boundary_or_be_backdated(tmp_path):
    ledger, event, fill, _ = setup(tmp_path)
    ledger.apply_fill(fill)
    cash = ledger.cash
    with pytest.raises(ValueError, match="boundary"):
        ledger.apply_funding(event.instrument_id, 101, 0.01, 10.0)
    assert ledger.cash == cash
    ledger.settle_at(event.instrument_id, 100)
    assert ledger.apply_funding(event.instrument_id, 101, 0.01, 10.0) == 0.0
    with pytest.raises(ValueError, match="before"):
        ledger.apply_funding(event.instrument_id, 99, 0.01, 10.0)


def test_multiple_terminal_boundaries_must_be_processed_in_order(tmp_path):
    _, event, _, inst = setup(tmp_path)
    other = make_instrument("BINANCE:PERP:ETHUSDT")
    later = replace(event, instrument_id=other.instrument_id, effective_ts=200)
    ledger = TerminalLedger(
        1000.0,
        {inst.instrument_id: inst, other.instrument_id: other},
        events=[event, later],
        allow_modeled=True,
    )
    with pytest.raises(ValueError, match="Earlier"):
        ledger.settle_at(other.instrument_id, 200)
    assert ledger.terminal_records == []
    ledger.settle_at(inst.instrument_id, 100)
    ledger.settle_at(other.instrument_id, 200)
    assert len(ledger.terminal_records) == 2
