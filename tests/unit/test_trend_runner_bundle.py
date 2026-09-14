from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from test_backtest_engine import make_instrument

from alphaforge.backtest.engine import StaticCostInputs
from alphaforge.config.settings import Settings
from alphaforge.core.calendar import calendar_for
from alphaforge.core.instruments import InstrumentStore
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.validation.trend_observation import ObservationError
from alphaforge.validation.trend_price_bridge import Action, ActionSnapshot
from alphaforge.validation.trend_runner_bundle import TrendRunnerBundle


def inputs():
    start = int(pd.Timestamp("2024-01-02", tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp("2025-09-01", tz="UTC").timestamp() * 1000)
    sessions = list(calendar_for(AssetClass.EQUITY).expected_bar_opens(start, end, Timeframe.D1))
    rows = []
    mapping = {f"XUSE:CASH:{s}USD": s for s in "ABCDEF"}
    for i, symbol in enumerate("ABCDEF"):
        rng = np.random.default_rng(400 + i)
        prices = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.008, len(sessions))))
        for t, price in zip(sessions, prices, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "session_ms": t,
                    "raw_volume": 1000000.0,
                    "price_disputed": False,
                    **{
                        f"{basis}_{f}": float(price * scale)
                        for basis, scale in [("raw", 1.0), ("signal", i + 2.0)]
                        for f in ["open", "high", "low", "close"]
                    },
                }
            )
    snapshots = {s: ActionSnapshot(s, start, end, start, "a" * 64, True, ()) for s in "ABCDEF"}
    return pd.DataFrame(rows), mapping, snapshots, start, end, sessions


def test_complete_controlled_runner(tmp_path):
    paired, mapping, snapshots, start, end, sessions = inputs()
    bundle = TrendRunnerBundle(
        paired,
        instrument_symbols=mapping,
        snapshots=snapshots,
        payments=[],
        mode="DIAGNOSTIC_CURRENT_VINTAGE",
    )
    bundle.prepare(tmp_path / "bundle")
    settings = Settings()
    settings = settings.model_copy(
        update={"data": settings.data.model_copy(update={"asset_class": AssetClass.EQUITY})}
    )
    with InstrumentStore(tmp_path / "ops.sqlite") as store:
        for iid, s in mapping.items():
            inst = replace(
                make_instrument("BINANCE:PERP:BTCUSDT"),
                instrument_id=iid,
                asset_class=AssetClass.EQUITY,
                market_type=MarketType.CASH,
                base=s,
                quote="USD",
                funding_interval_hours=None,
            )
            store.upsert(inst, as_of=1)
        service = bundle.signal_service(store, settings, history_anchor=start)
        signals = bundle.compute_signals(
            store, settings, history_anchor=start, start=start, end=end
        )
        assert np.isfinite(signals.mu_ann).sum() > 100
        tampered = signals.copy()
        tampered.loc[:, "mu_ann"] = 0.0
        with pytest.raises(ObservationError, match="bound runner output"):
            bundle.strategy(settings, tampered)
        other_settings = settings.model_copy(
            update={"signals": settings.signals.model_copy(update={"horizon_bars": 22})}
        )
        with pytest.raises(ObservationError, match="settings differ"):
            bundle.engine(store, other_settings)
        strategy = bundle.strategy(
            settings, signals, rebalance_bars=10, cov_window_bars=300, cov_min_periods=240
        )
        original_rebalance = strategy._rebalance
        original_allocator = strategy._allocator
        expected = []
        checked_nonflat = []

        class CheckedAllocator:
            def solve(self, mu, covariance, previous, cost, shortable):
                np.testing.assert_allclose(previous, expected[-1], rtol=0, atol=0)
                checked_nonflat.append(bool(np.any(previous != 0)))
                return original_allocator.solve(mu, covariance, previous, cost, shortable)

        def checked_rebalance(ctx, mu):
            ids = sorted(ctx.instruments)
            raw_last = strategy._close_panel(ctx, ids).iloc[-1]
            expected.append(
                np.array(
                    [ctx.positions.get(iid, 0.0) * float(raw_last[iid]) / ctx.equity for iid in ids]
                )
            )
            return original_rebalance(ctx, mu)

        strategy._allocator = CheckedAllocator()
        strategy._rebalance = checked_rebalance
        result = bundle.engine(
            store, settings, cost_inputs=StaticCostInputs(adv_quote=1e8, sigma_daily=0.02)
        ).run(strategy, list(mapping), start=sessions[300], end=end)
        assert len(result.fills) > 0
        assert any(checked_nonflat)
        # Execution must use raw opens, never the synthetic scale multiples.
        raw = paired.set_index(["symbol", "session_ms"])
        for row in result.fills.itertuples():
            price = raw.loc[(mapping[row.instrument_id], row.ts), "raw_open"]
            assert abs(row.price / price - 1) < 0.02
        assert result.config["paired_runner_binding"] == bundle.binding
        assert (
            service.trial_binding["raw_label_input_sha256"]
            == bundle.provider.binding["raw_label_input_sha256"]
        )


def test_disputed_data_block_before_writes(tmp_path):
    paired, mapping, snapshots, _, _, _ = inputs()
    paired.loc[0, "price_disputed"] = True
    with pytest.raises(ObservationError, match="Unresolved"):
        TrendRunnerBundle(
            paired,
            instrument_symbols=mapping,
            snapshots=snapshots,
            payments=[],
            mode="DIAGNOSTIC_CURRENT_VINTAGE",
        )
    assert not list(tmp_path.iterdir())


def test_staged_input_mutation_fails(tmp_path):
    paired, mapping, snapshots, _, _, _ = inputs()
    bundle = TrendRunnerBundle(
        paired,
        instrument_symbols=mapping,
        snapshots=snapshots,
        payments=[],
        mode="DIAGNOSTIC_CURRENT_VINTAGE",
    )
    bundle.prepare(tmp_path / "bundle")
    bundle.verify()
    path = next((tmp_path / "bundle").rglob("*.parquet"))
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ObservationError, match="changed"):
        bundle.verify()


def test_missing_payment_schedule_blocks_preparation():
    paired, mapping, snapshots, _, _, sessions = inputs()
    snapshots["A"] = replace(
        snapshots["A"],
        actions=(
            Action(
                "div",
                "A",
                sessions[30],
                "dividend",
                1.0,
            ),
        ),
    )
    with pytest.raises(ObservationError, match="complete dividend payment"):
        TrendRunnerBundle(
            paired,
            instrument_symbols=mapping,
            snapshots=snapshots,
            payments=[],
            mode="DIAGNOSTIC_CURRENT_VINTAGE",
        )


def test_diagnostic_input_cannot_claim_prospective_readiness():
    paired, mapping, snapshots, _, _, _ = inputs()
    with pytest.raises(ObservationError, match="diagnostic only"):
        TrendRunnerBundle(
            paired, instrument_symbols=mapping, snapshots=snapshots, payments=[], mode="PROSPECTIVE"
        )
