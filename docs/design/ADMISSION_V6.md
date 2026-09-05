# ALPHAC sleeve-admission contract v6

**Status:** superseded by v7 on 2026-08-23. Its exact bytes remain at
`config/archive/sleeve_admission_contract_v6_superseded.json`; it governed the 228-identity legacy
epoch, which was retired without regrading. This document is historical evidence, not current law.

**Builder:** `scripts/build_admission_contract_v6.py` — every figure in `frontier_arithmetic` is
derived from the governing identity at build time, not typed. Reads no data, runs no backtest,
spends no hypothesis identity.

---

## 1. The defect that motivated v6: three floors that could not all be met

v4 declared, in the same `thresholds` block:

```
net_sharpe_min             0.40
newey_west_t_min           2.00
minimum_oos_observations    252
```

A t-statistic on a mean return is approximately `Sharpe × √years`. So a candidate sitting exactly
on the declared Sharpe floor, measured over exactly the minimum sample the contract demands,
attains at most `0.40 × √1 = 0.40`. The declared t floor is **2.0**. To reach it at Sharpe 0.40 a
candidate needs **25 years** of out-of-sample data; at the declared 252-observation minimum the
pair demands a standalone Sharpe of **2.0 outright**, five times the floor a reader of the config
would see.

The consequence is not that v4 was strict. It is that **the Sharpe floor was decoration**. The
t floor was the real gate, it was invisible as such, and nothing in the sleeve atlas was ever
going to pass it.

The v5 proposal made this worse in the course of trying to fix something else. It correctly
lowered `net_sharpe_min` to 0.15 — a standalone Sharpe floor is the wrong instrument when
correlation binds — but left `newey_west_t_min` at 2.0, raising the hidden requirement from 25
years to **178 years**.

### The fix is structural, not a number

`load_admission_contract` now refuses to load any contract whose three significance floors cannot
all be satisfied at once, and names the implied sample length in the error. A contract that cannot
be satisfied is not a strict contract, it is a broken one, and it should fail before it is ever
used to judge anything. Both superseded contracts are refused by it today, with their real cost
printed — that is pinned in `tests/unit/test_admission_significance_floors.py`.

This is the same lesson this repository has now learned in several places, stated once more: **a
requirement nobody can satisfy is not a requirement.** The mirror also holds — a gate that cannot
fire is not a gate — which is why every new gate below ships with a mutation that must fail.

---

## 2. What replaced the standalone significance bar

| threshold | v4 | v6 | role |
|---|---|---|---|
| `net_sharpe_min` | 0.40 | **0.15** | screen, not decision |
| `newey_west_t_min` | 2.00 | **0.25** | sign gate |
| `newey_west_t_ratio_min` | — | **0.60** | autocorrelation-inflation gate |
| `book_sharpe_delta_lower_95_min_exclusive` | — | **0.0** | the decision |

**Why a standalone Sharpe bar is the wrong instrument.** When average pairwise correlation is the
binding constraint, standalone Sharpe does not rank a candidate's portfolio value. A Sharpe 0.25
sleeve at correlation −0.05 beats a Sharpe 0.60 sleeve at +0.30. A floor on the standalone number
therefore rejects, preferentially, the candidates the objective most needs.

**What actually decides admission** is the bootstrap *lower* bound on the book-Sharpe improvement,
which prices edge and correlation together and is strictly harder to game than either input alone.

**What the t floor is now for.** Excluding wrong-signed and indistinguishable-from-zero results.
0.25 is set immediately below what a floor-Sharpe candidate attains over the minimum sample
(`0.15 × √3 = 0.2598`), so it constrains without silently replacing the Sharpe floor.

**The ratio gate is not another significance bar.** A Newey-West correction accounts for
autocorrelation. A sleeve priced off stale or appraised marks — catastrophe bonds, municipal
basis, freight, anything thinly traded, which is *precisely* where the anti-correlated sources
live — shows an inflated naive Sharpe because its measured volatility is smoothed. The tell is not
a low t. It is a t far **below** the one its own reported Sharpe implies. Gating the ratio catches
smoothed pricing at any Sharpe level; a flat floor gets both cases backwards, waving through a
stale-priced sleeve with a high headline number and rejecting an honest one with a modest one.

---

## 3. Correlation: the one gate that tightened

`average_pairwise_correlation_max`: **0.15 → 0.00**, a sevenfold tightening.

At 0.15 the book's ceiling `s̄/√ρ̄` is 1.37 at measured quality — **below the objective at every
plausible per-sleeve quality**. `artifacts/analysis/breadth_acquisition/result.json` had recorded
`gate_permits_objective: false` internally since 2026-08-16. The site published the objective and
the gate side by side and never published the relationship between them.

When the instruction is "the gates may be too high, adjust them so we can reach the target", the
arithmetic answer for correlation is the **opposite** of loosening, and that is worth saying out
loud rather than quietly doing the other three.

### And a new gate on how well the correlation is known

`average_pairwise_correlation_upper_95_max`: **0.10** (new), alongside
`minimum_oos_observations`: **252 → 756**.

The average pairwise correlation is the number the entire objective turns on. At 252 observations
its sampling error is about **0.063** — roughly twice the size of the −0.03 effect that separates a
reachable book from an unreachable one. Gating a point estimate the sample cannot resolve is not a
strict gate; it is a coin flip wearing one. So v6 gates the **bound** as well as the point, and
requires three years rather than one so the bound can be tight enough to mean something.

`alphaforge.validation.diversification` gained `average_pairwise_correlation_upper_95`, computed by
resampling **every sleeve on the same drawn index set** within each bootstrap sample. Averaging the
per-pair upper bounds would be a different and wrong quantity — the mean of upper bounds is the
upper bound of no statistic at all, and because averaging reduces variance it is systematically too
wide. Two algebraic identity tests fail if anyone later replaces the shared draw with independent
per-pair draws.

---

## 4. Capacity: a floor written for a fund that does not exist yet

`capacity_usd_min`: **5,000,000 → 500,000**.

$5M per sleeve implies a **$70M book** at fourteen sleeves. The book does not run that. Worse, the
floor did not reject candidates uniformly — the return sources most likely to be genuinely
anti-correlated with a momentum-and-carry book (catastrophe bonds, municipal basis, freight,
power, sovereign dislocation) are **structurally thin**. The capacity floor was therefore selecting
*against* the diversification the objective depends on. That is the opposite of what a capacity
gate is for.

Nothing else about capacity relaxed. The capacity **curve**, its monotonicity reconciliation
(Sharpe must decay and cost must rise with capital) and the stressed fill-ratio floor of 0.95 are
unchanged, and a candidate must still reconcile its reported capacity to its own curve.

`capacity_policy.review_trigger` records when it goes back up: when deployed capital per sleeve
exceeds one fifth of the floor. Capacity is a property of the strategy; the *floor* is a property
of the book, and a floor that outruns the book costs edge for nothing.

---

## 5. Deflation, corrected in scope

The per-sleeve `deflated_sharpe_min` gate is **removed** (`null`), while
`deflated_sharpe_must_be_measured` is mandatory. A 0.95 DSR gate at the 756-observation minimum
requires annualized Sharpe 1.184 even with only two family trials—about eight times the declared
0.15 net-Sharpe screen. It made that screen decorative and demanded of a diversifying increment a
standalone result that none of the 33 restated legacy variants achieved. Family-scoped DSR remains
public evidence; omission fails closed.

`book_deflated_sharpe_min` **0.95** is new and strictly additional: the published claim is the
book's, so the **book** carries the full union. This is a correction, not a loosening; it is also
the only change here that makes something harder at the level where the public claim is made.

The v7 power audit subsequently showed that this threshold was a portfolio-maturity standard
misapplied to every incremental decision. V7 preserves mandatory public book DSR measurement and
moves the 0.95 threshold to forward-evidence maturity. Historical v6 verdicts are unchanged.

---

## 6. What v6 does *not* buy, published in the contract itself

`frontier_arithmetic` is derived at build time and states plainly:

- At the gate in force (ρ̄ = 0.00), fourteen sleeves at measured traded-basis quality
  (s̄ = 0.529) reach **1.979**.
- `gate_permits_objective_floor` = **false**.

Tightening the ceiling removed a ceiling that sat below the objective. It did not, on its own,
deliver the objective. The remaining distance must be bought with per-sleeve quality, genuinely
negative correlation, or both:

- at the gate exactly, the current 2.25–3.0 in-sample objective band needs
  **s̄ ≥ 0.601–0.802**;
- at today's traded-basis quality, 2.25 needs **ρ̄ ≤ −0.0174** and 3.0 needs
  **ρ̄ ≤ −0.0434**; and
- the PSD floor at fourteen sleeves is **−0.0769**, so both endpoints remain arithmetically
  available, but neither is delivered by the gate alone.

`tests/unit/test_admission_frontier_arithmetic.py` re-derives every one of those figures from the
identity independently of the builder, and asserts the published verdict follows from the figures
beside it **either way**, so the guard keeps telling the truth when quality rises and the verdict
flips to true.

---

## 7. Drawdown

`book_expected_max_drawdown_max` **0.11**, with the overlay mandatory and its halflives gated
(`covariance_halflife_days_max` 21, `realized_vol_halflife_days_max` 240,
`realized_vol_leg_must_be_unlevered` true).

The realized-leg scale defect is **resolved in production**: the leg is de-levered per bar before
comparison, and `tests/unit/test_overlay_realized_leg_scale.py` pins the caller's value rather than
the function's intention. The covariance halflife is **still the legacy 720 bars**, so the second
half of the drawdown result is not shipped — the measured study holds expected maximum drawdown at
10.2% only with **both** changes, and neither alone suffices.

It was briefly shipped, on 2026-08-21, and reverted the same day after an adversarial audit. Three
reasons, all recorded in the contract's `overlay_policy.why_the_halflife_change_was_reverted`:

1. **It was a trade, not a configuration edit.** No call site passes the argument — the crypto
   loop, the AlphaTrend gauntlet and the AlphaMax walk-forward all take the default — the
   walk-forwards are regenerated by the daily ticks, and `live_cycle.py` submits the last leg's
   weights straight to the broker. The commit that made the change said "nothing was re-run".
   That was wrong in the direction that mattered.
2. **The cost basis did not correspond.** The sweep is a *daily* simulation, so its `cov=720` cell
   is a 720-**day** halflife. The live crypto sleeve ran 720 **bars** on H1 — 30 days. The
   published 3.98pp therefore priced a 2.86-year-to-21-day move, not the one that would happen.
3. **The live estimator is not the simulated one.** `ewma_cov` is windowed at 720 bars and seeds
   from an equally weighted block of the oldest 240 rows, so a swept halflife does not map
   one-to-one onto its effective memory.

The unit machinery stands and is the part worth keeping: `cov_halflife_days` still converts
per calendar, and passing it explicitly at a profile that has measured it is how this change
should land.

⚠️ **The realized leg is still a bar count.** `realized_vol_halflife_bars = 240` is used verbatim,
with no calendar conversion, so on the crypto H1 sleeve it is **10 days** — while this contract
names its threshold `realized_vol_halflife_days_max: 240`. Only the covariance leg was converted.
An earlier revision of the contract asserted a per-calendar conversion for both; that was false
for this one, and it now says so.

Two figures are always published together, because only one of them is gated: 11% is reachable as
an **expected** maximum drawdown. No tested configuration held the **95th percentile** at or under
11%; the best was 13.8%.
