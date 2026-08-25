"""SignalService — THE alpha→portfolio seam (alphaDesign.md §9; leakage finding 2).

One class, two windows, one function body — the same anti-skew shape as
:class:`~alphaforge.features.engine.FeatureEngine`:

* **Research/batch** — :meth:`SignalService.compute_research`::

      FeatureEngine.compute_history (directional alpha specs + sigma_hat + open)
        → CSPipeline (winsorize → zscore) under the PIT universe mask
        → x FeatureSpec.direction                       ⇒ z_{k,i,t}
        → execution-aware forward returns (§5.1)        ⇒ y_{i,t,h}   (labels!)
        → per-alpha Rank-IC on the non-overlapping h-grid, LAGGED
          (RIC at t enters only where t' + h·Δ <= t — fully realized)
        → EWMA-IC blend weights, re-estimated AT EVERY GRID POINT  ⇒ w_k(t)
        → A = Σ w·z, Ã = cs_zscore(A)                   ⇒ alpha_blend
        → Grinold sizing                                ⇒ mu_ann

  Weights at ``t`` use ICs through ``t`` only — there is NO full-sample weight
  vector anywhere, so the research output is walk-forward-correct by
  construction (alphaDesign.md §9.1; docs §10.4).

* **Live** — :meth:`SignalService.on_bar_close`: the identical chain via
  ``compute_asof`` at one decision instant, with the latest caller-supplied
  :class:`~alphaforge.signals.blending.BlendWeights`. PARITY IS THE CONTRACT:
  at the same decision bar (and with the same weights) the live row must equal
  the research row — exactly for finite-window alphas, to the EWMA parity
  tolerance (1e-9 relative) where sigma_hat's truncated live window differs.

The service persists NOTHING and holds no mutable state: both methods are pure
functions of (lake, universe store, registry, cfg, arguments). The caller (the
live loop / research runner) persists predictions and the estimated weights.

THE μ CONTRACT (finding 2): the output column is literally named ``mu_ann`` =
``mu_h · (8760/h)`` with ``h = SignalsCfg.horizon_bars`` — the ONE horizon
constant shared with the portfolio layer (buildabilityCritique.md §3.10). See
:mod:`alphaforge.signals.sizing`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd
import pyarrow as pa

from alphaforge.config.sleeve import CRYPTO_PERP_SLEEVE, Sleeve
from alphaforge.core.time import Ms, bar_open_for_decision
from alphaforge.features.context import FeatureContext, long_series
from alphaforge.features.cross_section import CSPipeline
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library.vol import EWMA_HEADROOM_SPANS, EWMA_VOL_SPAN, ewma_vol
from alphaforge.features.spec import Family, FeatureSpec
from alphaforge.labeling import forward_returns
from alphaforge.signals.blending import (
    ALPHA_BLEND_COLUMN,
    BlendWeights,
    blend,
    estimate_blend_weights,
)
from alphaforge.signals.sizing import MU_ANN_COLUMN, GrinoldSizer
from alphaforge.validation.metrics import non_overlapping, rank_ic

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from alphaforge.config.settings import SignalsCfg
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.registry import FeatureRegistry

__all__ = ["SIGMA_COLUMN", "SignalService"]

SIGMA_COLUMN: Final[str] = "sigma_ewma_168"
"""Engine column name of the per-bar Grinold sigma_hat (EWMA span 168, zero-mean)."""

_OPEN_COLUMN: Final[str] = "open_px"
"""Engine column name of the raw open price (label construction only — the open
panel never feeds a signal; it exists so the §5.1 label is built from the SAME
PIT window the alphas saw)."""


def _sigma_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Per-bar EWMA sigma_hat of 1h log returns — thin adapter over the ONE sanctioned
    body :func:`alphaforge.features.library.vol.ewma_vol` (zero-mean,
    ``λ = 2/(span+1)``, ``min_periods = span``)."""
    return long_series(ewma_vol(ctx.panel("close"), span=int(spec.params["span"])), name=spec.name)


def _open_px_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Identity open price on the complete expected grid (plumbing, not an alpha)."""
    return long_series(ctx.panel("open"), name=spec.name)


_SIGMA_SPEC: Final[FeatureSpec] = FeatureSpec(
    name=SIGMA_COLUMN,
    family=Family.VOLATILITY,
    direction=0,
    cross_sectional=False,
    lookback_bars=EWMA_HEADROOM_SPANS * EWMA_VOL_SPAN,
    params={"ewma_family": True, "span": EWMA_VOL_SPAN},
    fn=_sigma_fn,
)

_OPEN_SPEC: Final[FeatureSpec] = FeatureSpec(
    name=_OPEN_COLUMN,
    family=Family.MARKET,
    direction=0,
    cross_sectional=False,
    lookback_bars=1,
    params={},
    fn=_open_px_fn,
)


class SignalService:
    """The seam class both research and live consume (module docstring).

    Args:
        engine: The Phase-4 feature engine (PIT windows, parity machinery).
        universe: PIT membership store — every cross-sectional statistic and
            every IC is computed over members-as-of only.
        registry: Feature registry the alpha specs are resolved from.
        cfg: ``SignalsCfg`` — supplies THE horizon constant ``horizon_bars``
            and ``ic_target`` (finding 2 / buildability §3.10).
        alpha_names: Directional alphas to blend; default = every registered
            spec with ``direction != 0``, in registration order (deterministic).
        pipeline: Cross-sectional chain for ``cross_sectional=True`` alphas
            (default winsorize → zscore). ``cross_sectional=False`` alphas
            (e.g. vol-normalized TS-momentum) pass through mask-only.
        min_members: Minimum cross-section size for z-scores and Rank-ICs.
        sleeve: The asset-class sleeve supplying the anchor timeframe + calendar
            (the ONE grid/annualization source, SPINE_ARC §3.6). Default
            :data:`~alphaforge.config.sleeve.CRYPTO_PERP_SLEEVE` (H1 + 24/7) keeps the
            crypto path byte-identical: the anchor TF is H1 and the annualization basis
            ``calendar.periods_per_year(H1) == 8760.0 == Timeframe.H1.bars_per_year``.
    """

    def __init__(
        self,
        engine: FeatureEngine,
        universe: UniverseStore,
        registry: FeatureRegistry,
        cfg: SignalsCfg,
        *,
        alpha_names: Sequence[str] | None = None,
        pipeline: CSPipeline | None = None,
        min_members: int = 5,
        sleeve: Sleeve = CRYPTO_PERP_SLEEVE,
    ) -> None:
        if alpha_names is None:
            specs = [s for s in registry.all_specs() if s.direction != 0]
        else:
            specs = [registry.get(name) for name in alpha_names]
        if not specs:
            raise ValueError("SignalService requires at least one directional alpha spec")
        for spec in specs:
            if spec.direction == 0:
                raise ValueError(
                    f"spec {spec.name!r} has direction=0 — not a directional alpha; "
                    "only direction=±1 specs may enter the blend"
                )
            if spec.name in (SIGMA_COLUMN, _OPEN_COLUMN):
                raise ValueError(
                    f"alpha name {spec.name!r} collides with a SignalService helper column"
                )
        self._engine = engine
        self._universe = universe
        self._cfg = cfg
        self._alpha_specs: tuple[FeatureSpec, ...] = tuple(specs)
        self._pipeline = pipeline if pipeline is not None else CSPipeline()
        self._min_members = min_members
        # Sleeve-resolved anchor TF + calendar — the ONE grid/annualization source.
        # Crypto (H1 + 24/7) reduces to the prior ANCHOR_TIMEFRAME==H1 / bars_per_year
        # path byte-identically (periods_per_year(H1) == 8760.0).
        self._anchor_tf = sleeve.anchor_tf
        self._calendar = sleeve.calendar
        self._periods_per_year = sleeve.periods_per_year()
        self._sizer = GrinoldSizer.from_cfg(
            cfg, timeframe=self._anchor_tf, periods_per_year=self._periods_per_year
        )

    @property
    def alpha_names(self) -> tuple[str, ...]:
        """Blended alphas, in blend-column order."""
        return tuple(s.name for s in self._alpha_specs)

    # ------------------------------------------------------------ research path

    def compute_research(self, start: Ms, end: Ms) -> pd.DataFrame:
        """Batch signal history over ``[start, end)`` (module docstring chain).

        Returns a float frame indexed by the complete ``(ts_open, instrument_id)``
        grid of the window x the union of point-in-time universe members over it,
        with columns ``alpha_blend`` and ``mu_ann``. Non-members (per timestamp)
        are NaN; cold-start rows (before the first fully-realized IC) use equal
        blend weights (documented in :mod:`alphaforge.signals.blending`).
        """
        frame, mask, zs = self._panel(start, end)
        weights = self._weights_from_panel(frame, mask, zs)
        return self._emit(frame, mask, zs, weights)

    def estimate_weights(self, start: Ms, end: Ms) -> BlendWeights:
        """The walk-forward :class:`BlendWeights` estimated over ``[start, end)``.

        The live loop persists this object (the service itself persists nothing)
        and feeds its latest row to :meth:`on_bar_close` via ``weights=``.
        """
        frame, mask, zs = self._panel(start, end)
        return self._weights_from_panel(frame, mask, zs)

    # ------------------------------------------------------------ live path

    def on_bar_close(self, as_of: Ms, *, weights: BlendWeights | None = None) -> pd.DataFrame:
        """One live decision row per universe member at ``as_of`` (epoch-ms UTC).

        The decision bar is ``t* = bar_open_for_decision(as_of, anchor_tf)`` (the
        sleeve's anchor TF, ``1h`` for the crypto sleeve); the
        cross-section is the PIT membership at ``t*``. ``weights`` is the latest
        stored/recomputed :class:`BlendWeights` (from :meth:`estimate_weights` /
        :meth:`compute_research`); ``None`` = documented cold start, equal
        weights. ``weights.asof(t*)`` picks the step-function row, so a weights
        object estimated through any ``end >= t*`` reproduces research exactly.

        Returns a float frame indexed by ``instrument_id`` with columns
        ``alpha_blend`` and ``mu_ann`` — and it MUST equal the research rows at
        the same ``t*`` (exactly for finite-window alphas; 1e-9 relative where
        the EWMA sigma_hat truncation convention applies). That parity is the deployed
        contract, enforced by the seam tests.
        """
        t_star = bar_open_for_decision(as_of, self._anchor_tf)
        members = sorted(self._universe.membership_asof(t_star))
        if not members:
            raise ValueError(f"universe is empty at decision bar {t_star} (as_of={as_of})")
        specs = [*self._alpha_specs, _SIGMA_SPEC]
        frame = self._engine.compute_asof(specs, members, as_of=as_of)
        mask = pd.Series(True, index=frame.index)  # ids ARE the members at t*
        zs = self._directional_zs(frame, mask)
        bw = weights if weights is not None else BlendWeights.equal(self.alpha_names)
        out = self._emit(frame, mask, zs, bw)
        return out.droplevel("ts_open")

    # ------------------------------------------------------------ internals

    def _panel(self, start: Ms, end: Ms) -> tuple[pd.DataFrame, pd.Series, Mapping[str, pd.Series]]:
        """(engine frame, PIT membership mask, processed directional z panel)."""
        ids = self._window_ids(start, end)
        if not ids:
            raise ValueError(f"no universe members overlap the window [{start}, {end})")
        specs = [*self._alpha_specs, _SIGMA_SPEC, _OPEN_SPEC]
        frame = self._engine.compute_history(specs, ids, start=start, end=end)
        assert isinstance(frame.index, pd.MultiIndex)  # engine index contract; mypy aid
        mask = self._membership_mask(frame.index)
        return frame, mask, self._directional_zs(frame, mask)

    def _weights_from_panel(
        self, frame: pd.DataFrame, mask: pd.Series, zs: Mapping[str, pd.Series]
    ) -> BlendWeights:
        """Rolling blend weights: per-alpha Rank-IC vs the §5.1 label, subsampled
        to the non-overlapping h-grid, lag-enforced inside
        :func:`estimate_blend_weights` (only ``t' + h·Δ <= t`` enters ÎC_t)."""
        h = self._cfg.horizon_bars
        bars = frame[_OPEN_COLUMN].dropna().rename("open").reset_index()
        fwd = forward_returns(bars, h, timeframe=self._anchor_tf, calendar=self._calendar).reindex(
            frame.index
        )
        # ABSOLUTE-grid subsampling (delta_ms = the 1h bar width): the kept IC
        # timestamps are pinned to a venue-fixed bar grid, NOT to this window's
        # own first bar. That makes the rolling blend weights SLICE-INVARIANT, so
        # the walk-forward's global-compute-and-slice path reproduces the per-leg
        # path's decisions to the EWMA warm-up tolerance (the global pass, having
        # more realized-IC history before each leg, is the MORE-correct reference).
        # CONTIGUOUS grid (crypto 24/7): epoch-fixed phase ((ts//Δ)%h==0) -> slice-invariant
        # blend weights (the comment above). GAPPY session grid (XNYS): (ts//Δ) skips
        # weekend/holiday indices, so the epoch anchor would NOT keep every h-th session;
        # use the POSITIONAL subsample (every h-th unique SESSION from the window start),
        # which is the correct non-overlapping h-session grid. The research WF is a single
        # global compute_research, so the positional phase is consistent across the run; a
        # session-INDEX absolute anchor (for equity-live per-leg slice-invariance) is a
        # deferred refinement (no equity live path yet).
        contiguous = self._calendar.contiguous
        delta = self._anchor_tf.ms if contiguous else None
        grid_ics = {
            name: non_overlapping(
                rank_ic(zs[name], fwd, mask, min_members=self._min_members), h, delta_ms=delta
            )
            for name in self.alpha_names
        }
        return estimate_blend_weights(
            grid_ics, horizon_bars=h, timeframe=self._anchor_tf, contiguous=contiguous
        )

    def _emit(
        self,
        frame: pd.DataFrame,
        mask: pd.Series,
        zs: Mapping[str, pd.Series],
        weights: BlendWeights,
    ) -> pd.DataFrame:
        """Blend → Ã → mu_ann; the single body both windows share (anti-skew)."""
        a_tilde = blend(zs, weights, mask, min_members=self._min_members)
        mu = self._sizer.mu_ann(a_tilde, frame[SIGMA_COLUMN])
        return pd.DataFrame({ALPHA_BLEND_COLUMN: a_tilde, MU_ANN_COLUMN: mu}, index=frame.index)

    def _directional_zs(self, frame: pd.DataFrame, mask: pd.Series) -> dict[str, pd.Series]:
        """Processed, direction-adjusted z per alpha: ``cross_sectional=True``
        specs go through the CS pipeline under the PIT mask (non-members NaN'd
        BEFORE any statistic); others (already comparable, e.g. vol-normalized
        TS-momentum) are mask-filtered only. All are multiplied by
        ``FeatureSpec.direction`` so positive z = expected outperformer."""
        cs_names = [s.name for s in self._alpha_specs if s.cross_sectional]
        processed = self._pipeline.apply(frame[cs_names], mask) if cs_names else pd.DataFrame()
        member = mask.reindex(frame.index, fill_value=False).astype(bool)
        out: dict[str, pd.Series] = {}
        for spec in self._alpha_specs:
            series = processed[spec.name] if spec.cross_sectional else frame[spec.name]
            out[spec.name] = series.where(member) * float(spec.direction)
        return out

    def _window_ids(self, start: Ms, end: Ms) -> list[str]:
        """Sorted union of instruments whose membership interval overlaps
        ``[start, end)`` (half-open both sides; ``effective_to`` null = open)."""
        ids, froms, tos = self._intervals()
        return sorted(
            {
                iid
                for iid, eff_from, eff_to in zip(ids, froms, tos, strict=True)
                if eff_from < end and (eff_to is None or eff_to > start)
            }
        )

    def _membership_mask(self, index: pd.MultiIndex) -> pd.Series:
        """Boolean PIT membership per ``(ts_open, instrument_id)`` row: member iff
        some interval has ``effective_from <= ts`` and (``effective_to`` null or
        ``> ts``) — identical semantics to ``UniverseStore.membership_asof``,
        vectorized over the panel grid."""
        ids, froms, tos = self._intervals()
        ts = index.get_level_values("ts_open").to_numpy(dtype=np.int64)
        inst = index.get_level_values("instrument_id").to_numpy()
        # The intervals span the WHOLE cross-asset universe (2000+ members); the
        # panel holds only this sleeve's ~20-40 instruments. An interval for an
        # instrument absent from the panel contributes an all-False term to the OR
        # (``inst == iid`` is never true), so skipping it is byte-identical -- but it
        # turns an O(intervals x N) full-numpy-scan-per-interval blowup (the dominant
        # live-cycle cost: 2000+ scans of the panel) into O(panel-instruments x N).
        # ``inst`` is an object/string array. Comparing that full array once per
        # membership interval dominated a five-year, 58-contract carry replay: the
        # same strings were compared hundreds of millions of times. Factorize the
        # immutable index once and compare compact integer codes below. This is an
        # exact representation change only -- ``codes == code_by_iid[iid]`` selects
        # precisely the rows for which the former ``inst == iid`` was true.
        inst_codes, unique_inst = pd.factorize(inst, sort=False)
        code_by_iid = {iid: code for code, iid in enumerate(unique_inst.tolist())}
        member = np.zeros(len(index), dtype=bool)
        for iid, eff_from, eff_to in zip(ids, froms, tos, strict=True):
            code = code_by_iid.get(iid)
            if code is None:
                continue
            in_span = ts >= eff_from if eff_to is None else (ts >= eff_from) & (ts < eff_to)
            member |= in_span & (inst_codes == code)
        return pd.Series(member, index=index)

    def _intervals(self) -> tuple[list[str], list[int], list[int | None]]:
        """Membership intervals as plain lists (one store read per call — the
        service holds no caches, staying pure across lake rebuilds)."""
        tbl = self._universe.read_intervals()
        ids: list[str] = tbl.column("instrument_id").to_pylist()
        froms: list[int] = tbl.column("effective_from").cast(pa.int64()).to_pylist()
        tos: list[int | None] = tbl.column("effective_to").cast(pa.int64()).to_pylist()
        return ids, froms, tos
