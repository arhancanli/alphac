# EFA event adjudication — September 12, 2026

Excluded the unsupported EFA December 16, 2003 dividend from a separate research
snapshot. The original event remains archived. Four unresolved payment events
remain: SPY June 16, 2006 and FXE April 2, 2007, July 1, 2008, October 3, 2011.
This exclusion is an evidence-based inference, not an explicit vendor retraction.

## Independent evidence and share basis

The [issuer's filed prospectus](https://www.sec.gov/Archives/edgar/data/1100663/000119312507106290/d497.htm)
contains audited Financial Highlights for the iShares MSCI EAFE Index Fund on
page 42. The fiscal year ended July 31, 2004 reports $0.52/share in total
distributions. Footnote b states that historical per-share figures reflect the
three-for-one split effective June 9, 2005. The earlier Financial Highlights
introduction identifies the figures as audited by PricewaterhouseCoopers LLP.

| Evidence, on that split-adjusted share basis | Distribution/share |
| --- | ---: |
| Audited fiscal total, rounded to cents | 0.52 |
| Current issuer history, December 22, 2003 event | 0.52251 |
| Retained source event | 0.52267 |
| Extra source event, December 16, 2003 | 0.15667 |
| Original source sum including extra event | 0.67934 |

The issuer history contains one distribution in the relevant fiscal year,
August 1, 2003 through July 31, 2004. Its date matches the retained source event.
Both retained-source and issuer amounts round to the audited $0.52, while the
original source sum rounds to $0.68. The extra event is absent from the issuer
history and breaks agreement with the independently reported fiscal total.

The retained source/issuer cash difference of $0.000160 on the adjusted basis
is preserved, not silently corrected. This differs from the preceding QQQ
adjudications, where retained amounts matched exactly. The inference rests on
the independent annual constraint plus event coverage, not absence alone.

The filing was inspected through the web reader; direct capture returned 403.
`filing_review.json` explicitly records a manual transcription, source URL,
section, observation time and share basis. The saved HTML is the failed request,
not the filing. A hash of the review note does not authenticate the full filing.
The script checks its consistency against saved event data but cannot independently
authenticate the manual transcription without re-reading the source.

## Derivatives and checks

`excluded_source_event.parquet` preserves the complete original event. Its raw
cash is approximately $0.47001/share before the later split. `revised_actions_v3.parquet`
contains 1,355 retained action rows, including the prior three cash corrections
and excluding the two previously adjudicated QQQ events. All retained rows are
unchanged from the preceding snapshot. `coverage_v5.parquet` contains 1,345
retained dividends: 1,341 accepted payment-date references and four unresolved.
This smaller inventory must not be described as a newly recovered payment date.

For arithmetic checks, the script reconstructs Decimal cash from original source
amount and split factor. It first requires agreement with stored raw floating-point
cash within two ULPs, avoiding a false mismatch from binary representation.
It verifies the exact split date and ratio, one retained issuer event, the fiscal
period, rounded totals, and preservation of every retained action row. Both prior
evidence seals are checked before writing derivatives.

Four new negative tests reject wrong fiscal totals, split ratios, split dates
and substitution of the supported event. Together with the three QQQ checks,
seven tests pass. Ruff and the real-data replay pass.

## Remaining work

The four payment disputes remain unchanged; this pass found no adequate primary
resolution for the competing SPY/FXE dates. Three historical price disputes,
cash precision differences and historical observation-time requirements also
remain open. Modern captures are not historical availability proof.

No price panel was rebuilt, no real forecasts/IC/returns were computed, and no
trading configuration changed. The historical payment schedule is not approved.
The hypothesis union remains 238; Sharpe 2 and 14+ qualified sleeves remain unmet.
Next: resolve the four payment dates and the price disputes, then rebuild the
corrected panel and validate all input bindings before a new performance trial.
