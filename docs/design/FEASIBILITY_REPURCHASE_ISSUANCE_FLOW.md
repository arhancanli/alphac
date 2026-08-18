# Repurchase and issuance flow: no-return SEC feasibility protocol

**Declared:** 2026-08-16  
**Return data:** prohibited  
**Hypotheses spent:** zero  
**Family trial account:** `corporate_equity_supply`  
**Prior return configurations:** three (`eq_net_issuance`)  
**Minimum family trial count if one completed-flow return identity is opened:** four  
**Independent-sleeve count:** prohibited; this is a same-family measurement refinement

## Question

Can completed repurchases and completed issuance be reconstructed from information available at
each SEC filing acceptance time, with enough coverage and semantic stability to justify exactly
one later return preregistration?

This audit measures data feasibility only. It may inspect filing metadata, XBRL facts, Item 703
tables, taxonomies, contexts, amendments, and extraction errors. It may not read prices, returns,
future delistings, signals, positions, portfolio correlations, or performance statistics.

## Frozen source and sample

- Official SEC `company_tickers.json`, Submissions API, Company Facts API, and immutable filing
  documents. No vendor-derived fundamentals.
- Forms 10-Q, 10-Q/A, 10-K, and 10-K/A filed from 2013-01-01 through 2025-12-31.
- A deterministic 600-CIK schema sample: canonical current SEC ticker rows, one row per CIK,
  ordered by `sha256("repurchase_issuance_flow_v1|CIK##########")`, first 600. This current roster
  is allowed only for schema feasibility and cannot become a historical return universe.
- A deterministic 240-filing Item 703 document sample from those CIKs, balanced by filing year
  where documents exist. Selection is by the same sealed hash rule, never by extraction success.
- Every raw response stores URL, retrieval time, byte count, SHA-256, CIK, accession, acceptance
  time, form, fiscal period, taxonomy tag, unit, start/end dates, `filed`, `frame`, and source file.

## Frozen fact families

The parser records, but does not combine or optimize, these standard-tag families:

- completed cash repurchases: `PaymentsForRepurchaseOfCommonStock` and direct successor tags with
  identical taxonomy definitions;
- completed common-stock issuance cash proceeds: `ProceedsFromIssuanceOfCommonStock` and direct
  successor tags with identical definitions;
- shares issued or repurchased/retired during the period where standard tags exist;
- weighted-average and period-end shares only as reconciliation diagnostics;
- stock-option exercise proceeds, share-based compensation, acquisition consideration, stock
  splits, tender offers, and non-cash issuance as explicit contamination flags, never silently
  merged into ordinary issuance.

Custom extension tags are preserved and counted but cannot be auto-mapped from text similarity.
Any successor mapping requires identical definitions and a published mapping table.

## Point-in-time rules

1. A fact becomes knowable at the filing's accepted timestamp, never at fiscal period end.
2. The first accepted filing is the historical value. An amendment is a new state from its own
   acceptance time and cannot rewrite earlier observations.
3. Cumulative year-to-date duration facts may be quarterized only by differencing facts that were
   both knowable at that decision time, share the same fiscal year and unit, and pass context
   lineage. Missing predecessors remain missing.
4. Company Facts frames are not used as historical truth because their “last filed” aggregation
   can incorporate later submissions.
5. Restatements, duplicate contexts, dimensions, unit changes, and conflicting tags are explicit
   failure states. No best-looking value is selected.
6. Item 703 tables are parsed from the immutable filing document tied to the accession. The
   vacated 2023 daily disclosure format is not assumed.

## Locked gates

All gates must pass before a return protocol can be written:

1. 100% raw-response hashes and accession/acceptance lineage.
2. At least 95% of sampled periodic filings join uniquely to SEC submissions metadata.
3. At least 70% of sampled issuer-years expose either a standard completed-repurchase cash fact or
   an accession-bound Item 703 table; Wilson 95% lower bound must be at least 65%.
4. At least 60% of sampled issuer-years expose a standard completed-issuance cash/share fact or an
   explicit contamination-resolved reconciliation; Wilson 95% lower bound at least 55%.
5. At least 85% Item 703 extraction precision and 80% recall on a frozen 60-document hand-label
   set selected before parser evaluation.
6. At least 95% of accepted facts have unambiguous unit, period, and form context.
7. Amendment replay is slice-invariant: truncating the corpus before an amendment reproduces the
   exact pre-amendment state hash.
8. Quarterization fails closed whenever a predecessor, unit, context, or fiscal-year identity is
   ambiguous; zero is never imputed.
9. Stock splits, stock compensation, acquisition issuance, tender offers, and custom tags each
   receive explicit coverage/error counts.
10. Return data opened and return identities spent both remain exactly zero.

## Decisions

- `PASS_TO_RETURN_PREREGISTRATION`: every gate passes and the complete manifest is hashed.
- `DATA_GATED`: coverage or semantic lineage is inadequate but a named vendor could resolve it.
- `KILL_FEASIBILITY`: actual repurchases and issuance cannot be separated reproducibly enough to
  support the economic identity.
- `REJECT_GOVERNANCE`: any return data was opened, the deterministic samples changed, or a missing
  value was inferred from future information.

Passing permits one separately sealed family-wise return identity. It does not choose a sign,
horizon, universe, threshold, or sleeve weight and does not create an ALPHAC sleeve.

## Identity-overlap decision

`artifacts/feasibility/repurchase_issuance_flow/identity_overlap_audit.json` reconciles this
proposal against the historical `eq_net_issuance` campaign. The prior signal measured the
year-over-year change in split-adjusted shares with the same long-repurchaser/short-issuer economic
thesis. Three distinct configurations are already in the union ledgers; results include a null,
Sharpe `-0.1289`, and Sharpe `-0.3113` with DSR `0.00010`, while a separate source-correct
full-window rerun reported `+0.1481`. That instability is prior family evidence, not a clean slate.

Completed cash flows are a distinct and potentially better measurement, but they remain in the
same corporate-equity-supply family. A later return protocol, if feasibility passes, must inherit
all prior trials, residualize against the frozen broad issuance signal, prove positive mean-zero
marginal book contribution, and use an untouched holdout. It may qualify only as a same-family
replacement or refinement and cannot count toward the ten new independent sleeves.

## Implemented pipeline and current state

The complete no-return collection, semantic-audit, blind-extraction, and combined-decision path
is implemented and covered by 48 focused tests. Official SEC collection and semantics are now
complete. The family is stopped at the intended blind-label gate: all 240 frozen documents are
sealed, no document has been parsed, and none of the 60 labels has been opened by the parser.

1. `scripts/build_repurchase_issuance_manifest.py` creates the deterministic 600-CIK sample and
   binds it to the raw SEC ticker-map hash.
2. `scripts/collect_repurchase_issuance_companyfacts.py` stores deterministic gzip responses,
   preserves every original and amended fact, writes immutable Parquet parts, and can resume by
   parser-version-qualified CIK identity.
3. `scripts/collect_repurchase_issuance_submissions.py` independently collects all eligible
   periodic filings so coverage is measured against real filing denominators rather than only
   companies with convenient tags.
4. `scripts/audit_repurchase_issuance_companyfacts.py` verifies both collection seals and part
   hashes, joins facts to accessions, computes context completeness and Wilson bounds, and can
   return only `ITEM703_AUDIT_REQUIRED` or `DATA_GATED`. It cannot pass full feasibility.
5. `scripts/audit_repurchase_issuance_semantics.py` independently replays amendment prefixes,
   proves slice invariance, quarterizes only same-year/same-unit/same-context facts known by that
   acceptance time, records every fail-closed reason, and reports all contamination categories.
6. `scripts/build_repurchase_item703_manifest.py` creates immutable year-balanced 240-document
   and 60-label samples from completed periodic filings, excluding amendments from selection.
7. `scripts/collect_repurchase_item703_documents.py` retrieves only the frozen filing documents,
   verifies the exact accession set, and stores deterministic gzip bodies and immutable statuses.
8. The 60 frozen documents are labeled independently in `labels.csv`. The labeler records table
   presence, month-row count, total-row presence, and notes without opening parser output.
9. `scripts/seal_repurchase_item703_labels.py` validates exact identities and complete labels,
   refuses to run after any parser output exists, and binds the labels to the parser-source hash.
10. `scripts/parse_repurchase_item703_documents.py` verifies every raw hash and the pre-evaluation
    parser hash, parses all 240 documents without reading labels, preserves tender-offer mention
    counts, and writes one immutable result.
11. `scripts/audit_repurchase_item703_extraction.py` opens the labels only after parsing, reports
    the full confusion matrix plus row-shape diagnostics, and enforces precision at least 85% and
    recall at least 80%. Passing still cannot admit the family or authorize a return probe.
12. `scripts/audit_repurchase_issuance_feasibility.py` revalidates every current part against the
    full cryptographic chain, computes conservative union coverage on the frozen document-sample
    issuer-years, applies every locked empirical and governance gate, and is the only stage allowed to
    emit `PASS_TO_RETURN_PREREGISTRATION`. Any missing or failed gate exits nonzero.

Company Facts parser v3 also makes semantic exclusions explicit. Stock compensation, option
exercise proceeds, acquisition issuance, mixed common/preferred facts, repurchase authorizations,
and split diagnostics have separate families and cannot count as direct ordinary issuance.
Balance-sheet `CommonStockSharesIssued` is reconciliation data, not a completed-period flow.
Custom extensions stay in immutable raw responses and receive explicit namespace, tag, and row
counts, but are never mapped by text similarity. The parser records official Company Facts 404s
as terminal `not_available_404` outcomes, never as successful payloads and never as retryable
silence. Those issuers remain in the frozen denominator.

### Empirical checkpoint: stopped before parser evaluation

- The SEC ticker manifest contains exactly 600 unique CIKs. Company Facts returned 520 payloads;
  80 manifested issuers had reproducible official 404s, and collection had zero unresolved errors.
  All 600 identities are explicitly accounted for.
- The independent submissions collection contains 15,009 periodic filings. Of 150,570 relevant
  facts, 99.993% join to an accession and 99.489% have complete unit/period/form context.
- Standard tags alone cover 46.45% of 3,903 issuer-years for completed repurchases (Wilson lower
  bound 44.89%) and 43.35% for completed issuance (Wilson lower bound 41.80%). These figures do
  not clear the locked combined coverage gates; they prove the Item 703 lane is necessary.
- Amendment replay is slice-invariant across 2,407 amendment facts. Quarterization derives 35,792
  quarters and fails closed on 19,087 facts, including 18,321 missing predecessors; zero values
  are imputed.
- The frozen Item 703 sample is 240/240 collected with exact accession identity. The year-balanced
  60-document `labels.csv` is blank by design. No parser output or return data exists.

The only authorized next action is an independent reviewer completing
`artifacts/feasibility/repurchase_issuance_flow/item703/labels.csv` from the linked filing documents
without inspecting parser output. The seal command must run before parsing. Until then the honest
decision is `BLIND_ITEM703_LABELING_REQUIRED`, not pass, kill, or return authorization.

```bash
uv run python scripts/build_repurchase_issuance_manifest.py
uv run python scripts/collect_repurchase_issuance_companyfacts.py
uv run python scripts/collect_repurchase_issuance_submissions.py
uv run python scripts/audit_repurchase_issuance_companyfacts.py
uv run python scripts/audit_repurchase_issuance_semantics.py
uv run python scripts/build_repurchase_item703_manifest.py
uv run python scripts/collect_repurchase_item703_documents.py
# Complete the frozen labels.csv independently; do not run or inspect parser output.
uv run python scripts/seal_repurchase_item703_labels.py
uv run python scripts/parse_repurchase_item703_documents.py
uv run python scripts/audit_repurchase_item703_extraction.py
uv run python scripts/audit_repurchase_issuance_feasibility.py
```
