"""Per-strategy research covariance hook with durable engine results."""

from types import MethodType

from alphamax_replay_support_v2 import persisting_engine_factory
from alphamax_session_price_basis import session_close_panel


def install_covariance_basis(strategy, reader, mode):
    if mode not in {"legacy", "sessions", "sessions_splits"}:
        raise ValueError("unknown covariance basis")
    if mode == "legacy":
        return
    previous = getattr(strategy, "_research_covariance_basis", None)
    if previous is not None:
        if previous != (mode, id(reader)):
            raise ValueError("cannot change persistent strategy covariance basis")
        return

    def panel(self, ctx, ids):
        return session_close_panel(
            reader, ctx, ids, self._cov_window_bars + 1, correct_splits=mode == "sessions_splits"
        )

    strategy._close_panel = MethodType(panel, strategy)
    strategy._research_covariance_basis = (mode, id(reader))


def covariance_engine_factory(directory, mode):
    parent = persisting_engine_factory(directory)

    class CovarianceEngine(parent):
        def __init__(self, *args, **kwargs):
            echo = dict(kwargs["config_echo"])
            echo["covariance_basis"] = mode
            kwargs["config_echo"] = echo
            super().__init__(*args, **kwargs)

        def run(self, strategy, *args, **kwargs):
            install_covariance_basis(strategy, self._reader, mode)
            return super().run(strategy, *args, **kwargs)

    return CovarianceEngine
