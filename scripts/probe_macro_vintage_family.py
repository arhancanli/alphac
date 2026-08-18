#!/usr/bin/env python3
"""PROBE — THE PIT MACRO SURPRISE FAMILY (5 remaining series). Pre-registered 2026-08-05.

Executes docs/design/PREREG_MACRO_VINTAGE_FAMILY.md exactly as declared, BEFORE any of the
five was run. The declaration is commit fb1ab88; this file is its execution.

WHY THE SPEC IS *IMPORTED*, NOT RETYPED
---------------------------------------
The pre-registration says "Every parameter is inherited unchanged from
scripts/probe_cpi_surprise_size.py. Nothing is re-tuned per series; that is the entire point
of a family test." Retyping the spec would let it drift by accident and there would be no way
to prove it had not. So `surprise`, `px`, `sharpe` and `nw_t` are IMPORTED from the CPI probe.
If the CPI spec ever changes, this file changes with it or fails loudly — it cannot silently
diverge. The ONLY per-series input is the sign, and the signs were fixed in advance from
mechanism (below), not fitted.

THE DECLARED SIGNS — fixed before any result was seen
-----------------------------------------------------
  EMPLOY  +1   nonfarm payrolls        \\
  IPT     +1   industrial production    | GROWTH channel: a hotter-than-expected level of
  HSTARTS +1   housing starts           | ACTIVITY is GOOD for small caps (more cyclical,
  RCONM   +1   real consumption        /  more domestically exposed).
  RUC     -1   unemployment RATE — inverted by construction: a higher-than-expected
               unemployment rate is WORSE activity.

Note this is the OPPOSITE prediction to the validated CPI result (which took -1 on an
INFLATION channel). The pre-registration is explicit that this asymmetry is deliberate and
that "if a growth series comes back significantly negative, that is a FAILED PREDICTION, not
a discovery to be re-signed."

THE READING RULES, ALSO PRE-DECLARED
------------------------------------
  * Per series, the same four gates the CPI config passed.
  * BONFERRONI: 5 trials, so a nominal one-sided p of 0.05 requires p <= 0.01, i.e.
    NW t >= 2.33 for FAMILY-WISE significance. t >= 1.5 is *suggestive* and earns a
    pre-registered forward test, never funding.
  * REDUNDANCY: any survivor with |rho| > 0.30 to an existing sleeve or to another survivor
    is not a separate sleeve; within a correlated cluster only the highest-t member is kept.
  * All five are reported together. No result may be reported without the other four.

PRIOR, recorded in the declaration so it cannot be adjusted afterwards: "I expect MOST of
these five to be nulls... Zero is entirely plausible and publishable."

    uv run python scripts/probe_macro_vintage_family.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# The spec itself, imported so it provably cannot drift from the validated CPI config.
from probe_cpi_surprise_size import (  # noqa: E402
    ANN,
    COST_ONEWAY,
    nw_t,
    px,
    sharpe,
    surprise,
)

from alphaforge.analytics.curve_store import write_curve  # noqa: E402
from alphaforge.core.time import now_ms  # noqa: E402
from alphaforge.validation.probe_ledger import record_probe_trial  # noqa: E402

OUT = Path("artifacts/probe/macro_vintage_family")

# (series, declared sign, human name) — DECLARED 2026-08-05, before execution.
FAMILY = [
    ("EMPLOY", +1, "nonfarm payroll employment"),
    ("IPT", +1, "industrial production"),
    ("HSTARTS", +1, "housing starts"),
    ("RCONM", +1, "real personal consumption"),
    ("RUC", -1, "unemployment rate (inverted)"),
]

BONFERRONI_T = 2.33   # 5 trials, one-sided p <= 0.01
SUGGESTIVE_T = 1.5    # the CPI allocation bar
REDUNDANCY_RHO = 0.30


def strategy(si: pd.Series, sign: int, spread: pd.Series) -> tuple[pd.Series, pd.Series]:
    """The pre-registered rule: w = SIGN * clip(SI, -1, +1) on the dollar-neutral spread,
    entered at the close of the first trading day STRICTLY AFTER the vintage date and held
    to the next vintage date. Identical to the CPI probe's construction."""
    w = pd.Series(0.0, index=spread.index)
    vs = list(si.index)
    for i, V in enumerate(vs[:-1]):
        after = spread.index[spread.index > V]
        if len(after) == 0:
            continue
        e0 = after[0]
        seg = (spread.index > e0) & (spread.index <= vs[i + 1])
        w.loc[seg] = sign * float(np.clip(si[V], -1, 1))
    turn = (w - w.shift(1)).abs().fillna(0.0)
    gross = w * spread
    net = (gross - turn * COST_ONEWAY * 2).dropna()
    return w, net


def curve(p: str) -> pd.Series:
    e = pd.read_parquet(p)
    s = pd.Series(e["equity"].astype(float).values,
                  index=pd.to_datetime(e["ts"], unit="ms").dt.normalize().values)
    return np.log(s[~s.index.duplicated()].sort_index()).diff().dropna()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    IWM, SPY, QQQ = px("IWM"), px("SPY"), px("QQQ")
    idx = IWM.index.intersection(SPY.index)
    spread = (np.log(IWM.reindex(idx)).diff() - np.log(SPY.reindex(idx)).diff()).dropna()
    idx2 = QQQ.index.intersection(SPY.index)
    sp2 = (np.log(QQQ.reindex(idx2)).diff() - np.log(SPY.reindex(idx2)).diff()).dropna()

    print("=" * 82)
    print("PIT MACRO SURPRISE FAMILY — 5 pre-registered series, reported together")
    print("=" * 82)
    print(f"  Bonferroni family-wise bar: NW t >= {BONFERRONI_T} | suggestive: t >= {SUGGESTIVE_T}")
    print(f"  costs {COST_ONEWAY*1e4:.0f}bp one-way per leg, two legs, monthly-ish rebalance\n")

    results, streams = [], {}
    for series, sign, human in FAMILY:
        try:
            si = surprise(series).dropna()
        except Exception as e:
            print(f"  {series:8s} SKIPPED — {e}")
            results.append({"series": series, "error": str(e)})
            continue
        w, net = strategy(si, sign, spread)
        live = net[w.abs() > 0]
        if len(live) < 100:
            print(f"  {series:8s} SKIPPED — only {len(live)} live days")
            results.append({"series": series, "error": f"only {len(live)} live days"})
            continue
        streams[series] = live
        # PERSIST EACH SERIES' CURVE BEFORE ANY VERDICT IS FORMED. Fourteen probes in this repo
        # recorded a scalar verdict and discarded the return stream, which is why three validated
        # candidates cannot be measured against the book without re-running them. These five are
        # pre-registered and reported together; losing their curves would repeat the defect on the
        # exact candidates the book most needs to combine.
        curve_path = write_curve(live, OUT / series.lower())
        # AND REGISTER THE TRIAL. The pre-registration promised in writing that these five
        # "enter var/experiments.jsonl"; they did not, because screen-stage probes never touched
        # a ledger. Five spent hypotheses were invisible to the deflation that every sleeve in
        # the book is graded against. record_probe_trial is idempotent on the config hash, so
        # re-running this file to regenerate an artifact cannot inflate N.
        rec = record_probe_trial(
            "macro_vintage_family",
            {"series": series, "sign": sign, "spread": "IWM-SPY", "cost_oneway_bp": COST_ONEWAY * 1e4},
            live,
            now_ms=now_ms(),
            prereg="docs/design/PREREG_MACRO_VINTAGE_FAMILY.md (commit fb1ab88)",
        )
        print(f"  {series:8s} curve -> {curve_path}   ledger hash {rec.config_hash}")
        eq = (1 + live).cumprod()
        w2 = w.reindex(sp2.index).fillna(0.0)
        pl = (w2 * sp2).dropna()
        pl = pl[w2.abs() > 0]
        r = {
            "series": series, "human": human, "sign": sign,
            "vintages": len(si),
            "live_days": len(live),
            "start": str(live.index.min().date()), "end": str(live.index.max().date()),
            "net_sharpe": sharpe(live), "nw_t": nw_t(live),
            "gross_sharpe": sharpe((w * spread)[w.abs() > 0]),
            "ann_ret": float(live.mean() * ANN), "vol": float(live.std(ddof=0) * np.sqrt(ANN)),
            "max_dd": float((eq / eq.cummax() - 1).min()),
            "placebo_sharpe": sharpe(pl), "placebo_nw_t": nw_t(pl),
        }
        results.append(r)
        print(f"  {series:8s} ({human})")
        print(f"      net SR {r['net_sharpe']:+.3f}  NW t {r['nw_t']:+.2f}  "
              f"ann {r['ann_ret']:+.2%}  vol {r['vol']:.2%}  maxDD {r['max_dd']:+.1%}  "
              f"{r['live_days']}d")
        print(f"      placebo QQQ-SPY: SR {r['placebo_sharpe']:+.3f}  t {r['placebo_nw_t']:+.2f}"
              f"   {'(dead, as required)' if abs(r['placebo_nw_t']) < 1.5 else '(ALIVE — not size-specific!)'}")

    # ------------------------------------------------------------------ the gates
    print("\n" + "=" * 82)
    print("PRE-REGISTERED GATES")
    print("=" * 82)
    B = {"eq": curve("artifacts/walkforward/k30_dn_63/equity.parquet"),
         "mf": curve("artifacts/walkforward/mf_live_fwd/equity.parquet"),
         "inv": curve("artifacts/walkforward/prereg_investment/equity.parquet")}
    print(f"\n{'series':>9}{'NW t':>8}{'net SR':>9}{'placebo':>9}{'own>bar':>9}"
          f"{'suggestive':>12}{'family-wise':>13}")
    survivors = []
    for r in results:
        if "error" in r:
            print(f"{r['series']:>9}{'—':>8}{'ERROR':>9}")
            continue
        live = streams[r["series"]]
        j = pd.concat([*B.values(), live.rename("c")], axis=1, keys=[*B.keys(), "c"]).dropna()
        bar_ok, rho = False, float("nan")
        if len(j) > 100:
            bk = j[["eq", "mf", "inv"]].mean(axis=1)
            rho = float(np.corrcoef(bk, j["c"])[0, 1])
            bar_ok = sharpe(j["c"]) > rho * sharpe(bk)
        r["rho_to_book"] = rho
        r["clears_bar"] = bool(bar_ok)
        r["placebo_dead"] = bool(abs(r["placebo_nw_t"]) < SUGGESTIVE_T)
        r["suggestive"] = bool(abs(r["nw_t"]) >= SUGGESTIVE_T)
        r["family_wise"] = bool(abs(r["nw_t"]) >= BONFERRONI_T)
        # A GROWTH series that comes back significantly NEGATIVE is a FAILED PREDICTION.
        r["sign_as_predicted"] = bool(r["net_sharpe"] > 0)
        if r["suggestive"] and r["placebo_dead"] and r["clears_bar"] and r["sign_as_predicted"]:
            survivors.append(r["series"])
        print(f"{r['series']:>9}{r['nw_t']:>+8.2f}{r['net_sharpe']:>+9.3f}"
              f"{'dead' if r['placebo_dead'] else 'ALIVE':>9}"
              f"{'yes' if bar_ok else 'no':>9}"
              f"{'YES' if r['suggestive'] else 'no':>12}"
              f"{'YES' if r['family_wise'] else 'no':>13}")

    # ------------------------------------------------------- the redundancy gate
    print("\n" + "=" * 82)
    print("REDUNDANCY GATE — the pre-registration expected this to be the binding constraint")
    print("=" * 82)
    if len(streams) >= 2:
        M = pd.concat(streams.values(), axis=1, keys=streams.keys()).dropna()
        print(f"\npairwise correlation of the five STRATEGY return series ({len(M)} common days)")
        print(M.corr().round(3).to_string())
        cm = M.corr()
        iu = np.triu_indices(len(cm), 1)
        print(f"\n  mean |rho| between family members: {np.abs(cm.values[iu]).mean():.3f}")
        print(f"  max  |rho|: {np.abs(cm.values[iu]).max():.3f}  "
              f"(gate kills a survivor above {REDUNDANCY_RHO})")

    print(f"\n  SURVIVORS of the per-series gates: {survivors or 'NONE'}")
    if len(survivors) > 1:
        S = pd.concat([streams[s] for s in survivors], axis=1, keys=survivors).dropna()
        cs = S.corr()
        print("\n  survivor-vs-survivor correlation:")
        print(cs.round(3).to_string())
        killed = set()
        for i, a in enumerate(survivors):
            for b in survivors[i + 1:]:
                if abs(cs.loc[a, b]) > REDUNDANCY_RHO:
                    ta = abs(next(r for r in results if r["series"] == a)["nw_t"])
                    tb = abs(next(r for r in results if r["series"] == b)["nw_t"])
                    loser = b if ta >= tb else a
                    killed.add(loser)
                    print(f"    CLUSTER {a}~{b} rho {cs.loc[a,b]:+.3f} > {REDUNDANCY_RHO}"
                          f" -> keep higher-t, drop {loser}")
        survivors = [s for s in survivors if s not in killed]

    print("\n" + "=" * 82)
    fw = [r["series"] for r in results if r.get("family_wise")]
    print(f"VERDICT: {len(survivors)} survivor(s) after all gates: {survivors or 'NONE'}")
    print(f"         {len(fw)} of 5 clear the Bonferroni family-wise bar (t >= {BONFERRONI_T}): "
          f"{fw or 'NONE'}")
    print("=" * 82)
    failed_pred = [r["series"] for r in results
                   if "error" not in r and not r["sign_as_predicted"] and abs(r["nw_t"]) >= 1.5]
    if failed_pred:
        print(f"  FAILED PREDICTIONS (significant but WRONG-SIGNED): {failed_pred}")
        print("  Per the pre-registration these are failures, NOT discoveries to be re-signed.")
    print("\n  NOTE ON THE TRIAL COUNT: this is FIVE trials. They raise N and therefore the")
    print("  deflation hurdle for every existing sleeve, whatever the outcome above. The")
    print("  pre-registration's own prior was that most would be null and that zero survivors")
    print("  is 'entirely plausible and publishable'.")
    print("  LEDGER GAP (disclosed, not hidden): screen-stage probes like this one write to")
    print("  artifacts/probe/ and the kill log, but are NOT yet wired into var/experiments.jsonl")
    print("  — the same gap glassbox_export.py already documents. The declaration said these")
    print("  five 'enter var/experiments.jsonl'; until that wiring lands, that is aspirational")
    print("  and the honest N must be tracked manually.")

    (OUT / "result.json").write_text(json.dumps({
        "prereg": "docs/design/PREREG_MACRO_VINTAGE_FAMILY.md (commit fb1ab88)",
        "spec_source": "imported from scripts/probe_cpi_surprise_size.py — cannot drift",
        "bonferroni_t": BONFERRONI_T, "suggestive_t": SUGGESTIVE_T,
        "redundancy_rho": REDUNDANCY_RHO,
        "results": results, "survivors": survivors, "family_wise": fw,
        "failed_predictions": failed_pred,
    }, indent=1, default=float))
    print(f"\nartifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
