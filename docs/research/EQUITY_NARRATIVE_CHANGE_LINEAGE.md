# Annual risk-factor narrative stability: a preregistered null

**Author:** Arhan Canli, Founder, System Architect, and Quantitative Researcher, Canli Capital  
**Research system:** ALPHAC / AlphaForge  
**Family key:** `equity_narrative_change`  
**Status:** public research record; not peer reviewed; not an investment solicitation  
**Evidence date:** 2026-08-22

## Abstract

ALPHAC preregistered one test of annual 10-K Item 1A narrative stability before opening the
2016–2025 return window. The locked strategy bought issuers with stable disclosures and sold
issuers with changed disclosures after controlling for filing reaction, momentum, and filing-time
industry. Across 2,514 observations, net Sharpe was -0.0074, DSR 0.0000114, Newey–West t-stat
-0.0242, and maximum drawdown -28.47%. Twelve of 20 research gates passed, but the return, DSR,
stress-cost, short-leg, capacity, mean-zero book-delta, and expected-shortfall gates failed. The
sealed verdict is **KILL**. No sleeve was admitted.

## Hypothesis, literature, and overlap

Material changes to risk disclosures may reveal changing operating or legal conditions before
prices fully adjust. Cohen, Malloy, and Nguyen's *Lazy Prices* provides the prior
([NBER working paper](https://www.nber.org/papers/w25084)); it does not validate ALPHAC's corpus,
signal, or return. The family is an issuer-information mechanism, not a momentum, value, quality,
or generic sentiment sleeve. Exactly one identity was tested, and its failed direction was not
inverted.

The locked signal was five-token-shingle Jaccard stability between each unamended 10-K Item 1A and
its immediate predecessor. Monthly residualization controlled for the filing reaction, 12-1
momentum, and accession-time two-digit SIC. The top residual quintile was long, the bottom quintile
short, each cohort held 63 sessions, and the stock book was hedged with contemporaneous 252-session
SPY betas. Baseline costs were 15 basis points one-way for stocks, one basis point for SPY, and 3%
annual borrow on shorts.

## Trial and point-in-time lineage

The immutable identity is hypothesis key `e2b76a7604131f00`, configuration hash
`41ce2b1f40450a6e`. The preregistration fixed the direction, section, parser, controls, timing,
costs, capacity limits, diversification test, and kill rules before returns were opened. SEC
acceptance timestamps and immutable accession archives governed document availability; Sharadar
issuer intervals, corporate actions, and delisted histories governed market lineage. A canonical
input manifest binds every consumed market series.

The corpus processed 82,491 eligible manifest rows, extracted 73,744 Item 1A sections, formed
65,050 adjacent filing pairs, and selected 5,556 rows across 52 cohorts. Fifty-eight terminal
force-flat events were disclosed. Their presence independently prevents an `ADD` decision pending
dedicated delisting payouts; the return gates already fail without relying on that escalation.

## Results and decision

| Measure | Persisted value |
|---|---:|
| Net / 2x-cost Sharpe | -0.0074 / -0.4621 |
| DSR / PSR | 0.0000114 / 0.4906 |
| Newey–West t-stat | -0.0242 |
| Maximum drawdown | -28.47% |
| Realized SPY beta | 0.0033 |
| Annual turnover | 3.954x |
| 1% ADV p05 capacity | $739,828.89 |

The low beta and low average correlation of 0.0235 do not rescue absent standalone edge. The
short leg's gross contribution was negative, capacity missed $5 million, and 10% book inclusion
failed the mean-zero control and worsened expected shortfall. The candidate passed 12 of 20
research checks and is technically ineligible under the admission contract.

**Decision: KILL.** The family contributes zero sleeves, no Alpaca position, and no published live
return. The result is not evidence of forward Sharpe or expected drawdown. A transcript,
embedding, sentiment, quarterly-filing, or opposite-direction test would be a new hypothesis and
must be separately preregistered and charged.

## Reproduction, evidence, and credit

- [`/research/prereg-earnings-narrative-change.md`](/research/prereg-earnings-narrative-change.md)
 : immutable preregistration.
- [`/glassbox/earnings_narrative_change_result.json`](/glassbox/earnings_narrative_change_result.json)
 : complete sealed result.
- [`/glassbox/equity_narrative_family.json`](/glassbox/equity_narrative_family.json): deterministic
  family packet with hashes, exact configuration, gates, and lineage.
- [`/glassbox/trial_packet_manifest.json`](/glassbox/trial_packet_manifest.json): global union join.

The work requires the pinned AlphaForge environment and source corpus. Public SHA-256 bindings
make artifact replacement detectable; they do not imply independent peer review. The research,
system architecture, and publication were authored and directed by **Arhan Canli**, Founder of
Canli Capital.
