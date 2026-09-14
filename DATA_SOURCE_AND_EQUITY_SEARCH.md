# Data-source decision and equity sleeve screen — 11 September 2026

For the fixed agricultural execution sample, keep Databento as the first choice.
This is a project-specific judgment: our credential works, compatible schemas
are listed, and the freshly quoted sample is $5.9667. Full retrieval returned
402 account_insufficient_funds; a one-record diagnostic succeeded but provides
no execution validation. Metadata quotes do not guarantee future cost or quality.
No full-sample files were downloaded. Do not repeat requests until budget is
resolved. The Databento portal was opened in Safari.

The provider's billing guide describes pay-as-you-go and historical monthly
limits. The owner should inspect balance/credits and usage settings and make
at least $10 of remaining historical budget available for this bounded sample.
This is not a request to enable unlimited spending. Current billing state beyond
the API rejection was not inspected.
[Databento billing guide](https://databento.com/docs/portal/billing).

CME DataMine is the direct-exchange fallback. Its documentation lists historical
market depth and top-of-book products. The product coverage, delivery format,
license and price for our precise windows still need confirmation; there is no
basis here to claim it is cheaper. We have not placed an order or contacted sales.
[CME DataMine](https://www.cmegroup.com/datamine.html),
[CME support and coverage](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457319709/CME%2BDataMine%2BSupport).

Use existing Sharadar for daily equity prices, fundamentals and corporate-action
work. Existing daily grain contracts can support slower-frequency controls, not
intraday fills. The last inventory found 8,436 equity-price partitions and 8,082
fundamental partitions; this does not certify quality across them. Contract
identity also requires care: 145 of 170 observed grain symbol strings map to
multiple instrument IDs in the daily lake. Symbols alone are not persistent
contract identifiers. Evidence is in `evidence/wasde-market-feasibility/`.

A new Polygon capability probe requested one GOOG quote during 2025-08-12 and
one unadjusted minute aggregate for the same day. Historical quotes returned
403; the minute-aggregate request returned 200 with one record. This proves
only these endpoint/date outcomes, not comprehensive plan coverage or a
particular subscription tier. No quote access is assumed from a working
reference endpoint. Receipts are in `evidence/equity-breadth-screen/`.

## Candidates matched to the existing data

### 1. Share-class relative pricing — first identity feasibility priority

Schultz and Shive's research studies dual-class price discrepancies and trading.
The paper is a lead, not evidence that today's pairs are profitable. The author
profile and SSRN abstract were located; the full SSRN page returned 403 in this
pass. Full methods review remains outstanding.
[Research record](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1338885),
[Author's publication listing](https://mendoza.nd.edu/mendoza-directory/profile/paul-schultz/).

We screened the entire local TICKERS archive without opening price returns.
Same-CIK/current-name, different primary/secondary identifiers and overlapping
price-date bounds produce 186 candidate pairs across 168 issuer groups after
heuristic unit/shell exclusions. This is a provisional document-review list,
not 186 arbitrage opportunities or an as-of historical universe. Current issuer
metadata folds in renamed companies and former SPAC units; unit-like ticker
suffix exclusions can also discard legitimate securities. The surviving pairs
still require dated legal-rights, conversion-ratio, dividend and identity checks.

Do not assume equal prices or a 1:1 hedge: voting rights and conversion ratios
can differ. Executable synchronized quotes, borrow and two-leg fill risk remain
required. Overlap review must include existing price-reversal/statistical-arbitrage
work and securities-lending supply. No new-family independence is established.

### 2. Expected earnings-announcement demand — calendar feasibility priority

Lamont and Frazzini report an announcement premium associated with announcement-
period trading volume. This motivates a scheduled-demand hypothesis distinct
from reading earnings narratives. We reviewed the primary abstract; the full
NBER PDF request returned 403. Predictable event risk could explain returns,
and modern net performance is untested.
[Primary research](https://www.nber.org/papers/w13090).

Existing daily prices and fundamentals help, but the SF1 header does not provide
a historical announced earnings schedule. Fiscal period, report period, datekey
and lastupdated are not interchangeable with a calendar known before the event.
Establish dated expected schedules or a separately specified forecast from
historically available inputs. Require event-risk controls, costs and overlap
against analyst revision and prior earnings-family work. Do not revive the
killed earnings-narrative identity under this title.

### 3. Intraday recurring flow — price-family overlap review first

Heston, Korajczyk and Sadka report return continuation at matching half-hour
intervals on successive trading days, alongside short-horizon liquidity effects.
Only the primary abstract was reviewed here. This is not a fresh net-of-cost
replication and may overlap prior intraday flow/momentum research.
[Primary paper record](https://arxiv.org/abs/1005.3535).

Polygon minute bars provide a possible initial data route, but full date coverage,
exchange calendars, corporate actions, stale-bar handling and executable quotes
are unverified. Review lineage against prior momentum/reversal and leveraged-ETF
flow probes before any formal trial. Timing improvements inside an existing
sleeve are useful but do not create another independent sleeve.

## Research already counted

The local quality and value/investment audits record 11 and 13 historical
identities respectively, without established admission. Gross profitability,
accruals and asset growth are therefore not new discoveries. Calendar-seasonality
and momentum variants also have prior specifications and results history.
Customer/supplier propagation already has a failed named-customer extraction
gate; ordinary price/fundamental access does not repair that graph. All these
histories stay in the denominator. No old family was reopened in this pass.

The target remains forward net Sharpe 2 and at least 14 qualified independent
sources, with canonical gates preserved. This pass adds three investigation
leads, zero return trials and zero admissions. API/MCP product work stays deferred.

## Subsequent budget fix

The owner resolved the Databento budget setting. All nine fixed sample
requests subsequently completed; see `WASDE_MARKET_SAMPLE_RESULTS.md`. The
earlier rejection remains historical evidence, not the current sample status.
