# Treasury source coverage decision

September 12, 2026. GovPX is the strongest documented match among the reviewed products for the proposed Treasury security universe. It is suitable for a metadata/coverage inquiry, not yet for purchase or an executable-return claim. Public descriptions do not establish our entitlement, exact CUSIP coverage, quote quality or financing availability.

| Source | Documented fit | Remaining limit | Decision |
|---|---|---|---|
| GovPX intraday | Bills, notes, off-the-run and WI coverage; history extends before our study | Indicative top-of-book; actual voice markets conditional; per-security history varies | First coverage inquiry |
| GovPX EOD | Bills and active/off-the-run notes; settlement and Treasury-type fields | Indicative snapshots; delivered after snapshot time; no firm size evidence | Possible reference/valuation supplement |
| BrokerTec | Historical benchmark note books | Listed tenors do not establish bill or off-the-run coverage | Execution supplement only if scope is confirmed |
| LSEG Tick History | Historical fixed-income interfaces and contributor data | Exact security, contributor, unit, quote-firmness and entitlement coverage unknown | Alternative inquiry |

CME documents GovPX history from January 2009 with security-specific variation. Its FAQ calls the top-of-book indicative; separate voice bid/ask and size fields apply when actual markets are available. That distinction prevents treating every populated quote as executable. These catalog statements support investigating coverage, not a conclusion that our 514 securities are present at every required instant. [GovPX documentation](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457223481/GovPX+Historical+Data).

GovPX EOD includes 3, 4 and 5 p.m. snapshots, delivered around thirty minutes later. A snapshot may describe a historical valuation time without having been available to a strategy then. The published EST label and offset-bearing example also need a documented daylight-saving convention. The EOD schema distinguishes bill cash-price fields and active/off-the-run/WI types; conversions and benchmark identity still require validation. [EOD documentation](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457223587/GovPX+End+of+Day+Historical+Data).

BrokerTec's listed note/bond tenors do not establish the bill hedge or continued coverage after benchmark replacement. Full-book history is documented before 2013, but top/depth history starts in 2014; its table and FAQ disagree on the month. [BrokerTec documentation](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457421032). LSEG documents historical fixed-income delivery through Tick History and other interfaces, but its broad catalog alone cannot resolve our instrument-level requirements. [LSEG fixed-income catalogue](https://www.lseg.com/en/data-catalogue/fixed-income).

## Concrete scope

The source-bound proposal has 305 phases and 1,830 entry/exit leg requests: 610 each for bills, two-year notes and ten-year notes. The preliminary inventory contains 305 bill, 156 two-year and 53 ten-year CUSIPs, spanning January 28, 2013 through January 7, 2026. Counts are before simultaneous-request deduplication and exclude the additional daily marks, coupon/financing records and failed-exit observations needed by a portfolio simulation. Final benchmark verification may change the inventory.

The apparent local CRSP match is not a Treasury database: its Parquet schema contains ticker, CIK, filing and accounting-tag fields under lake_sec/assets. Only schema metadata was read. The earlier 122-path filename inventory found reusable Treasury event/schedule records, but it cannot exclude differently named or external datasets. No relevant cash-market entitlement has been verified.

## Required response before acquisition

The prepared inquiry asks for a metadata-only CUSIP/date coverage manifest; benchmark changes and WI/reopening treatment; exact quote-field types and units; indicative versus firm/voice availability; delivery versus observation timestamps; historical cutoffs; repo/borrow sources; gap disclosures; licensing and price. We need explicit unknowns rather than broad product assurances. No sample prices, external messages or paid requests were sent.

Keep the Treasury strategy pending source qualification. Public documentation has resolved where to ask, but not whether the execution data exists for the locked implementation. The next independent task is the historical Treasury trading/settlement-calendar audit, which can expose impossible 16:00 decisions without purchasing quotes. No return hypothesis was spent; union remains 240. Sharpe 2 and 14+ qualified sleeves remain unmet.
