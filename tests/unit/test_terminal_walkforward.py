"""Exercise terminal configuration through actual multi-leg orchestration."""

import hashlib
from functools import partial

import pytest
from test_walkforward import HOUR, IDS, T0, _ConstMuSource
from test_walkforward import world as base_world

from alphaforge.analytics.walkforward import WalkForwardRunner
from alphaforge.backtest.terminal_engine import TerminalBacktester
from alphaforge.backtest.terminal_ledger import TerminalEvent


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    yield from base_world.__wrapped__(tmp_path_factory)


def runner(world, factory, binding):
    return WalkForwardRunner(
        world.reader,
        world.store,
        world.universe,
        world.cost_model,
        _ConstMuSource(),
        world.settings,
        cost_inputs=world.cost_inputs,
        engine_factory=factory,
        engine_research_config=binding,
    )


def test_actual_walkforward_retains_terminal_eligibility(world, tmp_path):
    source = tmp_path / "synthetic.json"
    source.write_text('{"synthetic":true}')
    event = TerminalEvent(
        instrument_id=IDS[0],
        effective_ts=T0 + int(450.5 * HOUR),
        price=100.0,
        fee_fraction=0.0005,
        basis="modeled",
        source_path=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    factory = partial(
        TerminalBacktester,
        terminal_events=[event],
        allow_modeled=True,
        carry_terminal_eligibility=True,
        funding_mark_policy="interval_open_proxy",
    )
    result = runner(world, factory, {"synthetic": True, "source_sha256": event.source_sha256}).run(
        T0, T0 + 900 * HOUR, train_bars=300, test_bars=200, rebalance_bars=24, cov_min_periods=120
    )
    assert len(result.legs) == 3
    assert len(result.legs[0].result.config["terminal_records"]) == 1
    assert all(not leg.result.config["terminal_records"] for leg in result.legs[1:])
    assert not (
        (result.fills.instrument_id == IDS[0]) & (result.fills.ts > event.effective_ts)
    ).any()
    assert sum(leg.result.counters.get("terminal_orders_blocked", 0) for leg in result.legs[1:]) > 0
    for prev, later in zip(result.legs, result.legs[1:], strict=False):
        assert later.result.equity.iloc[0] == pytest.approx(prev.result.equity.iloc[-1])
    assert result.config["research_engine"]["source_sha256"] == event.source_sha256


def test_engine_binding_precedes_signals(world):
    class Stop(Exception):
        pass

    class Log:
        def preflight_registration(self, config, reservation_path=None):
            assert config["research_engine"] == {"funding_mark_policy": "interval_open_proxy"}
            raise Stop

    research = runner(world, TerminalBacktester, {"funding_mark_policy": "interval_open_proxy"})
    with pytest.raises(Stop):
        research.run(
            T0, T0 + 900 * HOUR, train_bars=300, test_bars=200, now_ms=T0, experiment_log=Log()
        )


def test_factory_cannot_omit_registration_binding(world):
    with pytest.raises(ValueError, match="research configuration"):
        runner(world, TerminalBacktester, None)
