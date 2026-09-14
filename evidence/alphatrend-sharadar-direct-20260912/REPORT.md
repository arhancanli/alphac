# Sharadar direct access verified and full ETF history acquired

The new direct Sharadar credential successfully returned six SPY daily rows from
January 2–9, 2004. The legacy Nasdaq credential was not overwritten. No credential
value is included in logs, request metadata or this evidence packet.

A subsequent bounded acquisition made 34 GETs: funds and actions for each of the
17 AlphaTrend ETFs, January 1, 2003–September 11, 2026 inclusive. All 34 succeeded
without retries or redirects. Each response is below its 10,000-row limit and
passes symbol/date-scope checks. Exact CSV responses, local receipt times and
SHA256 digests are retained, alongside parsed parquet copies.

- 93,444 daily fund-price rows across all 17 ETFs.
- 1,370 action rows: 1,348 dividends, 10 splits, 10 listings and two ticker changes.
- Zero missing or unexpected XNYS sessions relative to the requested start and
  each ETF's first-price date in the preserved ticker metadata.
- Recent raw-close overlap covers all 493 captured SIP symbol/session pairs;
  maximum absolute provider difference is 0.609793 bp.

Sharadar supplies split-adjusted OHLCV and an unadjusted close. Raw OHL and volume
were imputed with the vendor's documented formulas: OHL times closeunadj/close,
volume times close/closeunadj. The unadjusted close is kept directly. These are
vendor-imputed historical raw coordinates, not independently recovered tape
prints. [Vendor formula documentation](https://sharadar.com/docs/faqs).

The first conversion flagged 12 OHLC boundary differences. Inspection showed
valid original vendor OHLC and floating errors of 1.42e-14–2.84e-14 dollars. A
separate v2 parquet repairs only these boundary discrepancies within an explicit
8-ULP limit; every delta is retained in normalization_review.json. Open, close,
volume and keys are unchanged. Original downloads and first conversion remain.
One zero-volume bar (UUP, March 15, 2007) is retained and flagged. Its treatment
must be explicit in candidate eligibility/execution; no volume was invented.

This resolves the missing long-history access/acquisition blocker. It does not
establish historical first-publication timing, payment-date coverage, exact
Yahoo-candidate equivalence or final engine integration. Current-vintage action
records must not be stamped as historically observed. The frozen candidate and
production lake remain unchanged. No strategy returns, IC comparison or new
hypothesis was computed; union remains 238. No paper producer was activated.

Next: validate action units, effective dates and split/dividend consistency on the
acquired prefix, define the zero-volume policy, then integrate separated raw
execution and synthetic feature/explicit label paths before registering the new
candidate and evaluating returns.
