# Customer–supplier propagation — locked no-return relationship-source protocol

**Short title:** Customer-supplier propagation: feasibility

**Declared:** 2026-08-16 before computing corpus prevalence, selecting the document sample, or
extracting any customer name. **Stage:** official-source feasibility only. Market prices, returns,
event outcomes, signs, horizons, and portfolio data are forbidden; zero return identities are spent.

## Frozen identity boundary

- Supplier universe: domestic common-stock issuers already present in the immutable 10-K manifest.
- Relationship availability: no earlier than the SEC acceptance timestamp of the supplier's 10-K.
- Relationship fact: the filing must state that one customer accounts for at least 10% of supplier
  revenue and explicitly identify that customer by name.
- Anonymous labels (`Customer A`, `one customer`, government categories), private entities, and
  names that cannot be resolved historically to one public issuer are not tradable edges.
- A later return protocol, if authorized, must use a separately timestamped customer event and
  next-eligible-session supplier entry. This source audit does not choose the event, sign, or horizon.

## Frozen corpus and prefilter

Use the existing hash-addressed SEC 10-K manifest and local primary-document cache. Restrict filing
dates to 2016-01-01 through 2025-12-31. Every manifest identity must map deterministically to
`data/raw/sec_10k_narrative/documents/{CIK}_{accession}.html.gz`.

A document is a concentration candidate only when its raw filing contains `customer` within 400
characters of a numeric percentage from 10% through 100%, the equivalent `percent` form, or
`ten percent`, after lower-casing and collapsing whitespace.
This intentionally broad prefilter measures recall-oriented source prevalence; it does not establish
a named relationship.

From each calendar year, rank candidates by SHA-256 of `customer_supplier|CIK|accession` and retain
the first 30. The resulting at-most-300-row sample is immutable. No failed or difficult document is
replaced.

## Frozen extraction and gates

Convert sampled filings with parser `sec-filing-sections-v2`. Preserve document hash and every
±500-character window around a qualifying concentration marker. A strict name candidate must:

1. occur in the same window as both customer language and a ≥10% concentration marker;
2. be a proper-name phrase adjacent to `accounted for`, `represented`, `sales to`, or `revenue from`;
3. exclude anonymous counts/labels, generic customer categories, governments, and pronouns; and
4. be preserved as extracted rather than silently fuzzy-matched.

This v1 audit passes to a separately declared historical-entity-resolution audit only if all gates
pass:

- at least 99% of in-period manifest documents exist and decompress successfully;
- at least 500 concentration candidates exist, with at least 25 in every calendar year;
- all ten years contribute exactly 30 rows to the deterministic sample;
- at least 50% of sampled documents yield one or more strict name candidates; and
- no sampled row lacks CIK, accession, acceptance timestamp, source URL, or document hash.

Thresholds and extraction rules are not altered after aggregate results are observed. A pass does
not authorize prices or returns. Failure is `DATA_GATED`. Even after a pass, historical public-issuer
resolution, relationship expiry, amendments, shared analyst coverage, event definition, delistings,
costs, capacity, neutralization, walk-forward design, PBO, DSR, and portfolio correlation remain
mandatory independent gates.

## Machine outputs

- `artifacts/feasibility/customer_supplier_propagation/candidate_manifest.parquet`
- `artifacts/feasibility/customer_supplier_propagation/document_sample.parquet`
- `artifacts/feasibility/customer_supplier_propagation/result.json`

## Claim boundary

This protocol can establish only whether public 10-K text is sufficiently prevalent and explicit to
justify a historical entity-resolution audit. It cannot establish an investable graph or any return,
Sharpe, drawdown, correlation, capacity, or sleeve-admission claim.

## Locked result

The exhaustive source pass covered 36,424 manifest filings from 2016–2025. Primary documents were
present and decompressible for 36,243 rows (99.503%), passing the 99% lineage gate. The broad
prefilter retained 29,220 filings, every year contributed well above 25 candidates, and the frozen
sample contains exactly 30 documents in each of ten years.

The relationship-definition gate failed. Only 106 of 300 sampled documents produced one or more
machine name candidates (35.333%, versus the locked 50% minimum). Post-result inspection also found
that the v1 syntactic candidates include geographies, customer categories, and fragments in addition
to genuine legal names. The output is therefore not a production relationship graph and must not be
silently entity-resolved. The extraction rule is not tuned after observing this result.

**Decision:** `DATA_GATED`. A separately declared v2 would require frozen human labels and a
precision/recall gate before historical entity resolution. Zero market records, prices, returns,
signs, horizons, or portfolio statistics were opened; zero return identities were spent.

Machine-readable result:
`artifacts/feasibility/customer_supplier_propagation/result.json`.
