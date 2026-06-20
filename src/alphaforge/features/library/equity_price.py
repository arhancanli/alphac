"""Price-based US-equity anomaly factors (EQUITIES_SLEEVE.md §4) — the first
equities sleeve factor library, daily (D1 session) bars.

These are the most-replicated price-only equity anomalies (value/quality need
fundamentals and come later): 12-1 cross-sectional momentum (skip the most recent
month), short-term (1-month) reversal, the low-volatility anomaly,
betting-against-beta (BAB, low-beta), plus a realized-vol and an Amihud-illiquidity
context. They register through the SAME :func:`~alphaforge.features.registry.feature`
decorator as the crypto factors and reuse the crypto factor math verbatim where the
structure is identical — only the windows change (daily *session* bars, not hours):

* 12-1 momentum (``eq_mom_252_21``) — Jegadeesh-Titman / Carhart skip-momentum,
  ``ln(C*_{t-21}/C*_{t-252})``: reuses
  :func:`~alphaforge.features.library.momentum.xs_momentum` (the crypto skip-momentum
  kernel) on the adjusted-close panel. CS, ``direction=+1``.
* 1-month reversal (``eq_rev_21``) — Jegadeesh (1990), plain (un-residualized; the
  residualization the crypto ``mr_res_*`` needs at hour scale is a post-v1 refinement
  for equities): ``-ln(C*_t/C*_{t-21})`` so higher = recent loser = expected
  outperformer. CS, ``direction=+1``.
* low-volatility anomaly (``eq_lowvol_252``) — realized close-to-close vol over 252
  sessions, annualized x√252; ``direction=-1`` carries the anomaly sign (low vol ⇒
  high risk-adjusted return), the body never negates. CS.
* market beta (``eq_beta_252``) — rolling beta vs the equal-weight PIT-universe daily
  return, reusing :func:`~alphaforge.features.library.mean_reversion.rolling_beta` +
  ``market_return`` + ``_member_mask`` (the conservative through-``t-1`` variant).
  ``direction=0`` utility input for BAB.
* betting-against-beta (``eq_bab_252``) — Frazzini-Pedersen low-beta signal:
  the body returns ``-beta`` and the CS pipeline winsor→z-scores it within the PIT
  universe (low beta ⇒ high score). CS, ``direction=+1``. (FP's leverage/rescale
  *portfolio* construction is the optimizer's concern, not the factor's — the factor
  is the cross-sectional low-beta exposure, like every other CS factor here.)
* realized vol context (``eq_vol_252``) — the SAME realized-vol number as
  ``eq_lowvol_252`` exposed ``direction=0`` as a risk/cost input (the alpha is the
  CS-ranked low-vol; the context feeds risk/cost). One shared body
  (:func:`realized_vol`) so the "context == alpha input" invariant cannot drift
  (EQUITIES_CRITIQUE N3).
* Amihud illiquidity context (``eq_amihud_63``) — reuses
  :func:`~alphaforge.features.library.liquidity.amihud_illiq` verbatim on adjusted
  close + dollar volume over 63 sessions (~a quarter). ``direction=0`` — the
  illiquidity *premium* is unreliable and conflicts with tradability (the crypto
  liquidity module's stance).

Adjusted prices (the core equities difference — EQUITIES_SLEEVE.md §1.3/§4.3). The
lake stores RAW (as-traded) bars; split/dividend adjustment is reconstructed PIT at
feature time, never baked into the lake (Polygon ``adjusted=true`` is adjusted *to
today* and silently rewrites history on each new split). Price factors here therefore
run on a **PIT split/total-return-adjusted** close panel from :func:`adjusted_close`,
which folds in, for each decision row ``t``, ONLY the corporate actions knowable by
``t`` (``available_at <= ts_open + Δ``) and applies a split announced after ``t`` only
to rows at/after its ``ex_date`` — the per-decision-row PIT discipline of
:meth:`~alphaforge.features.context.FeatureContext.funding_asof_join`, in equity
clothing (EQUITIES_CRITIQUE B5). A 2:1 split must NOT print as a -50% momentum return,
and a split must be invisible to decisions taken before its ``available_at``.

CORPORATE-ACTIONS READ PATH (now wired, SPINE_ARC P1): ``PITDataReader.corporate_actions``
+ ``FeatureContext.corporate_actions`` serve the :data:`_CA_COLUMNS` projection, masked
PIT on the stored ``available_at`` (never ``ex_date``; leakage finding 18). So
:func:`_adjusted_close_panel` reads the actions and reconstructs the adjusted close via
:func:`adjusted_close` — and FAILS CLOSED (raises) if a context ever exposes no
``corporate_actions`` getter, rather than silently feeding raw unadjusted prices to the
factors (a 2:1 split would otherwise print as a -50% return; leakage G1/G2). An empty
actions frame is the only pass-through (no action in the window ⇒ ``C* == C_raw``),
which is also the crypto path (perps have no corporate actions). The PIT-aware
engine/calendar wiring (EQUITIES_CRITIQUE B1: ``anchor_tf=D1`` + ``XNYSCalendar``
threaded through ``FeatureEngine``/``FeatureContext``) is also wired in this arc, but
the equity *compute* path is held behind a fail-closed engine guard until the equity
as-of window + ``forward_returns``/blend session hops are verified (SPINE_ARC §4). The
pure :func:`adjusted_close` reconstruction is fully unit-tested here against a planted
split (cross-row PIT), the load-bearing correctness gate.

Shared non-negotiables (identical to the crypto library): every value at decision
bar ``t`` is a pure function of data available at the bar close ``t + Δ``; window math
runs on the complete expected (session) bar grid (gaps ⇒ NaN, never bridged or
forward-filled); inputs are never mutated; ``lookback_bars`` derives from params at
the single factory construction site (leakage finding 20). All seven factors are
finite-window — parity atol = 0 across the board (no EWMA recursion anywhere).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from alphaforge.core.errors import ConfigError
from alphaforge.core.time import Timeframe
from alphaforge.features.context import long_series
from alphaforge.features.library.liquidity import amihud_illiq
from alphaforge.features.library.mean_reversion import (
    _member_mask,
    market_return,
    rolling_beta,
)
from alphaforge.features.library.momentum import xs_momentum
from alphaforge.features.library.vol import _log, _roll_var, log_returns
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from alphaforge.features.context import FeatureContext

__all__ = [
    "SESSIONS_PER_YEAR",
    "adjusted_close",
    "eq_amihud_63",
    "eq_bab_252",
    "eq_beta_252",
    "eq_lowvol_252",
    "eq_mom_252_21",
    "eq_rev_21",
    "eq_vol_252",
    "realized_vol",
    "reversal",
]

SESSIONS_PER_YEAR: Final[float] = 252.0
"""NYSE trading sessions per year — the single annualization base for daily equity
realized vol (EQUITIES_SLEEVE.md §3.1: ``XNYSCalendar.periods_per_year(D1) = 252``).

This is the calendared annualization the equity path uses INSTEAD of
``Timeframe.D1.bars_per_year`` (= 365, the 24/7 crypto number) — keeping the crypto
``sqrt(8760)``/``sqrt(365)`` bases out of the equity vol entirely. For the
``cross_sectional=True`` low-vol alpha the constant is a monotone CS transform and
cancels, but it is applied so the raw value is a genuine annualized vol (the unit the
``direction=0`` risk/cost context promises).
"""

#: Corporate-action column contract of the frame :func:`adjusted_close` consumes —
#: the columns ``FeatureContext.corporate_actions`` will serve (EQUITIES_SLEEVE.md
#: §2 ``CORPORATE_ACTIONS_SCHEMA`` projected to the feature surface). ``ratio`` is the
#: split factor (``split_to/split_from``; 1.0 for a dividend); ``available_at`` is the
#: knowable-by timestamp ALL joins use (never ``ex_date``).
_CA_COLUMNS: Final[tuple[str, ...]] = (
    "instrument_id",
    "ex_date",
    "available_at",
    "action_type",
    "ratio",
    "cash_amount",
)


# --------------------------------------------------------------- adjusted-close (PIT)


def adjusted_close(
    raw_close: pd.DataFrame,
    actions: pd.DataFrame,
    *,
    tf_ms: int,
    include_dividends: bool = True,
) -> pd.DataFrame:
    """PIT split/total-return-adjusted close on the complete (session) grid.

    ``include_dividends=False`` applies SPLITS ONLY (the v1 factor path: see
    :func:`_adjusted_close_panel`). The dividend total-return factor anchors on the close
    AT the ex-date, which is a FUTURE price for a not-yet-ex dividend — so the batch panel
    (which has that future bar) and the live minimal as-of window (which does not) disagree,
    and the batch fold is itself a lookahead. Splits are a pure ratio with no anchor price,
    so they are window-invariant and batch/as-of parity-exact. Dividends remain implemented
    (and tested) here for a future PIT-correct total-return factor/label.

    Each grid row ``s`` is itself a decision (the value labeled ``ts_open=s`` is
    decision-usable at its close ``s + Δ``), so the adjustment is computed PER ROW
    using ONLY what that row's own decision could know::

        CF(i, s)  = Π { ratio_a  :  a is a split of i with
                        available_at_a <= ts_open_s + Δ  AND  ex_date_a > ts_open_s }
        DF(i, s)  = Π { 1 - cash_a / C_raw(i, ex_open_a)  :  a is a dividend of i with
                        available_at_a <= ts_open_s + Δ  AND  ex_date_a > ts_open_s }
        C*(i, s)  = C_raw(i, s) · CF(i, s) · DF(i, s)

    i.e. a split/dividend folds *backward* into a PRE-EX bar ``s`` (``ex_date > s``,
    expressing that past price in post-action share terms) but ONLY once it is
    knowable at ``s``'s decision (``available_at <= ts_open_s + Δ``). This is the
    per-decision-row PIT discipline of :meth:`FeatureContext.funding_asof_join`
    (EQUITIES_CRITIQUE B5): the cumulative factor is a function of the ROW, not a
    single window-wide vector — a split announced *after* a historical decision must
    NOT retroactively rewrite that decision's price (that is lookahead). The honest
    consequence (NOT a bug): a bar more than the announcement-to-ex horizon before a
    split is, to a PIT observer standing there, genuinely UNADJUSTED — it predates the
    split's existence. Splits are typically declared weeks before the ex-date
    (Polygon's ``declaration_date`` → ``available_at``), so all but the earliest
    pre-announcement bars fold the split; bars before the declaration stay raw because
    no live trader there knew the split was coming.

    The result is computed as a per-row boolean mask (``available_at`` knowable AND
    pre-ex) times the split ratio / dividend factor, accumulated across actions — no
    per-row Python loop over the grid, batch/asof parity safe (each row's factor
    depends only on its own ``ts_open`` and the served actions, never on the window
    end, so the batch panel and the live minimal window agree bit-for-bit).

    Dividends use a multiplicative total-return factor ``1 - cash/C_raw(ex_open)``
    (reinvest-at-ex-price), the standard back-adjustment; ``cash_amount`` of a split
    row is null and contributes ``ratio`` only. NaN raw closes stay NaN (the factor
    multiplies through, preserving the no-bridging guarantee). ``actions`` may be
    empty (no corporate actions in the window) — then ``C* == C_raw`` exactly.

    Inputs are never mutated. ``tf_ms`` is the bar duration Δ (the availability lag
    ``ts_open + Δ`` of each decision row); pass ``Timeframe.D1.ms`` for daily equity
    bars.

    Args:
        raw_close: wide float64 raw-close panel on the complete grid (index =
            ``ts_open`` epoch ms, columns = instrument ids).
        actions: long corporate-actions frame with the :data:`_CA_COLUMNS` columns
            (``ratio`` the split factor / 1.0 for dividends; ``available_at`` the
            knowable-by ts; ``ex_date`` the ex/effective ts; ``cash_amount`` the
            per-share dividend cash, null for splits). Rows for instruments absent
            from ``raw_close.columns`` are ignored.
    """
    if tf_ms <= 0:
        raise ValueError(f"adjusted_close tf_ms must be > 0, got {tf_ms}")
    out = raw_close.astype("float64").copy()
    if actions.empty:
        return out
    grid = np.asarray(raw_close.index, dtype="int64")
    decision = grid + int(tf_ms)  # ts_open + Δ : what each row knows by its close
    columns = list(raw_close.columns)
    col_pos = {c: j for j, c in enumerate(columns)}
    n_rows = len(grid)
    raw_values = out.to_numpy(dtype="float64")  # for the dividend ex-open anchor price
    factor = np.ones((n_rows, len(columns)), dtype="float64")
    # Extract each action column as a typed numpy array once (iterrows yields loosely
    # typed rows): explicit dtypes keep the per-action arithmetic mypy-strict clean.
    a_iid = actions["instrument_id"].to_numpy(dtype=object)
    a_ex = actions["ex_date"].to_numpy(dtype="int64")
    a_avail = actions["available_at"].to_numpy(dtype="int64")
    a_type = actions["action_type"].to_numpy(dtype=object)
    a_ratio = actions["ratio"].to_numpy(dtype="float64")
    a_cash = actions["cash_amount"].to_numpy(dtype="float64")
    for k in range(len(actions)):
        j = col_pos.get(str(a_iid[k]))
        if j is None:
            continue
        ex_date = int(a_ex[k])
        avail = int(a_avail[k])
        action_type = str(a_type[k])
        if action_type == "split":
            # SPLITS back-adjust EVERY pre-ex bar (grid < ex_date). NOT the per-row
            # `decision >= avail` gate (the historical-bug: with available_at = ex_date + lag
            # and no declaration_date it was UNSATISFIABLE -> not ONE of ~6,900 splits ever
            # adjusted, so every price factor ran on split-broken prices -- a fake -90% crash
            # on every split, hitting exactly the momentum winners). The frame is already
            # masked to available_at <= as_of by the reader (ctx.corporate_actions uses
            # as_of=end), so every split here is knowable by the panel's decision cutoff.
            # Back-adjustment is the right model for a factor: a split inside the lookback is
            # in the PAST relative to the factor's decision T (T > ex) and must fold into the
            # pre-ex bars; a split AFTER T cancels in any ratio factor (both endpoints
            # adjusted) -> PIT-safe and batch/as-of FACTOR-parity-safe.
            applies = grid < ex_date
            if applies.any():
                factor[applies, j] *= float(a_ratio[k])
        elif action_type == "dividend":
            # Dividends keep the per-row PIT gate (the total-return factor anchors on the
            # ex-close, so it is path-dependent, NOT a window-invariant ratio). v1 factor
            # path is SPLIT-ONLY (include_dividends=False), so this branch is inert there.
            applies = (decision >= avail) & (grid < ex_date)
            if not applies.any():
                continue
            if not include_dividends:
                continue  # v1 factor path: SPLIT-ONLY (window-invariant, no ex-close anchor)
            cash = float(a_cash[k])
            if math.isnan(cash):
                continue
            # Reinvest-at-ex-price total-return factor 1 - cash/C_raw(ex_open).
            ex_pos = int(np.searchsorted(grid, ex_date))
            if ex_pos >= n_rows or int(grid[ex_pos]) != ex_date:
                continue  # ex-date not on the grid -> no anchorable price, skip
            px = float(raw_values[ex_pos, j])
            if not math.isfinite(px) or px <= 0.0:
                continue
            div_factor = 1.0 - cash / px
            if div_factor <= 0.0:
                continue  # degenerate (dividend >= price): leave unadjusted
            factor[applies, j] *= div_factor
        else:
            raise ValueError(
                f"adjusted_close: unknown action_type {action_type!r} (expected "
                "'split' or 'dividend')"
            )
    return out * pd.DataFrame(factor, index=raw_close.index, columns=raw_close.columns)


def _adjusted_close_panel(ctx: FeatureContext) -> pd.DataFrame:
    """The sanctioned PIT adjusted-close panel for the equity price factors.

    Reads the raw close panel and reconstructs the PIT split/total-return-adjusted
    close via :func:`adjusted_close` (EQUITIES_SLEEVE.md §4.3 — the ONE place equity
    adjustment happens, so the convention cannot drift between factors). Every equity
    price factor calls this; it is the single-site discipline that the crypto
    ``adv_quote_30d``/``sigma_daily`` shared inputs use.

    FAIL-CLOSED on a missing corporate-actions surface (the P1 teeth, SPINE_ARC §2.3):
    an equity price factor must NEVER silently run on raw unadjusted close — a 2:1
    split would print as a -50% return into momentum/reversal/beta/vol (leakage
    G1/G2). If the context exposes no ``corporate_actions`` getter at all, this RAISES
    rather than returning raw. The only surviving pass-through is an EMPTY actions
    frame: no corporate action in the window legitimately means ``C* == C_raw`` (the
    crypto path always hits this branch — perps have no corporate actions — so it is
    byte-identical there). The §4 ``FeatureEngine`` guard additionally rejects the whole
    EQUITY/D1 compute path until verified, so this raise is the safety net for the day
    that guard is lifted.
    """
    raw = ctx.panel("close")
    ca_getter = getattr(ctx, "corporate_actions", None)
    if ca_getter is None:
        raise ConfigError(  # FAIL-CLOSED: never silently feed raw prices to equity factors
            "equity price factors require a corporate-actions surface; FeatureContext "
            "exposes no corporate_actions() — refusing to run on raw unadjusted prices "
            "(a 2:1 split would print as a -50% return; leakage G1/G2)."
        )
    actions = ca_getter()
    if not isinstance(actions, pd.DataFrame):
        raise ConfigError("FeatureContext.corporate_actions() must return a DataFrame")
    if actions.empty:
        return raw  # legitimately no actions in the window: raw == adjusted
    # The decision-availability lag of a daily equity bar is exactly D1.ms (§3.2:
    # available_at = ts_open + 86_400_000) — independent of session gaps. Using the
    # explicit bar duration (not the inferred grid[1]-grid[0]) avoids a 2-session
    # lookahead when the first grid gap is a Fri→Mon hop (SPINE_ARC §2.4 / P18).
    #
    # SPLIT-ONLY (v1, owner-confirmed): the dividend total-return factor anchors on the
    # ex-date close — a FUTURE price for a not-yet-ex dividend — so the batch panel folds
    # it (lookahead) while the live minimal window cannot, breaking batch/as-of parity.
    # Splits are window-invariant (pure ratio), so a split-only panel is parity-exact and
    # lookahead-free — the standard basis for price momentum/reversal/vol. Dividend
    # total-return is deferred to a separate PIT-correct factor/label.
    return adjusted_close(raw, actions, tf_ms=Timeframe.D1.ms, include_dividends=False)


# --------------------------------------------------------------------- factor kernels


def reversal(adj_close: pd.DataFrame, *, window: int) -> pd.DataFrame:
    """Short-term reversal over ``window`` sessions (EQUITIES_SLEEVE.md §4.1)::

        REV_W(i, t) = - ln( C*_{i,t} / C*_{i,t-W} )

    The negative sign makes **higher value ⇒ recent loser ⇒ expected outperformer**
    (``direction=+1``). Computed positionally on the complete grid (``shift`` is an
    exact time op); NaN until ``W`` prior grid slots exist and NaN whenever either
    endpoint bar is missing — gaps are never bridged. Inputs are never mutated. This
    is exactly ``-xs_momentum(adj_close, lookback=W, skip=0)`` written out for the
    reversal sign convention; the crypto skip-momentum kernel is reused for 12-1
    momentum (:func:`~alphaforge.features.library.momentum.xs_momentum`).
    """
    if window <= 0:
        raise ValueError(f"reversal window must be > 0, got {window}")
    return -_log(adj_close / adj_close.shift(window))


def realized_vol(adj_close: pd.DataFrame, *, window: int, annualize: bool = True) -> pd.DataFrame:
    """Annualized realized vol of daily log returns over ``window`` sessions.

    Formula (EQUITIES_SLEEVE.md §4.1)::

        r_t        = ln(C*_t / C*_{t-1})
        sigma2(t)  = (1/(n-1)) Σ_{k=0..n-1} (r_{t-k} - r̄)²       # sample variance, ddof=1
        sigma(t)   = sqrt(sigma2(t)) · sqrt(252)                  # annualize=True

    Sample variance (ddof=1) of the ``window`` close-to-close log returns ending at
    ``t``, via the prefix-independent :func:`~alphaforge.features.library.vol._roll_var`
    (each window depends ONLY on its own contents — batch/live parity is exact,
    atol=0). ``annualize`` multiplies the per-session sigma by ``sqrt(252)`` (the
    calendared :data:`SESSIONS_PER_YEAR`, NOT the 24/7 365). Because ``r_t`` consumes
    ``C*_{t-1}``, the estimator needs ``window + 1`` bars: NaN until then, and any NaN
    inside a window (a data gap) yields NaN — never bridged. Inputs never mutated.

    This is the ONE realized-vol body; both ``eq_lowvol_252`` (the CS-ranked low-vol
    alpha, ``direction=-1``) and ``eq_vol_252`` (the ``direction=0`` risk/cost
    context) consume it, so the "context == alpha input" invariant cannot drift
    (EQUITIES_CRITIQUE N3).
    """
    if window < 2:
        raise ValueError(f"realized_vol window must be >= 2 (uses ddof=1), got {window}")
    returns = log_returns(adj_close).to_numpy(dtype="float64")
    var = _roll_var(returns, window)
    vol = np.sqrt(var)
    if annualize:
        vol = vol * math.sqrt(SESSIONS_PER_YEAR)
    return pd.DataFrame(vol, index=adj_close.index, columns=adj_close.columns)


def _market_beta(ctx: FeatureContext, adj_close: pd.DataFrame, *, window: int) -> pd.DataFrame:
    """Rolling market beta of each name vs the equal-weight PIT-universe daily return.

    The exact BAB/beta pipeline (EQUITIES_SLEEVE.md §4.2), reusing the crypto
    machinery verbatim (only the window is in sessions, not hours):

    1. ``returns = log_returns(adj_close)`` (daily).
    2. ``mask = _member_mask(ctx, ...)`` — the PIT membership mask
       (:func:`~alphaforge.features.library.mean_reversion._member_mask`; calendar-
       agnostic, only calls ``ctx.universe_asof``).
    3. ``mkt = market_return(returns, mask)`` — equal-weight PIT-universe daily market.
    4. ``beta = rolling_beta(returns, mkt, window)`` — strictly through ``t-1`` (the
       existing conservative variant; NaN until ``window`` valid pairs, NaN on a
       near-constant market). ``window`` is passed EXPLICITLY (the equity 252, not the
       crypto module default 720 — EQUITIES_CRITIQUE B6).

    Returns the raw beta panel; the spec's ``direction`` (or the ``-beta`` negation in
    :func:`_eq_bab_fn`) owns the sign.
    """
    returns = log_returns(adj_close)
    mask = _member_mask(ctx, adj_close.index, [str(c) for c in adj_close.columns])
    mkt = market_return(returns, mask)
    return rolling_beta(returns, mkt, window=window)


# -------------------------------------------------------------------- feature fns


def _eq_mom_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``eq_mom_252_21``: 12-1 momentum ``ln(C*_{t-21}/C*_{t-252})``.

    Reuses the crypto skip-momentum kernel
    :func:`~alphaforge.features.library.momentum.xs_momentum` on the PIT adjusted-close
    panel — structurally identical to ``mom_xs_*``, only L/skip change (252/21
    sessions). Pure function of adjusted closes strictly in the past (both endpoints
    are before ``t``); NaN until ``L + 1`` bars exist.
    """
    out = xs_momentum(
        _adjusted_close_panel(ctx),
        lookback=int(spec.params["lookback"]),
        skip=int(spec.params["skip"]),
    )
    return long_series(out, name=spec.name)


def _eq_rev_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``eq_rev_21``: 1-month reversal ``-ln(C*_t/C*_{t-21})``.

    See :func:`reversal`. Pure function of adjusted closes available at the decision
    close ``t + Δ`` (the bar ``t`` itself is decision-usable at its close); NaN until
    ``W + 1`` bars exist.
    """
    out = reversal(_adjusted_close_panel(ctx), window=int(spec.params["window"]))
    return long_series(out, name=spec.name)


def _eq_realized_vol_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``eq_lowvol_252`` / ``eq_vol_252`` — see :func:`realized_vol`.

    Both factors share this ONE body (and hence one realized-vol number); the spec's
    ``direction`` distinguishes the CS-ranked low-vol alpha (``-1``) from the
    ``direction=0`` risk/cost context (EQUITIES_CRITIQUE N3). The body NEVER negates —
    the low-vol sign is carried by ``direction=-1`` (library convention:
    cf. :mod:`alphaforge.features.library.market_state`), so the raw value is a genuine
    annualized vol comparable across both registrations.
    """
    out = realized_vol(_adjusted_close_panel(ctx), window=int(spec.params["window"]))
    return long_series(out, name=spec.name)


def _eq_beta_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``eq_beta_252``: raw rolling market beta (utility, direction 0).

    ``beta_{i,t} = Cov_{Wβ}(r_i, m) / Var_{Wβ}(m)`` over the ``window`` sessions ending
    ``t-1`` vs the equal-weight PIT-universe daily market — see :func:`_market_beta`.
    Returned raw; ``direction=0`` (an input to BAB / risk, not a standalone alpha).
    Every input is available at the decision close ``t + Δ``: closes through ``t`` (the
    bar-``t`` return is NOT used — beta is lagged to ``t-1``), membership at ``t``.
    """
    out = _market_beta(ctx, _adjusted_close_panel(ctx), window=int(spec.params["window"]))
    return long_series(out, name=spec.name)


def _eq_bab_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``eq_bab_252``: the betting-against-beta low-beta signal.

    Returns ``-beta`` (NEGATED here, by design): the CS pipeline
    (``cross_sectional=True``) then winsorizes + z-scores it within the PIT universe
    per bar, so a low-beta name gets a HIGH score and ``direction=+1`` reads "high
    score ⇒ high expected return," consistent with the framework's sign convention
    (EQUITIES_SLEEVE.md §4.2 step 6). Frazzini-Pedersen's leverage-and-rescale
    *portfolio* construction is the optimizer/sizing layer's job, not the factor's —
    the factor is the cross-sectional low-beta exposure, matching how every other CS
    factor here is just the ranked exposure.

    The negation lives in the body (not in ``direction``) precisely because ``eq_bab``
    and ``eq_beta`` share the same raw beta but expose OPPOSITE signs: ``eq_beta`` is
    raw (``direction=0`` utility), ``eq_bab`` is ``-beta`` ranked (``direction=+1``).
    Pinning the sign in the body keeps the two registrations unambiguous.
    """
    beta = _market_beta(ctx, _adjusted_close_panel(ctx), window=int(spec.params["window"]))
    return long_series(-beta, name=spec.name)


def _eq_amihud_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``eq_amihud_63``: Amihud illiquidity over 63 sessions.

    Reuses :func:`~alphaforge.features.library.liquidity.amihud_illiq` verbatim on the
    PIT adjusted close + dollar (``quote_volume``) volume — ``ln(ILLIQ + eps)`` of the
    mean ``|r|/QV`` over the window, skipping dead/gapped bars. ``direction=0``: a
    risk/cost/universe input, the illiquidity *premium* is unreliable and conflicts
    with tradability (the crypto liquidity module's stance). NaN until ``window + 1``
    bars exist (the returns need the previous close).
    """
    out = amihud_illiq(
        _adjusted_close_panel(ctx),
        ctx.panel("quote_volume"),
        window=int(spec.params["window"]),
    )
    return long_series(out, name=spec.name)


# ------------------------------------------------------------ registered factories


@feature
def eq_mom_252_21() -> FeatureSpec:
    """12-1 cross-sectional momentum: ``ln(C*_{t-21}/C*_{t-252})`` (252/21 sessions).

    The canonical Jegadeesh-Titman / Carhart factor — cumulative return from ``t-252``
    to ``t-21``, skipping the most recent month to dodge short-term reversal.
    ``lookback_bars = lookback + 1 = 253``: consumes ``C*_{t-252}`` and the bar ``t``
    itself (finding 20: derived from params at this single site). Finite window ⇒
    parity atol = 0.
    """
    lookback, skip = 252, 21
    return FeatureSpec(
        name="eq_mom_252_21",
        family=Family.MOMENTUM,
        direction=1,
        cross_sectional=True,
        lookback_bars=lookback + 1,  # consumes C*_{t-L} and the bar t itself
        params={"lookback": lookback, "skip": skip},
        fn=_eq_mom_fn,
    )


@feature
def eq_rev_21() -> FeatureSpec:
    """Short-term (1-month) reversal: ``-ln(C*_t/C*_{t-21})`` (21 sessions). direction +1, CS.

    Jegadeesh (1990); plain (un-residualized) for v1 — equity 1-month reversal is
    robust without the beta residualization the crypto ``mr_res_*`` needs at hour
    scale (residual reversal is a post-v1 refinement). ``lookback_bars = window + 1 =
    22`` (consumes ``C*_{t-21}`` and the bar ``t``). Finite window ⇒ parity atol = 0.
    """
    window = 21
    return FeatureSpec(
        name="eq_rev_21",
        family=Family.REVERSAL,
        direction=1,  # higher = recent loser = expected outperformer
        cross_sectional=True,
        lookback_bars=window + 1,
        params={"window": window},
        fn=_eq_rev_fn,
    )


@feature
def eq_lowvol_252() -> FeatureSpec:
    """Low-volatility anomaly: annualized realized vol over 252 sessions. direction -1, CS.

    Realized vol of daily log returns (annualized x√252); ``direction=-1`` carries the
    anomaly sign (low-risk names earn higher risk-adjusted returns), so the CS winsor→z
    ranks LOW vol HIGH — the body never negates (library convention: the spec's
    ``direction`` owns the sign). ``lookback_bars = window + 1 = 253`` (the daily
    returns consume ``C*_{t-1}``). Finite window ⇒ parity atol = 0.
    """
    window = 252
    return FeatureSpec(
        name="eq_lowvol_252",
        family=Family.VOLATILITY,
        direction=-1,  # low vol => higher expected risk-adjusted return (the anomaly)
        cross_sectional=True,
        lookback_bars=window + 1,  # daily log returns consume C*_{t-1}
        params={"window": window},
        fn=_eq_realized_vol_fn,
    )


@feature
def eq_beta_252() -> FeatureSpec:
    """Rolling market beta vs the equal-weight PIT-universe daily return (252 sessions).

    A ``direction=0`` utility input (the BAB building block / a risk input), NOT a
    standalone alpha, so ``cross_sectional=False`` (consumed raw, like the crypto
    ``adv_quote_30d``/``sigma_daily`` shared inputs). Beta uses returns
    ``t-252 .. t-1`` (conservative through ``t-1``); the oldest, a 1-bar log return at
    ``t-252``, needs ``C*_{t-253}``, so the factor reaches ``window + 1`` bars back
    plus the bar ``t`` itself ⇒ ``lookback_bars = window + 2 = 254`` (finding 20).
    Finite window ⇒ parity atol = 0.
    """
    window = 252
    return FeatureSpec(
        name="eq_beta_252",
        family=Family.MARKET,
        direction=0,
        cross_sectional=False,
        # beta uses returns t-window..t-1; oldest return needs C*_{t-window-1};
        # +1 for that extra close, +1 for the bar t itself (counted in lookback_bars).
        lookback_bars=window + 2,
        params={"window": window},
        fn=_eq_beta_fn,
    )


@feature
def eq_bab_252() -> FeatureSpec:
    """Betting-against-beta: ``-beta`` (low-beta) over 252 sessions. direction +1, CS.

    Frazzini-Pedersen. The body returns ``-beta``; the CS pipeline winsor→z-scores it
    within the PIT universe so low beta ⇒ high score, and ``direction=+1`` reads "high
    score ⇒ high expected return" (§4.2). Same ``lookback_bars = window + 2 = 254`` as
    ``eq_beta_252`` (it is the same beta, negated). Finite window ⇒ parity atol = 0.
    """
    window = 252
    return FeatureSpec(
        name="eq_bab_252",
        family=Family.MARKET,
        direction=1,  # body returns -beta => low beta ranks high => +1
        cross_sectional=True,
        lookback_bars=window + 2,
        params={"window": window},
        fn=_eq_bab_fn,
    )


@feature
def eq_vol_252() -> FeatureSpec:
    """Realized daily vol context over 252 sessions (annualized). direction 0, not CS.

    The SAME annualized realized-vol number as ``eq_lowvol_252`` exposed ``direction=0``
    as a risk/cost input (the alpha is the CS-ranked low-vol; this context feeds
    risk/cost) — one shared body (:func:`realized_vol`) so the two cannot drift
    (EQUITIES_CRITIQUE N3). ``cross_sectional=False`` (consumed raw, in native
    annualized-vol units). ``lookback_bars = window + 1 = 253``. Finite window ⇒
    parity atol = 0.
    """
    window = 252
    return FeatureSpec(
        name="eq_vol_252",
        family=Family.VOLATILITY,
        direction=0,
        cross_sectional=False,
        lookback_bars=window + 1,  # daily log returns consume C*_{t-1}
        params={"window": window},
        fn=_eq_realized_vol_fn,
    )


@feature
def eq_amihud_63() -> FeatureSpec:
    """Amihud illiquidity over 63 sessions (~a quarter). direction 0, not CS.

    ``ln(ILLIQ + eps)`` of the mean ``|r|/QV`` (dollar volume), reusing
    :func:`~alphaforge.features.library.liquidity.amihud_illiq`. ``direction=0`` — a
    risk/cost/universe input (the illiquidity premium is unreliable and conflicts with
    tradability). ``lookback_bars = window + 1 = 64`` (the returns need the previous
    close). Finite window ⇒ parity atol = 0.
    """
    window = 63
    return FeatureSpec(
        name="eq_amihud_63",
        family=Family.LIQUIDITY,
        direction=0,
        cross_sectional=False,
        lookback_bars=window + 1,  # returns need C*_{t-1}
        params={"window": window},
        fn=_eq_amihud_fn,
    )
