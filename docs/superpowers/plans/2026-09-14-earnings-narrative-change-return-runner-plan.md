# Earnings narrative change: return runner and first v2 reservation (ordinal 348)

**Author:** Arhan Canli (operating session under the owner's delegation of 2026-09-14)
**Status:** PLAN. Nothing here spends an identity. The pre-registration
(`docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md`, declared 2026-08-15) is the specification;
this plan only orders the implementation and names what each task must prove before the next.
**Why this family first:** the feasibility study passed to return pre-registration with every
document gate true (`artifacts/feasibility/earnings_narrative_change/result.json`, 477 sections,
373 comparable pairs, parser `sec-filing-sections-v2`), it needs no purchase, and an event-driven
long-short book is the kind of return least obviously tied to the four sleeves the book runs
(breadth arithmetic: only a non-positive average correlation reaches the Sharpe goal).

## What already exists

- `scripts/build_sec_10k_manifest.py`, `scripts/download_sec_10k_item1a.py`,
  `scripts/build_sec_item1a_pairs.py`: the corpus pipeline the feasibility pass ran on its locked
  sample (`locked_sample.csv`, `sections.parquet`, `pairs.parquet`), with the lineage the prereg
  demands (accession, acceptance timestamp, SIC from the immutable index page, section hash,
  predecessor accession).
- `scripts/probe_earnings_narrative_change.py`: the no-returns feasibility probe (extraction and
  pair gates). It is the only thing that has ever touched this corpus; no return has been loaded.
- The v2 full-evidence reservation (`config/forward_full_evidence_reservation_v2_template.json`)
  and the wired seriality guard (PR #34): ordinal 348 is reservable once the runner's evidence
  files exist to be hash-bound.
- `alphaforge.validation.diversification.diversification_report`: the shared engine every
  correlation and fixed-weight book number must come from.
- `scripts/run_crypto_carry_portable_v1.py`: the reserve, preflight, execute, seal shape a v2 runner
  follows (bound lake manifest, reservation validated before any return is computed).

## Tasks (each one a commit; a task's proof is stated, not implied)

### Task 1: full corpus, not the sample
Extend the manifest and downloader from the locked sample to every unamended 10-K primary
document from 2005 through 2025 for issuers in the Sharadar universe, resumable, rate-limited
per SEC policy, with the immutable-index SIC and `sic_missing_at_source` counted as the prereg
clarifies. **Proof:** the corpus result binds every Parquet part by ordered filename, byte length
and SHA-256; a rerun over a completed corpus downloads nothing and reproduces the digest.
**Budget:** days of downloads; this task runs unattended on the Mac (a launchd job with its own
lock), never inside a tick.

### Task 2: pairs and stability
`build_sec_item1a_pairs.py` over the full corpus: immediate unamended predecessor only, both
sections at least 500 words, five-token-shingle Jaccard, the exhaustive attrition ledger.
**Proof:** every latest-attempt corpus row is either an accepted pair endpoint or carries a
deterministic rejection reason; the pair result binds the corpus digest and the source manifest.

### Task 3: market inputs and the input manifest
A loader for the Sharadar SEP/ACTIONS/TICKERS snapshots already on disk, the SPY research series,
the XNYS session calendar derived from SPY, the CIK-to-ticker interval mapping (exclude, never
guess), the $5 close and $5 million median dollar-volume filters, the filing-reaction control
(latest close before acceptance to the first session whose open is after acceptance, less SPY).
**Proof:** one canonical input manifest binding every loaded symbol's values and missingness;
unit tests on a synthetic calendar for the acceptance-timing rule and for the mapping refusal.

### Task 4: signal
Monthly cohorts by acceptance month; percentile ranks; the per-cohort OLS of ranked stability on
intercept, ranked reaction, ranked momentum and one-hot accession-time SIC; residual quintiles;
the deficiency rules (20 eligible, five per tail, 10 residual degrees of freedom, 10 distinct
finite residuals; else flat). **Proof:** property tests that a saturated industry design yields a
flat cohort, that ties break by CIK, and that no coefficient crosses a cohort boundary.

### Task 5: portfolio, execution and costs
Entry at the second XNYS open after month-end, 63-session hold, equal-notional 50/50, concurrent
cohort averaging to gross 1.0, the clamped-beta SPY hedge, baseline and stress costs on netted
turnover, the missing-open deferral rule, the force-flat rule for delistings (reported, and any
occurrence makes the result `DATA-ESCALATE`, never `ADD`), capacity at 1/5/10 bps of ADV.
**Proof:** a synthetic three-stock world with a halt, a delisting and a month-end on a holiday
reproduces the prereg's worked semantics exactly.

### Task 6: evaluation and the v2 reservation
Calibration 2006-2015 may reveal broken plumbing and change nothing; the 2016-2025 OOS curve
opens once. Report everything the prereg lists (net and stressed Sharpe, Newey-West t, DSR
against the union count, drawdown, skew, turnover, beta, long/short contribution, annual results,
capacity, ordinary and bottom-decile-stress correlations to every current sleeve through
`diversification_report`, the 10% fixed marginal test funded pro rata, the mean-zero control,
leave-one-year-out). PBO is reported as not defined. **Before the OOS curve opens:** write the v2
reservation for ordinal 348 with every supplemental scenario frozen (cost stress, execution
stress) so this one identity can reach a decision; validate it with the wired guard; seal it.
**Proof:** `validate_reservation` returns VALIDATED_BEFORE_RETURN_COMPUTE with
`prior_identities_must_be_decided: true`; the reservation's evidence hashes equal the runner,
manifest and environment on disk.

### Task 7: run, packet, closure, publish
Run once. Build the identity packet, the closure (ADMIT, KILL or DATA-ESCALATE as the prereg
defines), the kill paper if killed; publish through `research_export.py` and the prospective
register. The union becomes 348; the site's denominator follows.

## What this plan does not decide
Whether the signal works. The locked direction is long stable, short changed; a failed result is
never inverted, and the second budgeted identity for this candidate is reserved for the MD&A
variant only under a new pre-registration.
