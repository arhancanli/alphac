#!/usr/bin/env python3
"""ALPHAMAX construction bundle probe — IC-screen first, gauntlet AT MOST one.

Three alternative constructions of the live 12-1 momentum sleeve, screened cheaply
against the plain `eq_mom_252_21` baseline on the SAME window / universe / machinery
as the burned zoo screen (data/research/zoo_eq98: 2010-01-01 -> 2026-06-01, h=63,
non-overlapping quarterly grid, Newey-West lags=6):

  1. eq_mom_273_147   intermediate momentum (Novy-Marx 2012 "echo", months t-12..t-7):
                      ln(C*_{t-147}/C*_{t-273}) — the six monthly returns ending seven
                      months back (21 sessions/month). Same registered body as the
                      canonical factor, zoo-style params variant.
  2. eq_mom_sn_252_21 sector-neutral 12-1: the canonical xs_momentum(252, 21) panel
                      demeaned per session WITHIN Sharadar sector (metadata from
                      data/sharadar_raw/TICKERS.zip; static current-snapshot mapping —
                      a mild PIT caveat, standard practice, noted in the report).
                      Demeaning happens in the factor body over the compute batch,
                      so the screen definition and any later WF definition are ONE.
  3. eq_52whigh_252   George-Hwang 52-week-high proximity (already zoo-registered;
                      re-screened here so all rows share one report + as a
                      reproduction check against the stored zoo_eq98 numbers).

PIT discipline is inherited wholesale: split-only `_adjusted_close_panel`, PIT
universe mask BEFORE any cross-sectional statistic, execution-aware forward returns
(signal at close, entry next session open, exit h sessions later), inference on the
non-overlapping h-grid.

Protocol (matches the repo's existing funnel discipline):
  - The IC screen persists artifacts/probe/alphamax_constructions/ic_screen.json and
    does NOT write the experiments ledger (zoo_screen.py precedent: screens are the
    cheap stage; their count feeds the downstream DSR deflation narrative).
  - `gauntlet` runs the ONE pre-registered best screener through the SAME
    WalkForwardRunner as everything else, cloning the prereg_momentum config
    byte-for-byte (start/end/train/test/embargo/rebalance/band/cash/universe ids)
    so the deep-history baseline (net Sharpe -0.049, DSR 0.00) is apples-to-apples
    with ZERO extra baseline trials. The run auto-appends to
    var_sharadar/experiments.jsonl via compute_validation — the ledger N climbs by
    exactly one and the printed DSR is deflated against it. A sensitivity block
    re-deflates at larger N (this probe's new screened variants + the whole
    223-factor zoo funnel).

Decision rule, PRE-REGISTERED before the screen ran: gauntlet the top construction
by |NW t| ONLY IF it (a) clears |t| >= 2.0 and (b) beats the plain 12-1 baseline's
t on the same screen. Otherwise: no trial is burned and the honest verdict is
"no improvement".

Usage:
    uv run python scripts/probe_alphamax_constructions.py screen
    uv run python scripts/probe_alphamax_constructions.py gauntlet --alpha <winner>
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import math
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

TICKERS_ZIP = _REPO / "data" / "sharadar_raw" / "TICKERS.zip"
PREREG_WF = _REPO / "artifacts" / "walkforward" / "prereg_momentum" / "walkforward.json"
PREREG_EQUITY = _REPO / "artifacts" / "walkforward" / "prereg_momentum" / "equity.parquet"
ZOO_EQ98 = _REPO / "data" / "research" / "zoo_eq98" / "ic_report.json"
OUT_DIR = _REPO / "artifacts" / "probe" / "alphamax_constructions"

BASELINE = "eq_mom_252_21"
CONSTRUCTIONS = ("eq_mom_273_147", "eq_mom_sn_252_21", "eq_52whigh_252")
HORIZON = 63  # the pre-registered quarterly horizon (signals.horizon_bars)

# instrument_id -> sector, filled by _load_sector_map() before any compute.
_SECTOR_BY_ID: dict[str, str] = {}


# --------------------------------------------------------------------- sector metadata
def _load_sector_map() -> dict[str, str]:
    """XUSE:CASH:<TICKER>USD -> Sharadar sector (current snapshot; 'UNKNOWN' if absent).

    Prefers rows of the SEP table (the price universe sharadar_load.py ingested).
    Tickers canonicalized exactly like scripts/sharadar_load.py (BRK.B -> BRKB).
    """
    if not TICKERS_ZIP.exists():
        raise FileNotFoundError(f"sector metadata source missing: {TICKERS_ZIP}")
    z = zipfile.ZipFile(TICKERS_ZIP)
    inner = next(n for n in z.namelist() if n.endswith(".csv"))
    with z.open(inner) as fh:
        df = pd.read_csv(fh, usecols=["ticker", "table", "sector"])
    df = df.dropna(subset=["ticker"])
    # SEP rows first (the loaded price universe), then anything else as fallback.
    df["_pref"] = (df["table"] == "SEP").astype(int)
    df = df.sort_values("_pref").dropna(subset=["sector"])
    canon = (
        df["ticker"].astype(str).str.upper()
        .str.replace(".", "", regex=False)
        .str.replace("-", "", regex=False)
    )
    # keep=last => SEP rows (sorted last) win over non-SEP rows for the same ticker
    sector_by_ticker = dict(zip(canon, df["sector"].astype(str), strict=True))
    return {f"XUSE:CASH:{t}USD": s for t, s in sector_by_ticker.items()}


def _sector_of(instrument_id: str) -> str:
    return _SECTOR_BY_ID.get(instrument_id, "UNKNOWN")


# --------------------------------------------------------------------- probe factors
def _eq_mom_sn_fn(ctx, spec):
    """Sector-neutral 12-1 momentum: xs_momentum(252, 21) demeaned per session within sector.

    The demeaning group is the compute batch's columns (finite values only, so
    delisted/not-yet-listed names drop out naturally). Names without sector metadata
    form their own 'UNKNOWN' bucket — the cross-section is IDENTICAL to the plain
    factor's, only the ranking baseline changes (Ehsani-Harvey-Li L/S recipe).
    """
    from alphaforge.features.context import long_series
    from alphaforge.features.library.equity_price import _adjusted_close_panel
    from alphaforge.features.library.momentum import xs_momentum

    px = _adjusted_close_panel(ctx)
    mom = xs_momentum(px, lookback=int(spec.params["lookback"]), skip=int(spec.params["skip"]))
    sectors = np.asarray([_sector_of(str(c)) for c in mom.columns])
    out = mom.copy()
    for sec in np.unique(sectors):
        cols = mom.columns[sectors == sec]
        sub = mom[cols]
        out[cols] = sub.sub(sub.mean(axis=1, skipna=True), axis=0)
    return long_series(out, name=spec.name)


def _register_probe_specs(reg) -> list[str]:
    """Register the two NEW constructions into ``reg`` (idempotent). Returns names added."""
    from alphaforge.features.library import equity_price as _eqp
    from alphaforge.features.spec import Family, FeatureSpec
    from alphaforge.research.zoo import _variant

    have = {s.name for s in reg.all_specs()}
    added: list[str] = []
    mom = _eqp.eq_mom_252_21()

    # Novy-Marx intermediate 12-7: the canonical body, window t-273 .. t-147.
    imom = _variant(
        mom, "eq_mom_273_147", lookback_bars=273 + 1, params={"lookback": 273, "skip": 147}
    )
    # Sector-neutral 12-1: same window as the canonical factor, new body.
    snmom = FeatureSpec(
        name="eq_mom_sn_252_21",
        family=Family.MOMENTUM,
        direction=1,
        cross_sectional=True,
        lookback_bars=252 + 1,
        params={"lookback": 252, "skip": 21},
        fn=_eq_mom_sn_fn,
    )
    for spec in (imom, snmom):
        if spec.name not in have:
            reg.register(lambda spec=spec: spec)
            added.append(spec.name)
    return added


# --------------------------------------------------------------------------- screen
def _screen(a: argparse.Namespace) -> int:
    import alphaforge.features.library  # noqa: F401  canonical factors
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import parse_utc
    from alphaforge.data.schemas import ohlcv_dataset
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.cross_section import CSPipeline
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.labeling import forward_returns
    from alphaforge.research import zoo
    from alphaforge.research.ic_report import NW_LAGS, _membership_mask
    from alphaforge.validation import ic_summary, non_overlapping, rank_ic

    _SECTOR_BY_ID.update(_load_sector_map())

    reg = default_registry()
    zoo.register_all(reg)
    added = _register_probe_specs(reg)
    by_name = {s.name: s for s in reg.all_specs()}
    names = [BASELINE, *CONSTRUCTIONS]
    specs = [by_name[n] for n in names]

    settings = load_settings(a.profile)
    sleeve = sleeve_for(settings.data.asset_class)
    tf, calendar = sleeve.anchor_tf, sleeve.calendar
    start = parse_utc(f"{a.start}T00:00:00Z")
    end = parse_utc(f"{a.end}T00:00:00Z")

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        engine = FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class)
        # The exact ICReportRunner candidate set: ever-members with bars in the lake.
        members = set(universe.read_intervals().column("instrument_id").to_pylist())
        in_lake = set(paths.instrument_ids(ohlcv_dataset(tf)))
        ids = sorted(members & in_lake)
        n_sector = sum(1 for i in ids if i in _SECTOR_BY_ID)
        print(
            f"screen: {len(ids)} instruments | window [{a.start}, {a.end}) | h={HORIZON} | "
            f"NW lags={NW_LAGS} | probe-registered: {added or '(already present)'}"
        )
        print(
            f"sector coverage: {n_sector}/{len(ids)} candidate ids have Sharadar sector "
            f"metadata ({n_sector / max(1, len(ids)):.1%}); rest bucket as UNKNOWN"
        )

        raw = engine.compute_history(specs, ids, start=start, end=end)
        mask = _membership_mask(universe, raw)
        processed = CSPipeline().apply(raw[names], mask)
        del raw

        # forward returns: ic_report._bars_frame replicated (labels may see the future
        # by construction; they are evaluation-only).
        delta = tf.ms
        read_end = end + (HORIZON + 1) * delta
        import pyarrow as pa

        tbl = reader.ohlcv(ids, start=start, end=read_end, as_of=read_end, tf=tf)
        ts = tbl.column("ts_open").cast(pa.int64()).combine_chunks().to_numpy(zero_copy_only=False)
        bars = pd.DataFrame(
            {
                "instrument_id": tbl.column("instrument_id").to_pylist(),
                "ts_open": np.asarray(ts, dtype=np.int64),
                "open": tbl.column("open").combine_chunks().to_numpy(zero_copy_only=False),
            }
        )
        del tbl
        fwd = forward_returns(bars, HORIZON, timeframe=tf, calendar=calendar)
        del bars

        rows: dict[str, dict] = {}
        for n in names:
            direction = float(by_name[n].direction)
            ic = rank_ic(processed[n] * direction, fwd, mask)
            s = ic_summary(non_overlapping(ic, HORIZON), lags=NW_LAGS)
            rows[n] = {
                "factor": n,
                "n_obs": s.n,
                "mean_ic": None if not math.isfinite(s.mean) else s.mean,
                "t_nw": None if not math.isfinite(s.t_nw) else s.t_nw,
                "hit_rate": None if not math.isfinite(s.hit_rate) else s.hit_rate,
                "ic_ir": None if not math.isfinite(s.ic_ir) else s.ic_ir,
                "by_year": {
                    str(y): (None if not math.isfinite(v) else round(v, 4))
                    for y, v in sorted(s.by_year.items())
                },
            }
            del ic

    # ---- report ---------------------------------------------------------------
    print(f"\n=== ALPHAMAX construction screen @ h={HORIZON} (Rank-IC, non-overlapping, NW t) ===")
    print(f"{'factor':<20}{'role':<14}{'n':>4}{'mean_IC':>9}{'NW t':>7}{'hit':>6}{'IC_IR':>8}")
    for n in names:
        r = rows[n]
        role = "BASELINE" if n == BASELINE else "candidate"
        print(
            f"{n:<20}{role:<14}{r['n_obs']:>4}"
            f"{(r['mean_ic'] if r['mean_ic'] is not None else float('nan')):>9.4f}"
            f"{(r['t_nw'] if r['t_nw'] is not None else float('nan')):>7.2f}"
            f"{(r['hit_rate'] if r['hit_rate'] is not None else float('nan')):>6.2f}"
            f"{(r['ic_ir'] if r['ic_ir'] is not None else float('nan')):>8.3f}"
        )

    # reproduction check against the stored zoo screen (same window => must match)
    repro: dict[str, dict] = {}
    if ZOO_EQ98.exists() and a.start == "2010-01-01" and a.end == "2026-06-01":
        stored = {
            r["factor"]: r
            for r in json.loads(ZOO_EQ98.read_text())["rows"]
            if int(r["horizon"]) == HORIZON
        }
        print("\nreproduction check vs data/research/zoo_eq98 (same window/machinery):")
        for n in (BASELINE, "eq_52whigh_252"):
            if n not in stored:
                continue
            got_t, want_t = rows[n]["t_nw"], stored[n]["t_nw"]
            got_m, want_m = rows[n]["mean_ic"], stored[n]["mean_ic"]
            ok = (
                got_t is not None
                and want_t is not None
                and abs(got_t - want_t) < 0.02
                and abs(got_m - want_m) < 0.002
            )
            repro[n] = {"got_t": got_t, "stored_t": want_t, "ok": bool(ok)}
            print(
                f"  {n:<18} t_nw {got_t:+.3f} vs stored {want_t:+.3f} | "
                f"mean_ic {got_m:+.4f} vs {want_m:+.4f} -> {'PASS' if ok else 'MISMATCH'}"
            )

    # pre-registered decision rule (see module docstring)
    cand = [(n, rows[n]["t_nw"]) for n in CONSTRUCTIONS if rows[n]["t_nw"] is not None]
    base_t = rows[BASELINE]["t_nw"] or float("nan")
    best, best_t = max(cand, key=lambda kv: abs(kv[1])) if cand else (None, float("nan"))
    worthy = best is not None and abs(best_t) >= 2.0 and abs(best_t) > abs(base_t)
    print(
        f"\nDECISION (pre-registered): best construction = {best} (|t|={abs(best_t):.2f}) vs "
        f"baseline |t|={abs(base_t):.2f}; gate = |t|>=2.0 AND beats baseline -> "
        f"{'GAUNTLET IT' if worthy else 'NO GAUNTLET — no construction earns a trial'}"
    )
    if worthy:
        print(f"  next: uv run python scripts/probe_alphamax_constructions.py gauntlet --alpha {best}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "window": {"start": a.start, "end": a.end},
        "horizon": HORIZON,
        "nw_lags": NW_LAGS,
        "n_instruments": len(ids),
        "sector_coverage": {"with_sector": n_sector, "candidates": len(ids)},
        "methodology": (
            "ICReportRunner pipeline replicated: compute_history -> PIT membership mask -> "
            "CSPipeline(winsorize_mad, cs_zscore) -> direction-adjust -> execution-aware "
            "forward returns (XNYS session hops) -> per-session Spearman rank-IC over members "
            "-> non-overlapping h-grid -> NW t. Sector-neutral variant demeans the RAW momentum "
            "panel within (session, sector) inside the factor body BEFORE the CS pipeline; "
            "sector metadata is a current TICKERS snapshot (static, mild PIT caveat)."
        ),
        "rows": [rows[n] for n in names],
        "reproduction_check": repro,
        "decision": {
            "rule": "gauntlet best construction iff |t_nw| >= 2.0 and |t_nw| > baseline |t_nw|",
            "baseline_t": base_t,
            "best": best,
            "best_t": best_t,
            "gauntlet_worthy": bool(worthy),
        },
        "ledger_note": (
            "IC screens do not append to experiments.jsonl (zoo_screen protocol); NEW screened "
            "configs this probe adds to the funnel: eq_mom_273_147, eq_mom_sn_252_21 (2). "
            "eq_52whigh_252 and the baseline were already counted in the 223-factor zoo screen."
        ),
    }
    (OUT_DIR / "ic_screen.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\npersisted: {OUT_DIR / 'ic_screen.json'}")
    return 0


# -------------------------------------------------------------------------- gauntlet
def _gauntlet(a: argparse.Namespace) -> int:
    import alphaforge.features.library  # noqa: F401  canonical factors
    from alphaforge.analytics.metrics import daily_returns
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.config.settings import load_settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import now_ms
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.research import zoo
    from alphaforge.signals.service import SignalService
    from alphaforge.validation.dsr import dsr_from_returns
    from alphaforge.validation.probe_ledger import selection_context

    _SECTOR_BY_ID.update(_load_sector_map())
    zoo.register_all()
    _register_probe_specs(default_registry())

    # Clone the prereg_momentum trial byte-for-byte except alpha_names: same window,
    # same harness, same costs, same pre-registered 1,108-name universe -> the stored
    # baseline (net Sharpe -0.049, DSR 0.00) is apples-to-apples with NO extra trial.
    prereg = json.loads(PREREG_WF.read_text())
    cfg = prereg["config"]
    ids = [str(i) for i in cfg["instrument_ids"]]
    # BUGFIX (attempt 2, disclosed 2026-07-11): the stored prereg config carries 60 vestigial
    # crypto-perp ids alongside the 1,048 Sharadar equities. The sharadar ops store has no SCD2
    # records for them, so the engine (correctly) refused the clone on first launch. Those
    # crypto ids had no Sharadar bars in the original baseline run either — filtering to the
    # equity namespace leaves the tradable universe byte-identical to the baseline's.
    ids = [i for i in ids if i.startswith("XUSE:")]
    start, end = int(cfg["start"]), int(cfg["end"])
    train, test = int(cfg["train_bars"]), int(cfg["test_bars"])
    reb, embargo = int(cfg["rebalance_bars"]), int(cfg["embargo_bars"])
    band, cash = float(cfg["no_trade_band"]), float(cfg["initial_cash"])
    print(
        f"gauntlet: {a.alpha} | prereg clone: start={start} end={end} train={train} "
        f"test={test} reb={reb} embargo={embargo} band={band} cash={cash:.0f} ids={len(ids)}"
    )

    settings = load_settings(a.profile)
    now = now_ms()
    out = OUT_DIR / f"gauntlet_{a.alpha}"
    out.mkdir(parents=True, exist_ok=True)

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            default_registry(),
            settings.signals,
            alpha_names=[a.alpha],
        )
        runner = WalkForwardRunner(
            reader, store, universe, TransactionCostModel.from_settings(settings), service, settings
        )
        result = runner.run(
            start,
            end,
            train_bars=train,
            test_bars=test,
            allocator="rank",
            embargo_bars=embargo,
            initial_cash=cash,
            rebalance_bars=reb,
            no_trade_band=band,
            out_dir=out,
            now_ms=now,
            alpha_names=[a.alpha],
            instrument_ids=ids,
        )

    s, v = result.summary, result.validation
    print(f"\n=== {a.alpha} — deep-history gauntlet (prereg_momentum clone) ===")
    print(
        f"net_sharpe={float(s.sharpe):+.3f}  vol={float(s.vol_ann):.3f}  "
        f"maxDD={float(s.max_dd):.3f}  CAGR={float(s.cagr):+.4f}  "
        f"turnover={float(s.turnover_ann):.2f}x  funding_net={float(s.funding_net):+.0f}"
    )
    if v is not None:
        print(
            f"DSR={float(v.dsr):.3f} (ledger N={v.n_trials}, used={v.n_trials_used})  "
            f"PSR={float(v.psr):.3f}  clears_gate={v.clears_dsr_gate}"
        )

    # baseline comparison (stored artifact — same config, only the alpha differs)
    ps, pv = prereg["summary"], prereg["validation"]
    print("\nbaseline eq_mom_252_21 (stored prereg_momentum, identical harness):")
    print(
        f"net_sharpe={ps['sharpe']:+.3f}  vol={ps['vol_ann']:.3f}  maxDD={ps['max_dd']:.3f}  "
        f"CAGR={ps['cagr']:+.4f}  turnover={ps['turnover_ann']:.2f}x  DSR={pv['dsr']:.3f}"
    )

    # honest-deflation sensitivity + decorrelation to the baseline curve
    rets = daily_returns(result.equity)
    n_ledger, var_sr = selection_context(root=_REPO)
    print(
        f"\nselection union: N={n_ledger} (this trial recorded) V[SR]={var_sr:.5f}"
    )
    rep = dsr_from_returns(rets, max(2, n_ledger), var_sr)
    print(f"current-union DSR={float(rep.dsr):.3f} PSR={float(rep.psr):.3f}")

    if PREREG_EQUITY.exists():
        raw_eq = pd.read_parquet(PREREG_EQUITY)  # columns: ts (epoch ms), equity
        base_eq = pd.Series(
            raw_eq["equity"].to_numpy(dtype="float64"),
            index=pd.Index(raw_eq["ts"].to_numpy(dtype="int64"), name="ts"),
            name="equity",
        )
        base_rets = daily_returns(base_eq)
        joined = pd.concat([rets.rename("var"), base_rets.rename("base")], axis=1).dropna()
        if len(joined) > 30:
            corr = float(joined["var"].corr(joined["base"]))
            print(f"\nOOS daily-return corr to plain 12-1 baseline: {corr:+.3f} (family rule: < ~0.3 = genuinely different)")

    print(f"\nartifacts: {out}")
    print("TRIALS BURNED THIS CALL: 1 full walk-forward (auto-recorded on the sharadar ledger).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe_alphamax_constructions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("screen", help="Rank-IC screen of the 3 constructions vs plain 12-1")
    sc.add_argument("--profile", default="sharadar")
    sc.add_argument("--start", default="2010-01-01")  # zoo_eq98 window — apples-to-apples
    sc.add_argument("--end", default="2026-06-01")
    ga = sub.add_parser("gauntlet", help="deflated WF gauntlet of ONE construction (prereg clone)")
    ga.add_argument("--profile", default="sharadar")
    ga.add_argument("--alpha", required=True, choices=list(CONSTRUCTIONS))
    a = ap.parse_args(argv)
    return _screen(a) if a.cmd == "screen" else _gauntlet(a)


if __name__ == "__main__":
    raise SystemExit(main())
