#!/usr/bin/env python3
"""PROBE — ALPHAMAX HYSTERESIS on the LIVE k30_dn_63 construction (turnover reduction).

2026-07-12. MEASURE-ONLY. Reads src/** + the k30_dn_63 artifact as templates and mutates no
production state. Every measured arm must pass union-ledger preflight and is recorded before
identity-aligned DSR. Under a paused campaign, unregistered arms fail before data loading.

WHY (vs scripts/probe_alphamax_turnover.py, the prior probe this session): that probe measured
hysteresis on the DEEP-HISTORY 2000-name Sharadar NULL sleeve (net Sharpe -0.05). The
transferable result was a ~28% turnover cut, Sharpe-neutral. A PROMOTION decision must rest on
the ACTUAL LIVE sleeve. This probe re-runs the SAME A/B on the LIVE k30_dn_63 construction:

  LIVE SLEEVE (artifacts/walkforward/k30_dn_63, EQUITY_WF in paper_trading_state.py; deployed):
    * signal   : eq_mom_252_21  (12-1 momentum), the config's only alpha_name
    * universe : the 375-name k30_dn_63 instrument_ids (358 present in the lake+universe today)
    * breadth  : rank_top_k = 30 per side (top-30 long / bottom-30 short) -- verified from the
                 leg positions (L~29-30 / S~30 per rebalance); NOT the 5%-fraction of the 2000-
                 name research book.
    * neutral  : dollar_neutral=True (Sigma w = 0), inverse-vol within each leg
    * cadence  : rebalance_bars = 63 (QUARTERLY) -- signals.horizon_bars, the production cadence
    * gross    : realized gross_mean ~= 0.691 (the 0.5-gross dollar-neutral base scaled ~1.38x
                 by the book vol-target overlay to ~0.13 realized vol). We reproduce this with a
                 constant per-leg gross of 0.345 (total ~0.69) so baseline turnover_ann anchors
                 to the live 4.11. Net Sharpe / DSR / maxDD / the turnover %-CUT are ALL invariant
                 to a constant gross scalar (mean, vol, cost and borrow all scale together), so the
                 verdict does not depend on this choice; it only sets the absolute turnover_ann.
    * costs    : 6 bp one-way (1 comm + 3 half-spread + 2 latency, equity.yaml) + 50 bp/yr GC
                 borrow on the short gross, accrued daily; 0.001 no-trade band (base.yaml).
    * window   : the LIVE out-of-sample curve 2023-07-06 .. 2026-06-01 (728 sessions, 12 quarterly
                 reforms) -- the decision-relevant window where the stored sleeve shows net Sharpe
                 0.907 @ turnover_ann 4.11. Momentum/vol are warmed from 2021 history.
  ANNUALIZATION: ANN=365 for BOTH Sharpe and turnover -- the repo/engine convention
    (metrics.turnover uses bar_a = MS_PER_YEAR/bar_ms = 365 for a D1 bar; sharpe uses
    DAYS_PER_YEAR=365). This makes baseline directly comparable to the stored 0.907 / 4.11.

ARMS (a single incumbent-priority hysteresis state machine parametrized by (exit_frac, min_hold);
breadth is HELD FIXED at K=30 per side so the ONLY thing that varies is churn, not diversification.
ENTER is always the top-K by rank -- a fresh name enters only if it is genuinely top-30):
  baseline    exit=topK   min_hold=0    plain quarterly top-30 reform (the live construction)
  hyst_third  exit=1/3    min_hold=0    THE task arm: enter top-30, HOLD until it exits the top-third
  hyst_qtr    exit=1/4    min_hold=0    robustness: tighter exit band
  hyst_half   exit=1/2    min_hold=0    robustness: wider exit band (shows monotonicity, not a mined knob)
  hold_63     exit=topK   min_hold=63   hold-longer: keep an entry >=63 sessions unless it leaves top-30
  hyst+hold   exit=1/3    min_hold=63   both

SUCCESS GATE (pre-registered, from the task): PROMOTE hyst_third iff ann turnover falls >= 25%
AND net Sharpe >= baseline (within noise) AND maxDD not worse. HONEST framing stated up front:
these fixes raise NET alpha only by cutting COST; gross Sharpe barely moves. The win is
turnover / capacity / lower rebalance-timing luck, NOT a Sharpe jump. A Sharpe-neutral big
turnover cut is the expected, promotable outcome; a pure wash is a legitimate result.

    uv run python scripts/probe_alphamax_hyst_live.py
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

OUT_DIR = _REPO / "artifacts" / "probe" / "alphamax_hyst_live"
K30_WF = _REPO / "artifacts" / "walkforward" / "k30_dn_63" / "walkforward.json"

# ---- construction constants (equity.yaml / base.yaml / k30_dn_63 config / optimizer.py) ----
ANN = 365.0            # engine headline basis (turnover bar_a & Sharpe DAYS_PER_YEAR) -> matches 0.907/4.11
TRADING_DAYS = 252.0   # borrow accrual + honest calendar-Sharpe cross-check
VOL_WINDOW = 63        # trailing sessions for the inverse-vol denominator
VOL_MINP = 30
GROSS_LEG = 0.345      # per-leg gross so total ~0.69 == live gross_mean (vol-target-scaled base)
W_MAX = 0.15           # portfolio.w_max (non-binding at K=30 -> weights ~0.01-0.03)
COST_ONEWAY = 6e-4     # 1bp comm + 3bp half-spread + 2bp latency (equity.yaml)
BORROW_ANN = 50e-4     # 50 bp/yr GC borrow on the short gross (equity.yaml)
NO_TRADE_BAND = 0.001  # base.yaml no_trade_band
K_PER_SIDE = 30        # rank_top_k of the LIVE k30 sleeve (fixed count, not a fraction)
REFORM_BARS = 63       # rebalance_bars (quarterly, production cadence)
LIVE_START = "2023-07-06"  # k30_dn_63 first OOS position (leg_00); window end from the artifact
WARMUP_START = "2021-01-01"

# name, (exit_frac, min_hold_bars);  exit_frac = None -> exit band == top-K (plain reform)
ARMS: list[tuple[str, float | None, int]] = [
    ("baseline",   None,  0),
    ("hyst_third", 1.0 / 3.0, 0),
    ("hyst_qtr",   0.25,  0),
    ("hyst_half",  0.50,  0),
    ("hold_63",    None,  63),
    ("hyst+hold",  1.0 / 3.0, 63),
]


# --------------------------------------------------------------- daily-return probe spec
def _probe_dret_fn(ctx, spec):
    from alphaforge.features.context import long_series
    from alphaforge.features.library.equity_price import _adjusted_close_panel

    px = _adjusted_close_panel(ctx)
    return long_series(px.pct_change(), name=spec.name)


def _register_dret(reg) -> None:
    from alphaforge.features.spec import Family, FeatureSpec

    if "probe_dret" in {s.name for s in reg.all_specs()}:
        return
    reg.register(lambda: FeatureSpec(
        name="probe_dret", family=Family.MOMENTUM, direction=1, cross_sectional=False,
        lookback_bars=2, params={}, fn=_probe_dret_fn,
    ))


# ------------------------------------------------------------------------- construction
def _leg_weights(sel: np.ndarray, invvol: np.ndarray, sign: float) -> np.ndarray:
    """Inverse-vol weights for one leg, |Sigma| = GROSS_LEG, +-W_MAX clipped, per-leg renorm
    -- the RankEqualVolFallback dollar-neutral leg (half = 0.25*gross_max here scaled to 0.345)."""
    w = np.zeros_like(invvol)
    if not sel.any():
        return w
    w[sel] = sign * invvol[sel]
    g = float(np.abs(w[sel]).sum())
    if g <= 0.0:
        return np.zeros_like(invvol)
    w[sel] *= GROSS_LEG / g
    w = np.clip(w, -W_MAX, W_MAX)
    g2 = float(np.abs(w[sel]).sum())
    ma = float(np.abs(w[sel]).max())
    if g2 > 0.0 and ma > 0.0:
        w[sel] *= min(GROSS_LEG / g2, W_MAX / ma)
    return w


def _select(
    frac: np.ndarray, eligible: np.ndarray, held_entry: np.ndarray, t: int,
    enter: float, exit_: float, min_hold: int, K: int, *, low_is_strong: bool,
) -> np.ndarray:
    """Incumbent-priority hysteresis membership for ONE leg (breadth fixed at K).

    `frac` = ascending momentum fractile in [0,1) (0 = strongest). An INCUMBENT is retained even
    when a marginal outsider now out-ranks it, so long as it is still inside the wider EXIT band
    (strength <= exit_) OR still inside its minimum hold. Remaining slots go to the best fresh
    ENTRANTS inside the tight ENTER band (top-K). exit_=enter & min_hold=0 -> plain top-K reform."""
    n = frac.shape[0]
    strength = frac if low_is_strong else (1.0 - frac)  # 0 = strongest for this leg
    held = held_entry >= 0
    age = t - held_entry
    retained = held & eligible & ((strength <= exit_) | (age < min_hold))
    sel = np.zeros(n, dtype=bool)
    ret_idx = np.where(retained)[0]
    if ret_idx.size > K:
        ret_idx = ret_idx[np.argsort(strength[ret_idx], kind="stable")][:K]
    sel[ret_idx] = True
    need = K - int(sel.sum())
    if need > 0:
        entrants = (~sel) & (~held) & eligible & (strength <= enter)
        e_idx = np.where(entrants)[0]
        if e_idx.size:
            e_idx = e_idx[np.argsort(strength[e_idx], kind="stable")][:need]
            sel[e_idx] = True
            need -= e_idx.size
    if need > 0:  # breadth backfill (thin cross-section): next-strongest eligible, any band
        pool = np.where(eligible & ~sel)[0]
        if pool.size:
            pool = pool[np.argsort(strength[pool], kind="stable")][:need]
            sel[pool] = True
    return sel


def simulate(
    mom: np.ndarray, ret: np.ndarray, member: np.ndarray, vol: np.ndarray, dates: np.ndarray,
    t0: int, reform_bars: int, exit_frac: float | None, min_hold: int,
) -> dict:
    """One arm on the LIVE window. Book initialized flat at t0 (go-live); reform every
    reform_bars; K=30 per side fixed. Returns net daily returns + turnover/cost diagnostics.
    ENTER band = top-K each reform (enter = K/n_elig); exit band = exit_frac (None -> = enter)."""
    T, N = mom.shape
    finite_mom = np.isfinite(mom)
    finite_vol = np.isfinite(vol) & (vol > 0)
    eligible_all = member & finite_mom & finite_vol
    # Common-to-all-arms return hygiene (large-caps: near-inert; keeps the A/B pristine).
    ret_use = np.clip(np.where(np.isfinite(ret), ret, 0.0), -0.5, 1.0)

    reb_set = set(range(t0, T, reform_bars))
    w_tgt = np.zeros(N, dtype=np.float64)
    w_prev_tgt = np.zeros(N, dtype=np.float64)
    hl_entry = np.full(N, -1, dtype=np.int64)
    hs_entry = np.full(N, -1, dtype=np.int64)
    net = np.full(T, np.nan, dtype=np.float64)
    gross = np.full(T, np.nan, dtype=np.float64)
    pending_cost = 0.0
    reb_turnovers: list[float] = []
    long_sizes: list[int] = []
    short_sizes: list[int] = []
    borrow_total = 0.0
    cost_total = 0.0

    for t in range(t0, T):
        g = float((w_tgt * ret_use[t]).sum())
        gross[t] = g
        short_gross = float(-np.minimum(w_tgt, 0.0).sum())
        borrow_t = short_gross * (BORROW_ANN / TRADING_DAYS)
        net[t] = g - borrow_t - pending_cost
        borrow_total += borrow_t
        cost_total += pending_cost
        pending_cost = 0.0

        if t in reb_set:
            elig = eligible_all[t]
            n_elig = int(elig.sum())
            if n_elig < 2 * K_PER_SIDE:
                continue
            m = mom[t]
            frac = np.full(N, np.inf, dtype=np.float64)
            ei = np.where(elig)[0]
            order = ei[np.argsort(-m[ei], kind="stable")]  # strongest momentum first
            frac[order] = np.arange(order.size, dtype=np.float64) / float(order.size)
            K = K_PER_SIDE
            enter = K / float(n_elig)                      # ENTER = top-K by rank
            exit_ = enter if exit_frac is None else float(exit_frac)

            long_sel = _select(frac, elig, hl_entry, t, enter, exit_, min_hold, K, low_is_strong=True)
            short_sel = _select(frac, elig, hs_entry, t, enter, exit_, min_hold, K, low_is_strong=False)
            short_sel &= ~long_sel

            invvol = np.where(finite_vol[t], 1.0 / np.where(vol[t] > 0, vol[t], np.nan), 0.0)
            invvol = np.nan_to_num(invvol, nan=0.0, posinf=0.0, neginf=0.0)
            new_tgt = _leg_weights(long_sel, invvol, +1.0) + _leg_weights(short_sel, invvol, -1.0)

            small = np.abs(new_tgt - w_prev_tgt) <= NO_TRADE_BAND
            new_tgt = np.where(small, w_prev_tgt, new_tgt)

            turnover = float(np.abs(new_tgt - w_prev_tgt).sum())
            reb_turnovers.append(turnover)
            pending_cost = turnover * COST_ONEWAY

            now_long = new_tgt > 1e-9
            now_short = new_tgt < -1e-9
            hl_entry = np.where(now_long & (hl_entry < 0), t, np.where(now_long, hl_entry, -1))
            hs_entry = np.where(now_short & (hs_entry < 0), t, np.where(now_short, hs_entry, -1))
            long_sizes.append(int(now_long.sum()))
            short_sizes.append(int(now_short.sum()))
            w_tgt = new_tgt
            w_prev_tgt = new_tgt

    idx = dates[t0:]
    net_s = pd.Series(net[t0:], index=idx).dropna()
    n_days = len(net_s)
    turnover_ann = (float(np.sum(reb_turnovers)) / n_days * ANN) if n_days else float("nan")
    return {
        "net": net_s,
        "gross": pd.Series(gross[t0:], index=idx).dropna(),
        "turnover_ann": turnover_ann,
        "cost_drag_ann_bps": (cost_total / n_days * ANN * 1e4) if n_days else float("nan"),
        "borrow_drag_ann_bps": (borrow_total / n_days * ANN * 1e4) if n_days else float("nan"),
        "n_reforms": len(reb_turnovers),
        "avg_turnover_per_reform": float(np.mean(reb_turnovers)) if reb_turnovers else float("nan"),
        "avg_long_names": float(np.mean(long_sizes)) if long_sizes else float("nan"),
        "avg_short_names": float(np.mean(short_sizes)) if short_sizes else float("nan"),
        "n_days": n_days,
    }


def _metrics(net: pd.Series, gross: pd.Series) -> dict:
    v = net.to_numpy(dtype=np.float64)
    g = gross.to_numpy(dtype=np.float64)
    sd = float(np.std(v, ddof=1))
    gd = float(np.std(g, ddof=1))
    eq = np.cumprod(1.0 + v)
    peak = np.maximum.accumulate(eq)
    max_dd = float(np.max(1.0 - eq / peak)) if eq.size else float("nan")
    yrs = len(v) / TRADING_DAYS
    total = float(np.prod(1.0 + v))
    return {
        "net_sharpe_ann365": (float(np.mean(v)) / sd * math.sqrt(ANN)) if sd > 0 else float("nan"),
        "net_sharpe_ann252": (float(np.mean(v)) / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else float("nan"),
        "gross_sharpe_ann365": (float(np.mean(g)) / gd * math.sqrt(ANN)) if gd > 0 else float("nan"),
        "vol_ann365": sd * math.sqrt(ANN),
        "max_dd": max_dd,
        "cagr": (total ** (1.0 / yrs) - 1.0) if yrs > 0 else float("nan"),
        "total_return": total - 1.0,
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="probe_alphamax_hyst_live")
    ap.add_argument("--profile", default="sharadar")
    ap.add_argument("--start", default=LIVE_START, help="book/measurement start (live OOS go-live)")
    ap.add_argument("--end", default="2026-06-01")
    ap.add_argument("--warmup", default=WARMUP_START, help="data load start for momentum/vol warmup")
    a = ap.parse_args(argv)

    import alphaforge.features.library  # noqa: F401
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import now_ms, parse_utc
    from alphaforge.data.schemas import ohlcv_dataset
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.research.ic_report import _membership_mask
    from alphaforge.validation.dsr import dsr_from_returns
    from alphaforge.validation.experiments import ExperimentUnion
    from alphaforge.validation.probe_ledger import record_probe_trial

    settings = load_settings(a.profile)
    union = ExperimentUnion.discover(settings.paths.var_dir / "experiments.jsonl", _REPO)

    def trial_config(arm: str, exit_frac: float | None, min_hold_bars: int) -> dict:
        return {
            "profile": a.profile,
            "sleeve": "k30_dn_63",
            "arm": arm,
            "signal": "eq_mom_252_21",
            "rank_top_k": K_PER_SIDE,
            "reform_bars": REFORM_BARS,
            "exit_frac": exit_frac,
            "min_hold_bars": min_hold_bars,
            "vol_window": VOL_WINDOW,
            "gross_leg": GROSS_LEG,
            "cost_oneway": COST_ONEWAY,
            "borrow_ann": BORROW_ANN,
            "warmup": a.warmup,
            "start": a.start,
            "end": a.end,
        }

    configs = [trial_config(*arm) for arm in ARMS]
    union.preflight_hypotheses(
        [{"probe": "alphamax_hyst_live", **config} for config in configs]
    )
    sleeve = sleeve_for(settings.data.asset_class)
    tf = sleeve.anchor_tf
    start = parse_utc(f"{a.warmup}T00:00:00Z")
    end = parse_utc(f"{a.end}T00:00:00Z")

    # LIVE universe = the k30_dn_63 instrument_ids (restricted to lake+universe presence)
    k30_ids = json.loads(K30_WF.read_text())["config"]["instrument_ids"]

    reg = default_registry()
    _register_dret(reg)
    by_name = {s.name: s for s in reg.all_specs()}
    specs = [by_name["eq_mom_252_21"], by_name["probe_dret"]]

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        engine = FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class)
        members = set(universe.read_intervals().column("instrument_id").to_pylist())
        in_lake = set(paths.instrument_ids(ohlcv_dataset(tf)))
        ids = sorted(set(k30_ids) & members & in_lake)
        print(f"LIVE k30 universe: {len(ids)}/{len(k30_ids)} names present in lake+universe | window warmup {a.warmup} book {a.start}..{a.end} | tf={tf.name}")
        raw = engine.compute_history(specs, ids, start=start, end=end)
        mask = _membership_mask(universe, raw)

    mom_w = raw["eq_mom_252_21"].unstack("instrument_id").sort_index()
    ret_w = raw["probe_dret"].unstack("instrument_id").sort_index()
    mem_w = mask.unstack("instrument_id").reindex(index=mom_w.index, columns=mom_w.columns, fill_value=False)
    ret_w = ret_w.reindex(index=mom_w.index, columns=mom_w.columns)
    vol_w = ret_w.rolling(VOL_WINDOW, min_periods=VOL_MINP).std() * math.sqrt(ANN)

    dates = mom_w.index.to_numpy(dtype=np.int64)
    mom = mom_w.to_numpy(dtype=np.float64)
    ret = ret_w.to_numpy(dtype=np.float64)
    member = mem_w.to_numpy(dtype=bool)
    vol = vol_w.to_numpy(dtype=np.float64)

    start_ms = int(parse_utc(f"{a.start}T00:00:00Z"))  # parse_utc -> epoch-ms int
    t0 = int(np.searchsorted(dates, start_ms, side="left"))
    n_after = int((dates >= start_ms).sum())
    print(f"panels: T={mom.shape[0]} sessions x N={mom.shape[1]} names | book t0 idx={t0} (>= {a.start}) -> {n_after} OOS sessions | "
          f"finite momentum: {np.isfinite(mom).mean():.1%} | member cells: {member.mean():.1%}")

    results: dict = {}
    audit_before = union.n_trials()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for (arm, exit_frac, mh), config in zip(ARMS, configs, strict=True):
        sim = simulate(mom, ret, member, vol, dates, t0, REFORM_BARS, exit_frac, mh)
        met = _metrics(sim["net"], sim["gross"])
        record_probe_trial(
            "alphamax_hyst_live",
            config,
            sim["net"],
            now_ms=now_ms(),
            periods_per_year=int(ANN),
            experiment_log=union,
        )
        results[arm] = {
            "exit_frac": exit_frac, "min_hold_bars": mh, **met,
            "turnover_ann": sim["turnover_ann"], "cost_drag_ann_bps": sim["cost_drag_ann_bps"],
            "borrow_drag_ann_bps": sim["borrow_drag_ann_bps"], "avg_turnover_per_reform": sim["avg_turnover_per_reform"],
            "avg_long_names": sim["avg_long_names"], "avg_short_names": sim["avg_short_names"],
            "n_reforms": sim["n_reforms"], "n_days": sim["n_days"], "_net": sim["net"],
        }

    n_led, var_sr = union.n_hypotheses(), union.hypothesis_sharpe_variance()
    for result in results.values():
        rep = dsr_from_returns(result["_net"], max(2, n_led), var_sr, ANN)
        result["dsr"] = {
            "selection_union": {
                "N": n_led,
                "dsr": float(np.real(rep.dsr)),
                "psr": float(np.real(rep.psr)),
            }
        }
    trials_logged = union.n_trials() - audit_before

    def pct(x: float) -> str:
        return f"{x:+.1%}" if math.isfinite(x) else "  n/a"

    base = results["baseline"]
    print("\n" + "=" * 118)
    print("ALPHAMAX HYSTERESIS on the LIVE k30_dn_63 construction  (K=30/side dollar-neutral 12-1; quarterly; 6bp one-way + 50bp borrow; PIT no same-bar)")
    print("STORED LIVE ANCHOR (artifacts/walkforward/k30_dn_63): net Sharpe 0.907 @ turnover_ann 4.11, maxDD 0.087, 728 sessions, 12 reforms")
    print("=" * 118)
    hdr = f"{'arm':<11}{'netSR365':>9}{'netSR252':>9}{'grossSR':>8}{'turn_ann':>9}{'Δturn':>8}{'ΔnetSR':>8}{'maxDD':>7}{'ΔmaxDD':>8}{'cost_bps':>9}{'borrow':>8}{'L/S':>8}{'reforms':>8}{'DSR':>7}"
    print(hdr)
    for arm, *_ in ARMS:
        r = results[arm]
        dturn = (r["turnover_ann"] - base["turnover_ann"]) / base["turnover_ann"] if base["turnover_ann"] else float("nan")
        dsr365 = r["net_sharpe_ann365"] - base["net_sharpe_ann365"]
        dmaxdd = r["max_dd"] - base["max_dd"]
        dsr_var = r["dsr"].get("var", {}).get("dsr", float("nan"))
        print(
            f"{arm:<11}{r['net_sharpe_ann365']:>9.3f}{r['net_sharpe_ann252']:>9.3f}{r['gross_sharpe_ann365']:>8.3f}"
            f"{r['turnover_ann']:>9.2f}{pct(dturn):>8}{dsr365:>+8.3f}{r['max_dd']:>7.3f}{dmaxdd:>+8.3f}"
            f"{r['cost_drag_ann_bps']:>9.1f}{r['borrow_drag_ann_bps']:>8.1f}{r['avg_long_names']:>4.0f}/{r['avg_short_names']:<3.0f}{r['n_reforms']:>8}{dsr_var:>7.3f}"
        )

    print("\ntreatment-vs-baseline net-return corr (near 1.0 = genuinely the same book, only cheaper):")
    base_net = base["_net"]
    for arm, *_ in ARMS[1:]:
        j = pd.concat([results[arm]["_net"].rename("t"), base_net.rename("b")], axis=1).dropna()
        print(f"  {arm:<11} corr={j['t'].corr(j['b']):.4f}")

    print("\nPRE-REGISTERED GATE (task): hyst_third PROMOTES iff turnover down >= 25% AND net Sharpe >= baseline (noise ok) AND maxDD not worse.")
    verdict: dict = {}
    for arm, *_ in ARMS[1:]:
        r = results[arm]
        dturn = (r["turnover_ann"] - base["turnover_ann"]) / base["turnover_ann"] if base["turnover_ann"] else 0.0
        dsr365 = r["net_sharpe_ann365"] - base["net_sharpe_ann365"]
        dmaxdd = r["max_dd"] - base["max_dd"]
        ok = (dturn <= -0.25) and (dsr365 >= -0.05) and (dmaxdd <= 0.005)
        verdict[arm] = {"turnover_cut": dturn, "net_sr_delta": dsr365, "maxdd_delta": dmaxdd, "passes_gate": bool(ok)}
        print(f"  {arm:<11}: turnover {pct(dturn)}, ΔnetSR {dsr365:+.3f}, ΔmaxDD {dmaxdd:+.3f} -> {'PASS' if ok else 'fail'}")

    payload = {
        "probe": "alphamax_hyst_live", "sleeve": "k30_dn_63",
        "window": {"warmup": a.warmup, "book_start": a.start, "end": a.end},
        "n_ids": len(ids), "k30_ids_total": len(k30_ids), "T": int(mom.shape[0]), "oos_sessions": n_after,
        "construction": {
            "K_per_side": K_PER_SIDE, "reform_bars": REFORM_BARS, "vol_window": VOL_WINDOW,
            "gross_leg": GROSS_LEG, "gross_total": 2 * GROSS_LEG, "w_max": W_MAX,
            "cost_oneway_bps": COST_ONEWAY * 1e4, "borrow_ann_bps": BORROW_ANN * 1e4,
            "no_trade_band": NO_TRADE_BAND, "ann_basis": ANN,
        },
        "stored_live_anchor": {"net_sharpe": 0.907, "turnover_ann": 4.11, "max_dd": 0.0868, "n_sessions": 728, "n_reforms": 12},
        "selection_union": {"N": n_led, "var_sr": var_sr},
        "results": {arm: {k: v for k, v in r.items() if k != "_net"} for arm, r in results.items()},
        "gate": verdict, "trials_logged_this_run": trials_logged,
        "note": "Every measured arm is union-registered before DSR; promotion remains a separate decision.",
    }
    (OUT_DIR / "report.json").write_text(json.dumps(payload, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\npersisted: {OUT_DIR / 'report.json'}")
    print(f"TRIAL RECORDS APPENDED THIS RUN: {trials_logged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
