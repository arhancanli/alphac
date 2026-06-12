"""Parity & truncation-invariance verification — the anti-skew safeguards.

Two harnesses (dataDesign.md §7.5; this IS the deployed-path guarantee of leakage
finding 3):

* :func:`verify_parity` — for sampled historical decision times, compute features via
  the batch path (``compute_history``) and the live path (``compute_asof``) and assert
  they agree: **atol = 0** for finite-window specs (both paths are deterministic
  float64 over the same PIT data; ANY difference is a window/alignment bug), **1e-9
  relative** for specs flagged ``ewma_family`` (infinite-memory recursions truncated
  at ``lookback_bars >= 10·span``; buildabilityCritique.md §6.1). Run in CI and
  available to ops for nightly checks.

* :func:`verify_truncation` — the anti-lookahead / lookback-honesty harness every
  factor builder's tests call: the value at ``t`` computed from FULL history must
  equal the value at ``t`` computed from EXACTLY ``lookback_bars`` bars. A feature
  that secretly consumes more history than declared (expanding windows, full-sample
  normalization, centered windows) fails instantly, because the live minimal window
  cannot reproduce it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np

from alphaforge.core.time import Ms, bar_open_for_decision
from alphaforge.features.engine import ANCHOR_TIMEFRAME, FeatureEngine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from alphaforge.features.spec import FeatureSpec

__all__ = [
    "EWMA_PARITY_RTOL",
    "ParityReport",
    "SpecParityResult",
    "parity_tolerance",
    "verify_parity",
    "verify_truncation",
]

EWMA_PARITY_RTOL: Final[float] = 1e-9
"""Relative tolerance for EWMA-family specs (see module docstring); 0.0 otherwise."""


def parity_tolerance(spec: FeatureSpec) -> float:
    """The relative tolerance the parity contract grants ``spec``.

    ``0.0`` (exact, atol=0) for finite-window specs; :data:`EWMA_PARITY_RTOL` for
    specs with ``params["ewma_family"]`` truthy, whose ``lookback_bars >= 10·span``
    convention bounds the truncation error far below it.
    """
    return EWMA_PARITY_RTOL if spec.is_ewma_family else 0.0


@dataclass(frozen=True, slots=True, kw_only=True)
class SpecParityResult:
    """Comparison outcome for one spec across all sampled timestamps.

    ``max_abs_diff`` is the largest absolute difference over all compared points
    (``0.0`` when everything matched bit-for-bit or both sides were NaN; ``inf``
    when exactly one side was NaN — a warmup/window-sizing mismatch). A point
    passes if both sides are NaN, or ``|a - b| <= rtol * max(|a|, |b|)`` (which for
    ``rtol = 0`` demands exact equality).
    """

    name: str
    rtol: float
    n_points: int
    n_mismatched: int
    max_abs_diff: float

    @property
    def passed(self) -> bool:
        """True iff every compared point satisfied the spec's tolerance."""
        return self.n_mismatched == 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ParityReport:
    """Per-spec parity results; ``passed`` iff every spec passed."""

    results: tuple[SpecParityResult, ...]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def result(self, name: str) -> SpecParityResult:
        """The result for spec ``name``; ``KeyError`` if it was not verified."""
        for r in self.results:
            if r.name == name:
                return r
        raise KeyError(f"no parity result for spec {name!r}")


def verify_parity(
    engine: FeatureEngine,
    specs: Sequence[FeatureSpec],
    instrument_ids: Sequence[str],
    ts_samples: Sequence[Ms],
    *,
    history_start: Ms | None = None,
) -> ParityReport:
    """Batch-vs-live parity check at sampled decision times (epoch ms UTC).

    For each sample ``T``: the live row is ``compute_asof(as_of=T)`` (decision bar
    ``t* = bar_open_for_decision(T, 1h)``, minimal window); the batch value is read
    from ONE ``compute_history`` pass spanning all samples, starting at
    ``history_start`` (default: the earliest sampled ``t*``). With ``history_start``
    well before the samples, the batch side sees far more history than the live
    side's ``max(lookback_bars)`` window — exactly the asymmetry the parity contract
    must survive. Tolerance per spec via :func:`parity_tolerance`.
    """
    if not ts_samples:
        raise ValueError("at least one ts_sample is required")
    tf = ANCHOR_TIMEFRAME
    spec_list = list(specs)
    ids = list(dict.fromkeys(instrument_ids))
    t_stars = sorted({bar_open_for_decision(t, tf) for t in ts_samples})
    start = t_stars[0] if history_start is None else history_start
    if start > t_stars[0]:
        raise ValueError(
            f"history_start={start} is after the earliest sampled decision bar {t_stars[0]}"
        )
    history = engine.compute_history(spec_list, ids, start=start, end=t_stars[-1] + tf.ms)

    n_points = {s.name: 0 for s in spec_list}
    n_mismatched = {s.name: 0 for s in spec_list}
    max_abs_diff = {s.name: 0.0 for s in spec_list}

    for t_star in t_stars:
        live = engine.compute_asof(spec_list, ids, as_of=t_star + tf.ms)
        for spec in spec_list:
            rtol = parity_tolerance(spec)
            live_col = live[spec.name]
            hist_col = history[spec.name].reindex(live_col.index)
            a = live_col.to_numpy(dtype="float64")
            b = hist_col.to_numpy(dtype="float64")
            both_nan = np.isnan(a) & np.isnan(b)
            raw_diff = np.abs(a - b)  # NaN where exactly one side is NaN
            diff = np.where(both_nan, 0.0, raw_diff)
            diff = np.where(np.isnan(diff), np.inf, diff)
            scale = np.maximum(np.abs(a), np.abs(b))
            with np.errstate(invalid="ignore"):
                ok = both_nan | (diff <= rtol * np.where(np.isfinite(scale), scale, 0.0))
            n_points[spec.name] += int(a.size)
            n_mismatched[spec.name] += int(np.count_nonzero(~ok))
            if a.size:
                max_abs_diff[spec.name] = max(max_abs_diff[spec.name], float(diff.max()))

    results = tuple(
        SpecParityResult(
            name=spec.name,
            rtol=parity_tolerance(spec),
            n_points=n_points[spec.name],
            n_mismatched=n_mismatched[spec.name],
            max_abs_diff=max_abs_diff[spec.name],
        )
        for spec in spec_list
    )
    return ParityReport(results=results)


def verify_truncation(
    engine: FeatureEngine,
    spec: FeatureSpec,
    instrument_ids: Sequence[str],
    ts_samples: Sequence[Ms],
    *,
    history_start: Ms,
) -> ParityReport:
    """Truncation invariance for ONE spec: full history vs exactly ``lookback_bars``.

    The full-history value comes from ``compute_history(start=history_start, ...)``
    (pass the earliest timestamp your lake covers, or anything well before
    ``min(ts_samples) - lookback_bars·Δ``); the truncated value comes from
    ``compute_asof`` with ONLY this spec — whose minimal window is then exactly
    ``spec.lookback_bars`` bars. Disagreement (beyond the spec's declared
    tolerance) proves the function consumes history beyond its declaration — the
    live path would silently produce different values than research. This is the
    harness every registered factor's tests must call (alphaDesign.md §12
    safeguard 1). ``history_start`` is explicit and mandatory: a default equal to
    the sample window would make the test vacuous.
    """
    if not math.isfinite(float(history_start)):
        raise ValueError("history_start must be a finite epoch-ms timestamp")
    return verify_parity(engine, [spec], instrument_ids, ts_samples, history_start=history_start)
