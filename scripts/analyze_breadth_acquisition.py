#!/usr/bin/env python3
"""ANALYSIS — order the sleeve-discovery queue by diversification value against data cost.

WHY THIS EXISTS. `config/sleeve_discovery.json` declares an excellent per-candidate discipline:
every candidate names its mechanism, its data, its providers and its kill condition. What it does
NOT declare is an ORDER. Eleven of thirteen candidates are data-gated and the 24-hypothesis budget
is fully allocated, so the question that actually governs whether the 14-sleeve objective is
reachable is: *which data do we buy first, and does buying it move the constraint that binds?*

THE CONSTRAINT THAT BINDS IS NOT SLEEVE COUNT. Book Sharpe is `s_bar * sqrt(N_eff)` with
`N_eff = N/(1+(N-1)*rho_bar)`, so the ceiling as N grows is `s_bar/sqrt(rho_bar)`. At N=14 the
PSD floor on average pairwise correlation is -1/(N-1) = -0.0769, so negative rho_bar is admissible
at this count in a way it is not at 250. Everything below is about rho_bar, not count.

WHAT THIS SCRIPT DOES AND DOES NOT CLAIM.
  It READS two files and derives everything from their own text:
    - config/sleeve_discovery.json  (objective, admission gates, candidates, kill criteria)
    - artifacts/analysis/frontier_14/result.json  (the book-Sharpe surface, if present)
  It CLASSIFIES each candidate by what the program's OWN kill criterion is worried about, and by
  whether the primary production source it names is a public authority or an institutional
  subscription. Both classifications are quotations, not opinions: the evidence string for each is
  printed beside the label so a reader can check the call.

  It does NOT measure any candidate's correlation. Nothing here is evidence that any candidate has
  alpha, a sign, or a correlation. No backtest runs, no data is read, no ledger is touched, and no
  hypothesis is consumed. It is an ORDERING over work not yet done.

  uv run python scripts/analyze_breadth_acquisition.py
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
DISCOVERY = _ROOT / "config" / "sleeve_discovery.json"
FRONTIER = _ROOT / "artifacts" / "analysis" / "frontier_14" / "result.json"
OUT_DIR = _ROOT / "artifacts" / "analysis" / "breadth_acquisition"
LEDGERS = [_ROOT / "var" / "experiments.jsonl"]

#: Public authorities. A candidate whose named providers include one of these has a FREE primary
#: source: the cost of opening it is engineering time, not a subscription. Matched against the
#: candidate's own `provider_options` strings.
PUBLIC_AUTHORITIES = {
    "SEC EDGAR", "CFTC", "EIA", "NOAA", "PJM", "ERCOT", "FINRA TRACE",
    "US Treasury Fiscal Data", "Federal Reserve", "Federal Reserve Bank of New York",
}

# THREE DISTINCT FAILURES, AND CONFLATING THEM MIS-ORDERS THE QUEUE. An earlier draft of this
# script lumped them into one "REDUNDANCY" bucket and labelled 8 of 9 public-source candidates
# with it, which made the ordering useless and overstated the correlation problem. They are not
# the same failure and they do not have the same fix:
#
#   SLEEVE-OVERLAP  the kill names an ACTUAL SLEEVE WE TRADE (AlphaMax, AlphaTrend, "existing
#                   equity sleeves"). This is the rho_bar problem. It is the one that decides
#                   whether the 14-sleeve objective is reachable.
#   GENERIC-FACTOR  the kill says the result may reduce to beta, seasonality, quality or momentum
#                   -- i.e. it may have no alpha of its own. That is an ALPHA problem, not a
#                   correlation problem, and it is a risk every candidate carries.
#   TAIL            the kill worries about crisis behaviour. This is the STRESSED-correlation
#                   problem: the sleeve may decorrelate on average and fail exactly in the
#                   episode where diversification is the entire point.

#: Names an existing sleeve or the live book. This is the rho_bar risk.
_SLEEVE_OVERLAP = re.compile(
    r"correlation to (AlphaMax|AlphaTrend|AlphaForge|AlphaVintage|AlphaLedger|existing[A-Za-z ]*sleeves)"
    r"|correlates above [\d.]+ with (AlphaMax|AlphaTrend|AlphaForge|AlphaVintage|AlphaLedger)"
    r"|subsumed by existing",
    re.IGNORECASE,
)
#: May have no alpha of its own once the obvious factor is removed. An alpha risk, not rho_bar.
_GENERIC_FACTOR = re.compile(
    r"merely quality or momentum|reduce[s]? to [a-z\- ]*(?:trend|seasonality)"
    r"|ordinary overnight beta|ordinary short index variance|unhedged duration beta",
    re.IGNORECASE,
)
#: May fail exactly in the stress, when diversification is the entire point.
_TAIL = re.compile(
    r"crisis expected shortfall|left-tail|crisis liquidity|break losses dominate|event-risk budget",
    re.IGNORECASE,
)


def ceiling(s_bar: float, rho_bar: float) -> float:
    """Book-Sharpe ceiling as N -> infinity. Undefined (unbounded) at rho_bar <= 0."""
    return math.inf if rho_bar <= 0 else s_bar / math.sqrt(rho_bar)


def book_sharpe(s_bar: float, rho_bar: float, n: int) -> float:
    """`s_bar * sqrt(N_eff)`. Fails closed below the PSD floor rather than returning a fantasy."""
    floor = -1.0 / (n - 1)
    if rho_bar < floor:
        raise ValueError(f"rho_bar {rho_bar} is below the PSD floor {floor:.4f} at N={n}")
    denom = 1.0 + (n - 1) * rho_bar
    return s_bar * math.sqrt(n / denom)


def required_rho(s_bar: float, target: float, n: int) -> float:
    """The rho_bar at which a book of N sleeves of quality s_bar exactly reaches `target`."""
    return (n * s_bar * s_bar / (target * target) - 1.0) / (n - 1)


def classify(cand: dict) -> dict:
    kill = str(cand.get("kill") or "")
    providers = [str(p) for p in (cand.get("provider_options") or [])]
    public_hits = [p for p in providers if p in PUBLIC_AUTHORITIES]

    # Reported in severity order for the rho_bar objective: a named overlap with a sleeve we
    # actually trade is the one that decides reachability, so it outranks the others. All matches
    # are kept, not just the winner, so the label can never hide a second concern.
    hits = {
        "SLEEVE-OVERLAP": _SLEEVE_OVERLAP.search(kill),
        "TAIL": _TAIL.search(kill),
        "GENERIC-FACTOR": _GENERIC_FACTOR.search(kill),
    }
    all_named = {k: m.group(0) for k, m in hits.items() if m}
    for label in ("SLEEVE-OVERLAP", "TAIL", "GENERIC-FACTOR"):
        if hits[label]:
            risk, evidence = label, hits[label].group(0)
            break
    else:
        risk, evidence = "NONE-NAMED", ""

    return {
        "id": cand.get("id"),
        "asset_class": cand.get("asset_class"),
        "status": cand.get("status"),
        "hypothesis_budget": cand.get("hypothesis_budget"),
        "providers": providers,
        "public_primary_source": bool(public_hits),
        "public_authorities_named": public_hits,
        "diversification_risk_named_by_its_own_kill": risk,
        "kill_evidence": evidence,
        "all_risks_named_by_its_own_kill": all_named,
        "kill": kill,
    }


def main() -> int:
    if not DISCOVERY.exists():
        raise SystemExit(f"FAIL: {DISCOVERY} missing")
    disc = json.loads(DISCOVERY.read_text())
    obj = disc["objective"]
    gates = disc["admission_gates"]

    before = [(p, sum(1 for _ in p.open())) for p in LEDGERS if p.exists()]

    n_target = int(obj["target_sleeve_count"])
    lo, hi = (float(x) for x in obj["portfolio_sharpe_target"])
    rho_gate = float(gates["average_pairwise_correlation_max"])

    # Sleeve quality: the measured 3-sleeve s_bar (0.529) and the 4-sleeve mean of the published
    # standalone Sharpes. Both are stated, neither is chosen to flatter.
    s_bars = {"measured_3_sleeve": 0.529, "published_4_sleeve_mean": (0.68 + 0.91 + 0.33 + 0.34) / 4}

    print("=" * 100)
    print(f"  BREADTH ACQUISITION ORDERING — objective {lo}-{hi} Sharpe across {n_target} sleeves")
    print("=" * 100)

    print("\n[1] DOES THE ADMISSION GATE PERMIT THE OBJECTIVE?")
    print(f"    admission gate average_pairwise_correlation_max = {rho_gate}")
    print(f"    PSD floor on average pairwise correlation at N={n_target}: {-1/(n_target-1):+.4f}")
    gate_rows = []
    for s in (0.40, 0.464, 0.529, 0.60, 0.70, 0.80, 0.90):
        b = book_sharpe(s, rho_gate, n_target)
        gate_rows.append({"s_bar": s, "book_sharpe_at_gate_ceiling": b, "reaches_low_target": b >= lo})
        print(f"      s_bar {s:.3f} -> book Sharpe {b:.3f} at rho_bar={rho_gate}   reaches {lo}? {'YES' if b>=lo else 'NO'}")
    if not any(r["reaches_low_target"] for r in gate_rows):
        print(f"    *** THE GATE BARS ITS OWN OBJECTIVE. At rho_bar={rho_gate} no sleeve quality in this")
        print(f"        range reaches {lo} at N={n_target}. A candidate can pass every evidence check and")
        print(f"        the book still cannot reach the target. The honest correction TIGHTENS this bar.")

    print("\n[2] REQUIRED rho_bar AT N=14 (this is the whole program)")
    req = {}
    for name, s in s_bars.items():
        req[name] = {}
        for tgt in (lo, hi):
            r = required_rho(s, tgt, n_target)
            req[name][str(tgt)] = r
            print(f"    s_bar {s:.3f} ({name:<24}) target {tgt} -> rho_bar must be <= {r:+.4f}"
                  f"{'   *** NEGATIVE ***' if r < 0 else ''}")

    print("\n[3] THE QUEUE, ORDERED BY (free data first, then lowest named diversification risk)")
    rows = [classify(c) for c in disc.get("candidates", [])]
    rank = {"NONE-NAMED": 0, "GENERIC-FACTOR": 1, "TAIL": 2, "SLEEVE-OVERLAP": 3}
    rows.sort(key=lambda r: (not r["public_primary_source"], rank[r["diversification_risk_named_by_its_own_kill"]], r["id"]))
    print(f"    {'CANDIDATE':<32} {'DATA':<12} {'RISK ITS OWN KILL NAMES':<24} {'HYP':<4} STATUS")
    print("    " + "-" * 108)
    for r in rows:
        print(f"    {r['id']:<32} {'PUBLIC' if r['public_primary_source'] else 'INSTITUTIONAL':<12} "
              f"{r['diversification_risk_named_by_its_own_kill']:<24} {str(r['hypothesis_budget'] or 0):<4} {r['status']}")

    pub = [r for r in rows if r["public_primary_source"]]
    inst = [r for r in rows if not r["public_primary_source"]]
    pub_red = sum(1 for r in pub if "SLEEVE-OVERLAP" in r["all_risks_named_by_its_own_kill"])
    inst_red = sum(1 for r in inst if "SLEEVE-OVERLAP" in r["all_risks_named_by_its_own_kill"])
    print(f"\n    public-source candidates: {len(pub)}   of which name a SLEEVE OVERLAP: {pub_red}")
    print(f"    institutional candidates : {len(inst)}   of which name a SLEEVE OVERLAP: {inst_red}")

    out = {
        "objective": obj,
        "admission_gate_average_pairwise_correlation_max": rho_gate,
        "psd_floor_at_target_n": -1.0 / (n_target - 1),
        "gate_permits_objective": any(r["reaches_low_target"] for r in gate_rows),
        "book_sharpe_at_gate_ceiling": gate_rows,
        "required_rho_bar": req,
        "queue_ordered": rows,
        "counts": {
            "public_primary_source": len(pub), "institutional": len(inst),
            "public_named_redundant": pub_red, "institutional_named_redundant": inst_red,
        },
        "claim_boundary": (
            "Ordering only. No candidate correlation, sign, or return is measured or claimed here. "
            "Zero hypotheses consumed; no data read; no backtest run."
        ),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "result.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")

    for p, n0 in before:
        n1 = sum(1 for _ in p.open())
        if n0 != n1:
            raise SystemExit(f"ABORT: {p} moved {n0} -> {n1}; the zero-trial claim is void.")
    print(f"\n    ledger unmoved ({', '.join(f'{p.name}={n}' for p, n in before) or 'none present'}); 0 hypotheses consumed")
    print(f"    written: {OUT_DIR / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
