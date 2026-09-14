"""Opt-in allocator: synthetic returns for risk, raw marks for positions."""

from __future__ import annotations

from collections.abc import Mapping

from alphaforge.backtest.engine import StrategyContext
from alphaforge.portfolio.strategy import (
    BlendStrategy,
    annualize_cov,
    ewma_cov,
    ledoit_wolf_cc,
    math,
    nearest_psd,
    np,
    vol_target,
)


class PairedPriceBlendStrategy(BlendStrategy):
    def __init__(self, *args, signal_reader, input_digest, **kwargs):
        super().__init__(*args, **kwargs)
        if len(input_digest) != 64:
            raise ValueError("Paired input digest required")
        int(input_digest, 16)
        self._signal_reader = signal_reader
        self.input_digest = input_digest

    def _signal_close_panel(self, ctx, ids):
        signal_ctx = StrategyContext(
            reader=self._signal_reader,
            tf=ctx.tf,
            ts=ctx.ts,
            equity=ctx.equity,
            positions=ctx.positions,
            instruments=ctx.instruments,
            asset_class=ctx.asset_class,
        )
        return super()._close_panel(signal_ctx, ids)

    def _rebalance(
        self, ctx: StrategyContext, mu_map: Mapping[str, float]
    ) -> dict[str, float] | None:
        """Σ -> allocator -> overlay -> w_max clip -> ladder multiplier -> targets.

        Returns the target book, or None to HOLD on a cold start (covariance
        window shorter than ``cov_min_periods``) or a degenerate cross-section
        (< 2 names with a known mu, >= 2 finite returns, and positive variance);
        each None path increments its own observability counter (F-E) so the two
        are distinguishable in :attr:`counters`.
        """
        tf = ctx.tf
        closes = self._signal_close_panel(ctx, sorted(ctx.instruments))
        rets = closes.pct_change(fill_method=None).iloc[1:]
        if len(rets) < self._cov_min_periods:
            self._n_hold_cov_cold_start += 1
            return None

        # Tradable cross-section: a known mu AND >= 2 finite returns (the
        # covariance variance-only fallback needs that many; instruments
        # without it are simply not sized this cycle — never guessed).
        finite_counts = rets.notna().sum(axis=0)
        ids = [iid for iid in closes.columns if iid in mu_map and int(finite_counts[iid]) >= 2]
        if len(ids) < 2:
            self._n_hold_degenerate_xsection += 1
            return None

        cov_bar = ewma_cov(
            rets.loc[:, ids],
            halflife_bars=self._cov_halflife_bars_for(ctx, tf),
            min_periods=self._cov_min_periods,
        )
        # Zero-variance columns (constant prints) make inverse-vol sizing
        # undefined — drop them from this cycle's cross-section.
        keep = np.flatnonzero(np.diag(cov_bar) > 0.0)
        if keep.size < 2:
            self._n_hold_degenerate_xsection += 1
            return None
        ids = [ids[int(i)] for i in keep]
        cov_bar = cov_bar[np.ix_(keep, keep)]

        # LW shrink on the jointly-complete columns (the asymptotic estimates
        # need a finite TxN window); young/gappy instruments keep their
        # documented diagonal-only EWMA fallback from ewma_cov.
        sub = rets.loc[:, ids]
        full = np.flatnonzero(sub.notna().all(axis=0).to_numpy())
        if full.size >= 2:
            block, _delta = ledoit_wolf_cc(
                sub.iloc[:, full].to_numpy(dtype=np.float64),
                cov_bar[np.ix_(full, full)],
            )
            cov_bar[np.ix_(full, full)] = block
        # Annualization basis from the sleeve calendar (the ONE source): 8760.0 for the
        # crypto H1 sleeve (Always24x7.periods_per_year(H1) == H1.bars_per_year, hence
        # byte-identical), 252.0 for equity D1 (XNYS) — never a bare tf.bars_per_year.
        periods_per_year = ctx.calendar.periods_per_year(tf)
        cov_ann = annualize_cov(nearest_psd(cov_bar), periods_per_year)

        mu = np.array([mu_map[iid] for iid in ids], dtype=np.float64)
        last_close = self._close_panel(ctx, ids).iloc[-1]
        w_prev = np.array(
            [
                ctx.positions.get(iid, 0.0) * float(last_close[iid]) / ctx.equity
                if math.isfinite(float(last_close[iid]))
                else 0.0
                for iid in ids
            ],
            dtype=np.float64,
        )
        shortable = np.array(
            [1.0 if ctx.instruments[iid].can_short else 0.0 for iid in ids],
            dtype=np.float64,
        )
        cost = np.full(len(ids), self._cost_frac, dtype=np.float64)

        result = self._allocator.solve(mu, cov_ann, w_prev, cost, shortable)
        realized_ann = self._realized_vol_ann(periods_per_year)
        # Recomputed here rather than read back out of vol_target so the counter cannot
        # drift from the overlay's own definition of ex-ante without a test noticing.
        _w = np.asarray(result.weights, dtype=np.float64).ravel()
        if realized_ann > math.sqrt(max(float(_w @ cov_ann @ _w), 0.0)):
            self._n_realized_leg_bound += 1
        w_vt, scale = vol_target(
            result.weights,
            cov_ann,
            realized_ann,
            target=self._vol_target_ann,
            s_max=self._vol_scale_max,
            gross_max=self._gross_max,
        )
        # The vol overlay TARGETS vol and may scale a per-asset weight ABOVE
        # w_max (up to w_max * s_max). The per-name hard cap is INVIOLABLE: the
        # documented live PreTradeChecker (max_position_frac = w_max) would
        # reject such an order, so the backtest re-clips to [-w_max, +w_max]
        # here, before the ladder multiplier (F-H). The small vol-target
        # shortfall from clipping is ACCEPTED — we do NOT re-scale the book back
        # up after clipping (that would just push another name past the cap).
        w_clip = np.clip(w_vt, -self._w_max, self._w_max)
        # Mask AFTER both allocation and volatility scaling. No subsequent
        # gross normalization may give rejected allocations to surviving names.
        w_clip = self._retain_cash(w_clip, ids, ctx)
        mult = self._ladder.gross_multiplier()

        self._last_result = result
        self._last_scale = scale
        self._n_rebalances += 1
        if result.status == "fallback_used":
            self._n_fallback_used += 1

        # The PRE-multiplier (vol-targeted, w_max-clipped) book, kept so a
        # HALF_GROSS non-rebalance bar can re-emit it rescaled to the live gross
        # multiplier (F-B). Held-but-unsized ids flatten (a silently-orphaned
        # position is a risk hole; absent ids are left untouched by the engine).
        pre_mult = {iid: float(w) for iid, w in zip(ids, w_clip, strict=True)}
        for iid in ctx.positions:
            pre_mult.setdefault(iid, 0.0)
        self._last_targets = pre_mult

        return {iid: w * mult for iid, w in pre_mult.items()}
