# Prospective admission-v7 power and scope audit

**Owner and author:** Arhan Canli  
**Frozen:** 2026-08-23  
**Status:** retrospective contract audit; no return experiment

## Question

Do the in-force v6 gates test the decision named by the gate, remain jointly satisfiable, and give
the prospective fourteen-sleeve programme enough search capacity to have a credible chance of
finding ten genuinely new sleeves?

This is not a blind preregistration. The current contract, current four-sleeve correlation, trial
ledger and historical aggregate hit rate are already known. Therefore any correction produced by
this audit applies only to identities reserved after a future v7 contract hash becomes effective.
The 228 legacy identities remain retired and cannot be rescued, re-labelled or made eligible.

## Frozen inputs

- `config/archive/sleeve_admission_contract_v6_superseded.json`;
- `config/archive/trial_accounting_v1_superseded.json`;
- `config/archive/admission_v7_power_audit_inputs.json`, the immutable pre-promotion value snapshot;
- `src/alphaforge/validation/dsr.py`; and
- this protocol.

No candidate return, candidate evidence packet or candidate verdict may be read. The audit may use
only aggregate trial accounting and current-book measurements already published before this file.

## Tests

1. **Satisfiability:** re-derive the Sharpe implied by every interacting significance floor.
2. **Decision scope:** distinguish an incremental sleeve-admission decision from a final portfolio
   maturity claim. A final-book threshold may be measured at each admission, but it must not reject
   a beneficial increment merely because the unfinished book has not already reached the final
   destination.
3. **Path dependence:** calculate what the current global average-correlation gate implicitly
   demands from the first new sleeve and what average relationship the 85 new pairs must achieve
   to reach the fourteen-sleeve objective.
4. **Search power:** use the declared historical aggregate hit rate of 3/46 only as a planning
   assumption. Compute the exact binomial probability of at least ten successes under the current
   remaining budget and under candidate prospective ceilings. This is not a forecast because the
   future families deliberately differ from the historical families.
5. **Multiplicity conservation:** any additional prospective identities remain in the complete
   union trial count. Recalibration may not erase or discount trial debt.

## Permitted corrections

- re-scope a threshold to the decision it actually measures;
- replace a path-dependent absolute level with a strict marginal-improvement gate plus a separately
  published objective trajectory;
- add staged prospective search capacity when ledger reconciliation consumed capacity without
  running a new experiment; and
- correct contradictory documentation.

## Forbidden corrections

- inspecting a known candidate and moving a threshold just beyond its result;
- retroactively qualifying an existing or retired identity;
- reducing data-lineage, survivorship, cost, execution, capacity-curve, stress, uncertainty,
  reproducibility or publication requirements;
- treating a target as evidence; or
- claiming that a higher search budget increases alpha rather than increasing the chance to look.

## Output boundary

The audit emits geometry and prospective recommendations only. It admits zero sleeves, consumes
zero hypothesis identities, changes no live strategy, and establishes no Sharpe, drawdown or
diversification target.
