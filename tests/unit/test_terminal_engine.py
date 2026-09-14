"""Synthetic execution proofs; no historical settlement-price claims."""

import hashlib

import pandas as pd
import pytest
from test_backtest_engine import BTC, ETH, HOUR, T0, bar_row, build_engine, make_instrument

from alphaforge.backtest.engine import ScriptedStrategy
from alphaforge.backtest.terminal_engine import TerminalBacktester
from alphaforge.backtest.terminal_ledger import TerminalEvent


def make_case(tmp_path, *, event_offset=2.5, funding_offsets=(2.25, 2.75), with_event=True):
    bars = [
        bar_row(iid, T0 + k * HOUR, open_=100, close=100) for k in range(5) for iid in (BTC, ETH)
    ]
    parent = build_engine(
        tmp_path,
        bars,
        [(BTC, T0 + int(k * HOUR), 0.01) for k in funding_offsets],
        [make_instrument(BTC), make_instrument(ETH)],
    )
    source = tmp_path / "synthetic.json"
    source.write_text('{"synthetic":true}')
    event = TerminalEvent(
        instrument_id=BTC,
        effective_ts=T0 + int(event_offset * HOUR),
        price=10.0,
        fee_fraction=0.01,
        basis="modeled",
        source_path=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    engine = TerminalBacktester(
        parent._reader,
        parent._instruments,
        parent._cost_model,
        cost_inputs=parent._cost_inputs,
        terminal_events=[event] if with_event else [],
        allow_modeled=True,
    )
    return parent, engine, event


def replay(engine):
    return engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.1}, T0 + 3 * HOUR: {BTC: 0.1, ETH: 0.1}}),
        [BTC, ETH],
        start=T0,
        end=T0 + 5 * HOUR,
        initial_cash=100_000.0,
    )


def test_intrabar_loss_funding_and_later_order_block(tmp_path):
    _, engine, event = make_case(tmp_path)
    result = replay(engine)
    btc = result.fills[result.fills.instrument_id == BTC]
    assert len(btc) == 2
    entry, terminal = btc.iloc[0], btc.iloc[1]
    assert terminal.ts == event.effective_ts
    assert terminal.reason == "administrative_terminal_settlement"
    assert terminal.price == 10.0
    assert terminal.qty == entry.qty
    assert terminal.realized_pnl_quote == pytest.approx(entry.qty * (10 - entry.price))
    assert terminal.fee == pytest.approx(entry.qty * 10 * 0.01)
    assert len(result.funding_events) == 1
    assert result.funding_events.iloc[0].ts_funding == T0 + int(2.25 * HOUR)
    assert result.counters["terminal_orders_blocked"] == 1
    assert len(result.config["terminal_records"]) == 1
    # At hour 3, only entry, pre-terminal funding and administrative close affect cash.
    expected = 100_000 - entry.qty * entry.price - entry.fee - entry.qty * 100 * 0.01
    expected += entry.qty * 10 - terminal.fee
    assert result.equity.loc[T0 + 3 * HOUR] == pytest.approx(expected)
    assert len(result.fills[result.fills.instrument_id == ETH]) == 1


def test_no_event_parent_parity(tmp_path):
    parent, engine, _ = make_case(tmp_path, with_event=False)
    a, b = replay(parent), replay(engine)
    pd.testing.assert_series_equal(a.equity, b.equity)
    pd.testing.assert_frame_equal(a.fills, b.fills)
    pd.testing.assert_frame_equal(a.funding_events, b.funding_events)
    pd.testing.assert_frame_equal(a.positions, b.positions)
    assert a.counters == b.counters


def test_coincident_funding_fails_explicitly(tmp_path):
    _, engine, _ = make_case(tmp_path, funding_offsets=(2.5,))
    with pytest.raises(ValueError, match="tie policy"):
        replay(engine)


@pytest.mark.parametrize("offset", [2.0, 3.0, 5.0])
def test_aligned_and_end_boundary_settle(tmp_path, offset):
    _, engine, event = make_case(tmp_path, event_offset=offset, funding_offsets=())
    result = replay(engine)
    assert len(result.config["terminal_records"]) == 1
    btc = result.fills[result.fills.instrument_id == BTC]
    assert btc.iloc[-1].ts == event.effective_ts


@pytest.mark.parametrize("offset", [0.0, 6.0])
def test_out_of_range_event_rejected(tmp_path, offset):
    _, engine, _ = make_case(tmp_path, event_offset=offset)
    with pytest.raises(ValueError, match="after start"):
        replay(engine)


def test_explicit_open_funding_control_changes_only_funding_cash(tmp_path):
    bars = [bar_row(BTC, T0 + k * HOUR, open_=100, close=120 if k == 2 else 100) for k in range(4)]
    parent = build_engine(
        tmp_path, bars, [(BTC, T0 + int(2.5 * HOUR), 0.01)], [make_instrument(BTC)]
    )
    results = []
    for policy in ["parent_interval_close", "interval_open_proxy"]:
        engine = TerminalBacktester(
            parent._reader,
            parent._instruments,
            parent._cost_model,
            cost_inputs=parent._cost_inputs,
            funding_mark_policy=policy,
        )
        results.append(
            engine.run(
                ScriptedStrategy({T0 + HOUR: {BTC: 0.1}}), [BTC], start=T0, end=T0 + 4 * HOUR
            )
        )
    a, b = results
    pd.testing.assert_frame_equal(a.fills, b.fills)
    assert a.funding_events.iloc[0].mark_price == 120
    assert b.funding_events.iloc[0].mark_price == 100
    assert b.equity.iloc[-1] - a.equity.iloc[-1] == pytest.approx(20.0)


def test_later_flat_leg_keeps_block_without_duplicate_settlement(tmp_path):
    _, engine, event = make_case(tmp_path, event_offset=2.5, funding_offsets=())
    engine.carry_terminal_eligibility = True
    first = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.1}}), [BTC, ETH], start=T0, end=T0 + 3 * HOUR
    )
    cash = float(first.equity.iloc[-1])
    later = engine.run(
        ScriptedStrategy({T0 + 4 * HOUR: {BTC: 0.1, ETH: 0.1}}),
        [BTC, ETH],
        start=T0 + 3 * HOUR,
        end=T0 + 5 * HOUR,
        initial_cash=cash,
    )
    assert len(first.config["terminal_records"]) == 1
    assert later.config["terminal_records"] == []
    assert later.equity.iloc[0] == cash
    assert later.counters["terminal_orders_blocked"] == 1
    assert list(later.fills.instrument_id) == [ETH]
    event.source_path.write_text("tampered")
    with pytest.raises(ValueError, match="hash"):
        engine.run(ScriptedStrategy({}), [BTC, ETH], start=T0 + 3 * HOUR, end=T0 + 5 * HOUR)


def test_future_terminal_does_not_block_earlier_leg(tmp_path):
    parent, engine, _ = make_case(tmp_path, funding_offsets=())
    engine.carry_terminal_eligibility = True
    outputs = [
        e.run(ScriptedStrategy({T0 + HOUR: {BTC: 0.1}}), [BTC, ETH], start=T0, end=T0 + 2 * HOUR)
        for e in [parent, engine]
    ]
    pd.testing.assert_frame_equal(outputs[0].fills, outputs[1].fills)
    pd.testing.assert_series_equal(outputs[0].equity, outputs[1].equity)
    assert len(outputs[1].fills) == 1
    assert outputs[1].config["terminal_records"] == []
