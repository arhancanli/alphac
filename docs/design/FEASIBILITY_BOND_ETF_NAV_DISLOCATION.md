# Bond-ETF NAV dislocation — locked no-return source feasibility protocol

**Short title:** Bond-ETF NAV dislocation: feasibility

**Declared:** 2026-08-16 before collecting issuer page payloads or computing historical coverage.
**Stage:** source and execution-measurement feasibility only. No ETF prices from a market-data
vendor, no TRACE transaction records, no returns, and no signal parameter may be opened.

## Frozen identity boundary

- Instruments: HYG and LQD, representing liquid US high-yield and investment-grade corporate-bond
  ETFs under one issuer disclosure format.
- Research period: 2016-01-01 through 2025-12-31.
- Economic identity: secondary-market correction of a valuation gap after distinguishing stale NAV
  from ETF price discovery. It is not authorized-participant creation/redemption arbitrage.
- Official issuer premium/discount is a source input, not a trade signal and not proof of mispricing.
- A future return protocol, if authorized, must enter no earlier than the next eligible session after
  all prior-day source values are public and must lock hedge, sign, horizon, costs, and stress rules.

## Frozen source routes

1. Fetch and hash the official iShares HYG and LQD product pages. Parse the embedded
   `performance.premiumDiscountChartData` dates and values without requesting ETF market history.
2. Fetch and hash each official `latest-holdings.csv`. This tests current schema only; it cannot be
   counted as historical holdings coverage.
3. Fetch FINRA's official TRACE historical-data information page and verify whether the stated
   transaction-level route requires an agreement/fees. Do not request transaction records.
4. Bind the SEC Rule 6c-11 disclosure requirement as source-contract evidence: recent daily data and
   recent premium/discount charts are not a permanent ten-year archive.

## Locked gates

All are required to advance to a separate licensed-data preregistration:

- issuer premium/discount dates cover at least 98% of XNYS sessions in 2016–2025 for each fund;
- at least one hash-addressed holdings snapshot per month exists for each fund (120 per fund), with
  CUSIP/identifier, quantity, weight, and an as-of date known before the next session;
- a transaction-level TRACE route with timestamps, price, size, corrections/cancellations, and
  stable bond identifiers is contractually available for the full period;
- constituent valuation timestamps and evaluated-price methodology are available point-in-time;
- ETF quote/trade data can support NBBO spread, latency, partial-fill, impact, and closing-auction
  stress, while underlying bonds support stale-print and no-trade treatment.

Failure of any gate is `DATA_GATED`. Passing does not authorize returns. Thresholds and routes are
not modified after collection. iNAV is not accepted as executable underlying value without a
separate stale-input audit.

## Machine outputs

- `artifacts/feasibility/bond_etf_nav_dislocation/issuer_premium_discount_manifest.parquet`
- `artifacts/feasibility/bond_etf_nav_dislocation/source_probe_manifest.parquet`
- `artifacts/feasibility/bond_etf_nav_dislocation/result.json`

## Claim boundary

This protocol measures source sufficiency only. It cannot establish a gap sign, threshold, return,
Sharpe ratio, drawdown, correlation, capacity, or sleeve-admission claim.

## Locked result

Both official issuer pages and current holdings files were retrieved and hash-bound successfully.
The embedded premium/discount series contains 249 target-period dates for each fund against 2,514
XNYS sessions in 2016–2025: 9.9045% coverage for HYG and LQD, far below the locked 98% gate. The
series begins on 2025-01-02, consistent with recent-disclosure availability rather than a permanent
ten-year archive. Each public holdings route supplied one current snapshot, versus 120 monthly
snapshots required per fund.

FINRA's official metadata confirms that transaction-level historical TRACE data exists through an
agreement and paid delivery route. No TRACE transaction was requested. Public issuer pages do not
supply the missing historical valuation timestamps or synchronized ETF/bond execution state needed
to distinguish stale bond marks from ETF mispricing.

**Decision:** `DATA_GATED`. Zero ETF market records, underlying bond transactions, returns, signs,
thresholds, horizons, or portfolio statistics were opened, and zero return identities were spent.

Machine-readable result:
`artifacts/feasibility/bond_etf_nav_dislocation/result.json`.
