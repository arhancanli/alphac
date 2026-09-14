# ALPHAC: Sharpe 2 and 14+ sleeves research phase

Superseded target notice, September 12: the owner now specifies **15+ qualified sleeves**, **combined-portfolio Sharpe above 2** and **maximum drawdown at most 11%**. See [LONG_TERM_GOALS.md](LONG_TERM_GOALS.md). The earlier narrative below is preserved as history.

The owner requests a portfolio Sharpe of 2 and at least 14 qualified economic
return sources. We interpret Sharpe 2 as a forward, net-of-cost aspiration.
Neither target is achieved. The existing canonical contract still records a 1.5
forward headline target; that historical contract and its published backtest
support band are not silently restated here. Admission thresholds remain intact.

## What qualifies

A name, new ticker, different venue or modified holding period does not create
an independent sleeve. The source audit must include the active book and all
retired/tested families. A family needs publication-timed data, executable costs,
a frozen trial identity, walk-forward results and measurable incremental book
benefit. Failed trials stay in the denominator.

Evaluate portfolio Sharpe after costs, uncertainty, stressed dependence,
capacity, turnover and concentration. Preserve the existing 756 OOS-observation
minimum and correlation/DSR/PBO gates; report effective event counts separately
for sparse monthly strategies. Do not inflate evidence with repeated daily
marks of the same trade. Do not increase leverage to manufacture a Sharpe gain.
The objective is useful independent return sources, not merely reaching 14 rows.

## This screen and next work

Update: [the deeper source review](BREADTH_SOURCE_REVIEW.md) supersedes the
initial screening stages below. Agriculture now has a 2015–2025 index audit;
FDA has a targeted schema audit; convertible return testing is parked.

| Lead | Current evidence | Next concrete deliverable |
|---|---|---|
| Agricultural forecast revisions | Official August 2026 report and August 2024 archive report retrieved and hashed | Release-index manifest with original vintages, crop years, units and timestamp exceptions |
| Drug exclusivity transitions | FDA API sample retrieved; current endpoint works | Historical publication-vintage and product/issuer/revenue mapping feasibility |
| Convertible issuance pressure | Original researcher-hosted paper located; full review incomplete | Dated terms, executable quotes, borrow and financing access review |

These are provisional leads, not three admitted or proven-independent families.
They join the existing 40-family/240-cell atlas and three earlier frontier leads;
those atlas counts are not changed by this screen. Prior family overlap remains
a required audit. Agricultural revisions receive the next source-collection
priority because an official historical archive was successfully reached.

[USDA](https://www.usda.gov/about-usda/general-information/staff-offices/office-chief-economist/commodity-markets/wasde-report)
lists monthly release dates and publishes report files. Its consolidated CSV
is updated the day after release, so it cannot be assumed available at the
report's release instant. We retrieved the August 2026 text report. Four inferred
older direct URLs failed; the [official archive](https://esmis.nal.usda.gov/publication/world-agricultural-supply-and-demand-estimates?page=2)
then resolved the August 2024 report. That disproves the inference that a failed
URL means missing historical data. Other sampled years remain unverified.

[FDA](https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files)
provides product, patent and exclusivity files and a monthly-updated JSON API.
Our one-record sample validates connectivity only, not completeness or historical
availability. Patent expiry must not be treated as a guaranteed competition
start date or a trading recommendation. Issuer mapping and revenue exposure
require their own dated sources.

[The researcher-hosted convertible-arbitrage paper](https://users.nber.org/~confer/2006/mmf06/tookes.pdf)
investigates convertible arbitrage and its price/liquidity effects. It is a
mechanism lead, not verified evidence for an executable ALPHAC implementation.
[FINRA](https://www.finra.org/finra-data/fixed-income/about-trade-activity)
clarifies that TRACE disseminates executed trades rather than quotes. Treating
those trades as firm executable bids/offers would invalidate a cost model.

## Deliverables and accounting

Local receipts: `evidence/breadth-source-screen/manifest.json`,
`wasde-historical-probe.json`, and `wasde-archive-recovery.json`. No prices were
opened, return trial reserved, return computed or sleeve admitted in this phase.

Next: complete the agricultural release/units/vintage manifest; screen eligibility
of FDA historical vintages; preserve the convertible lead behind execution and
overlap gates. Keep the existing FX, Treasury buyback and leveraged-ETF leads
under their prior cost/data/identity restrictions. Do not revive killed variants
or bypass the independent manual-label requirement for corporate equity supply.

The AlphaForge restart continues separately. Dedicated credentials now work;
the clock probe after the owner's settings update still fails. Research can
proceed, but no paper activation or improved performance is claimed.

## Source-feature reconstruction update

See `WASDE_RECONSTRUCTION.md` for the 109-report extraction and remaining
format/version/timing gaps. No return trial or admission has occurred. The
owner's later API/MCP service direction is recorded in `PRODUCT_VISION.md`;
algorithm improvement remains the current priority.
