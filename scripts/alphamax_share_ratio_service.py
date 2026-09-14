"""Research-only feature substitution; no global registry or live engine mutation."""

from dataclasses import replace

from alphamax_share_ratio_features import share_ratio_close, share_ratio_sigma

from alphaforge.core.types import AssetClass
from alphaforge.features.context import long_series
from alphaforge.features.library.momentum import xs_momentum
from alphaforge.signals.service import _OPEN_SPEC, _SIGMA_SPEC, SignalService


def corrected_momentum(ctx, spec):
    adjusted = share_ratio_close(ctx.panel("close"), ctx.corporate_actions())
    return long_series(
        xs_momentum(adjusted, lookback=int(spec.params["lookback"]), skip=int(spec.params["skip"])),
        name=spec.name,
    )


def corrected_sigma(ctx, spec):
    return long_series(
        share_ratio_sigma(
            ctx.panel("close"), ctx.corporate_actions(), span=int(spec.params["span"])
        ),
        name=spec.name,
    )


def substituted_specs(alpha_specs, mode):
    if mode not in {"legacy", "momentum", "momentum_sigma"}:
        raise ValueError("unknown correction mode")
    if mode == "legacy":
        return [*alpha_specs, _SIGMA_SPEC, _OPEN_SPEC]
    if [s.name for s in alpha_specs] != ["eq_mom_252_21"]:
        raise ValueError("correction frozen for single AlphaMax momentum spec")
    alpha = replace(alpha_specs[0], fn=corrected_momentum)
    sigma = replace(_SIGMA_SPEC, fn=corrected_sigma) if mode == "momentum_sigma" else _SIGMA_SPEC
    return [alpha, sigma, _OPEN_SPEC]


class ShareRatioSignalService(SignalService):
    def __init__(self, *args, correction_mode, **kwargs):
        if kwargs["sleeve"].asset_class is not AssetClass.EQUITY:
            raise ValueError("equity research correction only")
        super().__init__(*args, **kwargs)
        self._correction_mode = correction_mode
        substituted_specs(self._alpha_specs, correction_mode)

    def _panel(self, start, end):
        if self._correction_mode == "legacy":
            return super()._panel(start, end)
        ids = self._window_ids(start, end)
        if not ids:
            raise ValueError("no members in correction window")
        specs = substituted_specs(self._alpha_specs, self._correction_mode)
        frame = self._engine.compute_history(specs, ids, start=start, end=end)
        mask = self._membership_mask(frame.index)
        return frame, mask, self._directional_zs(frame, mask)

    def on_bar_close(self, *args, **kwargs):
        raise RuntimeError("Research-only adapter; live correction not qualified")
