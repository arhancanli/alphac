# Equity value, issuance, and investment: 13 identities and unstable evidence

**Short title:** Equity value and investment: complete trial lineage  
**Author:** Arhan Canli, Founder, System Architect, and Quantitative Researcher, Canli Capital  
**Research system:** ALPHAC / AlphaForge  
**Family key:** `equity_fundamental_value_investment`  
**Status:** public research record; not peer reviewed; not an investment solicitation  
**Evidence date:** 2026-08-22

## Abstract

ALPHAC recorded 13 equity value/investment identities: book-to-price, earnings yield,
sales-to-price, accruals, asset growth, net issuance, investment-to-revenue, a value composite, and
52-week-high context. Eleven have finite immutable Sharpe measurements ranging from -0.9676 to
+0.8276; nine of those 11 are negative. Accruals and one net-issuance run are non-finite. Asset
growth flips from -0.6858 over 2018–2021 to +0.8276 over 2000–2026, while both book-to-price runs
are negative. This is specification and data-instability evidence, not a validated return family.

## Economic hypotheses and literature

Value ratios ask whether prices are low relative to accounting fundamentals. Investment factors
ask whether aggressive asset growth or security issuance predicts lower subsequent returns,
possibly through overinvestment, mispricing, or financing flows. Accruals ask whether cash and
accounting components of earnings have different persistence.

The Fama–French five-factor model formalizes value, profitability, and investment factors
([Journal of Financial Economics](https://doi.org/10.1016/j.jfineco.2014.10.010)). Cooper, Gulen,
and Schill document the asset-growth effect
([Journal of Finance](https://doi.org/10.1111/j.1540-6261.2008.01370.x)). Pontiff and Woodgate study
shares outstanding and cross-sectional returns
([SSRN source record](https://doi.org/10.2139/ssrn.679143)). These are priors, not
validation of ALPHAC's formulas, timestamps, universe, or execution.

Value, investment, issuance, profitability, and momentum overlap mechanically and empirically.
The taxonomy groups these 13 implementations into one family-level evidence burden; it does not
present each accounting ratio as an independent sleeve.

## Complete family accounting

| Signal group | Identities | Persisted Sharpe evidence |
|---|---:|---|
| `eq_asset_growth` | 2 | -0.6858 and +0.8276 |
| `eq_book_to_price` | 2 | -0.9676 and -0.3219 |
| `eq_net_issuance` | 3 | -0.3113, -0.1289, and non-finite |
| `eq_ilrev` | 1 | +0.6911 |
| `eq_earnings_yield` | 1 | -0.5526 |
| `eq_sales_to_price` | 1 | -0.5185 |
| `eq_value_composite` | 1 | -0.5994 |
| `eq_52whigh_252` | 1 | -0.2895 |
| `eq_accruals` | 1 | non-finite |
| **Total** | **13** | **11 finite; 2 positive; 2 non-finite** |

Each row remains charged to the 228-identity union. The machine packet includes exact hypothesis
and configuration hashes, source-ledger hashes, observation counts, and available moments. It does
not invent results for non-finite measurements.

The strongest finite identity, long-history asset growth at +0.8276, is contradicted by the
shorter asset-growth run at -0.6858 and carries skew +7.5222 with kurtosis 188.87. The positive
investment-to-revenue identity has skew +16.5759 and kurtosis 591.70. Several negative runs have
equally extreme tails. Point estimates from such summary-only evidence cannot establish a stable
return process.

## Missing evidence and decision

The family audit has no complete curve binding for these 13 specific identities, so maximum
drawdown, DSR, PBO, capacity, and crisis correlation remain unmeasured. Historical documents and
some related artifacts may discuss individual signals, but they do not form a complete,
identity-matched family packet. The public packet says so explicitly.

No result is admitted, no Alpaca sleeve carries this family, and no live broker return is assigned
to it. A repurchase/issuance feasibility programme is separate forward research; it cannot validate
these legacy summaries retroactively.

**Decision: NOT ESTABLISHED / RESEARCH ONLY.** Zero sleeves. Admission requires one newly frozen
point-in-time specification, exact filing availability and issuer identity, survivorship and
delisting controls, borrow and costs, persisted curves, current-union deflation, capacity, crisis
diversification, and broker-reconciled forward evidence.

## Reproduction and credit

- `docs/design/PREREG_FUNDAMENTAL_SINGLES.md`: historical single-factor specification.
- `docs/design/PREREG_SLEEVE4_INVESTMENT.md`: asset-growth preregistration.
- `docs/design/LITERATURE_REPURCHASE_ISSUANCE_FLOW.md`: issuance literature and overlap boundary.
- `scripts/audit_equity_fundamental_families.py`: deterministic family audit.
- [`/glassbox/equity_value_investment_family.json`](/glassbox/equity_value_investment_family.json)
 : machine-readable packet.
- [`/glassbox/trial_packet_manifest.json`](/glassbox/trial_packet_manifest.json): global join.

This research and ALPHAC implementation were authored and directed by **Arhan Canli**, Founder of
Canli Capital. The public hashes support scrutiny; they do not imply peer review or future return.
