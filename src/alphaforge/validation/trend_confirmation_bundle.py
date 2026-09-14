"""Research-only bundle with explicit direction-confirmation strategy selection."""

from alphaforge.config.sleeve import sleeve_for
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import default_registry
from alphaforge.portfolio.trend_direction_confirmation import ConfirmedDirectionStrategy
from alphaforge.research.zoo import register_mf_trend_grid
from alphaforge.signals.raw_label_trend import RawLabelTrendSignalService
from alphaforge.validation.trend_observation import ObservationError
from alphaforge.validation.trend_runner_bundle import TrendRunnerBundle


class DirectionConfirmationBundle(TrendRunnerBundle):
    def signal_service(self, store, settings, *, history_anchor):
        self.verify()
        self._bind_settings(settings)
        registry = default_registry()
        register_mf_trend_grid(registry)
        universe = UniverseStore(self.signal_paths)
        return RawLabelTrendSignalService(
            FeatureEngine(
                PITDataReader(self.signal_paths),
                store,
                universe,
                asset_class=settings.data.asset_class,
            ),
            universe,
            registry,
            settings.signals,
            alpha_names=["mf_trend_63", "mf_trend_126", "mf_trend_252"],
            sleeve=sleeve_for(settings.data.asset_class),
            history_anchor=history_anchor,
            raw_label_provider=self.provider,
            blend_normalization="cross_sectional_zscore",
        )

    def strategy(self, settings, signal_frame, **kwargs):
        self.verify()
        self._bind_settings(settings)
        if self._signals_digest is None or self._frame_digest(signal_frame) != self._signals_digest:
            raise ObservationError("Signal frame is not the bound runner output")
        return ConfirmedDirectionStrategy(
            settings,
            signal_frame=signal_frame,
            allocator="trend",
            signal_reader=PITDataReader(self.signal_paths),
            input_digest=self.binding["paired_input_sha256"],
            **kwargs,
        )
