# Supplemental measurement class v1: design

**Author:** Arhan Canli (operating session under the owner's delegation of 2026-09-14)  
**Status:** DESIGN, NOT IN FORCE. Nothing here changes how any identity is counted until the
policy is promoted and the ledger code below ships with its tests.  
**Owner goal served:** budget discipline (phase 1 of the 2026-09-14 plan); the 320 review's
decision that "baseline re-measurements, cost or execution stress arms and accounting repairs
of existing sleeves are declared supplemental measurements of their identity in the
reservation before any result and are not new searches" (`config/trial_accounting.json`,
`staged_reviews_held.320`).

## The problem, measured

On 2026-09-12/13 the autonomous research session spent 118 hypothesis identities for zero
admissions. By the prospective-epoch register (`artifacts/research/prospective_epoch_register.json`)
those 118 fall into roughly 35 studies, and the ledger directories under
`artifacts/analysis/*_2026091{2,3}` show the shape: `baseline`, `candidate`, `baseline_stress`,
`candidate_stress`, `cost_stress`, `primary`. A study that asked ONE question (does this
candidate improve the combined book?) recorded four configurations, and each configuration is a
distinct hypothesis identity under the policy's definition ("a distinct economic or parameter
identity after removing only start and end"). The definition is right for what it was written
for: it stops a parameter sweep from hiding as one idea. It has no way to say that a cost-stress
re-run of the same idea is not a second idea.

The count the policy governs (selection N for deflation) is therefore inflated by measurements
that could never have been selected on their own, and the budget that was meant to buy new
economic mechanisms was spent on arms.

## The rule

A **reservation** may declare, before any result, a **primary** configuration and a closed set
of **supplemental scenarios**. A ledger row is supplemental to a reservation when, and only when:

1. it carries the reservation's identifier and a role of `supplemental`;
2. its configuration differs from the primary only in fields the reservation listed as
   **scenario axes** (`cost_rate`, `cost_stress`, `execution_cost_scenario`, `arm` restricted to
   `baseline`, and nothing else unless the policy is amended);
3. its scenario value **cannot flatter**: a cost scenario must be at least the primary's cost
   (a cheaper re-run is a new identity and is charged); a `baseline` arm must be the identity the
   candidate is compared against, already in the union or charged as a new identity itself; an
   execution scenario must be one of the declared stress scenarios;
4. the reservation was validated (hash-bound) before the primary's first result, exactly as the
   v2 full-evidence reservation template already requires for its diagnostic scenarios
   (`diagnostic_scenarios.scenario_hashes_frozen_before_returns = true`,
   `selection_permitted = false`, `all_scenarios_must_publish = true`).

A supplemental row remains an **immutable execution record**: it is published, it is hashed, it
is on the ledger. It does not add a **hypothesis identity**. Selection N counts the primary
once. The deflated Sharpe of the identity uses the primary's Sharpe; no supplemental row is
ever the row that carries the identity's claim.

Everything else is unchanged. A candidate arm IS a new identity (it is the idea being tested).
A window-only remeasurement is still forgiven by the existing rule. A row with no reservation,
or a row whose configuration differs from its primary in any field outside the declared axes,
is a new identity.

## What this does not do

It does **not** re-score the 118. None of them declared supplemental scenarios before a result;
the reservations exist but name a single `hypothesis_identity` each, and the arms were reserved
as separate identities. Re-labelling them now would be choosing the accounting after the
outcome, the exact thing the rule forbids. They stay 118, the union stays 347, and the budget
headroom stays 53. The rule is prospective.

It does not lower any admission gate, and it does not let a stress scenario stand in for a
missing primary.

## Implementation, when promoted

- `alphaforge.validation.experiments`: `ExperimentRecord` gains optional `reservation_id` and
  `role` (`primary` | `supplemental`), both absent on every existing row. `n_hypotheses()` and
  `hypothesis_records()` collapse supplemental rows onto their primary's key only when a
  validated reservation with a matching declared scenario is present; otherwise the row counts.
  A new `supplemental_remeasurements()` is published beside `window_only_remeasurements` so the
  exemption is visible.
- `alphaforge.validation.trial_reservation`: the reservation schema gains `scenario_axes` and
  `supplemental_scenarios` (each a full config hash, frozen before the primary result), and the
  validator refuses a scenario that could flatter (rule 3).
- `config/trial_accounting.json`: `definitions.supplemental_measurement` and
  `supplemental_scenario_axes`, promoted by the owner; the register and the public ledger show
  the new counts.
- Tests, before the code: a study with primary + three declared arms spends one identity; the
  same four rows without a reservation spend four; a cheaper cost arm spends a second identity;
  an undeclared axis spends a second identity; a supplemental row can never be the
  `hypothesis_records()` representative; the mutation that removes the "declared before result"
  check must turn a passing test red.

## Expected effect

At the mix observed on 2026-09-12/13 (one primary and about three arms per study), a study
costs one identity instead of four. Fifty-three identities then fund fifty-three questions
about new mechanisms rather than thirteen. It does not change the hit rate; it stops paying
for what is not a search.
