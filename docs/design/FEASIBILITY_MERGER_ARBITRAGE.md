# Merger arbitrage — official-source metadata feasibility protocol

**Declared:** 2026-08-15 before computing form counts, timeline coverage, or downloading any
sampled merger document. **Stage:** filing metadata and source engineering only; no prices,
spreads, outcomes, or return labels may be loaded, and zero return identities are spent.

## Mechanism boundary

The candidate is the contractual spread on announced acquisitions of US-listed public targets,
updated only when a filing or regulator release becomes public. It is not announcement drift,
value, momentum, quality, or an ex-post list of completed deals. The initial return identity, if
eventually authorized, will be cash-only deals; stock exchange ratios, collars, CVRs, appraisal
rights, and hostile/rumored transactions require separate contracts and identities.

## Official-source discovery contract

- Target-side high-precision anchors: unamended SEC `DEFM14A` and `SC 14D9` filings. A definitive
  merger proxy or target recommendation filing is used to discover a transaction, never as its
  historical trade-entry timestamp.
- Announcement reconstruction: the same target CIK's latest preceding unamended 8-K carrying Item
  1.01 within 60 calendar days. The SEC acceptance timestamp is the earliest possible availability;
  the attached agreement/press release must confirm that it is the same transaction.
- Outcome/update reconstruction: target 8-K Item 2.01 or 1.02, amendments to the anchor forms,
  merger proxies, and tender filings. Metadata proximity is a feasibility measure, not a final
  deal linker.
- Tender-offer cross-check: `SC TO-T` is counted but cannot be joined to a target by filer CIK,
  because the bidder commonly files it. Target identity must come from document-level subject-CIK
  or CUSIP lineage.
- Regulatory enrichment: FTC HSR Early Termination and DOJ/FTC case publications are optional
  state updates, not the sole deal universe. The FTC API requires a free data.gov key and has a
  structural coverage gap around the categorical early-termination suspension beginning in 2021.
- Issuer universe and survivorship: the existing 9,124-CIK domestic-common-stock manifest,
  including delisted ticker histories. CIK is the issuer key.

## Locked metadata audit

Read only the already cached official SEC submissions JSON pages under
`data/raw/sec_10k_narrative/submissions`. Select exact unamended forms from 2016-01-01 through
2025-12-31. Deduplicate on `(CIK, accession)`. For each target-side anchor, measure whether a prior
Item 1.01 8-K exists within 60 days and whether a later Item 2.01 or 1.02 8-K exists within 540
days. Do not inspect prices or choose windows from coverage results.

Create a deterministic future document sample by sorting each `(year, form)` cell on SHA-256 of
`form|CIK|accession` and retaining at most 10 anchors. The sample is frozen before any document
content is parsed.

Metadata feasibility passes only if:

1. every accepted anchor has CIK, accession, form, filing date, acceptance timestamp, primary
   document and immutable archive URL;
2. at least 80% of target anchors have a preceding Item 1.01 8-K inside the locked 60-day window;
3. at least 70% have a later Item 2.01/1.02 8-K inside 540 days; and
4. every year from 2016 through 2025 contains at least 20 target-side anchors.

Passing authorizes a separate document-extraction feasibility protocol. It does not authorize a
spread backtest. Failure cannot be repaired by expanding the windows after observing coverage.

## Production questions not answered here

- Exact cash consideration, dividends, ticking fees, financing, outside date, termination fee,
  vote/tender conditions and all amendments must be versioned from source documents.
- A dedicated historical delisting/terminal-return field is required for promotion. The local
  Sharadar lake contains delisted histories but no CRSP-style delisting-return field.
- PIT borrow availability/fees, trading halts, proration, CVR valuation and foreign/regulator
  timelines are absent. Alpaca is execution infrastructure, not historical deal-state data.
- A passing free corpus that lacks these fields can become `DATA-ESCALATE`, never silently `ADD`.

## Primary references

- SEC EDGAR APIs and bulk submissions: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC Form 8-K Item 1.01 rule: https://www.sec.gov/files/rules/final/33-8400.pdf
- FTC HSR Early Termination API: https://www.ftc.gov/developer/api/v0/endpoints/hsr-early-termination-notices-api
- FTC early-termination background: https://www.ftc.gov/enforcement/premerger-notification-program/early-termination-notices/about-early-termination-notices
- DOJ Antitrust case filings: https://www.justice.gov/atr/antitrust-case-filings

## Locked result

The offline audit scanned 2,794,953 cached official filing records and found 1,965 target-side
anchors across 1,798 CIKs. Required lineage was complete, every year had at least 145 anchors, and
91.76% had a later Item 2.01/1.02 outcome marker. The locked prior-announcement gate failed:
67.02% had an Item 1.01 8-K within 60 days, below the declared 80% minimum. The miss is concentrated
in definitive merger proxies (61.33%); target tender recommendations reached 86.65%, but that
form-level result cannot be substituted for the failed aggregate gate after observation.

**Decision:** `DATA_GATED`. The 60-day window is not widened, and no return identity was spent.
The 200-row deterministic document sample is retained for a separately declared tender-only or
licensed-deal-database feasibility study, not treated as authorization for a backtest.

Machine-readable result: `artifacts/feasibility/merger_arbitrage/result.json`.
