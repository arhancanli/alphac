# Earnings-narrative change — key-free corpus feasibility protocol

**Declared:** 2026-08-15, before downloading the sampled filing corpus and before reading any
security return associated with a filing.  
**Stage:** data engineering only; this stage can reject or data-gate the candidate but cannot
promote it into ALPHAC and spends no return-hypothesis identity.

## Economic prior

The candidate asks whether a point-in-time change in issuer language and disclosed operating
risks contains information that is not already represented by earnings surprise, sector, or price
momentum. The first implementation is deliberately lexical and deterministic. An embedding or
language-model score would create another hypothesis and is outside this feasibility stage.

The published *Lazy Prices* study reports that changes in regular 10-K and 10-Q language predict
future firm outcomes and returns, with risk-factor, litigation, and executive-team changes among
the informative components. That is a prior, not Canli Capital evidence. We will not copy its
reported return into our record or treat a corpus audit as replication.

## Official data contract

- Filing identity and availability: SEC `data.sec.gov/submissions/CIK##########.json`.
- Immutable source document: primary filing document under the accession-number directory in
  `www.sec.gov/Archives/edgar/data/`.
- Point-in-time timestamp: SEC `acceptanceDateTime`, not fiscal period end and not a later scrape
  time. A future return test must execute no earlier than the next tradable session after accepted
  dissemination.
- Forms in this audit: unamended 10-K and 10-Q only. Amendments, 20-F, 40-F, 8-K exhibits, proxy
  statements, and earnings-call transcripts are separate data contracts.
- Issuer identity: CIK. Ticker is display and price-link metadata only; ticker changes never join
  filing histories.

## Locked sample

Use the on-disk Sharadar ticker reference solely to construct a deterministic, non-return sample:
active domestic common stocks first priced by 2010, stratified by sector. Rank eligible issuers
inside each sector by SHA-256 of `sector|CIK` and select the first three. For each issuer, request
up to the three latest unamended 10-Ks and eight latest unamended 10-Qs accepted from 2019 through
2025. No company may be hand substituted after extraction results are observed.

## Deterministic extraction

1. Remove scripts, styles, inline-XBRL hidden content, and markup with a standard-library HTML
   parser while retaining block boundaries.
2. Normalize Unicode, whitespace, and case only for matching. Preserve the extracted readable
   text and its SHA-256 hash.
3. For 10-K, extract Item 1A Risk Factors and Item 7 MD&A. For 10-Q, extract Part I Item 2 MD&A
   and any Item 1A Risk Factors update that is actually present.
4. Search every plausible line-anchored heading occurrence. Pair each start with its nearest
   recognized end heading, reject table-of-contents spans with the minimum-length rule, and among
   valid spans retain the shortest deterministic section. This prevents an earlier prose
   cross-reference from swallowing the real section later in the filing.
5. Build only same-CIK, same-form, same-section chronological pairs. This audit computes token and
   shingle counts but no price, return, label, or predictive statistic.

## Pass / data-gate boundary

The filing-only candidate is feasible for preregistration only if all conditions hold:

1. at least 95% of selected primary documents download and hash successfully;
2. Item 1A extraction succeeds on at least 80% of sampled 10-Ks;
3. MD&A extraction succeeds on at least 80% of sampled 10-Ks and 10-Qs separately;
4. at least 70% of issuers have two or more comparable sections for both 10-K and 10-Q;
5. median extracted section length is at least 500 words and fewer than 5% of comparable pairs
   are exact duplicates; and
6. every accepted row retains CIK, accession, form, report date, filing date, acceptance timestamp,
   source URL, raw-document hash, section hash, and parser version.

Failure does not authorize looser regexes selected on returns. A parser revision must be versioned
and re-audited on this same locked sample. Passing authorizes a separate return preregistration;
it does not authorize a return claim.

## Production requirements not answered here

- Historical earnings surprise with point-in-time estimate vintages, or a preregistered
  announcement-return substitute that does not leak revised consensus.
- PIT sector and universe membership, delistings, corporate actions, spreads, ADV, and borrow.
- A documented policy for late filings, amendments, fiscal-year changes, and multiple accepted
  documents on one day.
- Earnings-call transcripts are optional only for a filing-only hypothesis. Adding transcripts,
  speaker roles, or semantic embeddings later is a new data contract and hypothesis identity.

## Parser-v1 audit finding

The first locked-sample run passed the aggregate thresholds but failed manual boundary review.
Version 1 flattened line boundaries and selected the longest valid span. In several filings that
caused extraction to begin at a table-of-contents entry or an earlier cross-reference and continue
through the real section ending. Its result and section corpus are retained with the
`parser_v1` suffix, but the pass is invalid and cannot authorize return work. Version 2 was fixed
without viewing returns: headings are line-anchored, the nearest end heading is mandatory, and the
shortest valid span defeats earlier cross-references. The same locked issuers and filings must be
re-audited against the unchanged gates.

## Parser-v2 locked result

Version 2 was run on the unchanged sample and passed every declared gate without loading a price
or return:

- 33 issuers across 11 sectors; 361 of 361 selected filings downloaded and hashed;
- 10-K Item 1A extraction 90.82%, 10-K MD&A 93.88%, and 10-Q MD&A 96.96%;
- issuer pair coverage 100.00% for 10-K and 96.97% for 10-Q;
- 477 extracted sections and 373 comparable pairs, with a 7,095-word median section;
- exact-duplicate pair rate 0.54%; and
- complete source lineage on every extracted row.

A second adversarial boundary review inspected deterministic samples, extraction-length tails,
the largest parser-v1/v2 differences, and exact source heading positions. The large FirstEnergy
MD&A observations are genuine sections in unusually long utility filings. The large Eagle Bancorp
v2/v1 differences are corrections: v1 stopped at an internal Item 8 cross-reference, while v2
reaches the actual next heading. No sampled v2 boundary failure was found.

**Decision:** `PASS_TO_RETURN_PREREGISTRATION`. This is a corpus-engineering result only. It spends
zero return hypotheses, makes no alpha claim, and does not authorize promotion or capital.

Machine-readable result:
`artifacts/feasibility/earnings_narrative_change/result.json`.

## Primary references

- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC access and archive paths: https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- Cohen, Malloy, and Nguyen, *Lazy Prices*: https://www.nber.org/papers/w25084
