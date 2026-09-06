# Forward full-evidence reservation v2

**Owner and author:** Arhan Canli  
**Status:** design proposal; not in force; no return authorization  
**Prospective scope:** reservation ordinal 230 or later after explicit promotion  
**Known-result scope:** prohibited

## Purpose

This proposal removes the design gap exposed by `crypto_carry_portable_v1`. That trial froze one
primary path but did not freeze the exact stress, capacity, execution, and book-analysis inputs
needed for admission. The primary result was therefore closed as `INCOMPLETE / NOT ADMITTED`
instead of selecting supplemental assumptions after observing its Sharpe.

Version 2 makes the full evidence graph part of the pre-result reservation. It does not change the
portable-v1 decision and cannot be used to regrade any known result. The machine-readable template
is `config/forward_full_evidence_reservation_v2_template.json`.

## Design constraints

A future reservation must satisfy four constraints before any return engine runs:

1. Every selectable return configuration is a named, counted hypothesis identity.
2. Every non-selectable stress or capacity replay has exact frozen assumptions and must publish.
3. Every book statistic binds the exact existing-book snapshot, candidate weight, alignment, stress
   mask, bootstrap, and overlay specification.
4. The runner withholds all interim outcomes until the complete registered batch finishes or fails.

These constraints separate search from diagnosis. A return configuration that can become the
winner belongs in the identity batch and increases the union trial count. A deterministic scenario
that can only challenge an identity may share its identity only after the trial policy explicitly
defines that class. The diagnostic cannot become a deployable winner, and every registered
diagnostic must be reported.

## Batch accounting and seriality

Probability of backtest overfitting (PBO) requires a matrix with at least two eligible return
columns. A one-identity reservation cannot produce that matrix. The future policy must therefore
support an atomic family batch:

- reserve every identity and exact configuration before the first return;
- charge every column to its family and the complete union;
- forbid adding, removing, or reordering identities after execution starts;
- suppress interim result access to prevent early stopping or post-result mutation;
- produce one permanent packet per identity plus one batch matrix receipt; and
- block any unrelated reservation until every batch packet is complete.

The current serial guard accepts one identity at a time. It must not be weakened ad hoc. A versioned
implementation must add batch-aware seriality, adversarial tests, a satisfiability audit, and owner
promotion before this template can authorize a return.

## Primary estimators

The template freezes the daily return basis, minimum sample, and significance rule. Headline
returns use Coordinated Universal Time day-last equity. The Newey-West lag is:

```text
max(7, floor(4 * (n_obs / 100) ** (2 / 9)))
```

The seven-day floor reflects weekly rebalancing; the automatic term increases with sample size.
The rule is fixed before returns and may not be replaced by the lag that produces the preferred
t-statistic. Probabilistic Sharpe ratio uses a zero annualized benchmark. Deflated Sharpe ratio
uses the complete union identity count and variance defined by the in-force accounting policy.

## PBO matrix

The reservation must list every identity column, split count, combination ceiling, seed, and
alignment rule. Each column must represent a counted return identity, not a capacity row or a copy
of another path. The matrix uses the intersection of daily rows and rejects internal missing dates.

If fewer than two columns survive or the matrix cannot be computed exactly as frozen, PBO is null
and the batch disposition is `INCOMPLETE / NOT ADMITTED`. Null may never be converted to zero.

## Stress and capacity scenarios

Every scenario receives an identifier and canonical assumptions hash before returns. The manifest
must include:

- baseline costs and execution assumptions;
- each stressed fee, spread, latency, impact, fill, rejection, and outage assumption;
- at least three capital points, including the governing $500,000 capacity point;
- the fill-ratio computation and monotonicity rule; and
- the rule that no scenario may replace the primary result or become a winner.

The author must define the values for the candidate's market before reservation. The template does
not supply universal stress multipliers because doing so would pretend that equity, futures,
options, and crypto venues share one execution model.

## Book and drawdown evidence

The reservation must hash the exact existing-book return matrix and its series identifiers. It must
also freeze:

- candidate weight;
- row-alignment rule;
- crisis or stress mask;
- bootstrap sample count, block size, seed, and confidence side;
- leave-one-period definition;
- expected-shortfall and drawdown estimators;
- book simulation specification; and
- overlay configuration.

The current v7 defaults remain 2,000 circular moving-block bootstrap samples, block size 21, seed
20260816, and a one-sided 95% bound. A promoted template must bind the contract hash so future
contract changes cannot silently alter a reserved batch.

The result must publish candidate-to-book correlation, pairwise correlations, their uncertainty
bounds, crisis-conditional dependence, tail co-loss, average-correlation change, book Sharpe
change, bootstrap lower bound, leave-period-out book contribution, expected-shortfall change,
maximum-drawdown change, expected maximum drawdown, and 95th-percentile maximum drawdown.

## Execution evidence

Each admission-contract execution dimension must be either applicable or not applicable. An
applicable dimension needs at least three exact scenarios and result hashes. A not-applicable
dimension needs a reason and evidence hash. The two sets must be disjoint and cover the contract's
entire dimension list.

The execution scenario manifest is frozen before return computation. A passing average cannot hide
a failed outage, rejected-order, borrow, limit, assignment, or counterparty scenario that applies
to the instrument.

## Data, code, and publication

Before execution, the reservation binds the point-in-time data manifest, runner, project file,
lockfile, and every pre-result scenario authority. The runner snapshots derived signals, universe,
instrument metadata, raw execution partitions, resolved configuration, and source environment
before the first leg.

Every identity receives a permanent paper and machine-readable packet, regardless of disposition.
The batch receives a matrix receipt. Private data remains private unless redistribution rights are
established. Repository preparation is not external submission, a digital object identifier, peer
review, or independent replication.

## Promotion gates

The template remains non-executable until all of these conditions pass:

1. a return-blind satisfiability audit proves that the complete conjunction can be measured;
2. trial accounting explicitly distinguishes selectable identities from mandatory diagnostics;
3. seriality supports a predeclared atomic batch without permitting an unreserved identity;
4. mutation tests reject missing hashes, null required fields, duplicate scenarios, and outcome
   fields;
5. public projections derive every gate and status from canonical artifacts; and
6. Arhan Canli records explicit prospective promotion.

Promotion applies only to reservations created after the promoted content hash. It cannot rescue
`crypto_carry_portable_v1` or any other known result.

## Acceptance test

A filled reservation passes only when a validator can answer these questions from pre-result bytes:

- What return identities can be selected?
- How many trials enter family and union deflation?
- What exact matrix defines PBO?
- What exact scenarios challenge cost, execution, and capacity?
- What existing book, weight, alignment, and stress mask define diversification?
- What simulation defines expected and p95 book drawdown?
- What evidence will be public, private, or unavailable?
- What result causes `ADMIT`, `KILL`, `INCOMPLETE`, or `INVALID`?

If any answer depends on seeing a return, the reservation fails before return computation.
