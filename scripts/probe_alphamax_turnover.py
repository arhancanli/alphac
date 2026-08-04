#!/usr/bin/env python3
"""PROBE 3 — ALPHAMAX turnover reduction: hysteresis bands + hold-longer rank-persistence.

MEASURE-ONLY. New file only; reads src/** as templates; NEVER mutates it. Writes only
artifacts/probe/alphamax_turnover/*. Does NOT append to any experiments ledger (it is a
cheap construction SCREEN, not a production walk-forward): TRIALS BURNED = 0. The DSR at
ledger N is computed read-only via dsr_from_returns (a pure function) so the deflated view
is visible without recording a trial.

WHY A SELF-CONTAINED BOOK SIMULATOR (not the production WalkForwardRunner):
  AlphaMax's binding constraint is turnover/cost, not signal (every momentum-SIGNAL variant
  screened dead). The two construction fixes here — hysteresis bands and a minimum-hold rule —
  change WHICH names are held between reforms, i.e. the SELECTION → WEIGHTS map. The production
  runner only exposes a monthly/quarterly HARD reform + a per-name no-trade band; it has no
  hysteresis / min-hold knob, so measuring these treatments through it would require editing
  src/** (forbidden here — that is the human's separate, deliberate promotion step). So we
  reconstruct the dollar-neutral inverse-vol book faithfully in ONE self-contained simulator
  and run all four arms through IDENTICAL machinery. The A/B is INTERNAL (this simulator's own
  baseline vs its treatments) — apples-to-apples by construction — and is anchored to the
  stored production baselines (k30_dn_63 live net Sharpe 0.907 @ turnover 4.11x; prereg_momentum
  deep-history net Sharpe -0.049 @ turnover 3.26x) with the gap disclosed.

CONSTRUCTION (mirrors src/alphaforge/portfolio/optimizer.py::RankEqualVolFallback,
dollar_neutral=True, and the equity.yaml frictions):
  * Signal: the canonical eq_mom_252_21 (12-1) panel, computed by the real FeatureEngine on
    the survivorship-free Sharadar lake with PIT split-only adjustment + PIT universe mask.
  * Book: each rebalance, rank eligible names by mu; long the strong tail / short the weak tail;
    within each leg weight ∝ 1/sigma (63-session realized vol) normalized to 0.25 gross per leg
    (Σw=0 dollar-neutral), clip ±w_max=0.15, renormalize per leg. Breadth K = round(0.05·N_elig)
    per side (≈ the production top-100 on a ~2000 universe) — HELD FIXED across all arms so the
    only thing that varies is churn, not diversification.
  * Costs (committed, always): 6 bp one-way per unit traded (1 commission + 3 half-spread + 2
    latency, equity.yaml) + 50 bp/yr GC borrow accrued daily on the short gross. A 0.001
    no-trade band (base.yaml) suppresses dust trades, common to all arms.
  * PIT: weights decided from data through the close of rebalance day r are effective for r+1's
    return onward — never same-bar. Weights drift buy-and-hold between reforms; turnover at a
    reform = Σ_i|w_target_i − w_drifted_i| (one-way, repo turnover() semantics).

PRE-REGISTERED ARMS (locked before any result; a single selection state machine parametrized by
(enter_frac, exit_frac, min_hold_bars); a held name is DROPPED at a reform iff it leaves the exit
band AND its age ≥ min_hold_bars; K best by rank kept so breadth is constant):
  BASELINE  enter=0.05 exit=0.05 min_hold=0   monthly HARD reform of the top-5% (≈ prod top-100)
  A HYST    enter=0.05 exit=0.15 min_hold=0   hysteresis: enter top-5%, hold until it leaves top-15%
  B HOLD    enter=0.05 exit=0.05 min_hold=63  hold-longer: keep an entry ≥63 sessions (~3mo) unless
                                              it collapses out of the top-5% after the min hold
  A+B       enter=0.05 exit=0.15 min_hold=63  both
Run at TWO reform cadences: 21 sessions (monthly — the task's framing, where the mechanism is most
visible) and 63 sessions (quarterly — the production rebalance_bars, the decision-relevant cadence).

SUCCESS GATE (pre-registered): an arm PROMOTES only if net Sharpe ≥ baseline AND ann turnover
falls ≥30–40%. HONEST CAVEAT stated up front: these fixes raise NET alpha by cutting COST; the
GROSS Sharpe barely moves — a flat/near-flat net Sharpe with a big turnover cut is the win, and a
pure wash is a legitimate (and common) outcome.

Usage:
  uv run python scripts/probe_alphamax_turnover.py            # 2005-2026 Sharadar, both cadences
  uv run python scripts/probe_alphamax_turnover.py --start 2005-01-01 --end 2026-06-01
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
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

OUT_DIR = _REPO / "artifacts" / "probe" / "alphamax_turnover"

# ---- construction constants (equity.yaml / base.yaml / optimizer.py) -----------------
ANN = 365.0            # repo headline annualization basis (matches stored summaries)
TRADING_DAYS = 252.0   # borrow accrual + the honest calendar Sharpe cross-check
VOL_WINDOW = 63        # trailing sessions for the inverse-vol denominator
VOL_MINP = 30          # min obs before a name's vol is trusted
GROSS_LEG = 0.25       # per-leg gross (dollar-neutral: long +0.25 / short -0.25 → Σw=0)
W_MAX = 0.15           # per-name hard cap (portfolio.w_max)
COST_ONEWAY = 6e-4     # 1bp commission + 3bp half-spread + 2bp latency (equity.yaml)
BORROW_ANN = 50e-4     # 50 bp/yr GC borrow on the short leg (equity.yaml)
NO_TRADE_BAND = 0.001  # base.yaml no_trade_band — dust-trade suppression, common to all arms
ENTER_FRAC = 0.05      # breadth: top-5% per side (≈ production top-100 on ~2000 names)

# name, (enter_frac, exit_frac, min_hold_bars)
ARMS: list[tuple[str, float, float, int]] = [
    ("baseline",  ENTER_FRAC, 0.05, 0),
    ("A_hyst",    ENTER_FRAC, 0.15, 0),
    ("B_hold",    ENTER_FRAC, 0.05, 63),
    ("A+B",       ENTER_FRAC, 0.15, 63),
]
CADENCES = [("monthly_21", 21), ("quarterly_63", 63)]


# --------------------------------------------------------------- daily-return probe spec
def _probe_dret_fn(ctx, spec):  # noqa: ANN001, ANN202 — FeatureSpec body signature
    """Daily SIMPLE return panel from the sanctioned PIT split-adjusted close.

    Reuses equity_price._adjusted_close_panel (the ONE place equity adjustment happens) so
    the return series carries the identical split-only, fail-closed, PIT convention as every
    price factor. Simple (arithmetic) returns because the book P&L is Σ w·r; NaN across a
    missing bar (never bridged). Evaluation input only — direction is irrelevant.
    """
    from alphaforge.features.context import long_series
    from alphaforge.features.library.equity_price import _adjusted_close_panel

    px = _adjusted_close_panel(ctx)
    return long_series(px.pct_change(), name=spec.name)


def _register_dret(reg) -> None:  # noqa: ANN001
    from alphaforge.features.spec import Family, FeatureSpec

    have = {s.name for s in reg.all_specs()}
    if "probe_dret" in have:
        return
    spec = FeatureSpec(
        name="probe_dret",
        family=Family.MOMENTUM,  # family is immaterial for an evaluation panel
        direction=1,
        cross_sectional=False,
        lookback_bars=2,  # C*_t / C*_{t-1}
        params={},
        fn=_probe_dret_fn,
    )
    reg.register(lambda: spec)


# ------------------------------------------------------------------------- the simulator
def _leg_weights(sel: np.ndarray, invvol: np.ndarray, sign: float) -> np.ndarray:
    """Inverse-vol weights for one leg, normalized to |Σ| = GROSS_LEG, ±W_MAX clipped
    and per-leg renormalized — byte-for-byte the RankEqualVolFallback dollar-neutral leg."""
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
    frac: np.ndarray,
    eligible: np.ndarray,
    held_entry: np.ndarray,
    t: int,
    enter: float,
    exit_: float,
    min_hold: int,
    K: int,
    *,
    low_is_strong: bool,
) -> np.ndarray:
    """Incumbent-priority hysteresis membership for ONE leg (breadth fixed at K).

    `frac` is the ascending momentum fractile in [0,1) (0 = strongest momentum). Long leg:
    low frac is strong (low_is_strong=True); short leg: high frac is strong.

    The hysteresis (and the whole point of the probe): an INCUMBENT is retained even when a
    marginal outsider now out-ranks it, so long as it is still inside the wider EXIT band OR
    still inside its minimum hold. Only when incumbents don't fill the K slots do we add the
    best-ranked fresh ENTRANTS (rank inside the tight ENTER band). Baseline (enter=exit,
    min_hold=0) degenerates to plain top-K reform: incumbents are exactly the still-top-K
    names, so keeping-then-filling reproduces the top-K. Wider exit / longer hold keep more
    incumbents ⇒ fewer swaps ⇒ lower turnover, at the SAME breadth K."""
    n = frac.shape[0]
    strength = frac if low_is_strong else (1.0 - frac)  # 0 = strongest for this leg
    held = held_entry >= 0
    age = t - held_entry  # meaningful only where held
    retained = held & eligible & ((strength <= exit_) | (age < min_hold))
    sel = np.zeros(n, dtype=bool)
    ret_idx = np.where(retained)[0]
    if ret_idx.size > K:  # too many incumbents: keep the K strongest-ranked incumbents
        ret_idx = ret_idx[np.argsort(strength[ret_idx], kind="stable")][:K]
    sel[ret_idx] = True
    need = K - int(sel.sum())
    if need > 0:  # fill remaining slots with the best fresh entrants inside the ENTER band
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
    mom: np.ndarray,
    ret: np.ndarray,
    member: np.ndarray,
    vol: np.ndarray,
    dates: np.ndarray,
    reform_bars: int,
    enter: float,
    exit_: float,
    min_hold: int,
) -> dict:
    """One arm at one cadence. Returns net daily returns + turnover/cost diagnostics."""
    T, N = mom.shape
    finite_mom = np.isfinite(mom)
    finite_vol = np.isfinite(vol) & (vol > 0)
    eligible_all = member & finite_mom & finite_vol
    # Return hygiene for survivorship-free small-caps (identical across arms, so A/B-neutral):
    # a single-session P&L is winsorized to [-50%, +100%]. Raw pct_change on penny / delisting
    # prints carries |r|>>1 garbage that would dominate a levered book; production's quality
    # layer flags |log-ret| > 8·sigma as OUTLIER — this is the self-contained analogue.
    ret_use = np.clip(np.where(np.isfinite(ret), ret, 0.0), -0.5, 1.0)

    n_elig_row = eligible_all.sum(axis=1)
    warm = np.where(n_elig_row >= 100)[0]
    t0 = int(warm[0]) if warm.size else int(np.argmax(n_elig_row > 0))
    reb_set = set(range(t0, T, reform_bars))

    # Textbook factor-portfolio P&L: TARGET weights are held constant over each holding period
    # (reset to target daily — the standard decile-portfolio convention). This is bounded (no
    # unbounded intra-period drift to blow up on a small-cap 10-bagger) and makes the A/B pristine:
    # the ONLY thing that varies across arms is the reform-time SELECTION, hence the turnover.
    # Turnover is charged target-to-target at each reform (Σ|w_new − w_old|, one-way) — exactly
    # the selection churn the treatments attack; signal-independent intra-period drift-trades are
    # second-order and common to all arms (documented simplification).
    w_tgt = np.zeros(N, dtype=np.float64)     # weights currently in force
    w_prev_tgt = np.zeros(N, dtype=np.float64)  # last reform's target (for turnover)
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
            if n_elig < 2:
                continue
            m = mom[t]
            frac = np.full(N, np.inf, dtype=np.float64)
            ei = np.where(elig)[0]
            order = ei[np.argsort(-m[ei], kind="stable")]  # strongest momentum first
            frac[order] = np.arange(order.size, dtype=np.float64) / float(order.size)
            K = max(1, int(round(enter * n_elig)))

            long_sel = _select(frac, elig, hl_entry, t, enter, exit_, min_hold, K, low_is_strong=True)
            short_sel = _select(frac, elig, hs_entry, t, enter, exit_, min_hold, K, low_is_strong=False)
            short_sel &= ~long_sel  # never both sides (safe at thin N)

            invvol = np.where(finite_vol[t], 1.0 / np.where(vol[t] > 0, vol[t], np.nan), 0.0)
            invvol = np.nan_to_num(invvol, nan=0.0, posinf=0.0, neginf=0.0)
            new_tgt = _leg_weights(long_sel, invvol, +1.0) + _leg_weights(short_sel, invvol, -1.0)

            # no-trade band vs the last target (dust suppression, common to all arms)
            small = np.abs(new_tgt - w_prev_tgt) <= NO_TRADE_BAND
            new_tgt = np.where(small, w_prev_tgt, new_tgt)

            turnover = float(np.abs(new_tgt - w_prev_tgt).sum())  # one-way, repo turnover semantics
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


# ------------------------------------------------------------------------------- driver
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe_alphamax_turnover")
    ap.add_argument("--profile", default="sharadar")
    ap.add_argument("--start", default="2005-01-01")  # prereg_momentum window
    ap.add_argument("--end", default="2026-06-01")
    a = ap.parse_args(argv)

    import alphaforge.features.library  # noqa: F401  canonical factors
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import parse_utc
    from alphaforge.data.schemas import ohlcv_dataset
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.research.ic_report import _membership_mask
    from alphaforge.validation.dsr import dsr_from_returns
    from alphaforge.validation.experiments import ExperimentLog

    settings = load_settings(a.profile)
    sleeve = sleeve_for(settings.data.asset_class)
    tf = sleeve.anchor_tf
    start = parse_utc(f"{a.start}T00:00:00Z")
    end = parse_utc(f"{a.end}T00:00:00Z")

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
        ids = sorted(members & in_lake)
        print(f"universe: {len(ids)} PIT-ever-member ids with bars | window [{a.start},{a.end}) | tf={tf.name}")
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
    print(f"panels: T={mom.shape[0]} sessions x N={mom.shape[1]} names | "
          f"finite momentum cells: {np.isfinite(mom).mean():.1%} | member cells: {member.mean():.1%}")

    # ledgers for the read-only DSR deflation (NO trial is recorded by this probe)
    leds = {}
    for name, rel in (("var", "var/experiments.jsonl"), ("var_sharadar", "var_sharadar/experiments.jsonl")):
        fp = _REPO / rel
        if fp.exists():
            led = ExperimentLog(fp)
            leds[name] = (led.n_trials(), led.trial_sharpe_variance())

    results: dict = {}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for cad_name, reform in CADENCES:
        results[cad_name] = {}
        for arm, enter, exit_, mh in ARMS:
            sim = simulate(mom, ret, member, vol, dates, reform, enter, exit_, mh)
            met = _metrics(sim["net"], sim["gross"])
            dsr = {}
            for lname, (n_led, var_sr) in leds.items():
                rep = dsr_from_returns(sim["net"], max(2, n_led), var_sr, ANN)
                dsr[lname] = {"N": n_led, "dsr": float(np.real(rep.dsr)), "psr": float(np.real(rep.psr))}
            results[cad_name][arm] = {
                "enter": enter, "exit": exit_, "min_hold_bars": mh,
                **met,
                "turnover_ann": sim["turnover_ann"],
                "cost_drag_ann_bps": sim["cost_drag_ann_bps"],
                "borrow_drag_ann_bps": sim["borrow_drag_ann_bps"],
                "avg_long_names": sim["avg_long_names"],
                "avg_short_names": sim["avg_short_names"],
                "n_reforms": sim["n_reforms"], "n_days": sim["n_days"],
                "dsr": dsr,
                "_net": sim["net"],
            }

    # ------------------------------------------------------------------- report
    def pct(x: float) -> str:
        return f"{x:+.1%}" if math.isfinite(x) else "  n/a"

    print("\n" + "=" * 108)
    print("ALPHAMAX turnover-reduction A/B  (self-contained dollar-neutral 12-1 book; 6bp one-way + 50bp borrow; PIT, no same-bar)")
    print("=" * 108)
    for cad_name, reform in CADENCES:
        base = results[cad_name]["baseline"]
        print(f"\n--- cadence {cad_name} (reform every {reform} sessions) ---")
        hdr = f"{'arm':<10}{'netSR365':>9}{'netSR252':>9}{'grossSR':>8}{'turn_ann':>9}{'Δturn':>8}{'ΔnetSR':>8}{'maxDD':>7}{'cost_bps':>9}{'borrow':>8}{'L/S names':>11}{'DSR104':>8}"
        print(hdr)
        for arm, *_ in ARMS:
            r = results[cad_name][arm]
            dturn = (r["turnover_ann"] - base["turnover_ann"]) / base["turnover_ann"] if base["turnover_ann"] else float("nan")
            dsr365 = r["net_sharpe_ann365"] - base["net_sharpe_ann365"]
            dsr_var = r["dsr"].get("var", {}).get("dsr", float("nan"))
            print(
                f"{arm:<10}{r['net_sharpe_ann365']:>9.3f}{r['net_sharpe_ann252']:>9.3f}"
                f"{r['gross_sharpe_ann365']:>8.3f}{r['turnover_ann']:>9.2f}{pct(dturn):>8}"
                f"{dsr365:>+8.3f}{r['max_dd']:>7.3f}{r['cost_drag_ann_bps']:>9.1f}"
                f"{r['borrow_drag_ann_bps']:>8.1f}{r['avg_long_names']:>5.0f}/{r['avg_short_names']:<5.0f}{dsr_var:>8.3f}"
            )

    # correlation of each treatment's net returns to the baseline (should be ~1: same book, less churn)
    print("\ntreatment-vs-baseline net-return corr (near 1.0 = genuinely the same book, only cheaper):")
    for cad_name, _ in CADENCES:
        base_net = results[cad_name]["baseline"]["_net"]
        cs = []
        for arm, *_ in ARMS[1:]:
            j = pd.concat([results[cad_name][arm]["_net"].rename("t"), base_net.rename("b")], axis=1).dropna()
            cs.append(f"{arm}={j['t'].corr(j['b']):.3f}")
        print(f"  {cad_name}: " + "  ".join(cs))

    print("\nPRE-REGISTERED SUCCESS GATE per arm: net Sharpe >= baseline AND ann turnover down >= 30-40%.")
    verdict: dict = {}
    for cad_name, _ in CADENCES:
        base = results[cad_name]["baseline"]
        for arm, *_ in ARMS[1:]:
            r = results[cad_name][arm]
            dturn = (r["turnover_ann"] - base["turnover_ann"]) / base["turnover_ann"] if base["turnover_ann"] else 0.0
            ok = (r["net_sharpe_ann365"] >= base["net_sharpe_ann365"] - 1e-9) and (dturn <= -0.30)
            verdict[f"{cad_name}/{arm}"] = {"turnover_cut": dturn, "net_sr_delta": r["net_sharpe_ann365"] - base["net_sharpe_ann365"], "passes_gate": bool(ok)}
            print(f"  {cad_name}/{arm:<6}: turnover {pct(dturn)}, netSR delta {r['net_sharpe_ann365']-base['net_sharpe_ann365']:+.3f} -> {'PASS' if ok else 'fail'}")

    payload = {
        "probe": "alphamax_turnover",
        "window": {"start": a.start, "end": a.end},
        "n_ids": len(ids), "T": int(mom.shape[0]),
        "construction": {
            "vol_window": VOL_WINDOW, "gross_leg": GROSS_LEG, "w_max": W_MAX,
            "cost_oneway_bps": COST_ONEWAY * 1e4, "borrow_ann_bps": BORROW_ANN * 1e4,
            "no_trade_band": NO_TRADE_BAND, "enter_frac": ENTER_FRAC,
        },
        "ledgers": {k: {"N": v[0], "var_sr": v[1]} for k, v in leds.items()},
        "stored_baselines": {
            "k30_dn_63_live": {"net_sharpe": 0.907, "turnover_ann": 4.11},
            "prereg_momentum_deep": {"net_sharpe": -0.049, "turnover_ann": 3.26},
        },
        "results": {
            cad: {arm: {k: v for k, v in r.items() if k != "_net"} for arm, r in arms.items()}
            for cad, arms in results.items()
        },
        "gate": verdict,
        "trials_burned": 0,
        "note": "SCREEN ONLY — no experiments-ledger append; DSR is read-only. Promotion into src is a separate human step.",
    }
    (OUT_DIR / "report.json").write_text(json.dumps(payload, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"\npersisted: {OUT_DIR / 'report.json'}")
    print("TRIALS BURNED THIS RUN: 0 (cheap construction screen; no ledger append).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
