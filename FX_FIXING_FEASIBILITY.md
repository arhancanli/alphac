# FX fixing inventory pressure — source feasibility, 2026-09-11

Status: targeted full-paper cost/method review completed; execution-cost and historical-timing gates strengthened.
No local return trial, admission or portfolio allocation has been made.

The previously unavailable conference link is no longer the only source route.
Krohn, Mueller and Whelan's research is available from the
[Bank of Canada](https://www.bankofcanada.ca/2021/10/staff-working-paper-2021-48/).
Its summary reports intraday dollar appreciation before major benchmark fixes
and reversal afterward. The authors associate the pattern with client demand
and dealer inventory management. This provides an economic hypothesis to test;
it does not establish a currently executable edge for ALPHAC.

The [FCA's study of the 4pm fix](https://www.fca.org.uk/publications/occasional-papers/occasional-paper-no-46-fixing-fix-assessing-effectiveness-4pm-fix)
reports a tradeoff after the fixing window was lengthened: improved benchmark
quality alongside higher quoted spreads, price impact and tracking error. This
is relevant adverse execution evidence. A pre-cost seasonal pattern cannot be
treated as a tradable result without measuring these costs.

These are publisher/author-hosting research summaries, not a completed review
of the papers' data, methods or supplementary material. The published literature
must count as known information when specifying a fresh holdout period.

## Next feasibility requirements

1. Obtain the benchmark methodology history, including window changes, local
   time zones, daylight-saving transitions, holidays and discontinued fixes.
2. Establish access to historical executable bid/ask observations around each
   fixing and a venue that can trade during the same hours. A daily FX series
   or an equity ETF outside its trading hours is not an adequate substitute.
3. Choose one mechanism before observing local returns: an unconditional timed
   inventory pattern or a flow-conditioned pattern. The latter requires a
   pre-decision observable flow measure; published explanatory dealer flows
   are not automatically available as trading inputs.
4. Check overlap with existing trend, carry, cross-currency basis and FX option
   risk-reversal mechanisms. Different timestamps alone do not prove independence.
5. Freeze one identity, its post-publication evaluation and cost assumptions in
   canonical trial accounting. Do not search every currency/window combination
   and count only the winner. Apply the existing admission gates to the book.

Kill or keep data-gated if historical timing cannot be reconstructed, execution
costs cannot be measured, venue access cannot reproduce the mechanism, or the
proposed identity merely duplicates an existing sleeve. No profitability,
correlation or independent-sleeve claim is made at this stage.

## Full-paper follow-up: decision changed

The [2021 paper, sections II and VII](https://www.bankofcanada.ca/wp-content/uploads/2021/10/swp2021-48.pdf) uses 1999–2019 indicative FX quotes. Most tested windows lose money with full quoted spreads; reduced-spread scenarios improve results. These scenarios are not evidence of our achievable costs. Trading reverses dollar exposure around fixing windows, so turnover matters. Its dealer-flow explanation cannot be implemented by assuming that futures order flow is interchangeable. Only these targeted sections and related mechanism discussion were reviewed; the online appendix and published-version differences remain unchecked. The PDF is preserved with a SHA-256 receipt under `evidence/fx-fixing-source/`.

There is also a dated timing discrepancy. The [ECB's December 2015 announcement](https://www.ecb.europa.eu/press/pr/date/2015/html/pr151207.en.html) specifies a 14:15 CET snapshot and moves publication to approximately 16:00 CET from July 2016. The [current reference-rate page](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) describes concertation around 14:10 CET. We have not established the effective date of that timing change. Publication time must not stand in for the underlying observation.

The LSEG methodology PDF URL returned 404 when downloaded directly; web opening also failed. Search snippets are not sufficient evidence of the current version, so current WMR methodology remains unverified.

### ALPHAC feasibility decision

Keep this lead **execution-cost and historical-timing gated**. Do not reserve a return trial yet. The next useful acquisition is a dated executable quote/depth sample from the intended FX venue, including commissions, spread, size, financing and rejected-fill behavior. No arbitrary spread discount is allowed to rescue the candidate.

A first identity, if these gates are met, should freeze one unconditional timing mechanism and a declared currency universe before inspecting local returns. A flow-conditioned version would require a separate identity and a demonstrably available pre-decision input. Historical timing needs effective dates, calendar exceptions and explicit daylight-saving treatment. Benchmark values are not executable fill prices.

Overlap review must include Treasury auction inventory pressure as well as FX trend, carry, basis and option risk reversal. This is a proposed risk review, not a measured correlation result. We will not count geographic fixing windows or currency variants as separate independent sleeves without evidence. No local returns or new admissions were produced.

Rerun inputs: `firecrawl-research-papers`; FX fixing feasibility; primary working paper plus benchmark administrators; targeted cost/method review. Firecrawl CLI unavailable; web and direct publisher download used.
