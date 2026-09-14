# PRE-REGISTRATION — annual MD&A narrative stability (the family's second and final identity)

**Declared 2026-09-14, before loading any security return associated with this signal, as the
second member of the earnings-narrative-change identity batch. One hypothesis identity. No
direction, section, horizon, or portfolio sweep.**

## Why a second identity, and why now

`docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md` (2026-08-15) locked the family's first identity
to 10-K Item 1A and reserved "the candidate's second and final budgeted identity" for the MD&A
variant "under a new preregistration". This is that preregistration.

It is written now for a governance reason, not an evidence reason. The v2 full-evidence
reservation (`docs/design/FORWARD_FULL_EVIDENCE_RESERVATION_V2.md`) requires a
probability-of-backtest-overfitting matrix, and a matrix needs at least two counted return
columns; a batch with one column cannot define PBO and can reach `INCOMPLETE` but never `ADMIT`.
The two identities of this family are therefore reserved together as one atomic batch
(`config/trial_accounting_evidence_classes.json`, class `identity_batch`): both reserved before the
first return of either, both counted in the family and in the complete union, decided together,
and no unrelated reservation admitted until both are decided. The batch does not merge the two
identities, exempt either from deflation, or let one be selected after seeing the other; each is
its own hypothesis with its own packet, and the PBO matrix over the two columns is reported as the
protocol defines. Nothing about the first identity's pre-registration changes.

## Economic mechanism and locked direction

Management's discussion and analysis is the section where management explains results and
outlook in its own words. Material changes in that narrative from one annual report to the next
can reveal changing operating conditions, changed guidance, or managerial concern before prices
fully incorporate them (Cohen, Malloy and Nguyen, *Lazy Prices*, is the prior; it is not Canli
Capital evidence, and its published effect is measured on the whole filing rather than one
section). The locked direction is **long stable disclosures and short changed disclosures**. A
failed result is never inverted.

This identity uses only 10-K Item 7. Item 1A belongs to the first identity. 10-Qs, earnings-call
transcripts, embeddings, sentiment, topic models and alternative lexical distances are outside
this test. This is the family's final budgeted identity: a further variant is a new family under a
new pre-registration and a new budget review.

## Point-in-time data and lineage

Identical to the first identity, with the section substituted:

- Filing metadata, acceptance timestamps, the accession-time two-digit SIC from the immutable
  accession index, the unamended 10-K primary document, and every clarification recorded in the
  first pre-registration apply unchanged.
- Source text: the same cached immutable documents the Item 1A corpus read
  (`data/raw/sec_10k_narrative`, 82,491 documents), re-parsed for Item 7 with
  `sec-filing-sections-v2` by `scripts/build_sec_10k_item7_corpus.py`. No network read. The corpus
  result (`artifacts/ingest/earnings_narrative_change/item7_corpus_result.json`) binds the same
  filings manifest SHA-256 the Item 1A corpus bound, every immutable part by ordered filename,
  byte length and SHA-256, and reports the Item 7 extraction rate and every extraction failure.
- Pairs: `scripts/build_sec_item1a_pairs.py` run unchanged over the Item 7 parts
  (`item7_pairs.parquet`, `item7_pairs_result.json`): immediate unamended 10-K predecessor for the
  same CIK, section SHA-256 recomputed from stored text, locked parser version, exhaustive
  adjacency attrition ledger.
- Equity history, adjustment, delisting handling, calendar, issuer mapping, SPY series and the
  input manifest: exactly as the first identity, produced by the same runner
  (`scripts/run_earnings_narrative_change_v1.py --section item7`).

The corpus may begin in 2005 to form predecessor pairs. Returns before 2016 are calibration only.
The locked OOS interval is 2016-01-01 through 2025-12-31.

## Signal

1. Extract Item 7 with `sec-filing-sections-v2`. Pair each filing only with the immediately prior
   unamended 10-K for the same CIK. Require both sections to contain at least 500 words.
2. Raw stability is five-token-shingle Jaccard similarity. Higher means less narrative change. No
   stemming, synonym model, length adjustment, or document-frequency weighting is allowed.
3. through 7. exactly as the first identity: monthly acceptance cohorts, the $5 price and $5
   million median dollar-volume screens, the filing-reaction control, 12-1 momentum, the
   within-cohort rank regression with one-hot accession-time SIC, the residual as the signal, the
   20-issuer and five-per-tail minimums, the top and bottom residual quintile, ties by CIK, the
   10-residual-degrees-of-freedom rule, flat otherwise.

## Timing, portfolio, costs, capacity

Exactly as the first identity: entry at the second XNYS session open after calendar month-end,
63-session hold, equal-notional 50/50 cohorts averaged to gross 1.0, the clamped-beta SPY hedge,
baseline costs of 15 bps / 1 bp / 3% borrow and stress costs of 30 bps / 2 bps / 6%, costs on
netted turnover, the missing-open deferral rule, the delisting force-flat rule (any occurrence
makes the result `DATA-ESCALATE`, never `ADD`), capacity at 1, 5 and 10 bps of trailing 21-session
median dollar ADV with the 1% ADV ceiling.

## Evaluation, the batch, and PBO

Everything the first identity reports is reported here, by the same code. In addition, because
this identity completes the batch:

- The PBO matrix has exactly two columns, the Item 1A identity and this one, aligned on the
  intersection of their daily rows with internal missing dates rejected. Combinatorially
  symmetric cross-validation uses 16 splits (12,870 combinations), seed 20260914, frozen in the
  reservation before the first return. With two columns PBO is coarse; it is reported exactly as
  computed, never as zero, and its gate (`pbo_max` 0.20) applies to the batch as the contract
  states.
- Interim results are withheld: the runner writes both identities' curves before either
  evaluation is read, and the batch matrix receipt is sealed with both packets.
- If PBO cannot be computed exactly as frozen, the batch disposition is `INCOMPLETE / NOT
  ADMITTED` for both identities; null is never converted to zero.

## Kill and escalation rules

Identical to the first identity's rules 1 through 7 and the `DATA-ESCALATE` rule for
unobtainable locate and borrow evidence, applied to this identity's own out-of-sample curve. The
batch adds one rule: an identity whose PBO gate fails is killed even if every other gate passes.

```prereg
profile: earnings_narrative_change_mdna_v1
lake_dir: data/lake_sharadar_full
alpha_names: sec_10k_item7_stability_jaccard5
allocator: monthly_residual_quintile_beta_hedged
section: 10-K Item 7
parser_version: sec-filing-sections-v2
direction: long_stable_short_changed
hold_sessions: 63
oos_start: 2016-01-01
oos_end: 2025-12-31
identity_batch: earnings_narrative_change_batch_1
```

## Primary references

- Cohen, Malloy, and Nguyen, *Lazy Prices*: https://www.nber.org/papers/w25084
- The first identity's pre-registration: `docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md`
- The batch protocol: `docs/design/FORWARD_FULL_EVIDENCE_RESERVATION_V2.md`
