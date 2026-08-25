# ALPHAC sleeve-admission contract v7

**Owner and author:** Arhan Canli  
**Status:** in force prospectively from reservation ordinal 229 on 2026-08-23  
**Evidence:** `artifacts/analysis/admission_gate_power_audit/result.json`
**Promotion receipt:** `config/admission_v7_promotion.json`

## What v7 changes

V7 changes the scope of two gates that tested the wrong stage of the programme. It does not lower
a threshold to admit a known result, and it does not alter any of the 228 retired identities.

### Full-union book DSR

The v6 threshold requires book DSR of at least 0.95 at every sleeve admission. With 756 observations
and 228 union identities, that requires annualized book Sharpe 2.2126. The current-composition
research simulation is 1.7846, so an otherwise valid first increment must add at least 0.4279 Sharpe
before any other evidence can matter. That is a final portfolio-maturity standard applied to an
incremental decision.

V7 keeps full-union book DSR mandatory and public at every admission. The 0.95 threshold remains the
gate before a mature portfolio claim. Incremental admission is instead decided by the existing
strictly positive bootstrap lower bound on book-Sharpe improvement, PBO, leave-period-out
robustness, full cost and execution evidence, stress, capacity and complete-union trial accounting.

### Correlation path

The current four-sleeve average is +0.024827. Requiring the five-sleeve global average to be at most
zero means the first candidate must average no more than -0.037241 against all four existing
sleeves. A candidate that is genuinely diversifying but averages -0.02 would be rejected even
though it moves the book materially toward the objective.

V7 therefore requires both:

1. candidate average correlation to the existing book no greater than zero; and
2. a strictly negative change in the book's global average pairwise correlation.

The +0.10 bootstrap upper-bound gate, +0.35 ordinary pair ceiling, +0.50 stress ceiling and their
confidence-bound checks remain unchanged. The global average remains mandatory and the -0.03
objective remains public. Based on the current six pairs, the 85 new pairs needed to reach fourteen
sleeves must average -0.033870; v7 does not conceal that requirement.

The frontier object consequently labels zero global correlation as a **legacy arithmetic
reference**, not as a gate in force. The two enforceable incremental correlation gates and the
fact that they do not by themselves establish either endpoint of the objective are machine-readable.

## What remains unchanged

- 756 candidate OOS observations and 504 correlation observations;
- positive net and stressed Sharpe screens;
- Newey-West sign and autocorrelation-inflation checks;
- PBO, purging, embargoes and complete trial accounting;
- a strictly positive bootstrap lower bound on marginal book Sharpe;
- leave-period-out robustness;
- expected-shortfall and drawdown comparisons;
- all point-in-time, survivorship and corporate-action controls;
- all execution scenarios, capacity curves and stressed fill reconciliation;
- complete publication and reproducibility evidence; and
- the rule that targets never count as admission evidence.

## Prospective boundary

V7 was promoted through a content-hashed owner record, active-contract and trial-policy bindings,
public projection reconciliation, and fail-closed reservation tests. It applies only from identity
229 onward. The 228 retired identities retain the exact v6 contract and verdict under which they
were tested; promotion does not regrade or erase them.
