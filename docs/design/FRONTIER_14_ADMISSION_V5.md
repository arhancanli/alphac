# The 14-sleeve frontier and the admission contract it implies (proposed v5)

Status: **HISTORICAL PROPOSAL — superseded, not in force.** The governing contract is now
[`config/sleeve_admission_contract.json`](../../config/sleeve_admission_contract.json) (v6), with
an honest forward Sharpe target of 1.5 and a 2.25–3.0 in-sample support band. This document is
retained as the arithmetic and review trail that led to the replacement.
The proposed replacement is
[`config/sleeve_admission_contract_v5_proposed.json`](../../config/sleeve_admission_contract_v5_proposed.json).
It loads through the real loader and every threshold it declares is enforced by
`evaluate_sleeve_evidence`, so promoting it is a one-line config swap rather than a code change.
Every number below is reproduced by [`scripts/analyze_frontier_14.py`](../../scripts/analyze_frontier_14.py)
into [`artifacts/analysis/frontier_14/result.json`](../../artifacts/analysis/frontier_14/result.json).
The script reads no market data, opens no holdout and spends no hypothesis identity.

## Why the contract has to change at all

The objective is an honest out-of-sample book Sharpe of 2.0–2.5 across at most fourteen sleeves
at approximately 11% maximum drawdown. The current contract cannot deliver that objective. Not
"has not yet" — cannot, as arithmetic, at any sleeve count, with any amount of research effort.

Equal-risk book Sharpe is

```
S_book = s_bar · sqrt(N) / sqrt(1 + (N-1)·rho_bar)      ->   s_bar / sqrt(rho_bar)   as N -> inf
```

The live gate permits `average_pairwise_correlation_max = 0.15`. A book that sits exactly at that
permitted ceiling is capped at:

| per-sleeve Sharpe | ceiling at rho_bar = 0.15 | reaches 2.0? |
|---|---|---|
| 0.464 (measured) | 1.20 | no |
| 0.529 (3-sleeve book) | 1.37 | no |
| 0.700 | 1.81 | no |
| 0.800 | 2.07 | yes |

At measured sleeve quality the live gate caps the book at **1.37**. A candidate can pass every one
of the seventy-five evidence checks, and the resulting book is still barred from the objective.
The gate is not merely permissive; it is permissive of outcomes the program has already ruled out.

## The correction is tighter, not looser

The instinct when a target is missed is to relax the tests. Here the arithmetic runs the other way.
At N = 14 the correlation the book *must* achieve is:

| per-sleeve Sharpe | rho_bar for S = 2.0 | rho_bar for S = 2.5 |
|---|---|---|
| 0.464 | −0.0190 | −0.0398 |
| 0.529 | −0.0016 | −0.0287 |
| 0.600 | +0.0200 | −0.0149 |
| 0.700 | +0.0550 | +0.0075 |

The required correlation is **negative** across the whole plausible range of sleeve quality. The
gate must therefore move from +0.15 to approximately **0.00**, a sevenfold tightening, before the
objective is even inside the feasible set.

This regime was ruled out of the earlier analysis for a correct reason that no longer applies.
[`scripts/analyze_feasible_frontier.py`](../../scripts/analyze_feasible_frontier.py) was written
against the previous framing of the goal — fifty to two hundred sleeves — and observed that the
positive-semidefinite floor on equal average correlation, −1/(N−1), collapses to −0.004 at N = 250,
making negative rho_bar a "3–4 sleeve luxury". At the restated count of fourteen the floor is
**−0.0769**. The requirement of −0.03 sits comfortably inside it. Restating the goal from 250
sleeves to 14 did not merely shrink the program; it reopened the only region of the frontier that
reaches the target.

Two of the candidates already killed this campaign measured average correlations of −0.064 and
+0.0002 against the book. Negatively correlated return streams are findable. What neither had was
alpha. That, and not correlation, is where the remaining research risk actually sits.

## The drawdown objective is bought by the overlay, not by a correlation bar

Maximum drawdown scales with the volatility a book *realizes*, and a book levered to a calm-regime
vol target realizes a multiple of that target when correlations converge. Simulating fourteen
equal-weight sleeves through a two-state correlation regime (12% of days in stress, mean run 40
days, 4,000 paths, 5 years, 10% vol target), driving the **production** overlay:

| stressed rho | overlay off | as shipped today | scale defect fixed | fixed + cov halflife 21 |
|---|---|---|---|---|
| 0.10 | E 11.7% / p95 19.5% | E 10.9% / p95 17.9% | E 10.3% / p95 16.7% | **E 9.0%** / p95 13.8% |
| 0.20 | E 14.3% / p95 24.4% | E 12.8% / p95 21.4% | E 11.7% / p95 19.2% | **E 9.4%** / p95 14.6% |
| 0.30 | E 16.5% / p95 29.0% | E 14.1% / p95 24.0% | E 12.7% / p95 20.9% | **E 9.7%** / p95 15.3% |
| 0.50 | E 20.2% / p95 35.5% | E 16.4% / p95 28.2% | E 14.2% / p95 24.2% | **E 10.2%** / p95 16.7% |

"As shipped today" is production's own configuration: covariance halflife 720 bars, realized-vol
halflife 240 bars (`strategy.py:159,161`), with the realized leg measured as production measures
it — see the defect below.

Three things follow.

**The overlay is doing real work but not enough of it.** As shipped it holds expected drawdown at
or under 11% only in the mildest stress bucket. At stressed rho of 0.50 — which the live contract
permits — expected drawdown is 16.4%, half again over the objective.

**The 11% objective is reachable, but only with both fixes.** Correcting the realized-leg scale
defect and shortening the covariance halflife from 720 to 21 holds expected maximum drawdown at or
under 10.2% across every stress level tested, including the permitted ceiling. Neither change alone
is sufficient.

**11% holds as an expected maximum drawdown and does not hold as a 95th-percentile bound.** Zero of
twenty-eight configurations held p95 at or under 11%; the best is 13.8%. The program document
frames 11% as "approximately … as a research objective", which the expected value satisfies and the
tail does not. That distinction must be published, not smoothed over.

Consequently the stressed-correlation ceiling of 0.50 does **not** need to tighten — but only
because the overlay, correctly configured, is doing the work. The overlay therefore stops being
optional. A contract that permits stressed rho of 0.50 while leaving vol targeting unspecified is
silently permitting a 20% expected drawdown.

## A defect on the same path: the overlay's fast regime detector never fires

The overlay computes `sigma_hat = max(ex_ante, realized)`. The two legs are separate estimators
with separate halflives — covariance at 720 bars, realized vol at 240 — and that asymmetry is the
entire point: the covariance leg is slow, the realized leg is fast, so the realized leg is the
book's quick regime detector.

> **STATUS 2026-08-18 — FIXED IN PRODUCTION.** Everything in this section described the shipped
> code when it was written and is retained as the diagnosis, not as current state.
> `_realized_vol_ann` now divides each observed bar return by the overlay scale that was in force
> for that bar before taking the EWMA, which is the same quantity the sweep's `leg=unlevered` arm
> measured. A `_scale_hist` list is appended alongside `_equity_hist`, index-aligned by
> construction. The follow-up this section asks for below is also done, and better than proposed:
> rather than a log to be read by hand, `BlendStrategy.counters` now reports `realized_leg_bound`,
> so the bind rate is a standing observable of the live book. Regression tests are in
> `tests/unit/test_overlay_realized_leg_scale.py`; note they live outside `test_overlay.py`
> deliberately, because the existing `test_realized_vol_dominates_when_larger` calls `vol_target()`
> directly and passed straight through this defect.
>
> Two things this does NOT change. The ladder's gross multiplier and the per-name `w_max` clip
> also move the traded book and are still not de-levered — both are no-ops in the NORMAL regime
> that dominates the sample, and neither was in the measured arm. And the drawdown objective still
> needs the covariance halflife decision as well: this study's own result is that **11% requires
> both**, and neither alone suffices. That half remains open pending the execution-side cost model
> for the turnover a shorter halflife implies.

It cannot fire. `BlendStrategy._realized_vol_ann` (`strategy.py:609`) measures the EWMA vol of
`_equity_hist`, which is appended post-overlay at `strategy.py:377` — the **levered** account
equity curve. The ex-ante leg is computed from `result.weights` at `strategy.py:539` — the
**unlevered** optimizer output.

The two are therefore never on the same scale. Whenever the applied scale `s` is below 1 the
realized leg is shrunk by that factor and loses the `max()`; whenever `s` is above 1 it is inflated
and the overlay double-counts its own leverage. Only `s = 1` compares like with like. Which regime
a given sleeve sits in is a configuration question this analysis does not settle — the simulated
fourteen-sleeve book runs at about 0.5x, which puts it squarely in the first case, but that figure
is this study's, not a measurement of the deployed sleeves.

Measured over the sweep: the realized leg is the binding term on **0.02%** of days as shipped,
against **81.8%** of days when placed on the same scale as the leg it is compared to. The fast
detector is, for practical purposes, not running.

**Confirming this against the deployed books is the first follow-up**, and it is cheap: log
`s`, `ex_ante` and `realized` per rebalance for each live sleeve and count how often the realized
leg binds. If it binds at a materially non-zero rate somewhere, that sleeve runs near `s = 1` and
the defect is dormant there.

Cost, at production halflives:

| stressed rho | E[MDD] as shipped | E[MDD] if fixed | cost | Sharpe |
|---|---|---|---|---|
| 0.10 | 10.9% | 10.3% | +0.60pp | 2.21 → 2.23 |
| 0.20 | 12.8% | 11.7% | +1.07pp | 2.03 → 2.06 |
| 0.30 | 14.1% | 12.7% | +1.48pp | 1.91 → 1.96 |
| 0.50 | 16.4% | 14.2% | +2.17pp | 1.71 → 1.77 |

`tests/unit/test_overlay.py::test_realized_vol_dominates_when_larger` passes throughout. It calls
`vol_target()` directly with a large realized value, so it pins the function's intention rather
than the value the caller actually supplies — the same shape as the funding-carry defect, where
nine tests pinned an intention and none pinned the path that runs.

**This is a live sizing path and the fix is not applied here.** It changes how a deployed strategy
levers itself and needs an explicit decision before it ships.

### A correction to an earlier revision of this analysis

The first revision of `analyze_frontier_14.py` gave both overlay legs the same halflife. EWMA is
linear, so `w' EWMA(r r') w == EWMA((w'r)^2)` exactly: the two legs were the same number, the arms
came out bit-identical (max difference 2.2e-16), and the "realized leg binds 32% of days" figure it
produced was floating-point tie-breaking rather than signal. It also implicitly assumed a
covariance halflife of 10–63 days, which production does not use, and so overstated how well the
overlay performs as shipped. The separate production halflives are the correction, and every number
in this document comes from the corrected run.

### What this simulation does not price

Leverage changes cost money, and the sweep charges nothing for them. Moving the covariance halflife
from 720 to 21 trades the book's gross exposure very much more often, so the measured gain is an
upper bound on the real one and could be partly or wholly eaten by cost. Choosing the halflife is a
joint question for this analysis and the execution-cost model, and it is the explicit hand-off
point to the execution-realism lane.

That makes the halflife the one v5 threshold whose value is provisional. 21 is what the uncosted
sweep requires to hold the 11% objective at the permitted stressed correlation; if the costing
comes back and 21 is unaffordable, the honest response is to tighten
`stressed_pairwise_correlation_max` instead, not to quietly accept a higher drawdown.

## Proposed v5 threshold deltas

Nine entries in `thresholds` change. Every one of them is enforced by `evaluate_sleeve_evidence`;
nothing that is not a gate appears in this table.

| threshold | v4 | v5 | direction | why |
|---|---|---|---|---|
| `average_pairwise_correlation_max` | +0.15 | **0.00** | tighter 7x | +0.15 caps the book at 1.37; 0.00 is the minimum consistent with S = 2.0 |
| `net_sharpe_min` | 0.40 | **0.15** | looser | see below — replaced in force, not removed |
| `stressed_sharpe_min` | 0.40 | **0.15** | looser | same reasoning, applied to the stressed window |
| `book_sharpe_delta_lower_95_min_exclusive` | — | **0.0** | new, stricter | the bootstrap lower bound on book contribution must clear zero, not the point estimate |
| `book_deflated_sharpe_min` | — | **0.95** | new, stricter | deflated against the full union; the headline claim is the book's, so the book carries it |
| `book_expected_max_drawdown_max` | — | **0.11** | new | the drawdown objective, gated at the statistic that can actually hold it |
| `covariance_halflife_days_max` | — | **21** | new | 720 (production today) holds 16.4% at permitted stressed rho; 21 holds 10.2%. Provisional pending execution costing |
| `realized_vol_halflife_days_max` | — | **240** | new | production's value and the one every sweep cell used; bounds regression, not design |
| `realized_vol_leg_must_be_unlevered` | — | **true** | new | ~~the leg is measured on levered equity today and therefore binds on 0.02% of days instead of 81.8%~~ **FIXED 2026-08-18**; the bar this row proposed is now satisfied by the shipped code, and `counters["realized_leg_bound"]` reports the live rate |

`stressed_pairwise_correlation_max` stays at 0.50, survivable *given* the overlay rather than on its
own. `deflated_sharpe_min` keeps its 0.95 value but changes selection unit — see below.

Three things that are **not** gates live outside `thresholds`, deliberately:

| entry | where | value |
|---|---|---|
| `average_pairwise_correlation_objective` | `objective` | −0.03 — the correlation at which 14 sleeves reach 2.5. An aim, not a bar. |
| `portfolio_max_drawdown_statistic` / `..._p95_must_be_published` | `objective` | gate on expected max drawdown; publish the p95 unsmoothed |
| `mandatory_vol_target_overlay`, `sigma_hat_rule`, `known_defect` | `overlay_policy` | the overlay stops being optional, and the open defect is recorded in the contract itself |
| `per_sleeve_selection_unit` / `book_selection_unit` | `deflation_policy` | family for the leg, full union for the book |

### On lowering `net_sharpe_min` from 0.40 to 0.15

This is the one bar that gets easier, and it is the one that most needs justifying.

A standalone Sharpe floor is the wrong instrument for a book whose binding constraint is
correlation. A sleeve at Sharpe 0.25 with correlation −0.05 to the book contributes more to
`S_book` than a sleeve at Sharpe 0.60 with correlation +0.30, and the v4 contract admits the second
and rejects the first. Since −0.03 average correlation is now a *requirement* rather than a bonus,
a floor that discards the diversifiers is directly adverse to the objective.

It is not removed. It is replaced by a stricter test of the thing actually wanted: the 95%
bootstrap lower bound on the candidate's contribution to book Sharpe must exceed zero. v4 gated the
point estimate; v5 gates the confidence bound. The residual 0.15 floor exists only to reject
streams with no economic content at all, and `newey_west_t_min = 2.0` is unchanged.

### On deflating per-sleeve Sharpe against family rather than union trials

The deflated Sharpe ratio deflates for the number of trials **the selection was made from**. v4
deflates every candidate against the union of all 162 hypothesis identities ever run, across all
families. A freshly pre-registered, direction-locked, parameter-locked candidate in a new economic
family was not selected from those 162; charging it their multiplicity is not conservatism, it is a
mis-specified estimator, and it is the reason all 33 restated legacy variants fail simultaneously.

v5 splits the claim from the leg. Each sleeve is deflated against its own family's trial count.
The **book** — which is the claim actually published — is deflated against the complete union,
which grows with every future trial. Net effect on the headline number: strictly harder, because v4
has no book-level deflation gate at all.

One limit, stated rather than glossed: `deflated_sharpe_min` gates a number the candidate
*supplies* (`statistics.deflated_sharpe`). The contract cannot verify which selection unit produced
it. `deflation_policy` records the required unit and `lineage.family_trial_account` names the
family, but honouring it is the producing code's job, and the gate would accept a correctly-shaped
number computed the wrong way. Closing that needs the DSR computation itself to read the family
count and stamp its selection unit into the evidence — which is the natural next task in this lane,
and is exactly the "law the guard cannot see" shape if left undone.

## The first draft of this proposal was itself decorative

Worth recording, because it is the failure mode this repository keeps hitting.

The v5 contract as first written declared eight new thresholds. `evaluate_sleeve_evidence` read
**one** of them. The other seven — book-level DSR, the bootstrap lower bound on book contribution,
the book drawdown gate, both halflife caps, the unlevered-leg flag, and the correlation objective —
would have sat in the JSON looking enforced while gating nothing. Promoting that file would have
produced a contract that was *stricter on paper and identical in behaviour*.

Three things now prevent it:

**`tests/unit/test_admission_contract_is_fully_enforced.py`** substitutes a recording mapping for
the contract's `thresholds` and asserts, against evidence that passes, that every declared key was
actually fetched on the path that runs. It does not grep for key names — a reader constructing keys
dynamically would defeat that — and it covers every `config/sleeve_admission_contract*.json` by
glob, so no future contract can be promoted with decorative thresholds in it. It carries its own
can-this-check-fail test, and a test that the glob matched anything at all, since a glob that
silently matches nothing makes every parametrized case vacuously pass.

**Declare-to-enforce.** The new gates live in `OPTIONAL_NUMERIC_GATES` and `OPTIONAL_BOOLEAN_GATES`
at module level and apply if and only if the contract declares the corresponding threshold. v4 is
unaffected; v5 gets all eight; and a gate cannot be added to the code without a contract declaring
it, nor declared in a contract without the code reading it.

**`evidence_checks_per_candidate` is now derived** from the contract's own contents rather than a
hand-maintained constant, and `load_admission_contract` accepts the v5 schema. That derivation
immediately caught the v5 draft claiming 82 checks when it performs 83.

The correlation objective moved out of `thresholds` entirely and into `objective`, where it
belongs: thresholds are gates, and something that is not enforced must not sit among them wearing a
gate's costume.

## What is still blocked, and by what

Research is machine-paused: `config/trial_accounting.json` records 162 observed hypothesis
identities against a fixed budget of 160, with `research_status = PAUSED_BUDGET_REVIEW`. No
contract revision changes that. At the measured hit rate of 6.5%, ten further sleeves imply on the
order of 150 additional trials, and each one raises the book's own deflation hurdle. Authorizing a
prospective budget — with that arithmetic stated — is an owner decision and a precondition for the
14-sleeve objective, not a consequence of it.

## Claim boundary

Nothing here is evidence for a sleeve, a Sharpe or a drawdown. It is a statement of what the
measured inputs imply about which outcomes remain attainable, and therefore what the admission
contract must require in order not to certify books that cannot reach the stated objective. The
targets remain research objectives. Fourteen sleeves is reached only if ten further identities
independently clear every gate; otherwise the book stays smaller and the measured result is
published as it comes.
