#!/usr/bin/env python3
"""PROBE — ALPHAMAX CONSTRUCTION DRIFT: which construction should the live sleeve run?

MEASURE-ONLY. New file. Reads src/** as a library; NEVER mutates src/**, configs/**,
scripts/alphamax_tick.sh, or launchd. Writes ONLY artifacts/sweep/alphamax_construction/**.
The golden master is untouched.

TRIALS BURNED = 0 (pre-registered). Every WalkForwardRunner.run() call below passes
``now_ms=None``, which the runner documents as "the anti-overfit step is skipped entirely
(validation stays None, nothing is recorded)". No row is appended to var/experiments.jsonl.
DSR is then computed READ-ONLY here via the blessed alphaforge.validation.dsr.dsr_from_returns
against the ledger N as it stands (N=111 at time of writing) and the ledger's own
trial-Sharpe variance — i.e. the same deflation the runner would have applied, without
inflating N. This is legitimate because the question is "which of two ALREADY-EXISTING
constructions is right", not "is there a new edge": no new hypothesis is being searched.

======================================================================================
THE SITUATION (verified from the two stored artifacts, not re-derived)
======================================================================================
The live tick runs:
    af research walkforward --profile equity --train-days 365 --test-days 91
        --alphas eq_mom_252_21 --out artifacts/walkforward/equity_live_fwd
and takes rebalance_bars from the CLI DEFAULT (24), K from the profile (rank_top_k=100),
and the universe from the profile (universe.size=2000 -> 2,537 ids overlapping the window).
The PUBLIC evidence base cites the frozen artifacts/walkforward/k30_dn_63.

FULL STORED DIFF (read from both walkforward.json ``config``/``summary``/``validation``):

    parameter          k30_dn_63 (evidenced)       equity_live_fwd (live)
    -----------------  --------------------------  ----------------------------
    rebalance_bars     63 (quarterly)              24 (~monthly)
    rank_top_k (K)     30 / side (verified from    100 / side (profile default;
                       leg_00 positions: 29L/30S)  observed 86-99 per side)
    universe           375 frozen ids (Polygon-    2,537 ids (top-2000 profile
                       era top-500 rule)           universe)
    train_bars         252                         365
    test_bars          63                          91
    purge_bars         21 (horizon_bars was 21     63 (horizon_bars=63 today)
                       when it was generated)
    embargo_bars       274                         274          (SAME)
    no_trade_band      0.0010                      0.0010       (SAME)
    allocator          rank                        rank         (SAME)
    alpha              eq_mom_252_21               eq_mom_252_21(SAME)
    initial_cash       100_000                     100_000      (SAME)
    window             2022-07-01 .. 2026-06-01    2024-05-19 .. 2026-07-20
    OOS span           2023-07-05 .. 2026-05-30    2025-11-03 .. 2026-07-18
    n_legs             12                          2
    n_obs (daily)      728                         173
    net Sharpe         0.907                       0.055
    turnover_ann       4.11x                       7.49x
    DSR (ledger N)     0.341 (N=27)                0.151 (N=111)

So SEVEN parameters differ, not two. And the headline gap 0.907 vs 0.055 is confounded
by the single largest difference of all: the live artifact has 173 OOS observations
(0.69 yr) against 728 (2.9 yr). SE(Sharpe) ~ 1/sqrt(years) => ~1.20 vs ~0.59. The stored
comparison CANNOT distinguish construction from noise. That is the first finding, and it
is why this probe re-runs everything on one common window and one common leg grid.

======================================================================================
PRE-REGISTERED COMPARISON (locked BEFORE any number was computed)
======================================================================================
COMMON BASIS for every arm (nothing else may vary):
    window        2022-07-01 .. 2026-06-01   (k30_dn_63's window: the longest BOTH
                                              constructions can honestly support --
                                              the narrow arm's frozen 375-id universe
                                              is only defined over it)
    train_bars    252   test_bars 63   embargo_bars 274   (k30's leg grid -> 12 legs,
                                                           the most OOS obs available)
    allocator     rank        alpha eq_mom_252_21     no_trade_band 0.0010
    cash          100_000     dollar_neutral True (equity.yaml)
    costs         COMMITTED equity model, unchanged: 1bp commission + 3bp half-spread
                  + 2bp latency = 6bp ONE-WAY, + 50bp/yr GC borrow accrued daily on the
                  short leg, + sqrt-impact on D1 ADV (impact_coef 1.0). PIT throughout;
                  NextOpenFill (no same-bar fills).
    horizon_bars  63 (today's profile) for every arm except R0 (see below)

ARMS (full 2x2x2 factorial over the three suspected drivers + 2 controls):
    R0  REPLICA     reb=63  K=30   narrow(375)  h=21   -- VALIDITY ANCHOR. Reproduces
                    k30_dn_63 as it was actually generated (horizon 21). If R0 does not
                    land near the stored 0.907, the whole comparison is unreliable and
                    that is reported as the finding.
    A1  BLESSED     reb=63  K=30   narrow(375)  h=63
    A2  LIVE        reb=24  K=100  wide(2537)   h=63
    I1  cadence     reb=24  K=30   narrow(375)  h=63   -- live CADENCE, blessed rest
    I2  cadence     reb=63  K=100  wide(2537)   h=63   -- blessed CADENCE, live rest
    I3  universe    reb=63  K=30   wide(2537)   h=63   -- blessed cadence+K, wide universe
    I4  breadth     reb=63  K=100  narrow(375)  h=63   -- blessed cadence+universe, live K
    G1  grid        reb=63  K=30   narrow(375)  h=63, train=365/test=91 -- isolates the
                    leg-grid difference at otherwise-blessed settings.

ATTRIBUTION RULE (pre-registered): the driver of the A1->A2 gap is the single parameter
whose one-at-a-time flip (A1->I1 cadence, A1->I3 universe, A1->I4 breadth) moves net
Sharpe the most in the direction of A2. My stated prior is CADENCE via turnover cost
(7.49x vs 4.11x at 6bp one-way ~ 20bp/yr extra drag). The prior may be WRONG; the
factorial is what decides.

COST SENSITIVITY (step 4, computed in closed form -- ZERO extra runs): with net
arithmetic return r_net, one-way cost c (bps) and one-way annual turnover T,
    r_net(c) = r_gross - c*T - borrow   =>   break-even c* = c_0 + r_net(c_0)/T
evaluated at c_0 = 6bp. c* is the one-way cost at which the arm's net return hits zero;
a LOW c* means the arm is fragile to execution slippage. Reported per arm alongside the
realized cost drag c_0*T.

SUCCESS CRITERIA (pre-registered): an honest "the live construction is fine" or "they are
statistically indistinguishable" is a FULL result. The recommendation must follow the
numbers, not the seniority of the blessed config. Because every arm here is a
RE-MEASUREMENT of two constructions that already exist (no new alpha, no new knob is
being searched), no arm is eligible to be promoted as a new edge on the strength of this
probe alone.

Usage:
    uv run python scripts/probe_alphamax_construction.py                 # all arms
    uv run python scripts/probe_alphamax_construction.py --arms R0,A1,A2
    uv run python scripts/probe_alphamax_construction.py --report        # re-print cache
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

OUT_DIR = _REPO / "artifacts" / "sweep" / "alphamax_construction"
CACHE = OUT_DIR / "arms.json"

K30_ART = _REPO / "artifacts" / "walkforward" / "k30_dn_63" / "walkforward.json"
LIVE_ART = _REPO / "artifacts" / "walkforward" / "equity_live_fwd" / "walkforward.json"

# Common basis (see docstring). Windows are UTC midnight.
WIN_START = "2022-07-01"
WIN_END = "2026-06-01"
TRAIN_BARS = 252
TEST_BARS = 63
EMBARGO_BARS = 274
NO_TRADE_BAND = 0.0010
CASH = 100_000.0
ALPHA = "eq_mom_252_21"
BASE_COST_ONEWAY_BPS = 6.0  # 1 commission + 3 half-spread + 2 latency (configs/equity.yaml)
BORROW_BPS_ANN = 50.0


@dataclass(frozen=True)
class Arm:
    name: str
    label: str
    rebalance_bars: int
    top_k: int
    universe: str  # "narrow" (k30's frozen 375 ids) | "wide" (profile top-2000)
    horizon_bars: int = 63
    train_bars: int = TRAIN_BARS
    test_bars: int = TEST_BARS


ARMS: tuple[Arm, ...] = (
    Arm("R0", "REPLICA  (k30 as generated, h=21)", 63, 30, "narrow", horizon_bars=21),
    Arm("A1", "BLESSED  reb63 K30  narrow", 63, 30, "narrow"),
    Arm("A2", "LIVE     reb24 K100 wide", 24, 100, "wide"),
    Arm("I1", "cadence  reb24 K30  narrow", 24, 30, "narrow"),
    Arm("I2", "cadence  reb63 K100 wide", 63, 100, "wide"),
    Arm("I3", "universe reb63 K30  wide", 63, 30, "wide"),
    Arm("I4", "breadth  reb63 K100 narrow", 63, 100, "narrow"),
    Arm("G1", "grid     reb63 K30  narrow 365/91", 63, 30, "narrow", train_bars=365, test_bars=91),
)


@dataclass
class ArmResult:
    name: str
    label: str
    params: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)


def _narrow_ids() -> list[str]:
    """k30_dn_63's frozen instrument list (its universe RULE no longer exists in the store).

    NOT survivorship-selected: the list is the union of PIT universe members over the
    2022-2026 window and contains delisted/acquired names (FRC, BBBY, ATVI, ABMD, HZNP,
    COUP, AVLR, ...). The wide arm's list is resolved the same way the live tick resolves
    it (PIT members overlapping the window), so both arms share the same style of
    universe snapshot -- a caveat, but a SYMMETRIC one.
    """
    cfg = json.loads(K30_ART.read_text())["config"]
    return sorted(dict.fromkeys(cfg["instrument_ids"]))


def _ledger_deflation() -> tuple[int, float]:
    """READ-ONLY identity-aligned union selection context."""
    from alphaforge.validation.probe_ledger import selection_context

    return selection_context(root=_REPO)


def _run_arm(arm: Arm, narrow_ids: list[str], n_trials: int, sr_var: float) -> ArmResult:
    import alphaforge.features.library  # noqa: F401  register canonical factors
    from alphaforge.analytics.metrics import daily_returns
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.config.settings import load_settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import parse_utc
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService
    from alphaforge.validation.dsr import dsr_from_returns

    settings = load_settings("equity")
    # In-memory overrides ONLY (configs/equity.yaml on disk is never touched):
    #   portfolio.rank_top_k -> the K knob the rank allocator reads
    #   signals.horizon_bars -> h, which also sets the walk-forward PURGE
    settings = settings.model_copy(
        update={
            "portfolio": settings.portfolio.model_copy(update={"rank_top_k": arm.top_k}),
            "signals": settings.signals.model_copy(update={"horizon_bars": arm.horizon_bars}),
        }
    )

    start, end = parse_utc(f"{WIN_START}T00:00:00Z"), parse_utc(f"{WIN_END}T00:00:00Z")
    ids = narrow_ids if arm.universe == "narrow" else None
    out = OUT_DIR / f"wf_{arm.name}"
    out.mkdir(parents=True, exist_ok=True)

    paths = LakePaths(settings.paths.lake_dir)
    t0 = time.time()
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            default_registry(),
            settings.signals,
            alpha_names=[ALPHA],
        )
        runner = WalkForwardRunner(
            reader,
            store,
            universe,
            TransactionCostModel.from_settings(settings),
            service,
            settings,
        )
        result = runner.run(
            start,
            end,
            train_bars=arm.train_bars,
            test_bars=arm.test_bars,
            allocator="rank",
            embargo_bars=EMBARGO_BARS,
            initial_cash=CASH,
            instrument_ids=ids,
            rebalance_bars=arm.rebalance_bars,
            no_trade_band=NO_TRADE_BAND,
            out_dir=out,
            now_ms=None,  # <-- ZERO trials burned: no ledger write, validation stays None
            alpha_names=[ALPHA],
        )
    elapsed = time.time() - t0

    s = result.summary
    rets = daily_returns(result.equity)
    rep = dsr_from_returns(rets, max(2, n_trials), sr_var)

    turn = float(s.turnover_ann)
    years = float(s.n_days) / 365.0 if s.n_days else float("nan")
    # Arithmetic-mean annual net return (the basis the break-even algebra is linear in),
    # NOT the compounded CAGR: cost enters returns additively.
    r_net_ann = float(rets.mean()) * 252.0
    cost_drag_bps = BASE_COST_ONEWAY_BPS * turn  # bps/yr from the explicit one-way cost
    breakeven_bps = BASE_COST_ONEWAY_BPS + (r_net_ann * 1e4 / turn) if turn > 0 else float("nan")

    return ArmResult(
        name=arm.name,
        label=arm.label,
        params={
            "rebalance_bars": arm.rebalance_bars,
            "rank_top_k": arm.top_k,
            "universe": arm.universe,
            "n_instruments": len(result.config["instrument_ids"]),
            "horizon_bars": arm.horizon_bars,
            "train_bars": arm.train_bars,
            "test_bars": arm.test_bars,
            "n_legs": int(result.config["n_legs"]),
            "window": [WIN_START, WIN_END],
        },
        metrics={
            "net_sharpe": float(s.sharpe),
            "dsr": float(rep.dsr),
            "psr": float(rep.psr),
            "n_trials_deflated_against": int(n_trials),
            "turnover_ann": turn,
            "cost_drag_bps_yr": cost_drag_bps,
            "borrow_bps_yr": BORROW_BPS_ANN * 0.5,  # ~half the gross is short (dollar-neutral)
            "breakeven_oneway_bps": breakeven_bps,
            "max_dd": float(s.max_dd),
            "vol_ann": float(s.vol_ann),
            "cagr": float(s.cagr),
            "net_ret_ann_arith": r_net_ann,
            "fees_paid": float(s.fees_paid),
            "n_obs": int(rep.n_obs),
            "oos_years": years,
            "se_sharpe": 1.0 / math.sqrt(years) if years and years > 0 else float("nan"),
            "runtime_s": elapsed,
        },
    )


def _fmt(results: list[ArmResult]) -> str:
    lines: list[str] = []
    hdr = (
        f"{'arm':<4} {'construction':<34} {'netSR':>7} {'DSR':>6} {'turn':>6} "
        f"{'drag':>7} {'bkeven':>7} {'maxDD':>7} {'vol':>6} {'nobs':>6} {'SE(SR)':>7}"
    )
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for r in results:
        m = r.metrics
        lines.append(
            f"{r.name:<4} {r.label:<34} {m['net_sharpe']:>7.3f} {m['dsr']:>6.3f} "
            f"{m['turnover_ann']:>6.2f} {m['cost_drag_bps_yr']:>6.1f}b "
            f"{m['breakeven_oneway_bps']:>6.1f}b {m['max_dd']:>7.3f} {m['vol_ann']:>6.3f} "
            f"{m['n_obs']:>6d} {m['se_sharpe']:>7.2f}"
        )
    by = {r.name: r.metrics["net_sharpe"] for r in results}
    if {"A1", "A2"} <= by.keys():
        lines.append("")
        lines.append(f"HEADLINE GAP  A1(blessed) - A2(live) = {by['A1'] - by['A2']:+.3f} net Sharpe")
        for name, what in (("I1", "cadence 63->24"), ("I3", "universe narrow->wide"), ("I4", "K 30->100")):
            if name in by:
                lines.append(f"  one-at-a-time from A1: {what:<24} -> {by[name]:+.3f} "
                             f"(delta {by[name] - by['A1']:+.3f})")
        if "G1" in by:
            lines.append(f"  one-at-a-time from A1: {'grid 252/63->365/91':<24} -> {by['G1']:+.3f} "
                         f"(delta {by['G1'] - by['A1']:+.3f})")
    lines.append("")
    lines.append(_window_decomposition())
    return "\n".join(lines)


def _window_decomposition() -> str:
    """Why the STORED 0.907-vs-0.055 gap is a WINDOW artifact, not a construction gap.

    Splits the live artifact's own stored OOS curve at 2026-06-01 (where the frozen
    k30_dn_63 window ends) and re-scores every probe arm on the overlapping slice.
    Pure arithmetic on curves that already exist -- no walk-forward, no trial.
    """
    import numpy as np
    import pandas as pd

    def load(p: Path) -> pd.Series:
        d = pd.read_parquet(p)
        return pd.Series(d["equity"].to_numpy(), index=pd.to_datetime(d["ts"], unit="ms", utc=True))

    def sr(r: pd.Series) -> float:
        return float(r.mean() / r.std() * math.sqrt(365.0)) if len(r) > 2 else float("nan")

    cut = pd.Timestamp("2026-06-01", tz="UTC")
    lo, hi = pd.Timestamp("2025-11-03", tz="UTC"), pd.Timestamp("2026-05-30", tz="UTC")
    out = ["WINDOW DECOMPOSITION (arithmetic on stored curves; 0 runs)"]
    r = load(LIVE_ART.parent / "equity.parquet").pct_change().dropna()
    pre, post = r[r.index < cut], r[r.index >= cut]
    out.append(
        f"  stored equity_live_fwd  FULL          n={len(r):4d} SR={sr(r):7.3f} "
        f"cum={(1 + r).prod() - 1:+.4f}"
    )
    out.append(
        f"                          .. 2026-05-31 n={len(pre):4d} SR={sr(pre):7.3f} "
        f"cum={(1 + pre).prod() - 1:+.4f}   <- overlaps k30_dn_63"
    )
    out.append(
        f"                          2026-06-01 .. n={len(post):4d} SR={sr(post):7.3f} "
        f"cum={(1 + post).prod() - 1:+.4f}   <- k30_dn_63 NEVER SAW THIS"
    )
    out.append("  probe arms re-scored on the overlapping slice 2025-11-03 .. 2026-05-30:")
    for name in ("A1", "A2", "I1", "I2", "I3", "I4"):
        p = OUT_DIR / f"wf_{name}" / "equity.parquet"
        if not p.exists():
            continue
        rr = load(p).pct_change().dropna()
        rr = rr[(rr.index >= lo) & (rr.index <= hi)]
        out.append(f"    {name}: n={len(rr):4d} SR={sr(rr):7.3f}")
    _ = np  # numpy imported for parity with the repo's metric stack
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe_alphamax_construction")
    ap.add_argument("--arms", default=",".join(a.name for a in ARMS))
    ap.add_argument("--report", action="store_true", help="re-print the cached results only")
    a = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cached: dict[str, dict] = {}
    if CACHE.exists():
        cached = json.loads(CACHE.read_text())

    if not a.report:
        wanted = [arm for arm in ARMS if arm.name in set(a.arms.split(","))]
        narrow_ids = _narrow_ids()
        n_trials, sr_var = _ledger_deflation()
        print(f"ledger: N={n_trials} V[SR]={sr_var:.6g}  (READ-ONLY; this probe burns 0 trials)")
        print(f"narrow universe: {len(narrow_ids)} frozen ids from k30_dn_63")
        for arm in wanted:
            print(f"--- running {arm.name}: {arm.label} ...", flush=True)
            res = _run_arm(arm, narrow_ids, n_trials, sr_var)
            cached[arm.name] = {"label": res.label, "params": res.params, "metrics": res.metrics}
            CACHE.write_text(json.dumps(cached, indent=1, sort_keys=True))
            m = res.metrics
            print(
                f"    netSR={m['net_sharpe']:.3f} DSR={m['dsr']:.3f} turn={m['turnover_ann']:.2f} "
                f"maxDD={m['max_dd']:.3f} nobs={m['n_obs']} ({m['runtime_s']:.0f}s)",
                flush=True,
            )

    order = [x.name for x in ARMS]
    results = [
        ArmResult(name=k, label=cached[k]["label"], params=cached[k]["params"], metrics=cached[k]["metrics"])
        for k in order
        if k in cached
    ]
    if results:
        text = _fmt(results)
        print()
        print(text)
        (OUT_DIR / "report.txt").write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
