# SFP access controls and recovered ETF action archive

Seven bounded Nasdaq GETs in this phase, no retries or redirects:

| Control | Result |
| --- | --- |
| SFP unfiltered, one row | ZF price row dated December 31, 2018 |
| SEP AAPL, one row | One price row |
| SFP metadata | Valid schema, ticker/date filters, premium flag, version 2 |
| TICKERS table=SFP, ticker=SPY | SPY recognized; price metadata reaches September 11, 2026 |
| SFP SPY January 2004 without page limit | Zero rows |
| SFP ZF filtered, one row | One row |
| SFP IEF/TLT/QQQ, five-row limit | Zero rows |

These controls establish a functioning key/API path and usable sample table rows.
They do not establish access to the target ETF price history. Removing the page
limit did not solve SPY's empty result; a filtered ZF query works. Limited product
access is a possible explanation, not a confirmed subscription diagnosis. A schema
or ticker catalog is not a substitute for price rows. Stop repeating equivalent
empty probes until account/product access or another input source changes.
Nasdaq separately documents API-key authentication and premium subscriptions:
[authentication](https://docs.data.nasdaq.com/docs/api-and-analysis-tools-for-tables-data),
[getting started](https://docs.data.nasdaq.com/docs/getting-started).

The local ACTIONS.zip was also streamed and matched against all 17 ETF symbols.
1,414 matching records were recovered: 1,384 dividends, 11 splits, 16 listings,
one initiation and two ticker-change records, spanning December 31, 1997–June 18,
2026. These are archived vendor records, not normalized or approved lifecycle
inputs. The schema has date/action/ticker/value but no payment or publication date.
Date meaning, units, split basis and historical completeness require validation.
No assumption of same-day knowledge or immediate settlement was introduced.

Matched records and archive hash are retained. These recovered actions improve
coverage but do not supply the missing long ETF price series. No new strategy
trial, hypothesis, broker order or candidate activation; union remains 238.
