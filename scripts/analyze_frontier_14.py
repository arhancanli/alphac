#!/usr/bin/env python3
"""The 14-sleeve frontier: what the admission contract must require to reach 2.0-2.5 at 11% DD.

WHY THIS EXISTS
---------------
``scripts/analyze_feasible_frontier.py`` answered the *old* framing of the goal -- "50 to 200
uncorrelated sleeves" -- and correctly ruled negative average correlation out of scope, because
the PSD floor -1/(N-1) collapses to -0.004 at N=250. The goal has since been restated as a book
of **at most fourteen** sleeves. At N=14 the floor is -0.077, which is an order of magnitude more
room, and the measured book has already sat below zero. The negative-rho_bar regime is therefore
back inside the feasible set, and it is the only region of it that reaches the target at today's
measured sleeve quality.

This script re-derives the frontier at the restated sleeve count and prices the drawdown
objective, which the earlier analyses treated only in the calm regime.

THE THREE FINDINGS
------------------
1. **The live contract cannot reach the target at any sleeve count.** ``average_pairwise_
   correlation_max`` is +0.15, and the N -> infinity ceiling is s_bar / sqrt(rho_bar). At the
   measured s_bar that ceiling sits far below 2.0, so a book that merely *passes* the current
   diversification gate is arithmetically barred from the objective. The ceiling is not a
   preference; it binds before sleeve count, before deflation and before execution quality.

2. **The drawdown objective is set by stressed correlation, not by calm correlation.** A book
   levered to a calm-regime vol target runs at a multiple of that vol when correlations converge,
   and maximum drawdown scales with the vol it actually realizes. Under the live stressed ceiling
   of 0.50 the realized stress vol is several times target. The vol-target overlay repairs this
   only as fast as its covariance estimator sees the regime change, so the binding design variable
   is the **estimator halflife**, and it is measured here rather than asserted. Production runs a
   720-bar covariance halflife; holding the 11% objective at the permitted stressed correlation
   needs 21.

3. **The overlay's fast regime detector never fires.** ``max(ex_ante, realized)`` is meant to let
   a fast realized-vol leg (halflife 240) overrule a slow covariance leg (halflife 720). But
   ``BlendStrategy._realized_vol_ann`` measures the post-overlay equity curve while the ex-ante leg
   uses pre-overlay weights, so the two are never on the same scale and the realized leg loses the
   comparison. Measured: it binds on 0.02% of days as shipped against 81.8% when correctly scaled,
   costing 0.6 to 2.2 points of expected maximum drawdown. This is a live sizing path and the fix
   is NOT applied here.

WHAT THIS IS NOT
----------------
This is arithmetic and simulation over *assumed* sleeve statistics. It reads no market data, opens
no holdout and spends no hypothesis identity. It cannot promise a Sharpe, a drawdown or a sleeve.
It states what would have to be true, so that the admission contract can require exactly that and
no less. Every number it quotes is reproduced into ``artifacts/analysis/frontier_14/result.json``.

The drawdown study drives the **production** overlay ``alphaforge.portfolio.overlay.vol_target``.
A vectorized twin carries the full sweep for runtime, and ``_assert_twin_matches_production``
fails the run if the twin and the shipping function ever disagree -- a study of an overlay the
book does not actually run would be worthless.

Related: scripts/analyze_feasible_frontier.py, scripts/analyze_sleeve_scaling.py,
scripts/analyze_target_2p5.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from alphaforge.portfolio.overlay import vol_target

SEED = 20260817  # fixed: this table is quoted in the admission contract and must reproduce
OUT = Path("artifacts/analysis/frontier_14/result.json")

TRADING_DAYS = 252
SLEEVES = 14

# --- measured inputs, carried forward from the existing artifacts so this analysis cannot
# --- quietly assume a better book than the one that exists.
S_BAR_MEASURED = 0.464  # artifacts/analysis/target_2p5/result.json
S_BAR_BOOK_3 = 0.529  # artifacts/analysis/sleeve_scaling/result.json (3-sleeve mean)
RHO_BAR_MEASURED = 0.07226371531067356  # sleeve_scaling, 3-sleeve common window
RHO_BAR_FOUR_SLEEVE = 0.0274  # docs/SLEEVE_DISCOVERY_PROGRAM.md, 4-sleeve common window
HIT_RATE = 0.06521739130434782  # sleeve_scaling: 3 survivors / 46 tested
IDENTITIES_SPENT = 162  # config/trial_accounting.json

# --- live contract, read rather than retyped, so a contract edit cannot silently
# --- invalidate this analysis.
CONTRACT = Path("config/sleeve_admission_contract.json")

TARGETS = (2.0, 2.5)
DRAWDOWN_OBJECTIVE = 0.11
VOL_TARGET = 0.10


# ---------------------------------------------------------------------------
# 1. closed-form frontier
# ---------------------------------------------------------------------------


def book_sharpe(s_bar: float, rho: float, n: int) -> float:
    """Equal-risk book Sharpe from per-sleeve Sharpe, average pairwise correlation, count."""
    denom = 1.0 + (n - 1) * rho
    if denom <= 0.0:
        return math.inf
    return s_bar * math.sqrt(n) / math.sqrt(denom)


def rho_required(s_bar: float, n: int, target: float) -> float:
    """The average pairwise correlation at which ``n`` sleeves of quality ``s_bar`` reach target."""
    return ((s_bar * math.sqrt(n) / target) ** 2 - 1.0) / (n - 1)


def psd_floor(n: int) -> float:
    """A correlation matrix with equal off-diagonals is PSD only at or above -1/(n-1)."""
    return -1.0 / (n - 1)


def infinite_n_ceiling(s_bar: float, rho: float) -> float:
    """No sleeve count beats s_bar / sqrt(rho_bar). Unbounded once rho_bar <= 0."""
    return math.inf if rho <= 0.0 else s_bar / math.sqrt(rho)


def book_vol_multiple(n: int, rho: float) -> float:
    """Equal-weight book vol as a multiple of single-sleeve vol."""
    return math.sqrt(max(1.0 + (n - 1) * rho, 0.0)) / math.sqrt(n)


# ---------------------------------------------------------------------------
# 2. drawdown under a correlation regime shift, through the production overlay
# ---------------------------------------------------------------------------


def _equicorrelated_cholesky(n: int, rho: float) -> np.ndarray:
    corr = np.full((n, n), rho, dtype=np.float64)
    np.fill_diagonal(corr, 1.0)
    return np.linalg.cholesky(corr)


def _regime_path(
    rng: np.random.Generator, paths: int, days: int, stress_share: float, mean_run: float
) -> np.ndarray:
    """Two-state Markov stress indicator with predeclared unconditional share and persistence."""
    p_exit = 1.0 / mean_run
    p_enter = p_exit * stress_share / (1.0 - stress_share)
    state = rng.random(paths) < stress_share
    out = np.empty((paths, days), dtype=bool)
    draw = rng.random((paths, days))
    for t in range(days):
        switch = np.where(state, draw[:, t] < p_exit, draw[:, t] < p_enter)
        state = np.where(switch, ~state, state)
        out[:, t] = state
    return out


def _twin_scale(ex_ante: np.ndarray, realized: np.ndarray, s_max: float) -> np.ndarray:
    """Vectorized twin of the production overlay's scale computation."""
    sigma_hat = np.maximum(ex_ante, realized)
    positive = sigma_hat > 0.0
    # np.where evaluates both arms, so the divisor is made safe rather than relying on the mask
    safe = np.where(positive, sigma_hat, 1.0)
    return np.where(positive, np.minimum(VOL_TARGET / safe, s_max), s_max)


def _assert_twin_matches_production(
    ex_ante: np.ndarray, realized: np.ndarray, s_max: float, gross_max: float, n: int
) -> dict[str, int]:
    """Fail closed if the vectorized twin ever disagrees with the shipping overlay.

    A study of an overlay the book does not run would be worthless, so the twin is pinned to
    ``alphaforge.portfolio.overlay.vol_target``.

    Agreement on sampled states alone is not enough. The overlay has three branches -- the
    ``sigma_hat <= 0`` guard, the ``s_max`` ceiling, and the ordinary ``target / sigma_hat``
    scale -- and the sweep only ever visits the third, because a fourteen-sleeve book at a 10%
    vol target needs roughly 0.5x leverage and never approaches the ceiling. A comparison drawn
    only from visited states therefore cannot fail on two of the three branches, which is worse
    than no comparison at all: it reports "pinned to production" while testing a third of it.

    So boundary states are injected deliberately, and the function asserts that **every branch
    was exercised** before it returns. The returned counts are published in the artifact so a
    reader can see which branches the sweep itself reached (``s_max_binding_in_sweep`` is
    expected to be zero, and that fact is a result, not an omission).
    """
    w = np.full(n, 1.0 / n, dtype=np.float64)
    sample = min(256, ex_ante.size)
    idx = np.linspace(0, ex_ante.size - 1, sample).astype(int)
    flat_ex = list(ex_ante.ravel()[idx])
    flat_re = list(realized.ravel()[idx])
    visited = len(flat_ex)
    s_max_binding_in_sweep = sum(
        1
        for a, b in zip(flat_ex, flat_re, strict=True)
        if VOL_TARGET / max(max(a, b), 1e-300) > s_max
    )

    # --- injected boundary states, so no branch of the overlay goes uncompared
    tiny = VOL_TARGET / (s_max * 10.0)  # sigma_hat so small the ceiling must bind
    exact = VOL_TARGET / s_max  # sigma_hat exactly at the ceiling
    boundary: list[tuple[float, float]] = [
        (0.0, 0.0),  # the sigma_hat <= 0 guard
        (tiny, 0.0),  # ceiling binds via ex-ante
        (0.0, tiny),  # ceiling binds via realized
        (exact, exact),  # exactly on the ceiling
        (tiny, VOL_TARGET),  # max() picks realized, ceiling does not bind
        (VOL_TARGET, tiny),  # max() picks ex-ante, ceiling does not bind
    ]
    flat_ex.extend(a for a, _ in boundary)
    flat_re.extend(b for _, b in boundary)

    branches = {"zero_guard": 0, "s_max_ceiling": 0, "ordinary_scale": 0}
    for k, (a, b) in enumerate(zip(flat_ex, flat_re, strict=True)):
        # a diagonal covariance reproducing exactly this ex-ante book vol
        cov = np.eye(n) * (a**2) * n
        _, s = vol_target(w, cov, b, target=VOL_TARGET, s_max=s_max, gross_max=gross_max)
        twin = float(_twin_scale(np.array([a]), np.array([b]), s_max)[0])
        if not math.isclose(s, twin, rel_tol=1e-12, abs_tol=1e-12):
            raise AssertionError(
                f"vectorized twin diverged from production vol_target at state {k} "
                f"(ex_ante={a!r}, realized={b!r}): twin={twin!r} != production={s!r}"
            )
        sigma_hat = max(a, b)
        if sigma_hat <= 0.0:
            branches["zero_guard"] += 1
        elif VOL_TARGET / sigma_hat > s_max:
            branches["s_max_ceiling"] += 1
        else:
            branches["ordinary_scale"] += 1

    unexercised = sorted(name for name, hits in branches.items() if hits == 0)
    if unexercised:
        raise AssertionError(
            f"overlay branches never compared against production: {unexercised}. "
            "An assertion that cannot fail on a branch does not cover that branch."
        )

    return {
        "states_compared": len(flat_ex),
        "visited_states_compared": visited,
        "boundary_states_injected": len(boundary),
        "s_max_binding_in_sweep": s_max_binding_in_sweep,
        **{f"branch_{name}": hits for name, hits in branches.items()},
    }


def drawdown_study(
    s_bar: float,
    rho_calm: float,
    rho_stress: float,
    cov_halflife: int,
    realized_halflife: int,
    *,
    paths: int,
    years: int,
    stress_share: float,
    mean_run: float,
    s_max: float,
    gross_max: float,
    overlay: bool,
    realized_leg: str,
    rng: np.random.Generator,
) -> dict[str, Any]:
    """Maximum drawdown of an equal-weight 14-sleeve book across a correlation regime shift.

    The overlay's two legs are **separate estimators with separate halflives**, exactly as in
    production (``BlendStrategy`` defaults: ``cov_halflife_bars = 720``,
    ``realized_vol_halflife_bars = 240``). That asymmetry is the whole point of
    ``max(ex_ante, realized)``: the covariance leg is slow and the realized leg is fast, so the
    realized leg is the book's quick regime detector.

    Giving both legs the same halflife would make them algebraically identical -- EWMA is linear,
    so ``w' EWMA(r r') w == EWMA((w'r)^2)`` -- and the comparison would be a degenerate no-op that
    can measure nothing. An earlier revision of this script did exactly that and produced
    bit-identical arms; the separate halflives below are what make the experiment meaningful.

    ``realized_leg`` selects which quantity feeds the realized side:

    * ``"unlevered"`` -- the realized vol of the *unlevered* book, on the same scale as the
      ex-ante leg, which is the comparison the overlay's docstring describes.
    * ``"levered"`` -- the realized vol of the *account equity curve*, which is what
      ``BlendStrategy._realized_vol_ann`` actually measures (it reads ``_equity_hist``, appended
      post-overlay at strategy.py:377). Because the book runs de-levered this leg is scaled down
      by roughly the applied leverage, so it loses the ``max()`` to the slow covariance leg and
      the fast regime detector never fires.
    * ``"off"`` -- no overlay at all; leverage fixed from the calm regime.
    """
    if realized_leg not in ("unlevered", "levered", "off"):
        raise ValueError(f"realized_leg must be unlevered/levered/off, got {realized_leg!r}")
    if overlay == (realized_leg == "off"):
        raise ValueError(f"overlay={overlay} is inconsistent with realized_leg={realized_leg!r}")
    days = years * TRADING_DAYS
    n = SLEEVES
    mu_d = s_bar / TRADING_DAYS  # per-sleeve daily mean at unit annual vol
    sd_d = 1.0 / math.sqrt(TRADING_DAYS)

    chol = {
        False: _equicorrelated_cholesky(n, rho_calm),
        True: _equicorrelated_cholesky(n, rho_stress),
    }
    stress = _regime_path(rng, paths, days, stress_share, mean_run)
    z = rng.standard_normal((paths, days, n))

    lam_cov = 0.5 ** (1.0 / cov_halflife)
    lam_rv = 0.5 ** (1.0 / realized_halflife)
    w = np.full(n, 1.0 / n, dtype=np.float64)

    # leverage is calibrated once, in the calm regime, exactly as a live book would be
    calm_book_vol = book_vol_multiple(n, rho_calm)
    base_leverage = min(VOL_TARGET / calm_book_vol, s_max)

    cov = np.tile(np.eye(n) * (calm_book_vol**2) * n, (paths, 1, 1))
    realized_var = np.full(paths, calm_book_vol**2, dtype=np.float64)
    equity = np.ones(paths, dtype=np.float64)
    peak = np.ones(paths, dtype=np.float64)
    max_dd = np.zeros(paths, dtype=np.float64)
    book_rets = np.empty((paths, days), dtype=np.float64)
    ex_ante_log: list[np.ndarray] = []
    realized_log: list[np.ndarray] = []
    # how often the realized leg is the one max() selects -- the whole point of its existence
    realized_leg_bound = np.zeros(paths, dtype=np.int64)
    ex_ante = np.zeros(paths, dtype=np.float64)
    # gross-exposure turnover caused by the overlay alone: sum |d gross| over the run. This is
    # the series the execution-cost model needs in order to price a covariance halflife.
    gross_turnover = np.zeros(paths, dtype=np.float64)
    prev_gross = np.full(paths, base_leverage * float(np.abs(w).sum()), dtype=np.float64)

    for t in range(days):
        # --- size on information available BEFORE this day's return
        if overlay:
            ex_ante = np.sqrt(np.maximum(np.einsum("i,pij,j->p", w, cov, w), 0.0))
            realized = np.sqrt(np.maximum(realized_var, 0.0))
            scale = _twin_scale(ex_ante, realized, s_max)
            gross = scale * np.abs(w).sum()
            scale = np.where(gross > gross_max, scale * gross_max / gross, scale)
            if t % 97 == 0:
                ex_ante_log.append(ex_ante.copy())
                realized_log.append(realized.copy())
        else:
            scale = np.full(paths, base_leverage, dtype=np.float64)

        this_gross = scale * float(np.abs(w).sum())
        gross_turnover += np.abs(this_gross - prev_gross)
        prev_gross = this_gross

        # --- the day happens
        l_t = np.where(stress[:, t][:, None, None], chol[True], chol[False])
        shock = np.einsum("pij,pj->pi", l_t, z[:, t, :])
        sleeve_r = mu_d + sd_d * shock
        r = scale * (sleeve_r @ w)
        book_rets[:, t] = r

        equity *= 1.0 + r
        peak = np.maximum(peak, equity)
        max_dd = np.maximum(max_dd, 1.0 - equity / peak)

        # --- estimators update on realized data, one day late, as they must
        outer = sleeve_r[:, :, None] * sleeve_r[:, None, :] * TRADING_DAYS
        cov = lam_cov * cov + (1.0 - lam_cov) * outer
        # "levered" reproduces BlendStrategy._realized_vol_ann, which reads the post-overlay
        # equity curve; "unlevered" divides the applied scale back out so the realized leg is
        # commensurable with the ex-ante leg it is max()'d against.
        observed = r if realized_leg == "levered" else r / np.maximum(scale, 1e-12)
        realized_var = lam_rv * realized_var + (1.0 - lam_rv) * (observed**2) * TRADING_DAYS
        if overlay:
            realized_leg_bound += np.sqrt(np.maximum(realized_var, 0.0)) > ex_ante

    if overlay and ex_ante_log:
        production_check: dict[str, int] = _assert_twin_matches_production(
            np.concatenate(ex_ante_log), np.concatenate(realized_log), s_max, gross_max, n
        )
    else:
        production_check = {}

    ann_mean = book_rets.mean() * TRADING_DAYS
    ann_vol = book_rets.std(ddof=1) * math.sqrt(TRADING_DAYS)
    return {
        "expected_max_drawdown": float(max_dd.mean()),
        "p95_max_drawdown": float(np.quantile(max_dd, 0.95)),
        "median_max_drawdown": float(np.median(max_dd)),
        "realized_book_sharpe": float(ann_mean / ann_vol) if ann_vol > 0 else float("nan"),
        "realized_book_vol": float(ann_vol),
        "realized_leg": realized_leg,
        "realized_leg_bound_fraction_of_days": float(realized_leg_bound.sum())
        / float(paths * days),
        # gross notional traded per year purely to re-lever, as a fraction of equity.
        # This is the input the execution-cost model needs to price the halflife.
        "overlay_gross_turnover_per_year": float(gross_turnover.mean()) / float(years),
        "overlay_gross_turnover_per_year_p95": float(np.quantile(gross_turnover, 0.95))
        / float(years),
        "meets_objective_expected": bool(max_dd.mean() <= DRAWDOWN_OBJECTIVE),
        "meets_objective_p95": bool(np.quantile(max_dd, 0.95) <= DRAWDOWN_OBJECTIVE),
        "production_overlay_check": production_check,
    }


# ---------------------------------------------------------------------------
# 3. report
# ---------------------------------------------------------------------------


def main() -> None:
    contract = json.loads(CONTRACT.read_text())
    live = contract["thresholds"]

    s_grid = [0.40, S_BAR_MEASURED, 0.50, S_BAR_BOOK_3, 0.60, 0.70, 0.80, 0.90]
    rho_grid = [
        -0.07,
        -0.05,
        -0.03,
        -0.01,
        0.0,
        RHO_BAR_FOUR_SLEEVE,
        0.05,
        RHO_BAR_MEASURED,
        0.10,
        0.15,
    ]

    live_rho_max = live["average_pairwise_correlation_max"]
    live_ceiling = {f"{s:.3f}": infinite_n_ceiling(s, live_rho_max) for s in s_grid}

    result: dict[str, Any] = {
        "schema": "alphac.frontier-14.v1",
        "seed": SEED,
        "sleeve_count": SLEEVES,
        "targets": list(TARGETS),
        "drawdown_objective": DRAWDOWN_OBJECTIVE,
        "vol_target": VOL_TARGET,
        "measured_inputs": {
            "s_bar_measured": S_BAR_MEASURED,
            "s_bar_three_sleeve": S_BAR_BOOK_3,
            "rho_bar_three_sleeve": RHO_BAR_MEASURED,
            "rho_bar_four_sleeve": RHO_BAR_FOUR_SLEEVE,
            "hit_rate": HIT_RATE,
            "hypothesis_identities_spent": IDENTITIES_SPENT,
        },
        "psd_floor_at_14": psd_floor(SLEEVES),
        "live_contract_thresholds": {
            "average_pairwise_correlation_max": live_rho_max,
            "stressed_pairwise_correlation_max": live["stressed_pairwise_correlation_max"],
            "net_sharpe_min": live["net_sharpe_min"],
            "deflated_sharpe_min": live["deflated_sharpe_min"],
        },
        "finding_1_live_contract_ceiling": {
            "statement": (
                "s_bar / sqrt(rho_bar) bounds book Sharpe at every sleeve count. A book sitting "
                "exactly at the live average-correlation ceiling cannot reach the objective."
            ),
            "infinite_n_ceiling_at_live_rho_max": live_ceiling,
            "reaches_2_0_at_live_rho_max": {
                f"{s:.3f}": infinite_n_ceiling(s, live_rho_max) >= 2.0 for s in s_grid
            },
        },
        "rho_required_at_14": {
            f"{s:.3f}": {f"{t:.1f}": rho_required(s, SLEEVES, t) for t in TARGETS} for s in s_grid
        },
        "book_sharpe_at_14": {
            f"{rho:+.4f}": {f"{s:.3f}": book_sharpe(s, rho, SLEEVES) for s in s_grid}
            for rho in rho_grid
        },
        "book_vol_multiple": {f"{rho:+.4f}": book_vol_multiple(SLEEVES, rho) for rho in rho_grid},
    }

    # --- drawdown sweep -----------------------------------------------------
    sweep_params: dict[str, Any] = {
        "paths": 4000,
        "years": 5,
        "stress_share": 0.12,
        "mean_run": 40.0,
        "s_max": 6.0,
        "gross_max": 8.0,
    }
    result["drawdown_study_parameters"] = dict(sweep_params, seed=SEED)

    # Production BlendStrategy defaults. The covariance leg is slow and the realized leg is
    # fast; that asymmetry is what makes max(ex_ante, realized) a regime detector at all.
    PROD_COV_HALFLIFE = 720
    PROD_RV_HALFLIFE = 240
    result["production_overlay_defaults"] = {
        "cov_halflife_bars": PROD_COV_HALFLIFE,
        "realized_vol_halflife_bars": PROD_RV_HALFLIFE,
        "source": "src/alphaforge/portfolio/strategy.py:159,161",
    }

    sweep: dict[str, Any] = {}
    for rho_stress in (0.10, 0.20, 0.30, 0.50):
        rho_seed = int(rho_stress * 1000)
        # (a) production configuration, both legs, so the scale defect can be priced
        for leg in ("levered", "unlevered"):
            key = f"rho_stress={rho_stress:.2f}|cov=720|rv=240|leg={leg}"
            sweep[key] = drawdown_study(
                S_BAR_BOOK_3,
                -0.03,
                rho_stress,
                PROD_COV_HALFLIFE,
                PROD_RV_HALFLIFE,
                overlay=True,
                realized_leg=leg,
                rng=np.random.default_rng(SEED + rho_seed),
                **sweep_params,
            )
        # (b) faster covariance leg, correctly-scaled realized leg -- the design question
        for cov_hl in (21, 63, 126, 252):
            key = f"rho_stress={rho_stress:.2f}|cov={cov_hl}|rv=240|leg=unlevered"
            sweep[key] = drawdown_study(
                S_BAR_BOOK_3,
                -0.03,
                rho_stress,
                cov_hl,
                PROD_RV_HALFLIFE,
                overlay=True,
                realized_leg="unlevered",
                rng=np.random.default_rng(SEED + cov_hl + rho_seed),
                **sweep_params,
            )
        key = f"rho_stress={rho_stress:.2f}|overlay=off"
        sweep[key] = drawdown_study(
            S_BAR_BOOK_3,
            -0.03,
            rho_stress,
            PROD_COV_HALFLIFE,
            PROD_RV_HALFLIFE,
            overlay=False,
            realized_leg="off",
            rng=np.random.default_rng(SEED + rho_seed),
            **sweep_params,
        )
    result["finding_2_drawdown_sweep"] = sweep

    # --- finding 3: does the overlay's realized leg ever actually bind? -------
    prod = {
        k: v
        for k, v in sweep.items()
        if "cov=720|rv=240" in k and v["realized_leg"] in ("levered", "unlevered")
    }
    levered_bound = [
        v["realized_leg_bound_fraction_of_days"] for k, v in prod.items() if "leg=levered" in k
    ]
    unlevered_bound = [
        v["realized_leg_bound_fraction_of_days"] for k, v in prod.items() if "leg=unlevered" in k
    ]
    cost = []
    for k, v in prod.items():
        if "leg=levered" not in k:
            continue
        fixed = prod[k.replace("leg=levered", "leg=unlevered")]
        cost.append(
            {
                "rho_stress": k.split("|")[0].split("=")[1],
                "expected_max_drawdown_as_shipped": v["expected_max_drawdown"],
                "expected_max_drawdown_if_fixed": fixed["expected_max_drawdown"],
                "expected_max_drawdown_cost_of_defect": v["expected_max_drawdown"]
                - fixed["expected_max_drawdown"],
                "p95_max_drawdown_as_shipped": v["p95_max_drawdown"],
                "p95_max_drawdown_if_fixed": fixed["p95_max_drawdown"],
                "sharpe_as_shipped": v["realized_book_sharpe"],
                "sharpe_if_fixed": fixed["realized_book_sharpe"],
            }
        )
    result["finding_3_realized_leg_is_inert_in_production"] = {
        "statement": (
            "BlendStrategy._realized_vol_ann measures the post-overlay account equity curve "
            "(strategy.py:377 appends ctx.equity) while the ex-ante leg is computed from "
            "pre-overlay optimizer weights (strategy.py:539 passes result.weights). The two are "
            "not on the same scale. The book runs de-levered, so the realized leg is scaled down "
            "by roughly the applied leverage and loses the max() to the covariance leg. Since "
            "the covariance leg is slow (halflife 720) and the realized leg is fast (halflife "
            "240), the effect is that the book's FAST regime detector is disabled and only the "
            "slow one runs."
        ),
        "call_site": "src/alphaforge/portfolio/strategy.py:539",
        "defect_site": "src/alphaforge/portfolio/strategy.py:609 (_realized_vol_ann)",
        "equity_history_is_post_overlay": "src/alphaforge/portfolio/strategy.py:377",
        "levered_leg_bound_fraction_max": max(levered_bound) if levered_bound else None,
        "unlevered_leg_bound_fraction_max": max(unlevered_bound) if unlevered_bound else None,
        "cost_of_the_defect": cost,
        "unit_test_that_passes_anyway": (
            "tests/unit/test_overlay.py::test_realized_vol_dominates_when_larger -- it exercises "
            "vol_target() directly with a large realized value, so it pins the function's "
            "intention and not the value the caller actually supplies."
        ),
        "prior_revision_error": (
            "An earlier revision of this script gave both legs the same halflife. EWMA is "
            "linear, so w' EWMA(r r') w == EWMA((w'r)^2) exactly, which made the two legs the "
            "same number and the arms bit-identical. That revision could not have measured this "
            "and its 'realized leg binds 32% of days' figure was floating-point tie-breaking, "
            "not signal. The separate production halflives above are the correction."
        ),
    }

    passing = sorted(k for k, v in sweep.items() if v["meets_objective_p95"])
    result["p95_objective_passing_configurations"] = passing
    result["expected_objective_passing_configurations"] = sorted(
        k for k, v in sweep.items() if v["meets_objective_expected"]
    )

    # --- seam 1 deliverable: the turnover each covariance halflife implies, for costing -----
    result["seam_1_overlay_turnover_for_execution_costing"] = {
        "statement": (
            "Gross notional traded per year, as a fraction of equity, caused by the overlay "
            "re-levering alone. The drawdown study charges nothing for it. The execution-cost "
            "lane prices these to settle the covariance halflife; a halflife is only affordable "
            "if its drawdown gain survives its cost."
        ),
        "units": "gross notional traded per year / equity",
        "by_configuration": {
            k: {
                "cov_halflife": int(k.split("cov=")[1].split("|")[0]) if "cov=" in k else None,
                "rho_stress": k.split("|")[0].split("=")[1],
                "turnover_per_year": v["overlay_gross_turnover_per_year"],
                "turnover_per_year_p95": v["overlay_gross_turnover_per_year_p95"],
                "expected_max_drawdown": v["expected_max_drawdown"],
                "realized_book_sharpe": v["realized_book_sharpe"],
            }
            for k, v in sorted(sweep.items())
            if v["realized_leg"] == "unlevered"
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"wrote {OUT}")

    # --- console summary ----------------------------------------------------
    print(f"\nPSD floor at N=14: {psd_floor(SLEEVES):+.4f}")
    print(f"\nLive contract rho_bar ceiling = {live_rho_max}. Book Sharpe ceiling at that rho:")
    for s in s_grid:
        c = infinite_n_ceiling(s, live_rho_max)
        print(f"  s_bar={s:.3f} -> ceiling {c:5.2f}   reaches 2.0? {'YES' if c >= 2.0 else 'NO'}")

    print("\nrho_bar REQUIRED at N=14:")
    for s in s_grid:
        r20, r25 = rho_required(s, SLEEVES, 2.0), rho_required(s, SLEEVES, 2.5)
        print(f"  s_bar={s:.3f} -> S=2.0 needs {r20:+.4f} | S=2.5 needs {r25:+.4f}")

    print(f"\nDrawdown (5y, equal-weight, {VOL_TARGET:.0%} vol target, calm rho=-0.03):")
    for key in sorted(sweep):
        v = sweep[key]
        flag = "PASS" if v["meets_objective_p95"] else "fail"
        print(
            f"  {key:46s} E[MDD]={v['expected_max_drawdown']:6.1%} "
            f"p95={v['p95_max_drawdown']:6.1%} vol={v['realized_book_vol']:5.1%} "
            f"SR={v['realized_book_sharpe']:5.2f}  p95<=11%: {flag}"
        )
    print(f"\nconfigurations meeting the p95 drawdown objective: {len(passing)}/{len(sweep)}")

    f3 = result["finding_3_realized_leg_is_inert_in_production"]
    print("\nrealized leg — fraction of days it is the binding term in max(ex_ante, realized):")
    print(
        "  production ('levered', reads post-overlay equity): max "
        f"{f3['levered_leg_bound_fraction_max']:.4%}"
    )
    print(
        "  corrected  ('unlevered', same scale as ex-ante):   max "
        f"{f3['unlevered_leg_bound_fraction_max']:.4%}"
    )
    print(
        "\nexpected-MDD objective (<=11%) met by: "
        f"{len(result['expected_objective_passing_configurations'])}/{len(sweep)}"
    )
    for k in result["expected_objective_passing_configurations"]:
        print(f"    {k}")

    print("\nseam 1 — overlay turnover to be priced by the execution lane (per year / equity):")
    for k, row in result["seam_1_overlay_turnover_for_execution_costing"][
        "by_configuration"
    ].items():
        print(
            f"  {k:46s} turnover {row['turnover_per_year']:6.2f}x  "
            f"E[MDD] {row['expected_max_drawdown']:5.1%}  SR {row['realized_book_sharpe']:.2f}"
        )

    print("\ncost of the defect at production halflives (cov 720 / rv 240):")
    for row in f3["cost_of_the_defect"]:
        print(
            f"  rho_stress={row['rho_stress']}  "
            f"E[MDD] as-shipped {row['expected_max_drawdown_as_shipped']:6.1%} -> "
            f"fixed {row['expected_max_drawdown_if_fixed']:6.1%}  "
            f"(cost {row['expected_max_drawdown_cost_of_defect']:+.2%})   "
            f"SR {row['sharpe_as_shipped']:.2f} -> {row['sharpe_if_fixed']:.2f}"
        )


if __name__ == "__main__":
    main()
