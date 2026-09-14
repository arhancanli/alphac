# Treasury calendar conflict audit

September 12, 2026. The proposed fixed 16:00 decision rule has 15 boundary conflicts across 12 dates in the extracted SIFMA recommendations. These affect 15 of 305 planned phases. This is a lower-bound conflict audit, not a complete venue calendar. The dates remain unchanged and no phase has been silently shifted or removed.

Of the 15 conflicts, six are pre entries, seven post exits, one a pre exit and one a post entry. The latter pair occurs on December 24, 2018: the proposed auction-day reversal falls after the recommended early close. Columbus Day and Veterans Day explain the other flagged dates. Complete date, phase, source-page and raw-cell provenance is in boundaries.json.

## Source and extraction

The saved SIFMA historical compilation supplies 2013–2019 tables; six downloaded annual outlook PDFs supply 2020–2025 table material, including January 2026 New Year's references. The extraction produced 240 recommendation records, retaining adjacent-year duplicates and original source cells. These retrospective documents do not prove what was known at each historical decision time. [Historical compilation](https://www.sifma.org/wp-content/uploads/2017/08/Misc-US-Historical-Holiday-Market-Recommendations-SIFMA.pdf).

Five weekday/date contradictions remain quarantined: two in the historical compilation and three in the 2021/2022 outlooks. The 2023 outlook's calendar heading says 2022 despite its 2023 rows. Rows are handled by explicit dates and page provenance, not by assuming the title is correct. Some annual recommendations may have later amendments. Absence of a listed conflict is not proof of a normal trading session. Initial extraction diagnostics are preserved; a parser fix restored numeric day continuations that had been mistaken for page numbers.

SIFMA recommendations are not binding venue hours and do not by themselves determine settlement eligibility. Historical venue notices, extraordinary closures, early-close amendments and missing source rows remain required. No automatic weekday or NYSE substitute is accepted. [SIFMA recommendation scope](https://www.sifma.org/news/press-releases/sifma-issues-2023-and-2024-fixed-income-recommendations-for-full-early-holiday-closes-in-the-u-s-u-k-and-japan).

## Settlement correction

The previous proposed specification used the next Fedwire Securities session for regular settlement. That is insufficient. SIFMA's April 7, 2023 Good Friday notice says the Federal Reserve was open, but recommends the date not be treated as a good secondary-market settlement day and recommends T+2 for government/agency trades entered that Friday. It excludes money-market transactions from its settlement recommendations. This notice is an explicit counterexample to equating a service-open date with market-good settlement. [Dated notice](https://www.sifma.org/news/press-releases/sifma-recommends-an-early-market-close-on-april-7-in-the-u-s-in-observance-of-good-friday).

The new helper counts dates on which both externally supplied service and market calendars permit settlement, using an explicit positive lag. Unknown dates and nonboolean states fail. Tests illustrate Thursday settling Monday when Friday is market-ineligible, and Friday settling Tuesday under a supplied two-day convention. These are source-consistent examples, not a verified calendar for every historical trade or every bill. Instrument-specific market rules and any exceptions must be bound before using the helper.

See SETTLEMENT_ADDENDUM.md. The previous immutable specification and helper are preserved, and neither is silently promoted into production.

## Validation and next decision

37 focused tests pass, including 11 new parsing/calendar cases. Ruff passes the current audit, new helper and tests. Source PDF hashes and 610 boundary counts were checked; every flagged boundary retains its source cell. No prices, returns, orders, paid data or messages were involved. Hypothesis union remains 240 and no new sleeve is qualified.

The fixed-clock proposal is not ready for a return registration. Next: resolve the 15 conflicts using dated venue/auction notices and complete market settlement rules. Any revised clock or exclusion policy must be a separately documented implementation choice, retain the full event denominator and be fixed before returns. In particular, moving the Christmas Eve auction reversal or dropping inconvenient exits cannot be justified by subsequent profitability. The broader source/financing gaps remain pending. Sharpe 2 and 14+ qualified sleeves remain unmet.
