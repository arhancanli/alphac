# Spin-off dislocation — initial Form 10 document-schema protocol

**Declared:** 2026-08-16 after the Form 10 lineage pass and before opening any filing document in
this stage. **Market prices and returns remain forbidden.**

## Frozen sample

From the sealed 204 initial `10-12B` registrations in 2016–2025, sort each year by SHA-256 of
`CIK|accession` and retain the first ten, or all rows when a year has fewer than ten. The resulting
sample is 98 filings: ten in 2016–2024 and eight in 2025. Difficult or non-spin registrations are
not replaced.

## Locked extraction

1. Download and hash the official filing index page derived from the full-index archive filename.
2. Extract the SEC acceptance timestamp and the document-table link whose type is exactly
   `10-12B`.
3. Download and hash that immutable primary document, normalize visible text with the existing
   `sec-filing-sections-v2` parser, and record byte/word counts.
4. Record fixed, non-exclusive evidence flags for `spin-off`/`spinoff`, `separation and
   distribution`, and pro-rata distribution-to-parent-stockholders language.
5. Record diagnostic mentions of distribution ratio, record date, and distribution date. These
   diagnostics do not define an event and cannot be used to select a better parser after results.

No company names, filings, or years may be removed because they are not genuine spin-offs. Form 10
is deliberately being tested as a noisy discovery source.

## Locked gates

All must pass for `PASS_TO_AMENDMENT_CHAIN_AUDIT`:

- exactly 98 frozen filings;
- 100% official filing-index downloads and exact `10-12B` primary-document links;
- 100% acceptance-timestamp coverage;
- 100% primary-document downloads and immutable hashes;
- at least 50% of documents contain explicit spin-off or separation-and-distribution language;
- at least 30% contain pro-rata distribution-to-stockholder language; and
- no market data, returns, or return hypotheses are opened.

Failure is `DATA_GATED`; patterns and thresholds are not revised after aggregate results are seen.
A pass authorizes only a separately frozen amendment-chain and blind-accuracy audit. It does not
authorize a return test or assert that flagged documents are tradable events.

## Locked result

All 98 official filing indexes, acceptance timestamps, exact `10-12B` primary-document links, and
primary documents were recovered and hash-bound. Explicit spin-off or separation language appeared
in 68 documents (69.39%), passing the 50% discovery-source gate. The terms needed to define an
event were not present reliably in the initial registration:

- pro-rata distribution language: 16/98 (16.33%), below the locked 30% gate;
- ratio mentions: 8/98;
- record-date mentions: 4/98; and
- distribution-date mentions: 0/98.

**Decision:** `DATA_GATED`. The fixed patterns are not revised and the failed initial-registration
identity is not advanced to an amendment-chain audit. A future route requires a materially new,
preregistered amendment-known identity or licensed point-in-time corporate-action feed. No market
data or returns were opened and zero return hypotheses were spent.
