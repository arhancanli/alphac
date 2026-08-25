# Inflation breakeven relative value — no-return source-feasibility audit

**Short title:** Inflation breakeven relative value: feasibility  
**Author:** Arhan Canli  
**Audited:** 2026-08-22  
**Stage:** forensic source audit after atlas enumeration; not a return preregistration.

## Scope and trial accounting

- Family account: `inflation_breakeven_relative_value`.
- Atlas cells: 2Y/5Y and 5Y/10Y, each at 21d, 63d, and 126d.
- This audit opens no security prices, market returns, portfolio returns, forward labels, signs,
  Sharpe ratios, drawdowns, correlations, or capacity estimates.
- Return hypotheses spent: **zero**. The six atlas cells remain untested.
- Existing source counts were already visible when this audit was written. Its thresholds are
  institutional data requirements, not a claim of preregistered statistical cutoffs.

## Evidence inspected

1. `T5YIE.parquet` and `T10YIE.parquet` from the local macro lake: observation date, value, and
   locally assigned publication date only.
2. `PCPI_first_release.parquet`: vintage CPI values and the flag distinguishing genuine first
   releases from the initial inherited history.
3. The macro-lake metadata and arrival log, to distinguish a current snapshot from preserved
   historical vintages.
4. The repository's data files for any security-level TIPS/nominal-bond history, inflation-swap
   history, cashflows, index ratios, quotes, or total returns.

## Required gates before a return preregistration

All must pass:

1. The chosen signal maturities have at least the contract's three years of aligned observations,
   unique dates, no internal nulls, and conservative availability timestamps.
2. Every maturity named by the chosen universe exists. A 2Y/5Y identity cannot borrow the 10Y
   series and retain its name.
3. Historical values are bound to genuine as-of vintages or an authoritative no-revision
   contract. A current full-history file plus synthetic `observation + 1 business day` timestamps
   does not prove what the historical file contained on that date.
4. Vintage CPI coverage is sufficient and its conservative publication rule is locked.
5. The implementation has security-level cashflows/index ratios and executable price or quote
   history for matched nominal/TIPS baskets, or licensed inflation-swap history. Constant-maturity
   estimates are signal inputs, not executable returns.
6. Bid/ask, financing, duration, carry, seasonality, index lag, deflation-floor treatment, and
   stressed capacity can be modelled from preserved inputs.

## Result

The 5Y and 10Y files are aligned, long, unique, and internally complete. Vintage CPI is also held.
That establishes signal-source depth only.

The 2Y leg is absent. The daily breakeven files are one current historical snapshot, not a
historical-vintage archive. No security-level matched nominal/TIPS prices, cashflows, index ratios,
quotes, total returns, inflation-swap history, or execution-calibration record is present.

**Decision: `DATA_GATED`.** The prior atlas reachability label “obtainable from data already held”
was too broad and is superseded by this audit. No return trial is authorized. A future owner
decision may acquire a lawful point-in-time fixed-income dataset; an ETF proxy would be a newly
named identity and cannot silently rescue this one.

