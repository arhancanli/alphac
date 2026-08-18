# Tender-offer spread — official-source document feasibility protocol

**Declared:** 2026-08-15 before downloading or parsing any document in this protocol.
**Stage:** document/source engineering only. Prices, returns, spreads, and outcome labels are
forbidden; zero return identities are spent.

## Why this is a separate protocol

The aggregate merger-arbitrage metadata protocol failed its locked prior-announcement coverage
gate and remains `DATA_GATED`. That result is not repaired or replaced here. It revealed a
structural distinction worth testing separately: target tender recommendations use the dedicated
`SC 14D9` disclosure path, while definitive merger proxies do not. This protocol therefore tests a
narrower cash tender-offer mechanism with its own future identity and explicit exclusions.

The source sample is frozen before this declaration in
`artifacts/feasibility/merger_arbitrage/locked_document_sample.csv`. Use exactly the 100 `SC 14D9`
rows: ten deterministic target filings in each calendar year from 2016 through 2025. Do not replace
failed or difficult documents and do not select on subsequent price behavior.

## Economic and source boundary

- Candidate mechanism: convergence of an announced all-cash tender price to the target price while
  bearing financing, regulatory, minimum-tender, timing, proration, and break risk.
- Earliest candidate state is the SEC acceptance time of the target `SC 14D9`; the later of that
  timestamp and the bidder's linked tender filing will govern any future return protocol.
- Exchange offers, mixed consideration, CVRs, appraisal trades, odd-lot strategies, partial offers,
  hostile offers opposed by the board, and offers lacking a unique per-share cash amount are out.
- `SC TO-T` bidder linkage, amendments, expiration extensions, withdrawals, completion, terminal
  returns, and borrow remain unresolved production requirements. This document does not authorize
  a backtest.

## Locked deterministic parser

Convert each immutable primary filing document to normalized visible text with
`sec-filing-sections-v2`. Extract the shortest valid span beginning at Item 4, Solicitation or
Recommendation, and ending at Item 5, Persons/Assets Retained, or the next numbered item. Within
that span:

1. retain only strict cash-per-share clauses containing a dollar amount and both a consideration
   phrase (`offer price`, `purchase price`, `consideration`, or `price of`) and a per-share phrase;
2. canonicalize dollars to cents, reject values below $1 or above $1,000, and preserve every
   distinct candidate rather than choosing the largest or first;
3. declare a unique price only when exactly one distinct strict candidate remains;
4. classify the board posture as `recommend_accept`, `recommend_reject`, `neutral_or_unable`, or
   `unresolved` using fixed phrase families; conflicting phrase families are `unresolved`;
5. preserve raw/document hashes, source URL, parser version, section hash, candidates, and excerpts.

## Locked machine-coverage gates

All must pass on the 100-document sample:

- 100/100 immutable primary documents download successfully;
- Item 4 is extracted from at least 90%;
- at least 85% of extracted Item 4 sections contain one or more strict cash-per-share clauses;
- at least 80% of extracted sections produce exactly one canonical price;
- no more than 10% produce multiple distinct strict prices; and
- at least 80% receive a non-`unresolved` recommendation classification.

Failure is `DATA_GATED`; thresholds and regexes are not revised after seeing aggregate results.

## Frozen accuracy audit

Before aggregate parser results are viewed, select three documents per year by the existing
`sample_rank`, producing a 30-document audit set. A human label must be entered from the source
document for (a) unique cash price or explicit ineligibility and (b) recommendation posture.
The label file stores source hashes and cannot omit hard documents.

Only a blind score of at least 95% exact price/ineligibility agreement and 90% exact recommendation
agreement can pass document feasibility. Until all 30 labels exist, the decision is
`HUMAN_AUDIT_REQUIRED`, never pass. The audit spends no return identity.

## Requirements still needed after a pass

A separate return preregistration must lock bidder/target linkage, amendments, entry timing,
completion and break labels, terminal/delisting treatment, halts, costs, borrow, capacity, hedge,
deflation, PBO, and correlation gates. Licensed point-in-time M&A data may still be required.
Alpaca is not useful at this stage.

## Primary source

- SEC EDGAR APIs and filing archives: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

## Locked result

All 100 documents downloaded successfully and Item 4 extraction reached 94%, passing the 90%
gate. Strict cash-per-share clause coverage reached 85.11% of extracted sections, narrowly passing
its 85% gate. The fields needed to define a trade did not pass:

- only 10.64% of extracted sections produced exactly one canonical price, versus 80% required;
- 74.47% produced multiple distinct strict prices, versus at most 10% allowed; and
- only 22.34% produced a non-conflicting recommendation classification, versus 80% required.

Ambiguity is broad rather than a single-year format break: the median strict candidate count ranges
from 1.5 to 5.5 across the ten annual cells. Item 4 contains valuation references and repeated or
amended consideration amounts that a fixed regex cannot safely turn into historical deal state.
The parser is not revised after observing this result, and the frozen human-label stage is not used
to rescue failed machine gates.

**Decision:** `DATA_GATED`. Zero prices or returns were loaded and zero return identities were
spent. The 100-document, hash-addressed corpus remains useful for a future independently labelled
extractor or licensed point-in-time M&A feed.

Machine-readable result:
`artifacts/feasibility/tender_offer_spread/result.json`.
