# QQQ event adjudication — September 12, 2026

Excluded two unsupported extra QQQ dividend events from a separate research
snapshot. The original rows remain archived; this is an evidence-based inference,
not an explicit vendor retraction. Five dividend events remain unresolved.
This phase did not recover payment dates or compute strategy performance.

## Independent fiscal-year check

The issuer's audited financial highlights report distributions per share for
fiscal years ending September 30. The existing Invesco event history agrees
exactly with the four supported source events in each relevant fiscal year:

| Fiscal year | Reported distribution/share | Issuer event sum | Source sum with extra event | Unsupported event |
| --- | ---: | ---: | ---: | --- |
| 2010 | $0.33 | $0.32991 | $0.41891 | June 25, 2010: $0.089 |
| 2012 | $0.62 | $0.61667 | $0.66567 | December 27, 2011: $0.049 |

The issuer sums round to the audited values at the report's cent precision.
The original source sums do not. Each unmatched event is absent from Invesco's
history, while every other source event in its fiscal year matches the issuer
on both exact ex-date and cash. Removing exactly that unsupported event restores
agreement. No other event amount or date is changed.

Primary sources: [QQQ 2010 annual report, Financial Highlights](https://www.sec.gov/Archives/edgar/data/1067839/000110465910064790/a10-18275_1n30b2.htm),
[QQQ 2012 annual report, Financial Highlights](https://www.sec.gov/Archives/edgar/data/1067839/000110465913005075/a12-24340_1n30b2.htm),
and the previously saved Invesco QQQ distribution response.

The reports were inspected through the web reader; direct downloads returned
403. `annual_report_review.json` is an explicit manual transcription of the
two audited distribution figures and fiscal periods, with source URLs and actual
review times. Its hash binds that note, not full report bytes. Unsuccessful HTML
captures are retained and are not represented as annual reports. The source
identity and distribution classification were inspected in the report headings;
this arithmetic check alone cannot authenticate a manually entered figure.

## Artifacts and validation

`excluded_source_events.parquet` preserves both complete original event rows.
`exclusion_reviews.json` records each original event identity, supporting totals,
source URL and explicit inference. `revised_actions_v2.parquet` contains 1,356
actions, including the prior three cash revisions and 1,346 retained dividends.
All retained rows are verified unchanged from the preceding snapshot.

`coverage_v4.parquet` removes only those two excluded event keys: 1,341 accepted
payment-date references and five unresolved events remain. The prior 1,348-event
inventory is preserved, so the smaller unresolved count must not be described as
two newly recovered payment dates.

The offline replay verifies both prior evidence seals, exact event-set agreement,
cash equality for every retained QQQ event in the two fiscal years, audited
rounding agreement, rejection of the original totals, and preservation of all
retained rows. Three negative tests pass: incorrect annual total, substitution
of a supported event, or incorrect suspect amount all refuse to produce a
revised snapshot. Ruff passes.

## Remaining work

Still unresolved: EFA December 16, 2003; SPY June 16, 2006; and FXE April 2, 2007,
July 1, 2008 and October 3, 2011. Searches found secondary corroboration for some
competing payment dates, but no adequate new primary confirmation this pass.
No payment dates were guessed and no remaining EFA event was removed solely
because it was absent from a current issuer table.

Three historical price disputes and historical availability requirements remain
open. The complete price panel has not been rebuilt, and the historical payment
schedule is not approved. The existing settlement book requires observation by
ex-date; modern reference captures do not satisfy that condition. The snapshot
is a current-vintage research correction, not prospective evidence.

No real forecasts, IC, returns or trading configuration changes occurred. The
hypothesis union remains 238. Sharpe 2 and 14+ qualified sleeves remain unmet.
Next: seek fiscal-year evidence for the EFA extra event and explicit primary
payment records for SPY/FXE, then rebuild and revalidate the corrected inputs.
