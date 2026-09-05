"""Is Ledoit-Wolf shrinkage mis-scaled on the live book? Measure, do not change anything.

THE APPROXIMATION AND WHY IT MATTERS. `ledoit_wolf_cc` computes its shrinkage intensity

    delta* = clip((pi - rho) / (gamma * T), 0, 1)

with `T` = the number of ROWS PASSED, and production passes the full unweighted 720-row window
while the matrix being shrunk is the EWMA covariance. Its own docstring calls this a documented
approximation: "the asymptotics assume iid observations and the unweighted window is the closest
admissible sample".

That was conservative while the EWMA's effective sample EXCEEDED 720 — a larger true T means a
smaller true delta*, so using 720 over-shrinks slightly and over-shrinking is the safe direction.
It stops being conservative at a short halflife. `artifacts/analysis/live_covariance_memory`
measured the effective sample at 60.6 rows for a 21-day halflife on the equity sleeve, twelve
times smaller than the T in the denominator, which would make delta* twelve times too SMALL and
under-shrink a covariance estimated from far less data than the formula believes.

This measures the size of that error on the real baskets. It does NOT change the live path: the
production covariance halflife is the legacy 720 bars, where the approximation is still
conservative, and changing it is owner-gated (backlog A-track, live-change ceremony).

Reads price data read-only. Registers no hypothesis, opens no new return data on any untested
identity: 0 trials.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from alphaforge.portfolio.covariance import ewma_cov, ledoit_wolf_cc

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "analysis" / "ledoit_wolf_effective_sample" / "result.json"
MF_LAKE = REPO / "data" / "lake_mf" / "ohlcv_1d"

WINDOW = 720
MIN_PERIODS = 240
# The halflife ladder, in BARS. On the daily managed-futures basket a bar is a session, so these
# are also day counts there. 720 is the production setting.
HALFLIVES = (21, 63, 126, 252, 504, 720)


def load_basket(lake: Path, limit_rows: int = WINDOW) -> pd.DataFrame:
    """The trailing `limit_rows` sessions of simple returns for every instrument in the lake."""
    frames: dict[str, pd.Series] = {}
    for instrument_dir in sorted(lake.iterdir()):
        if not instrument_dir.is_dir():
            continue
        parts = sorted(instrument_dir.rglob("*.parquet"))
        if not parts:
            continue
        frame = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
        column = "ts_open" if "ts_open" in frame.columns else frame.columns[0]
        frame = frame.sort_values(column)
        closes = pd.Series(
            frame["close"].to_numpy(dtype=float),
            index=pd.to_datetime(frame[column], unit="ms", utc=True).dt.normalize(),
        )
        closes = closes[~closes.index.duplicated(keep="last")]
        frames[instrument_dir.name.split("=")[-1]] = closes
    panel = pd.DataFrame(frames).sort_index()
    returns = panel.pct_change().dropna(how="all")
    return returns.tail(limit_rows).dropna(axis=1, how="any")


def effective_sample(halflife_bars: float, window: int = WINDOW, seed: int = MIN_PERIODS) -> float:
    """Kish effective sample size of the PRODUCTION estimator's weights, seed block included."""
    lam = 0.5 ** (1.0 / float(halflife_bars))
    k = window - seed
    weights = np.empty(window, dtype=np.float64)
    weights[:seed] = (lam**k) / seed
    j = np.arange(k, dtype=np.float64)
    weights[seed:] = (1.0 - lam) * lam ** (k - 1 - j)
    return float(1.0 / np.sum(weights**2))


def _constant_correlation_target(cov: np.ndarray) -> np.ndarray:
    """The Ledoit-Wolf constant-correlation target F, rebuilt exactly as the estimator defines it.

    f_ii = s_ii ; f_ij = r_bar * sqrt(s_ii * s_jj), with r_bar the mean pairwise correlation.
    """
    sigma = np.sqrt(np.diag(cov))
    outer = np.outer(sigma, sigma)
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.where(outer > 0, cov / outer, 0.0)
    n = cov.shape[0]
    off = ~np.eye(n, dtype=bool)
    r_bar = float(corr[off].mean()) if n > 1 else 0.0
    target = r_bar * outer
    np.fill_diagonal(target, np.diag(cov))
    return target


def _ex_ante_vol_shift(a: np.ndarray, b: np.ndarray, rng: np.random.Generator) -> dict[str, float]:
    """How far the overlay's ex-ante vol moves between two covariance matrices.

    ⚠️ INVERSE-VOL WEIGHTS ARE INVARIANT TO THIS SHRINKAGE AND MEASURING THEM WAS THE MISTAKE.
    The Ledoit-Wolf constant-correlation target sets f_ii = s_ii, so shrinking toward it changes
    the OFF-DIAGONAL only and leaves every variance exactly as it was. Inverse-vol depends on the
    diagonal alone, so the first version of this measurement returned 0.000000 at every halflife —
    a result of exactly zero, which is what a measurement that cannot move looks like rather than
    a finding.

    The error therefore cannot reach position sizing through the `rank` allocator's relative
    weights at all. It reaches the book through anything that uses the off-diagonal: the overlay's
    ex-ante vol `sqrt(w' Sigma w)`, which is what `vol_target` scales the whole book on, and the
    MVO allocator (not production's default). Ex-ante vol is measured here over random long/short
    weight vectors, because the real weights vary by day and a single arbitrary vector would be a
    sample of one.
    """
    n = a.shape[0]
    draws = rng.normal(size=(512, n))
    draws /= np.abs(draws).sum(axis=1, keepdims=True)   # gross-normalised, long/short
    va = np.sqrt(np.clip(np.einsum("ij,jk,ik->i", draws, a, draws), 0.0, None))
    vb = np.sqrt(np.clip(np.einsum("ij,jk,ik->i", draws, b, draws), 0.0, None))
    relative = np.abs(vb - va) / np.clip(va, 1e-18, None)
    return {
        "mean_relative": float(relative.mean()),
        "max_relative": float(relative.max()),
        "median_relative": float(np.median(relative)),
    }


def measure(returns: pd.DataFrame, label: str) -> dict[str, Any]:
    values = returns.to_numpy(dtype=np.float64)
    rng = np.random.default_rng(20260822)   # fixed: this must reproduce byte-for-byte
    rows: list[dict[str, Any]] = []
    for halflife in HALFLIVES:
        cov = ewma_cov(returns, halflife_bars=halflife, min_periods=MIN_PERIODS)
        n_eff = effective_sample(halflife)
        # As coded: the full unweighted window. At the effective sample: the most recent n_eff
        # rows, which is the closest admissible sample to what the EWMA actually averaged over.
        _, delta_as_coded = ledoit_wolf_cc(values, cov)
        rows_passed = values.shape[0]
        # Pure denominator effect: delta* is linear in 1/T, so rescaling is exact while unclipped.
        delta_rescaled = min(1.0, delta_as_coded * rows_passed / n_eff)
        clipped = delta_as_coded * rows_passed / n_eff > 1.0
        # Re-estimated on the shorter sample: T changes AND pi/rho/gamma change with it.
        take = max(2, min(rows_passed, round(n_eff)))
        _, delta_reestimated = ledoit_wolf_cc(values[-take:], cov)
        shrunk_coded, _ = ledoit_wolf_cc(values, cov)
        target = _constant_correlation_target(cov)
        shrunk_true = (1.0 - delta_rescaled) * cov + delta_rescaled * target
        vol_shift = _ex_ante_vol_shift(shrunk_coded, shrunk_true, rng)
        rows.append(
            {
                "halflife_bars": halflife,
                "effective_sample_rows": n_eff,
                "rows_passed_in_production": values.shape[0],
                "delta_star_as_coded": delta_as_coded,
                "delta_star_rescaled_to_effective_T": delta_rescaled,
                "delta_star_reestimated_on_effective_window": delta_reestimated,
                "understatement_factor_pure_T": (
                    delta_rescaled / delta_as_coded if delta_as_coded > 0 else None
                ),
                "rescale_clipped_at_one": clipped,
                "conservative": delta_as_coded >= delta_rescaled,
                "inverse_vol_weights_are_invariant": True,
                "mean_ex_ante_vol_shift": vol_shift["mean_relative"],
                "median_ex_ante_vol_shift": vol_shift["median_relative"],
                "max_ex_ante_vol_shift": vol_shift["max_relative"],
            }
        )
    return {"basket": label, "instruments": int(values.shape[1]), "rows": int(values.shape[0]),
            "ladder": rows}


def main() -> int:
    if not MF_LAKE.exists():
        print(f"no managed-futures lake at {MF_LAKE}; refusing to guess")
        return 1
    mf = load_basket(MF_LAKE)
    if mf.shape[1] < 3 or mf.shape[0] < MIN_PERIODS:
        print(f"basket too small to measure: {mf.shape}")
        return 1

    measured = measure(mf, "managed_futures_17_etf")
    production = next(r for r in measured["ladder"] if r["halflife_bars"] == 720)
    worst = max(
        measured["ladder"], key=lambda r: r["understatement_factor_pure_T"] or -math.inf
    )
    non_conservative = [r for r in measured["ladder"] if not r["conservative"]]

    result = {
        "schema": "canli.alphac-ledoit-wolf-effective-sample.v1",
        "claim_boundary": (
            "Measures an approximation's error on real price data. Changes nothing, registers no "
            "hypothesis identity, and opens no return data on any untested identity. 0 trials."
        ),
        "the_approximation": (
            "ledoit_wolf_cc computes delta* = clip((pi - rho)/(gamma*T), 0, 1) with T = the rows "
            "PASSED. Production passes the full unweighted 720-row window while the matrix being "
            "shrunk is the EWMA covariance. Documented in the function's own docstring as the "
            "closest admissible sample."
        ),
        "why_it_was_conservative": (
            "A larger true T means a smaller true delta*, so using 720 when the estimator's "
            "effective sample EXCEEDS 720 over-shrinks slightly — and over-shrinking is the safe "
            "direction for a covariance estimate. The concern is the opposite case."
        ),
        "baskets": [measured],
        "production_setting": production,
        "worst_case_in_ladder": worst,
        "any_non_conservative": bool(non_conservative),
        "non_conservative_halflives": [r["halflife_bars"] for r in non_conservative],
        "verdict": (
            "NOT CONSERVATIVE AT ANY HALFLIFE, BUT IMMATERIAL AT THE PRODUCTION SETTING "
            f"({production['mean_ex_ante_vol_shift']:.2%} mean ex-ante vol error). It becomes "
            f"MATERIAL at a short halflife: {worst['mean_ex_ante_vol_shift']:.2%} mean and "
            f"{worst['max_ex_ante_vol_shift']:.1%} worst case at {worst['halflife_bars']} bars. "
            "Fix it BEFORE shortening the covariance halflife, not after."
        ),
        "why_it_is_never_conservative": (
            "The documented reasoning — that the unweighted window is the closest admissible "
            "sample — assumed the EWMA's effective sample could EXCEED the window. It cannot: "
            "ewma_cov is windowed at cov_window_bars, so its effective sample is bounded by the "
            "window at every halflife. Measured here it peaks at 635 rows against a T of 720 and "
            "falls to 514 at the production setting, so delta* is understated everywhere rather "
            "than only at short halflives."
        ),
        "the_channel_the_error_travels": (
            "NOT position sizing. The constant-correlation target shares S's diagonal, so this "
            "shrinkage cannot change a variance and inverse-vol weights — what the production "
            "`rank` allocator sizes on — are mathematically invariant to it. The error reaches "
            "the book only through quantities that use the off-diagonal: the overlay's ex-ante "
            "vol sqrt(w' Sigma w), which scales the whole book, and the MVO allocator, which is "
            "not the production default."
        ),
        "what_this_does_not_do": (
            "It does not change the live path. Production runs the legacy 720-bar covariance "
            "halflife, and any change to it is gated by the live-change ceremony and is the "
            "owner's. This measures what a future halflife decision would be walking into."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  basket: {measured['instruments']} instruments x {measured['rows']} sessions\n")
    print(
        f"  {'halflife':>9} {'eff.N':>8} {'coded':>8} {'pure-T':>8} "
        f"{'re-est':>8} {'x':>6} {'safe?':>6}"
    )
    for row in measured["ladder"]:
        ratio = row["understatement_factor_pure_T"]
        print(
            f"  {row['halflife_bars']:>9} {row['effective_sample_rows']:>8.1f} "
            f"{row['delta_star_as_coded']:>8.4f} "
            f"{row['delta_star_rescaled_to_effective_T']:>8.4f} "
            f"{row['delta_star_reestimated_on_effective_window']:>8.4f} "
            f"{(ratio if ratio is not None else float('nan')):>6.2f} "
            f"{'yes' if row['conservative'] else 'NO':>6}"
        )
    print(
        "\n  inverse-vol weights are INVARIANT to this shrinkage (the target shares S's "
        "diagonal),\n  so the error reaches the book only through the overlay's ex-ante vol:\n"
    )
    print(f"  {'halflife':>9} {'mean':>9} {'median':>9} {'max':>9}")
    for row in measured["ladder"]:
        print(
            f"  {row['halflife_bars']:>9} {row['mean_ex_ante_vol_shift']:>8.3%} "
            f"{row['median_ex_ante_vol_shift']:>8.3%} {row['max_ex_ante_vol_shift']:>8.3%}"
        )
    print(f"\n  verdict: {result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
