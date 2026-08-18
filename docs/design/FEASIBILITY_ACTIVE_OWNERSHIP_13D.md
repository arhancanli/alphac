# Active ownership escalation — Schedule 13D metadata feasibility protocol

**Declared:** 2026-08-15 before downloading quarterly index files, counting Schedule 13D filings,
or parsing any Schedule 13D submission header. **Stage:** official metadata/source engineering only;
documents, prices, returns, and outcome labels are forbidden. Zero return identities are spent.

## Mechanism boundary

The candidate is the medium-horizon effect of a new beneficial owner disclosing more than 5%
ownership with control intent, later narrowed by a separately locked Item 4 classifier to specific
active plans such as board representation, governance change, capital allocation, strategic review,
or sale advocacy. It is not generic institutional ownership, Schedule 13G, insider buying, merger
spread convergence, or the already tested closed-end-fund discount catalyst.

Initial `SC 13D` and amendments `SC 13D/A` are different states. This protocol discovers only exact
initial `SC 13D` forms. A future state machine must link amendments without treating each amendment
as a fresh event.

## Official-source discovery contract

- Period: 2010-01-01 through 2025-12-31, fixed before counts.
- Universe discovery: all 64 static quarterly SEC EDGAR `master.idx` files under
  `/Archives/edgar/full-index/{year}/QTR{quarter}/master.idx`, not target-company submissions.
  The index CIK is the filer and cannot be assumed to be the target.
- Target identity: parse `SUBJECT-COMPANY` CIK from the immutable accession `.hdr.sgml`; separately
  parse `FILED-BY` CIK and acceptance datetime. Never infer the target from a current ticker or
  company name.
- Deterministic header sample: sort each year by SHA-256 of `year|filer CIK|accession` and retain
  exactly ten initial filings. No failed or inconvenient sample row may be replaced.
- Contemporaneous security mapping: subject CIK must map to exactly one Sharadar domestic-common
  ticker interval whose first/last price dates contain the SEC filing date. This is reference-data
  feasibility, not a price query.
- Immutable source bytes, SHA-256 hashes, URLs, quarterly source lineage, and parser version are
  retained. Access is throttled so combined Canli Capital SEC traffic remains below the SEC's
  published fair-access ceiling.

## Locked metadata gates

All must pass:

1. all 64 quarterly indexes download and parse;
2. every year contains at least 100 exact initial `SC 13D` filings;
3. no duplicate accession survives index assembly;
4. all 160 frozen headers download successfully;
5. at least 98% of headers contain an acceptance datetime, subject CIK, and filed-by CIK;
6. at least 98% of parsed filed-by CIKs equal the index filer CIK; and
7. at least 80% of parsed subject CIKs map to exactly one contemporaneous domestic-common ticker
   interval.

A pass authorizes a separate Item 4 document-extraction protocol only. It does not authorize a
return test. Thresholds, period, form family, sample size, and mapping logic are not changed after
counts are observed.

## Known timing regime break

The SEC's 2023 amendments shortened the initial Schedule 13D deadline from ten days to five
business days and require amendments within two business days. A future return protocol must use
the actual SEC acceptance timestamp, enter no earlier than the next eligible market session, and
report pre/post-rule stability. It cannot assume that filing delay or information freshness is
constant over 2010-2025.

## Requirements beyond this gate

- A locked parser must distinguish concrete Item 4 activism from boilerplate and transactional,
  family, compensation, creditor, and post-merger ownership.
- Reporting-person lineage, groups, amendments, ownership percentages, derivatives, exits, and
  amendments changing purpose must be versioned point-in-time.
- Any return identity requires terminal/delisting treatment, halts, borrow, costs, ADV capacity,
  beta/sector/momentum controls, DSR/PBO, correlation, stress, and fixed ALPHAC book-delta gates.
- Alpaca is not needed for metadata or research. It becomes relevant only after a candidate clears
  research and is approved for isolated shadow execution.

## Primary references

- SEC access and full-index documentation:
  https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- SEC beneficial-ownership amendments:
  https://www.sec.gov/newsroom/press-releases/2023-219
- SEC adopting release:
  https://www.sec.gov/files/rules/final/2023/33-11253.pdf

## Locked v1 result

The v1 audit is `DATA_GATED`. It found 21,162 unique legacy-form accessions through 2024 and
downloaded all 150 available frozen headers. Parser v1 incorrectly expected
`CENTRAL-INDEX-KEY`; real headers use `CIK`. That implementation defect is preserved in
`result_parser_v1.json`. Parser v2 corrected only the declared SGML field spelling and then reached
100% subject/filed-by/acceptance lineage.

The corrected run exposed three source assumptions that still fail v1:

- the structured form transition replaces `SC 13D` with `SCHEDULE 13D`, leaving zero exact legacy
  initial forms in 2025 and only 150 rather than 160 frozen headers;
- 20,775 accessions appear twice in the global index because the filing is associated with both
  subject and reporting-owner CIKs; comparing one arbitrarily retained index CIK with `FILED-BY`
  therefore reaches only 36.67%, although the filed-by CIK is present in the full associated CIK
  set for 100% of sampled filings; and
- only 40% of the unrestricted ten-per-year global sample maps to one contemporaneous licensed
  domestic-common ticker, below the locked 80% gate.

No field threshold or form family is changed inside v1. A separately declared schema-aware v2
protocol may use both official initial-form names, accession-level association sets, and a larger
sample to test absolute investable coverage. V1 spent zero return identities.

Machine-readable v1 result:
`artifacts/feasibility/active_ownership_13d/result.json`.

