# Repurchase and issuance flow: literature dossier

**Reviewed:** 2026-08-16  
**Research state:** source reviewed; returns unopened  
**Decision:** advance only to a key-free SEC data-feasibility audit inside the already-tested
`corporate_equity_supply` family; this cannot count as a new independent sleeve

## Abstract

The literature supports a real economic family around corporate equity supply. Net share
issuance has predicted lower subsequent cross-sectional returns, while repurchase research finds
that announcements are optional rather than commitments and that actual repurchases contain
different information from authorizations. That distinction is central to this candidate: ALPHAC
will not trade press-release authorizations. The proposed identity uses only completed repurchases
and completed issuance known from accepted filings, then neutralizes size, value, profitability,
investment, momentum, sector, and broad issuance exposure.

The evidence does not establish a deployable edge. Several studies show that issuance-related
returns share exposures with broader investment and mispricing factors, many published anomalies
fail modern replication hurdles, and trading costs reduce anomaly profitability. The correct next
step is therefore a no-return audit of SEC filing-time coverage, taxonomy stability, amendment
handling, and Item 703 extraction. Return testing remains prohibited until that audit passes and a
single family-wise identity is preregistered.

## Key papers and official sources

1. [Pontiff and Woodgate, “Shares Outstanding and Cross-Sectional Returns”](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=679143)
   reports that post-1970 changes in shares outstanding predict the cross-section of US returns.
   This motivates equity-supply measurement, but the paper's broad share-count measure can mix
   repurchases, issuance, stock compensation, splits, and acquisitions.
2. [McLean, Pontiff, and Watanabe, “Share Issuance and Cross-Sectional Returns: International Evidence”](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1008312)
   finds issuance predictability across 41 countries and reports that non-US evidence is driven
   more by weak returns after issuance than strong returns after repurchases. This argues against
   assuming symmetric long and short legs.
3. [Grullon and Michaely, “The Information Content of Share Repurchase Programs”](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2004.00645.x)
   finds no post-announcement operating-performance increase, but documents lower systematic risk
   and cost of capital. A repurchase signal may therefore proxy for changing risk rather than
   mispricing.
4. [Oded, “Why Do Firms Announce Open-Market Repurchase Programs?”](https://academic.oup.com/rfs/article-pdf/18/1/271/24421535/hhh004.pdf)
   emphasizes that an authorization is not a commitment and some announced programs execute no
   purchases. This is why the candidate is based on completed activity.
5. [Busch and Obernberger, “Actual Share Repurchases, Price Efficiency, and the Information Content of Stock Prices”](https://academic.oup.com/rfs/article-abstract/30/1/324/2669974)
   studies manually collected actual repurchases and reports improved price efficiency and lower
   idiosyncratic risk, especially in down markets. It supports separating actual execution from
   authorization while warning that market-state interactions matter.
6. [Stambaugh and Yuan, “Mispricing Factors”](https://academic.oup.com/rfs/article/30/4/1270/2965095)
   shows that net stock issues and composite equity issues can be absorbed by broader correlated
   anomaly clusters. ALPHAC must residualize and test incremental book contribution.
7. [Novy-Marx and Velikov, “A Taxonomy of Anomalies and Their Trading Costs”](https://academic.oup.com/rfs/article-abstract/29/1/104/1844518)
   shows that costs reduce anomaly profitability and that buy/hold spreads can reduce turnover.
   The eventual protocol must include asymmetric entry/hold bands and realistic short-side costs.
8. [Hou, Xue, and Zhang, “Replicating Anomalies”](https://academic.oup.com/rfs/article/33/5/2019/5236964)
   reports broad replication failure under value weighting, microcap controls, and multiple-test
   hurdles. This supports NYSE-style breakpoints, liquidity floors, family-wise trial accounting,
   and publication of a null.
9. [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
   documents key-free submissions and Company Facts APIs, accession and filing metadata, and the
   nightly bulk archives. Company Facts is usable only with filing-time and accession lineage;
   ex-post frames are not a point-in-time backtest by themselves.
10. [SEC Item 703 pre-amendment text](https://www.sec.gov/files/corpfin/pre-amendment-item-703.pdf)
    requires monthly issuer-purchase tables in periodic reports, including actual shares purchased,
    average price, plan purchases, and remaining authorization. The SEC's later daily-data rule was
    [vacated in December 2023](https://www.sec.gov/newsroom/whats-new/further-announcement-regarding-share-repurchase-disclosure-modernization-rule),
    so the feasibility audit cannot assume the vacated disclosure format exists.

## Consensus and contradictions

- Corporate equity supply is economically motivated, but the long repurchase and short issuance
  legs need not be mirror images.
- Completed repurchases are a cleaner identity than authorizations, but reporting is delayed and
  heterogeneous.
- Much of the apparent return spread may be shared with investment, profitability, value,
  momentum, and broad mispricing factors.
- Small and illiquid stocks can dominate published anomalies; executable value-weighted evidence
  is the relevant standard.
- Filing amendments, cumulative year-to-date XBRL contexts, custom tags, stock compensation,
  splits, mergers, and tender offers can all create false flow unless explicitly reconciled.

## Open questions

1. What fraction of issuer quarters exposes completed repurchases through stable standard tags?
2. Can Item 703 tables be extracted with high precision without future filings repairing earlier
   history?
3. Can completed issuance be distinguished from stock compensation, acquisitions, splits, and
   other non-cash share changes?
4. Does any eventual residual survive post-publication years, costs, borrow, delistings, and
   correlation to AlphaMax?
5. Is the economically defensible identity long net repurchasers and short issuers, or only the
   issuance leg? The feasibility audit cannot answer this and must not select a sign.

## Rerun inputs

```text
workflow: firecrawl-research-papers (primary-source fallback; API key unavailable)
topic: completed corporate repurchases versus issuance as a cross-sectional return source
target_count: 10
output: markdown literature dossier and no-return feasibility decision
```
