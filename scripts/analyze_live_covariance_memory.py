"""What the LIVE covariance estimator actually does with a halflife parameter, per sleeve.

WHY THIS EXISTS. The drawdown sweep that set overlay policy simulated an UNTRUNCATED EWMA
recursion. Production's `ewma_cov` is not that: it sees only `cov_window_bars` rows and seeds S_0
with the EQUALLY WEIGHTED sample covariance of the oldest `min_periods` rows, then decays that
seed block by lambda^k. So a halflife written into the config and the memory the estimator really
has are two different numbers, and the mapping between them was never measured. Changing the
default on the strength of the sweep -- which is what happened on 2026-08-21 and was reverted the
same day -- assumed that mapping is the identity.

This measures it. The analytic weights below are VERIFIED against the production function by unit
impulse (a 1.0 in row t makes out[0,0] equal that row's weight); they agree to 2e-19, and
`tests/unit/test_live_covariance_memory.py` pins that agreement rather than trusting this comment.

Reads no market data, runs no backtest, registers no hypothesis: 0 trials.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "analysis" / "live_covariance_memory" / "result.json"

# Production defaults (src/alphaforge/portfolio/strategy.py).
WINDOW_BARS = 720
MIN_PERIODS = 240
LEGACY_HALFLIFE_BARS = 720

# Bars per day on each sleeve's own calendar: periods_per_year(tf) / periods_per_year(D1).
SLEEVES = {"crypto_H1": 24.0, "equity_D1": 1.0}
# Day counts worth mapping: the legacy setting on each calendar, and the sweep's ladder.
CANDIDATE_DAYS = (3.0, 7.0, 14.0, 21.0, 30.0, 63.0, 126.0, 252.0, 720.0)


def weights(halflife_bars: float, window: int = WINDOW_BARS, seed: int = MIN_PERIODS):
    """The exact weight each row of the window carries in the production estimator."""
    lam = 0.5 ** (1.0 / float(halflife_bars))
    k = window - seed
    w = np.empty(window, dtype=np.float64)
    w[:seed] = (lam**k) / seed
    j = np.arange(k, dtype=np.float64)
    w[seed:] = (1.0 - lam) * lam ** (k - 1 - j)
    return w


def profile(
    halflife_bars: float,
    bars_per_day: float,
    window: int = WINDOW_BARS,
    seed: int = MIN_PERIODS,
) -> dict:
    w = weights(halflife_bars, window=window, seed=seed)
    ages = np.arange(window - 1, -1, -1, dtype=np.float64)  # row 0 is the OLDEST
    lam = 0.5 ** (1.0 / float(halflife_bars))
    cumulative = np.cumsum(w[::-1])          # newest-first
    index = min(int(np.searchsorted(cumulative, 0.5)), window - 1)
    median_age = float(ages[::-1][index])
    effective_sample = float(1.0 / np.sum(w**2))   # Kish
    mean_age = float(np.sum(w * ages))
    # The halflife an UNTRUNCATED EWMA would need to show this median age. For an untruncated
    # EWMA the median weight age IS the halflife, which is what makes this the honest comparison.
    return {
        "halflife_bars": halflife_bars,
        "halflife_days": halflife_bars / bars_per_day,
        "window_bars": window,
        "seed_bars": seed,
        "window_days": window / bars_per_day,
        "seed_block_weight": float(np.sum(w[:seed])),
        "lambda": lam,
        "effective_sample_rows": effective_sample,
        "mean_weight_age_days": mean_age / bars_per_day,
        "median_weight_age_days": median_age / bars_per_day,
        "untruncated_equivalent_halflife_days": median_age / bars_per_day,
        "truncation_absorbed_fraction": (
            1.0 - (median_age / halflife_bars) if halflife_bars else float("nan")
        ),
    }


def main() -> int:
    sleeves: dict[str, dict] = {}
    for sleeve, bars_per_day in SLEEVES.items():
        rows = []
        for days in CANDIDATE_DAYS:
            bars = days * bars_per_day
            if bars < 1:
                continue
            rows.append(profile(bars, bars_per_day))
        legacy = profile(LEGACY_HALFLIFE_BARS, bars_per_day)
        sleeves[sleeve] = {
            "bars_per_day": bars_per_day,
            "legacy_setting": {
                "halflife_bars": LEGACY_HALFLIFE_BARS,
                "means_days": LEGACY_HALFLIFE_BARS / bars_per_day,
                **legacy,
            },
            "by_requested_days": rows,
        }

    crypto = sleeves["crypto_H1"]
    def _at(data: dict, days: float) -> dict:
        return next(r for r in data["by_requested_days"] if r["halflife_days"] == days)

    crypto_7 = _at(crypto, 7.0)
    crypto_14 = _at(crypto, 14.0)
    crypto_30 = _at(crypto, 30.0)
    crypto_720 = _at(crypto, 720.0)

    result = {
        "schema": "canli.alphac-live-covariance-memory.v1",
        "claim_boundary": (
            "A property of the ESTIMATOR, derived from its exact weighting and verified against "
            "the production function by unit impulse. Reads no market data, runs no backtest, "
            "registers no hypothesis identity, and recommends no halflife. 0 trials."
        ),
        "production": {
            "cov_window_bars": WINDOW_BARS,
            "cov_min_periods": MIN_PERIODS,
            "legacy_cov_halflife_bars": LEGACY_HALFLIFE_BARS,
            "estimator": "alphaforge.portfolio.covariance.ewma_cov",
        },
        "why_the_parameter_is_not_the_memory": (
            "ewma_cov sees only cov_window_bars rows and seeds S_0 with the EQUALLY WEIGHTED "
            "sample covariance of the oldest cov_min_periods rows, decayed by lambda^k. The seed "
            "block is therefore a flat slab of old data the recursion cannot forget inside the "
            "window, and the shorter the requested halflife the smaller that slab -- but it never "
            "vanishes. The sweep that set overlay policy simulated an untruncated recursion, so "
            "its halflife ladder and this estimator's memory are different quantities."
        ),
        "sleeves": sleeves,
        "the_headline": (
            "The WINDOW bounds the memory, so the halflife is faithful below it and truncated "
            f"above it. On the crypto H1 sleeve the 720-bar window is 30 days: a 7-day request "
            f"delivers {crypto_7['median_weight_age_days']:.1f} days and a 14-day request "
            f"{crypto_14['median_weight_age_days']:.1f}, while a 30-day request delivers "
            f"{crypto_30['median_weight_age_days']:.1f} and a 720-day request "
            f"{crypto_720['median_weight_age_days']:.1f}. The legacy setting is 30 days requested "
            "against 22 days of memory. On the equity D1 sleeve the same 720-bar window is 720 "
            "SESSIONS, so the parameter is faithful across the whole practical range and only the "
            "legacy 720-day setting is truncated, to 529 days."
        ),
        "correction_2026_08_21": (
            "An earlier revision of this analysis sampled only 21 days and up, found every result "
            "in a 20-25 day band, and concluded the parameter was 'nearly inert' on crypto with "
            "cov_window_bars as the only lever. That was wrong and is withdrawn. The band is the "
            "window, not the parameter: below 30 days the halflife is honoured almost exactly "
            "(3d -> 3.0d, 7d -> 7.0d, 14d -> 14.0d). Reading the shape of a sampled range as a "
            "property of the mechanism is the error, and the ladder now spans both sides of the "
            "window so it cannot recur."
        ),
        "which_lever_to_use_for_SHORT_memory": (
            "Both routes reach short memory and they are not equivalent. Halflife 7 days at the "
            "production 720-bar window gives 7.0 days of memory on an effective sample of ~475 "
            "rows; shortening the window to 240 bars gives ~8 days of memory on ~107 rows. The "
            "HALFLIFE route preserves roughly four times the effective sample for comparable "
            "memory, which also keeps ledoit_wolf_cc's T=720 approximation far closer to valid. "
            "If the drawdown study's finding holds -- that shorter covariance memory reduces "
            "expected maximum drawdown -- the halflife is the instrument, and it has to be asked "
            "for BELOW the window rather than at 21 days where truncation has already started."
        ),
        "ledoit_wolf_intensity_mismatch": {
            "site": "src/alphaforge/portfolio/strategy.py, the ledoit_wolf_cc call",
            "description": (
                "ledoit_wolf_cc computes its shrinkage intensity delta* with T = the number of "
                "rows passed, and production passes the full unweighted 720-row window while the "
                "matrix being shrunk is the EWMA. That approximation is documented and was "
                "conservative while the EWMA's effective sample EXCEEDED 720. It stops being "
                "conservative at a short halflife."
            ),
            "effective_sample_by_request": {
                sleeve: {
                    f"{row['halflife_days']:.0f}d": row["effective_sample_rows"]
                    for row in data["by_requested_days"]
                }
                for sleeve, data in sleeves.items()
            },
            "status": "OPEN — flagged, not fixed; no study has measured it",
        },
        "what_this_does_not_say": (
            "It does not say which halflife is right. It says what the estimator DOES with each "
            "one, which is the mapping a halflife decision needs and did not have. Choosing a "
            "value still requires a drawdown study run through this estimator rather than through "
            "an untruncated simulation of it."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    for sleeve, data in sleeves.items():
        print(f"\n  {sleeve}  ({data['bars_per_day']:.0f} bars/day, window {WINDOW_BARS} bars)")
        print(f"    {'requested':>10} {'seed wt':>9} {'eff. sample':>12} {'ACTUAL memory':>15}")
        for row in data["by_requested_days"]:
            print(f"    {row['halflife_days']:>8.0f}d {row['seed_block_weight']:>9.1%} "
                  f"{row['effective_sample_rows']:>12.1f} "
                  f"{row['median_weight_age_days']:>13.1f}d")
        legacy = data["legacy_setting"]
        print(f"    legacy 720 bars = {legacy['means_days']:.0f}d requested -> "
              f"{legacy['median_weight_age_days']:.1f}d actual")
    print(f"\n  {result['the_headline']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
