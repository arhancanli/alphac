# ALPHAC forward pre-registration — DRAFT

> **UNSIGNED — REQUIRES OWNER.** This document has no force until the owner signs and publishes
> it. It is deliberately not referenced from canlicapital.com. Drafted 2026-08-21 by the
> autonomous backlog (item A1); publishing it is an irrevocable public commitment and is on the
> owner-blocked list.

---

## 1. Why this document exists

Every backtest this book has produced is deflated to nothing. Per-sleeve DSR is 0.213, 0.052 and
0.000 against a 0.95 gate; **zero of thirty-three restated variants clear it**. That is not a
statement about the strategies — it is a statement about what a backtest selected from 162
hypothesis identities can ever prove. It cannot.

There is exactly one instrument that escapes deflation: a specification **fixed in advance** and
run **forward**. It is N = 1 by construction, so there is no multiplicity to correct for, and the
hurdle collapses to `1.96 / sqrt(T)`:

| forward record | Sharpe required to reject the null |
|---|---|
| 1 year | 1.960 |
| 3 years | 1.132 |
| **5 years** | **0.877** |
| 10 years | 0.620 |

Against a deflated backtest hurdle of **2.44** at the current trial count. That gap — 2.44 against
0.88 — is the entire reason this document matters, and it is available for the price of writing
down what is being run before it runs and then not touching it.

`docs/design/PRE_REGISTRATION.md` §9 already promises this: *"Earn the grade forward: ≥6–12 months
paper-trading the frozen book before any real capital."* What has never existed is an artifact
saying **what** is frozen, **from when**, and **judged how**. Without that, the record accruing
since 2026-08-07 is data. With it, it is a test.

**The clock is the asset.** It cannot be bought, only waited for, and it reset to zero on
2026-08-07 with the v3 re-baseline. It is fourteen days old at the time of drafting.

---

## 2. What is frozen

### 2.1 The book

**ALPHAC Cross-Asset Book**, four sleeves at equal quarters:

| key | sleeve | weight | mechanism |
|---|---|---|---|
| `alphaforge` | AlphaForge | 0.25 | Funding-rate carry, Binance USDT-M perpetuals, market-neutral |
| `alphamax` | AlphaMax | 0.25 | 12-1 cross-sectional momentum, dollar-neutral, survivorship-free |
| `managed_futures` | AlphaTrend | 0.25 | Time-series momentum, 17-market basket, inverse-vol weighted |
| `alphavintage` | AlphaVintage | 0.25 | PIT CPI surprise as a dollar-neutral IWM-minus-SPY size spread |

Plus a **disclosed +10% strategic net-long overlay**, mixed 50/50 BTC/SPY, carried as a separate
labelled line and never blended into the neutral sleeves.

⚠️ **AlphaVintage's inclusion is a known open question, not an oversight.** Its own result artifact
records verdict KILLED, and the production admission evaluator rejects it today
(`artifacts/analysis/admission_dry_run`: book-Sharpe delta −0.0063). It is in the frozen book
because removing it costs **39% more maximum drawdown** and 15% of the diversification ratio
(`artifacts/analysis/book_without_alphavintage`). **If the owner changes this allocation, the test
restarts** — see §6.

### 2.2 The sizing configuration

Bound to fingerprint `sha256:e79dd975…4368901`
(`artifacts/engineering/live_config_fingerprint.json`, declared in
`config/live_change_contract.json`):

```
allocator                    rank
rebalance_bars               24        (daily on 1h bars)
rebalance_anchor             run
cov_window_bars              720
cov_halflife_days            None      -> LEGACY_COV_HALFLIFE_BARS = 720
cov_min_periods              240
realized_vol_halflife_bars   240
cost_frac_oneway             0.001
```

### 2.3 The overlay

Mandatory vol-target overlay (`alphaforge.portfolio.overlay.vol_target`), annualised target
**10%**, `sigma_hat = max(ex_ante, realized)`, realized leg de-levered per bar before comparison.

⚠️ Two known and deliberately unresolved facts, recorded so a later reader is not surprised:
the **covariance halflife is inert above ~14 days on the crypto sleeve** because the 720-bar
window is 30 days there; and `ledoit_wolf_cc` computes its shrinkage with `T = 720` while the
EWMA's effective sample is smaller. Neither is being changed inside this test.

### 2.4 The start date

**2026-08-07**, the v3 re-baseline, when all sleeves moved to fresh $1M paper accounts. The record
before that date belongs to a different specification and is not part of this test.

---

## 3. What is being claimed

**An honest forward Sharpe of 1.5**, net of modelled costs, on the neutral core, with expected
maximum drawdown near 11%.

Stated forward and not in-sample deliberately: this book's own measured backtest-to-forward gap is
**1.5× to 3×** (in-sample equal-risk ≈ 1.04 against an honest forward estimate of 0.3–0.9). A
target quoted in-sample is quoted in the units that flatter.

**This is a target, not a prediction.** The honest expectation at the time of drafting is
materially below it: today's per-sleeve quality (s̄ 0.469) with four sleeves does not produce 1.5,
and nothing in this document asserts that it will.

---

## 4. How it is judged

Measured on the **neutral core** — the +10% strategic tilt is reported separately and excluded
from every figure below, because it buys market participation rather than risk-adjusted quality.

| horizon | PASS | INCONCLUSIVE | FAIL |
|---|---|---|---|
| 1 year | realised Sharpe ≥ 1.960 | between | ≤ 0 |
| 3 years | ≥ 1.132 | between | ≤ 0 |
| 5 years | ≥ 0.877 | between | ≤ 0 |
| 10 years | ≥ 0.620 | between | ≤ 0 |

The PASS thresholds are `1.96/sqrt(T)` — the two-sided 95% rejection of a zero-Sharpe null at
N = 1. **They are not the 1.5 target.** Clearing them means the edge is distinguishable from
luck; reaching 1.5 is a separate and higher bar, and both will be reported.

**INCONCLUSIVE is the expected outcome for years.** It is reported as such and never rounded
toward PASS.

Secondary measures, reported at every horizon and never used to choose anything: realised maximum
drawdown against the 11% expected objective (with the 95th percentile beside it, because no tested
configuration held p95 at or under 11% and the best was 13.8%); realised average pairwise
correlation against the −0.0174 the target implies; per-sleeve contribution; and the gap between
realised and modelled costs.

---

## 5. What would make this dishonest, and is therefore forbidden

- Changing the sleeve set, the weights, the overlay or the sizing configuration and continuing to
  report one continuous record.
- Reporting the record from a start date other than 2026-08-07.
- Reporting the book **with** the strategic tilt as though it were the neutral core.
- Choosing a measurement window after seeing the data.
- Reporting an INCONCLUSIVE result as a PASS.
- Quietly excluding a sleeve that is dragging.

---

## 6. What VOIDS this test

Any of the following ends this record and starts a new one, with the old record kept and published
as ended:

1. **Any change to the frozen configuration in §2.2 or §2.3.** The fingerprint is the arbiter, and
   `scripts/check_live_change_declared.py` blocks the publish when it moves.
2. **Any change to the sleeve set or weights in §2.1** — including withdrawing AlphaVintage.
3. **A gap in the record** exceeding a threshold to be set by item A5, because a discontinuous
   record is not the same experiment either side of the gap.
4. **Any move to real capital**, which changes the execution regime.
5. **Re-baselining the accounts**, as happened on 2026-08-07.

A void is not a failure and is not hidden. The record to that point is published with its end date
and the reason, and a new pre-registration is written.

---

## 7. What this does not claim

It does not claim the strategies work. It does not claim the target will be reached — the honest
expectation is below it. It does not claim paper-traded execution equals real execution: fills are
modelled, borrow is charged at 50bp/yr on the short leg, and market impact is assumed away at this
size on the evidence that median dollar ADV makes it a non-constraint.

It claims exactly one thing: **that this specification was fixed before the record it will be
judged on, so the record cannot be chosen after the fact.**

---

## 8. Signature block

```
UNSIGNED — REQUIRES OWNER

signed_by:
signed_at:
config_fingerprint:  sha256:e79dd9751715c6adc63c7642c18c0b1d075c9d2ca4b2b034f8e2da5764368901
record_start:        2026-08-07
first_judgement:     2027-08-07  (1 year)
```

On signing: commit, anchor into the transparency chain, publish to
`/glassbox/forward_preregistration.json`, and add the horizon dates to the roadmap. Until then it
has no force and is not referenced from the site.
