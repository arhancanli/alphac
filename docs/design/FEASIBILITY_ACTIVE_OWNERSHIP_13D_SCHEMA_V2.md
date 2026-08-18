# Active ownership escalation — schema-aware Schedule 13D metadata v2

**Declared:** 2026-08-15 after v1 closed `DATA_GATED` and before assembling v2 counts, selecting
the v2 sample, downloading any additional header, or opening a document/return. **Stage:** official
metadata only; zero return identities are spent.

## Corrections authorized by v1

This is a new source contract, not a revision of v1's result. It addresses only source mechanics
observed in v1:

1. exact initial forms are `SC 13D` and, after the structured-data transition, `SCHEDULE 13D`;
2. an accession can have multiple index-associated CIKs, so the immutable SGML header is
   authoritative and both subject and filed-by CIKs must belong to the accession association set;
3. feasibility depends on a sufficiently large investable subset, not 80% of an unrestricted
   global universe that intentionally includes funds, trusts, private issuers, and foreign classes.

No documents, Item 4 text, prices, returns, or outcomes informed this contract.

## Locked v2 sample and gates

Use the same 64 cached official quarterly indexes from 2010-2025. Retain both exact initial-form
names, group all rows by accession, and preserve the sorted set of associated CIKs. Select 50 unique
accessions per year using SHA-256 of `year|accession`; do not replace failures. Download the
immutable `.hdr.sgml` using the archive path in the index filename. Map subject CIK at filing date
against the same domestic-common ticker interval table used by the earnings corpus.

All gates must pass:

- all 64 indexes are present and parse;
- every year has at least 100 unique initial accessions across the two exact form names;
- the sample contains exactly 800 headers, 50 in every year;
- all 800 headers download;
- subject CIK, filed-by CIK, and acceptance datetime lineage is at least 98%;
- both header CIKs are members of the index association set in at least 98% of lineage-complete
  rows;
- at least ten sampled filings map to exactly one contemporaneous domestic-common ticker in every
  year; and
- the overall unique-ticker mapping rate has a two-sided 95% Wilson lower confidence bound above
  20%.

Passing authorizes a separately locked Item 4 classifier feasibility audit. It does not authorize
returns. Failing is `DATA_GATED`, with no form expansion, sample replacement, or threshold revision.

## Primary references

- SEC archive index documentation:
  https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- SEC beneficial-ownership amendments:
  https://www.sec.gov/newsroom/press-releases/2023-219

## Locked result

V2 passed every declared gate without opening a filing body or return:

- 22,353 unique initial accessions across both exact form names;
- at least 1,100 initial accessions in every year, including 1,115 structured filings in 2025;
- all 800 frozen headers downloaded;
- 100% acceptance/subject/filed-by lineage and 100% header-CIK membership in each accession's
  index association set;
- 378 unique contemporaneous domestic-common mappings, or 47.25%;
- a two-sided 95% Wilson lower bound of 43.81%, above the locked 20% gate; and
- between 15 and 33 unique mappings in every 50-header annual cell, above ten required.

**Decision:** `PASS_TO_DOCUMENT_FEASIBILITY`. This is evidence that an investable official-source
corpus can be assembled, not evidence of activist alpha. Zero return identities were spent.

Machine-readable result:
`artifacts/feasibility/active_ownership_13d_schema_v2/result.json`.
