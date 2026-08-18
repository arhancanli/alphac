# Spin-off dislocation — SEC Form 10 lineage protocol

**Declared:** 2026-08-16 before downloading any SEC full index for this protocol.  
**Stage:** official-source lineage only. Prices, returns, event outcomes, and performance are
forbidden. Zero return hypotheses are spent.

## Locked question

Can the complete 2016–2025 exchange-registration candidate universe be reconstructed from official
quarterly EDGAR full indexes without starting from a modern ticker list or known successful
spin-offs?

## Frozen source and population

- Download all 40 SEC `master.idx` files for 2016 Q1 through 2025 Q4.
- Hash-bind raw bytes and preserve URL, year, quarter, byte count, row count, and parse status.
- Retain form type exactly `10-12B` or `10-12B/A`.
- An initial candidate is form `10-12B`; amendments remain lineage but never create new events.
- Preserve CIK, company name as filed, filing date, archive filename, accession, form, and source
  quarter. Do not join to current tickers, prices, corporate-action outcomes, or commercial event
  lists.

Form 10 registrations are not presumed to be spin-offs. This stage discovers candidates only.

## Locked gates

All are required for `PASS_TO_DOCUMENT_SCHEMA_AUDIT`:

1. Exactly 40 quarter indexes download and parse with immutable SHA-256 hashes.
2. Every retained archive filename yields a canonical SEC accession.
3. Filing identity `(CIK, accession)` is unique after exact-row deduplication.
4. Every year contains at least one initial `10-12B`, and the ten-year initial population contains
   at least 50 rows. These are source-usefulness gates, not alpha gates.
5. No prices or returns are opened and no return hypothesis is spent.

Failure is `SOURCE_LINEAGE_REQUIRED` or `DATA_GATED`; thresholds are not revised after aggregate
counts are observed.

## Required next stage after a pass

A new locked document-schema audit must obtain acceptance timestamps and immutable primary
documents, distinguish genuine pro-rata separations from other registrations, map parent and
child, and extract distribution ratio, record/distribution dates, amendment state, cancellation,
when-issued status, fractional-share handling, and tax-basis references. It must use a frozen blind
accuracy set before any prices are opened.

Only after that stage passes may a return preregistration define instrument identity, parent/child
legs, entry clock, auction and when-issued execution, corporate actions, costs, borrow, capacity,
holdouts, trial accounting, DSR/PBO, perturbations, and diversification gates.

## Primary source

- SEC quarterly full indexes: `https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{q}/master.idx`
- SEC Form 10: https://www.sec.gov/files/form10.pdf
