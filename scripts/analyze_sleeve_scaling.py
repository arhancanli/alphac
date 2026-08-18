#!/usr/bin/env python3
"""ANALYSIS — what does a 50-250 sleeve book actually buy, and what does searching for it cost?

NOT a strategy trial. This runs no backtest, fits nothing, and does NOT enter
var/experiments.jsonl. It is arithmetic over curves we already own plus the trial
ledger we already wrote, answering one question the owner asked directly:

    "my long term vision is reaching 50-250 uncorrelated good sleeves"

Three measured quantities decide whether that vision pays:

  1. rho_bar  -- the AVERAGE PAIRWISE CORRELATION of the sleeves we can actually find.
     Effective breadth is N_eff = N / (1 + (N-1) * rho_bar), and a book of N
     equal-risk sleeves each of Sharpe s scores  S_book = s * sqrt(N_eff).
     As N -> infinity, N_eff -> 1/rho_bar. THE CEILING IS SET BY rho_bar, NOT BY N.
     This is why "250 sleeves" is not 250x anything: at rho_bar = 0.10 the most
     breadth any number of sleeves can ever deliver is N_eff = 10.

  2. hit_rate -- survivors per candidate tested, read from the published kill log.
     It converts a sleeve target into a TRIAL COUNT.

  3. sigma_SR -- the cross-sectional dispersion of trial Sharpes in our own ledger.
     It converts a trial count into a DEFLATION HURDLE via the expected maximum
     Sharpe under the null (Bailey/Lopez de Prado):

        SR*(N) = sigma_SR * [ (1-gamma) * Z(1 - 1/N) + gamma * Z(1 - 1/(N*e)) ]

     Every trial we run raises N for the WHOLE BOOK -- our own deflation.json already
     commits us to "deflate against the FULL N". So searching for sleeve number 51
     raises the bar that sleeves 1-50 must clear.

The punchline this computes: S_book saturates (bounded by s/sqrt(rho_bar)) while
SR* grows without bound (like sqrt(2 ln N)). They cross. There is an OPTIMAL number
of sleeves to search for, and it is a measured number, not a preference.

    uv run python scripts/analyze_sleeve_scaling.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ANN = 252
EULER = 0.5772156649015329
OUT = Path("artifacts/analysis/sleeve_scaling")

# The THREE curves that make up the live book. One per sleeve, and nothing else.
#
# CORRECTED 2026-08-06. This dict previously held FOUR curves under the comment "the four
# curves that make up the live book", including `prereg_investment` -- which is NOT a sleeve.
# `data/paper/state.json` book.sleeves is and always was [alphaforge, alphamax,
# managed_futures]. The extra curve changed the two numbers this whole project is steered by,
# and it changed them in our favour:
#
#     4 curves (published):  s_bar 0.464   rho_bar -0.0398   ceiling INFINITE
#     3 sleeves (correct):   s_bar 0.529   rho_bar +0.0723   ceiling 1.97
#
# The published NEGATIVE average correlation -- the number the public site calls "the edge" --
# existed only because a strategy we do not trade was averaged in. The three sleeves we DO
# trade are POSITIVELY correlated. Since the book's ceiling is s_bar/sqrt(rho_bar), a positive
# rho_bar means a hard ceiling of 1.97 where we had been publishing no ceiling at all.
#
# If a curve is ever added here it must correspond to a sleeve in state.json's book.sleeves.
# A number used to steer the firm must be measured on the firm.
SLEEVES = {
    "eq_mom (k30_dn_63)": "artifacts/walkforward/k30_dn_63/equity.parquet",
    "trend (mf_live_fwd)": "artifacts/walkforward/mf_live_fwd/equity.parquet",
    "crypto_carry_wk": "artifacts/walkforward/crypto_carry_wk/equity.parquet",
}


def daily_logret(path: str) -> pd.Series:
    """Equity curve -> daily log returns, tolerant of hourly curves (crypto)."""
    e = pd.read_parquet(path)
    s = pd.Series(
        e["equity"].astype(float).values,
        index=pd.to_datetime(e["ts"], unit="ms"),
    ).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    daily = s.resample("1D").last().dropna()  # hourly -> daily close-to-close
    return np.log(daily).diff().dropna()


def sharpe(r: pd.Series | np.ndarray) -> float:
    x = np.asarray(r, float)
    sd = x.std(ddof=0)
    return float(x.mean() / sd * math.sqrt(ANN)) if sd > 0 else 0.0


def z(p: float) -> float:
    """Inverse standard normal CDF (Acklam-free: use erfinv)."""
    return float(math.sqrt(2.0) * math.erf(2.0 * p - 1.0)) if False else _ppf(p)


def _ppf(p: float) -> float:
    # Newton on erf; adequate and dependency-free for the p we use (p -> 1).
    from statistics import NormalDist

    return float(NormalDist().inv_cdf(p))


def sr_star(n_trials: int, sigma_sr: float) -> float:
    """Expected MAXIMUM Sharpe from n independent null trials (Bailey/LdP)."""
    n = max(int(n_trials), 2)
    return sigma_sr * ((1 - EULER) * _ppf(1 - 1 / n) + EULER * _ppf(1 - 1 / (n * math.e)))


def rho_floor(n: int) -> float:
    """THE PSD CONSTRAINT. A correlation matrix must be positive semi-definite, which
    bounds the average pairwise correlation of n streams from BELOW at -1/(n-1).

    This is the mathematical fact that kills naive extrapolation of a small book's
    negative rho_bar. Four sleeves may average -0.04 (floor -0.333). Two hundred and
    fifty sleeves CANNOT average below -0.004: as N grows the floor is dragged to
    zero, so today's negative correlation is a small-N luxury, not a scaling law.
    """
    return -1.0 / (n - 1) if n > 1 else -1.0


def n_eff(n: int, rho: float) -> float:
    """Effective breadth of n sleeves at average pairwise correlation rho."""
    if n <= 1:
        return float(n)
    rho = max(rho, rho_floor(n) + 1e-9)   # cannot request an infeasible correlation
    denom = 1 + (n - 1) * rho
    return float(n / denom) if denom > 0 else float("inf")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- 1. rho_bar
    curves = {k: daily_logret(v) for k, v in SLEEVES.items()}
    for k, v in curves.items():
        print(f"  {k:24s} {len(v):>6}d  {v.index.min().date()}..{v.index.max().date()}"
              f"  SR {sharpe(v):+.3f}")

    J = pd.concat(curves.values(), axis=1, keys=curves.keys()).dropna()
    print(f"\nCOMMON WINDOW: {J.index.min().date()}..{J.index.max().date()}  ({len(J)} days)")
    C = J.corr()
    print("\nPAIRWISE CORRELATION (measured, common window)")
    print(C.round(3).to_string())

    k = len(C)
    iu = np.triu_indices(k, 1)
    pair_rhos = C.values[iu]
    rho_bar = float(pair_rhos.mean())
    rho_max = float(pair_rhos.max())
    s_bar = float(np.mean([sharpe(J[c]) for c in J.columns]))
    ne_now = n_eff(k, rho_bar)

    # equal-RISK (inverse-vol) is what the theory below assumes; equal-weight is not.
    vols = J.std(ddof=0)
    eqrisk = (J / vols).mean(axis=1)
    print(f"\n  average pairwise rho_bar  {rho_bar:+.4f}   (max pair {rho_max:+.3f})")
    print(f"  PSD floor at N={k}          {rho_floor(k):+.4f}   <- rho_bar cannot go below this")
    print(f"  average sleeve Sharpe s   {s_bar:+.3f}   (common window, {len(J)}d)")
    print(f"  N_eff at N={k}             {ne_now:.2f}   -> predicted book SR "
          f"{s_bar*math.sqrt(ne_now):+.3f}")
    print(f"  measured EQUAL-RISK book SR  {sharpe(eqrisk):+.3f}   <- the like-for-like check")
    print(f"  measured equal-weight book SR {sharpe(J.mean(axis=1)):+.3f}   "
          f"(higher only because it overweights the high-vol sleeves)")

    # ------------------------------------------------------- 2. the breadth ceiling
    print("\n" + "=" * 78)
    print("THE CEILING: N_eff -> 1/rho_bar. More sleeves cannot escape their correlation.")
    print("=" * 78)
    # Corrected 2026-08-06 with the curve set: on the three sleeves actually traded, rho_bar is
    # POSITIVE, so the book has a hard ceiling rather than the unbounded one a negative average
    # would imply. The old prose asserted "NEGATIVE" unconditionally and would have printed that
    # word over a positive number.
    _sign = "NEGATIVE" if rho_bar < 0 else "POSITIVE"
    print(f"\n  Today's rho_bar is {_sign} ({rho_bar:+.3f}) across {len(SLEEVES)} sleeves.")
    if rho_bar > 0:
        print(f"  That is a HARD CEILING: no sleeve count takes the book past "
              f"s_bar/sqrt(rho_bar).")
    else:
        print("  A negative average is a SMALL-N luxury; the PSD floor is -1/(N-1).")
    print(f"  The PSD floor -1/(N-1) forces average correlation toward zero as N grows:")
    print(f"    N=4 floor {rho_floor(4):+.3f} | N=50 floor {rho_floor(50):+.4f} | "
          f"N=250 floor {rho_floor(250):+.4f}")
    print("  So a 250-sleeve book cannot be built on negative average correlation.")
    print("  The realistic question is which POSITIVE rho_bar we can hold at scale.\n")
    print(f"{'rho_bar':>8}{'ceiling N_eff':>15}{'ceiling S_book':>16}"
          f"{'N=10':>9}{'N=50':>9}{'N=250':>9}{'50->250 gain':>14}")
    for rho in (0.01, 0.02, 0.05, 0.08, 0.10, 0.15, 0.30):
        ceil_ne = 1 / rho
        row = [s_bar * math.sqrt(n_eff(n, rho)) for n in (10, 50, 250)]
        print(f"{rho:>8.3f}{ceil_ne:>15.1f}{s_bar*math.sqrt(ceil_ne):>16.3f}"
              f"{row[0]:>9.3f}{row[1]:>9.3f}{row[2]:>9.3f}{row[2]/row[1]:>13.2f}x")

    # ------------------------------------------------- 3. hit rate -> trial count
    kl = json.loads(Path("/Users/arhancanli/meridian/public/glassbox/kill_log.json").read_text())
    killed = int(kl.get("killed_count", 0)) + int(kl.get("screen_killed_count", 0))
    survived = int(kl.get("survived_count", 0))
    tested = killed + survived
    hit = survived / tested if tested else 0.0
    print("\n" + "=" * 78)
    print("THE SEARCH COST: our own measured hit rate, from the published kill log")
    print("=" * 78)
    print(f"  tested {tested}   killed {killed}   survived {survived}   "
          f"HIT RATE {hit:.1%}  (1 sleeve per {1/hit if hit else float('inf'):.0f} candidates)")

    led = [json.loads(x) for x in open("var/experiments.jsonl") if x.strip()]
    raw = np.array([r.get("sharpe_ann", np.nan) for r in led], float)
    srs = raw[np.isfinite(raw)]          # some ledger rows carry NaN Sharpes
    sigma_sr = float(srs.std(ddof=1))
    n_ledger = len(led)
    print(f"  ledger trials N={n_ledger}  ({len(srs)} with a finite Sharpe; "
          f"{n_ledger-len(srs)} NaN)")
    print(f"  trial-Sharpe dispersion sigma_SR {sigma_sr:.3f}   (mean {srs.mean():+.3f}, "
          f"min {srs.min():+.2f}, max {srs.max():+.2f})")
    print(f"  CURRENT deflation hurdle SR*({n_ledger}) = {sr_star(n_ledger, sigma_sr):.3f}"
          f"   <- any book Sharpe below this is indistinguishable from search luck")

    # -------------------------------------- 4. the crossover: breadth vs deflation
    print("\n" + "=" * 78)
    print("BREADTH GAIN vs DEFLATION COST — the number that decides the vision")
    print("=" * 78)
    print(f"sleeve Sharpe {s_bar:.3f}, hit rate {hit:.1%}, sigma_SR {sigma_sr:.3f},")
    print("and our own published rule that every candidate enters the SAME N.\n")

    scen = {}
    for rho_use in (0.05, 0.10, 0.15):
        print(f"--- scenario: rho_bar = {rho_use:.2f} "
              f"(ceiling N_eff {1/rho_use:.0f}, ceiling S_book {s_bar/math.sqrt(rho_use):.2f}) ---")
        print(f"{'sleeves':>8}{'trials':>9}{'N_total':>9}{'N_eff':>8}"
              f"{'S_book':>9}{'SR* hurdle':>12}{'MARGIN':>10}")
        best, rows = (-9e9, 0), []
        for n_sl in (4, 6, 8, 10, 15, 20, 30, 50, 75, 100, 150, 250):
            extra = int(round((n_sl - k) / hit)) if hit and n_sl > k else 0
            n_tot = n_ledger + max(extra, 0)
            ne = n_eff(n_sl, rho_use)
            sb = s_bar * math.sqrt(ne)
            hurdle = sr_star(n_tot, sigma_sr)
            margin = sb - hurdle
            rows.append({"sleeves": n_sl, "trials_needed": extra, "n_total": n_tot,
                         "n_eff": ne, "s_book": sb, "sr_star": hurdle, "margin": margin})
            if margin > best[0]:
                best = (margin, n_sl)
            print(f"{n_sl:>8}{extra:>9}{n_tot:>9}{ne:>8.2f}{sb:>9.3f}{hurdle:>12.3f}"
                  f"{margin:>+10.3f}")
        print(f"  -> margin-maximising sleeve count {best[1]}  (margin {best[0]:+.3f})\n")
        scen[f"rho_{rho_use:.2f}"] = {"rows": rows, "argmax_sleeves": best[1],
                                      "max_margin": best[0]}

    print("  margin = book Sharpe minus the multiple-testing hurdle its OWN SEARCH created.")
    print("  S_book saturates at s/sqrt(rho_bar); SR* grows like sqrt(2 ln N) without bound.")
    print("  Searching for more sleeves therefore stops paying at a FINITE, MEASURED number.")

    # ------------------------------------------------- 5. the OTHER axis: sample length
    #
    # sigma_SR is not a constant of nature. Under the null an annualised Sharpe estimated
    # on T years has sd ~ sd_t / sqrt(T). Our ledger's t-stats (SR * sqrt(T)) have
    # sd = sd_t and mean ~ 0, so we can read the hurdle off ANY window we like -- and the
    # hurdle falls as 1/sqrt(T). Sample length is the lever the sleeve count is not.
    def _f(v) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("nan")

    t_stats = np.array([_f(r.get("sharpe_ann")) * math.sqrt(_f(r.get("n_obs")) / ANN)
                        for r in led], float)
    t_stats = t_stats[np.isfinite(t_stats)]
    sd_t = float(t_stats.std(ddof=1))
    print("\n" + "=" * 78)
    print("THE OTHER AXIS: SAMPLE LENGTH. sigma_SR = sd_t / sqrt(T), so SR* falls as 1/sqrt(T)")
    print("=" * 78)
    print(f"  ledger t-stats (SR*sqrt(T)): mean {t_stats.mean():+.3f}  sd {sd_t:.3f}")
    print("  pure noise would give mean 0.00, sd 1.00. Mean is ~0 (the average idea has NO")
    print("  edge, as the kill log says). sd slightly above 1 = some genuine dispersion plus")
    print("  fat tails / autocorrelation that the naive sqrt(T) scaling understates.\n")
    print(f"{'T years':>9}{'sigma_SR':>10}{'SR*(N=125)':>12}{'SR*(N=830)':>12}"
          f"{'SR*(N=3897)':>13}{'t>=1.96 needs SR':>18}")
    surface_T = []
    for Ty in (2.9, 5, 10, 15, 20, 30, 50):
        s_sr = sd_t / math.sqrt(Ty)
        row = {"T_years": Ty, "sigma_sr": s_sr,
               "sr_star_125": sr_star(125, s_sr), "sr_star_830": sr_star(830, s_sr),
               "sr_star_3897": sr_star(3897, s_sr), "prereg_sr_needed": 1.96 / math.sqrt(Ty)}
        surface_T.append(row)
        print(f"{Ty:>9.1f}{s_sr:>10.3f}{row['sr_star_125']:>12.3f}{row['sr_star_830']:>12.3f}"
              f"{row['sr_star_3897']:>13.3f}{row['prereg_sr_needed']:>18.3f}")
    print("\n  LAST COLUMN IS THE ESCAPE HATCH. A book that is PRE-REGISTERED and then simply")
    print("  RUN FORWARD is not selected from N trials -- N = 1, so the multiple-testing")
    print("  hurdle collapses to ordinary significance, SR >= 1.96/sqrt(T).")

    # ----------------------------------- 6. the joint decision surface (sleeves x years)
    print("\n" + "=" * 78)
    print("DECISION SURFACE — book margin (S_book - SR*) by SLEEVES x YEARS, rho_bar=0.10")
    print("=" * 78)
    print("  positive = the book beats the hurdle its own search created\n")
    hdr = "".join(f"{y:>9.0f}y" for y in (3, 5, 10, 20, 30))
    print(f"{'sleeves':>9}{hdr}")
    surface = []
    for n_sl in (4, 10, 20, 50, 100, 250):
        extra = int(round((n_sl - k) / hit)) if hit and n_sl > k else 0
        n_tot = n_ledger + max(extra, 0)
        sb = s_bar * math.sqrt(n_eff(n_sl, 0.10))
        cells, line = {}, f"{n_sl:>9}"
        for Ty in (3, 5, 10, 20, 30):
            m_ = sb - sr_star(n_tot, sd_t / math.sqrt(Ty))
            cells[str(Ty)] = m_
            line += f"{m_:>+10.2f}"
        surface.append({"sleeves": n_sl, "trials": n_tot, "s_book": sb, "margin_by_years": cells})
        print(line)
    print("\n  Read DOWN a column: adding sleeves helps, then stops (S_book saturates).")
    print("  Read ACROSS a row: adding YEARS helps without limit (SR* falls as 1/sqrt(T)).")
    print("  The vision is not wrong. The binding variable is just not the one assumed.")

    (OUT / "result.json").write_text(json.dumps({
        "measured": {
            "sleeves": list(curves.keys()),
            "common_window_days": int(len(J)),
            "common_window": [str(J.index.min().date()), str(J.index.max().date())],
            "rho_bar": rho_bar, "rho_max_pair": rho_max, "rho_floor_at_n": rho_floor(k),
            "sleeve_sharpe_mean": s_bar,
            "n_eff_now": ne_now,
            "book_sharpe_equal_risk": sharpe(eqrisk),
            "book_sharpe_equal_weight": sharpe(J.mean(axis=1)),
            "hit_rate": hit, "tested": tested, "survived": survived,
            "ledger_trials": n_ledger, "ledger_finite_sharpes": int(len(srs)),
            "sigma_sr": sigma_sr, "sr_star_now": sr_star(n_ledger, sigma_sr),
        },
        "psd_floor": {str(n): rho_floor(n) for n in (4, 10, 50, 250)},
        "scenarios": scen,
        "sample_length": {"sd_t": sd_t, "t_mean": float(t_stats.mean()), "rows": surface_T},
        "decision_surface_rho_0p10": surface,
    }, indent=1))
    print(f"\nartifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
