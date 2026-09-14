from dataclasses import replace

import numpy as np
import pytest
from test_backtest_engine import make_instrument
from test_trend_runner_bundle import inputs

from alphaforge.backtest.engine import StaticCostInputs
from alphaforge.config.settings import Settings
from alphaforge.core.calendar import calendar_for
from alphaforge.core.instruments import InstrumentStore
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass, MarketType
from trend_group_risk_bundle import GroupComparisonBundle
from alphaforge.validation.trend_observation import ObservationError


def test_group_engine_cadence_and_raw_execution(tmp_path):
    paired, mapping, snapshots, start, end, sessions = inputs()
    rename=dict(zip('ABCDEF',['SPY','QQQ','SHY','IEF','FXE','GLD']))
    paired['symbol']=paired.symbol.map(rename)
    mapping={f'XUSE:CASH:{v}USD':v for v in rename.values()}
    snapshots={rename[k]:replace(v,symbol=rename[k]) for k,v in snapshots.items()}
    bundle = GroupComparisonBundle(
        paired,
        normalization="cross_sectional_zscore",
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
        original_allocator = strategy._group_allocator
        expected = []
        checked_nonflat = []

        class CheckedAllocator:
            @property
            def last_diagnostics(self):
                return original_allocator.last_diagnostics
            def solve_for_ids(self, ids, mu, covariance, previous, cost, shortable):
                np.testing.assert_allclose(previous, expected[-1], rtol=0, atol=0)
                checked_nonflat.append(bool(np.any(previous != 0)))
                return original_allocator.solve_for_ids(ids, mu, covariance, previous, cost, shortable)

        def checked_rebalance(ctx, mu):
            ids = sorted(ctx.instruments)
            raw_last = strategy._close_panel(ctx, ids).iloc[-1]
            expected.append(
                np.array(
                    [ctx.positions.get(iid, 0.0) * float(raw_last[iid]) / ctx.equity for iid in ids]
                )
            )
            return original_rebalance(ctx, mu)

        strategy._group_allocator = CheckedAllocator()
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

        assert len(strategy.group_risk_audit)==len(strategy.direction_audit)
        assert all(set(x['group_vol_before_limits'])=={'equity','rates','currency','commodity'} for x in strategy.group_risk_audit)
        assert len(strategy.direction_audit) >= 3
        cal = calendar_for(AssetClass.EQUITY)
        for before, after in zip(
            strategy.direction_audit, strategy.direction_audit[1:], strict=False
        ):
            expected_ts = before["ts"]
            for _ in range(10):
                expected_ts = cal.next_bar_open(expected_ts, Timeframe.D1)
            assert after["ts"] == expected_ts
        assert all(np.isfinite(result.equity))
