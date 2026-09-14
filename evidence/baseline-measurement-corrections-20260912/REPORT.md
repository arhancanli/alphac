# Baseline measurement corrections — phase complete

Both audited measurement defects are fixed in the isolated research checkout. Production source files still match the previous audit snapshots. Original reports and marks are preserved; no deployment, new market-return variant, portfolio reweighting, account operation or sleeve admission occurred.

## Changes

**Historical combined drawdown:** `book.py` includes normalized starting capital 1.0 in the running peak. Its negative drawdown sign convention, return series, equity-series length and all allocation behavior are preserved. A first-day 10% loss followed by a flat day now reports a drawdown magnitude of 10%, versus the old incorrect 0%. Regression cases cover successive initial losses, recovery, later losses, no losses, and an initial loss attributable solely to the overlay.

**Forward interval accounting:** the evaluator validates date order and separates one-day returns from multi-day returns. Its report records missing-day counts, actual interval endpoints and the complete observed gap return. No missing mark is filled or inferred. If any gap exists, the statistical status is `FAIL_CLOSED_IRREGULAR_DAILY_RECORD`: no Sharpe estimate, target-observed claim or target-establishment probability is released, even when the surviving sample is long enough and all provenance checks pass. Independent provenance failure still takes precedence while preserving the underlying irregular-record status.

The corrected record includes `measurement_version=daily_interval_validation_v2` and an explicit irregular-frequency label when required. Cumulative return and observed drawdown continue to use the complete original sequence of marks. Actual drawdown within an unobserved interval is unknown; the observed-mark drawdown is not a bound on intraday or missing-day losses.

## Replay of frozen paper evidence

| Measurement | Original | Corrected |
|---|---:|---:|
| One-day return observation claim | 34 | 33 |
| Adjacent observed-mark intervals | 34 | 34 |
| Missing daily marks | Not identified by this evaluator | 2 |
| Cumulative return | -2.72169% | -2.72169% |
| Observed-mark maximum drawdown | 3.87083872% | 3.87083872% |
| Sharpe status | Immature record | Irregular daily record; estimate withheld |

August 8–11 remains a three-day interval in the receipt. All original equity marks and all valid one-day returns are unchanged. The comparison uses the same frozen evidence and historical contract parameters; it does not migrate the older contract to the owner's new objectives, generate a new book, or claim current broker/provenance verification.

The historical four-sleeve/overlay market study was **not** recomputed. Therefore the synthetic drawdown correction is not presented as the size of a correction to that study. Its old modeled expected/p95 figures remain historical and are not regraded.

## Validation

- **48 tests passed**, including 13 new regression cases across book drawdown and forward intervals.
- One historical workstation-artifact check is skipped because the published artifact is absent in this isolated checkout. The frozen actual paper marks were independently replayed by the comparison script instead; this is not a full production-publication validation.
- Existing continuous-record maturity and target-establishment cases still pass; long signed/provenance-valid records with gaps cannot publish Sharpe.
- Synthetic evaluator tests now stage their dependencies in temporary directories instead of requiring mutable workstation publication artifacts.
- Ruff passes for all five changed/new Python files.
- Nine comparison source hashes verify. The original production evaluator and combiner remain byte-identical to prior snapshots, and test imports resolve to the isolated implementation.

`comparison.json` records before/after evidence; `verification.json` records checks and the test command; `implementation/` retains exact implementation and test files. An initial comparison run, made before cosmetic lint repairs to its driver, remains in the sibling `baseline-measurement-corrections-20260912-initial` directory. The final receipt binds the repaired driver.

## Progress and next phase

This phase improves measurement correctness and prevents false statistical eligibility. It does **not** improve strategy returns or establish Sharpe >2, maximum drawdown <=11%, or 15 qualified sleeves.

Next proposed phase: investigate whether authentic August 9/10 marks can be recovered from retained paper/account evidence, preserving original publication history. If they cannot, explicitly retain the gap and define a separate prospective evaluation epoch rather than fabricating marks. Then finalize the combined-book evaluation contract, economic timestamp alignment and costs before another registered portfolio experiment. Production rollout of these corrections is a separate phase with public-schema and publication checks.

Stop at this phase boundary for the owner's review.
