# Lane contract: Codex and Claude on ALPHAC

Two agents are working the same repository at the same time. This file is the split, the file
boundaries, and the two places the lanes have to meet. Written 2026-08-17.

## The split, by demonstrated strength

**Codex holds the execution-realism and domain-primitive lane.** It has shipped point-in-time
dated-futures lifecycle (contracts, session roll deadlines, price limits, variation margin) and
options lifecycle (terms, quotes, official settlements, cash/physical delivery, expiry lapse,
observed assignment), both classified `DOMAIN_PRIMITIVES_ONLY`, byte-identical across ALPHAC and
both sites, strict-mypy clean, with fail-closed edge cases and zero hypotheses consumed. That is
the work this repository most needs done exhaustively and deterministically, and it is the lane
where an error is caught by a type or a hash rather than by judgement.

**Claude holds the portfolio-mathematics and statistical-validity lane.** Frontier arithmetic,
deflation and multiple-testing design, correlation as an optimization objective rather than a
ceiling, vol-target overlay calibration, drawdown budgeting, admission-contract design, and
candidate generation for negatively correlated mechanisms.

Neither lane opens a holdout or spends a hypothesis identity without the budget question below
being settled first.

## File boundaries

| Lane | Owns |
|---|---|
| Codex | `src/alphaforge/execution/**`, `src/alphaforge/data/**`, `docs/research/*_FOUNDATION.md`, `docs/research/EXECUTION_REALISM.md`, the site bundles |
| Claude | `src/alphaforge/validation/**`, `src/alphaforge/portfolio/**`, `scripts/analyze_*.py`, `docs/design/FRONTIER_*`, `docs/design/LANE_CONTRACT_*`, `artifacts/analysis/**`, `config/sleeve_admission_contract*.json` |
| Owner only | `config/trial_accounting.json` (budget), promoting any `*_v5_proposed.json` to live |

Anything not listed: claim it in this file before editing it.

## Seam 1 — the overlay halflife is a joint answer

[`docs/design/FRONTIER_14_ADMISSION_V5.md`](FRONTIER_14_ADMISSION_V5.md) establishes that the 11%
drawdown objective is held by the vol-target overlay rather than by any correlation ceiling, and
that reaching it requires shortening the covariance halflife from production's **720** to **21**.
At 720 the book takes a 14.2% expected maximum drawdown at the permitted stressed correlation; at
21 it takes 10.2%.

That sweep charges **nothing** for the leverage turnover a short halflife causes. Claude's half of
the round-trip is now delivered — `seam_1_overlay_turnover_for_execution_costing` in
[`artifacts/analysis/frontier_14/result.json`](../../artifacts/analysis/frontier_14/result.json)
gives gross notional traded per year, as a fraction of equity, for every halflife and stress level:

| covariance halflife | turnover / year | E[MDD] at stressed rho 0.50 |
|---|---|---|
| 720 (today) | 0.15x | 14.2% |
| 252 | 0.17x | 14.1% |
| 126 | 0.24x | 13.0% |
| 63 | 0.33x | 11.6% |
| **21** | **0.60x** | **10.2%** |

So the change costs roughly **0.45x of equity in extra gross turnover per year**. At a 10bp
round-trip that is about 4.5bp of annual drag against a 4-percentage-point drawdown reduction, and
it stays affordable even at implausibly high cost assumptions. That is an argument, not a
measurement.

- **Claude → Codex:** ✅ delivered — the turnover series above.
- **Codex → Claude:** annualized cost in bps of that turnover under the realized execution model,
  including the partial-fill, spread and impact terms the primitives now support.
- **Joint:** the halflife that maximizes net Sharpe subject to expected max drawdown ≤ 11%.

Until that round-trip closes, 21 stands as provisional. If the costing shows 21 is unaffordable,
the honest response is to tighten `stressed_pairwise_correlation_max` instead, not to accept a
higher drawdown quietly.

## Seam 1b — an open defect on the same path, in Claude's lane

`BlendStrategy._realized_vol_ann` (`strategy.py:609`) measures the EWMA vol of `_equity_hist`,
which is appended **post-overlay** (`strategy.py:377`), while the ex-ante leg it is `max()`'d
against is computed from **pre-overlay** optimizer weights (`strategy.py:539`). The two are never
on the same scale: below 1x leverage the realized leg is shrunk and loses the comparison, above 1x
it is inflated and the overlay double-counts its own leverage. In the simulated book (~0.5x) the
realized leg is the binding term on **0.02%** of days as shipped, against **81.8%** when placed on
the same scale. Whether each *deployed* sleeve sits in that regime is unmeasured — logging `s`,
`ex_ante` and `realized` per rebalance settles it cheaply and is the first follow-up.

Since the covariance leg is slow (720) and the realized leg is fast (240), the practical effect is
that the book's fast regime detector never fires. Cost: **+0.6 to +2.2 percentage points** of
expected maximum drawdown, worse the more severe the stress.

`tests/unit/test_overlay.py::test_realized_vol_dominates_when_larger` passes throughout — it calls
`vol_target()` directly with a large realized value, pinning the function's intention rather than
the value the caller supplies.

**Status: OPEN, fix not applied.** This is a live sizing path on a deployed strategy and needs an
explicit owner decision before it ships. Codex should not route around it or fix it independently;
if execution work touches sizing, flag it here first.

## Seam 2 — the primitives are the unlock for the sleeves that matter

The frontier result is that reaching 2.0–2.5 at fourteen sleeves requires **negative** average
pairwise correlation (−0.002 for 2.0, −0.029 for 2.5, against a PSD floor of −0.077). Merely
uncorrelated is not sufficient. Negatively correlated return sources are disproportionately convex
— they are long optionality, dispersion, or supply-constraint mechanisms — and in this repository
those are exactly the families sitting `DATA_GATED` on missing primitives.

This makes the execution-primitive lane the critical path for the portfolio objective, not a
parallel nicety:

| Primitive | Unlocks | Why it matters to rho_bar < 0 |
|---|---|---|
| Options surface, settlement, assignment | options dispersion | the canonical convexity sleeve; long-gamma legs are structurally negative-beta to the carry and trend sleeves already in the book |
| Borrow availability, locates, recalls, fees | securities-lending supply | supply constraint binds hardest when the book's existing sleeves are stressed |
| Dated futures, rolls, limits, margin | electricity load/weather, commodity carry hedging | physical-constraint mechanisms with no shared driver with equity momentum |

**Recommended reprioritization:** finish the options surface ahead of the borrow lifecycle. Options
dispersion is the single highest-value unlock for a negative-correlation book, and borrow
availability gates a mechanism whose expected standalone Sharpe is lower.

## A pattern both lanes should adopt

The v5 contract as first drafted declared eight new thresholds and `evaluate_sleeve_evidence` read
one of them. Seven gates would have been decorative — stricter on paper, byte-identical in
behaviour. Codex's persisted-contract tests are the same shape of artefact and worth checking
against the same question.

The guard is `tests/unit/test_admission_contract_is_fully_enforced.py`: it swaps a **recording
mapping** in for the contract's `thresholds` and asserts every declared key was actually fetched
during a real evaluation. It records fetches rather than grepping for names, globs every contract
file, and carries both a can-this-check-fail test and a test that the glob matched anything at all.
Gates are declare-to-enforce through module-level registries, and
`evidence_checks_per_candidate` is derived rather than hand-maintained — which immediately caught
the v5 draft claiming 82 checks when it performs 83.

Generalised: **a config-declared rule needs a test that the code reads it, not a test that the code
would behave correctly if it did.**

## The blocking owner decision

`config/trial_accounting.json` reports 162 observed hypothesis identities against a fixed budget of
160, `research_status = PAUSED_BUDGET_REVIEW`. New return-hypothesis registration is
machine-blocked. At the measured 6.5% hit rate, ten further sleeves imply roughly 150 more trials,
and every one of them raises the book's own deflation hurdle under the proposed book-level DSR gate.

Both lanes can proceed on engineering, data lineage, execution and publication work indefinitely.
Neither can produce a fourteenth sleeve until that budget is re-authorized with the arithmetic
stated. Do not route around it.
