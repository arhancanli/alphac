# Reviewer engagement and vendor requests, 2026-09-14

**Author:** Arhan Canli (operating session under the owner's delegation of 2026-09-14)  
**Status:** DRAFTS FOR THE OWNER TO SEND. `config/external_review_protocol.json` records
`outreach_authorized: false`; nothing here has been sent, and the assistant sends nothing. The
owner sends, records the receipt fields the protocol requires, and flips the flag.

## 1. The independent reviewer (tiers 1 of the data-unlock brief)

**What exists.** Two frozen blind-label packets, each self-verifying:

| packet | rows | path | verify |
| --- | --- | --- | --- |
| active ownership, Schedule 13D Item 4 (v3) | 48 | `artifacts/labeling/active_ownership_13d_item4_v3_blind/` | `python3 verify_review.py` prints `PACKET_VALID` |
| tender offer, Schedule 14D9 Item 4 (v1) | 30 | `artifacts/labeling/tender_offer_item4_blind/` | `python3 verify_review.py` prints `PACKET_VALID` |

The 48-row packet ships with `INSTRUCTIONS.md` (the frozen rubric: mark `human_specific_active_intent`
only for a stated, specific, present action; copy one source sentence verbatim; one aggregate
ownership percentage or `unresolved`), an offline `review.html` workspace that makes no network
request, and the two files the reviewer returns (`completed_labels.csv`,
`completed_attestation.json`). The importer refuses labels without the no-AI, conflict,
relationship, compensation and independence attestation.

**Who qualifies.** Someone independent of this research and of the parser's development, who
reads SEC filings for a living or has done so: a securities paralegal, a former analyst, a
finance graduate student. Not the owner, not anyone who has seen the parser's output.

**Engagement terms to state in the message.** Fixed fee per completed packet (the owner sets
it; 48 filings at ten to fifteen minutes each is roughly a day's work), payment on a
`PACKET_VALID` verifier run of the returned files, no access to prices or returns, no use of AI
tools (attested), and permission to name the reviewer's role (not name) in the public record.

**Draft message (owner sends; replace the bracketed fields).**

> Subject: Paid independent review of 48 SEC Schedule 13D filings (offline, about one day)
>
> I run a small systematic research project that publishes its evidence in the open. Before I
> may use a classifier on Schedule 13D filings, my own rules require a human, independent of
> the research, to label a frozen set of 48 filings against a written rubric. I am looking for
> someone who reads SEC filings comfortably. The work is offline in a browser page I supply, no
> software to install, and takes about a day. It pays [fee] on completion, verified by a script
> that checks only the format of your answers, never their content. You would attest that you
> used no AI tools and have no relationship to the issuers or to me. If you are open to it I
> will send the packet and the rubric. [Name], Canli Capital, [contact].

## 2. Vendor quotes (tier 3, the two purchases that open two families each)

The repository holds no vendor pricing. Both requests must ask for publication rights for
derived, security-level research, because `config/data_source_rights_policy.json` already forbids
redistributing raw rows from every held source and a purchase without derived-publication rights
buys nothing this project can publish.

### 2a. Rates vendor: forward points, OIS curves, constant-maturity swaps

Opens `cross_currency_basis` and `swap_spread_dislocation`. The Treasury leg is held from 1962;
the free H.15 constant-maturity swap series was discontinued, so the swap leg is vendor-only.

> Subject: Historical rates data quote: FX forward points, OIS and CMS curves, daily, 2013 to date
>
> Please quote daily history from January 2013 to date, delivered as files with a documented
> schema and a stated revision policy, for: (1) FX forward points for G10 pairs against USD at 1M,
> 3M, 6M and 1Y; (2) OIS curves for USD, EUR, GBP, JPY, CHF at the same tenors; (3) USD
> constant-maturity swap rates at 2Y, 5Y, 10Y and 30Y. State the licence terms for publishing
> derived research (statistics, charts, model outputs) that does not redistribute your rows,
> and whether point-in-time snapshots or only current-revised history are available.

### 2b. Index provider: historical constituents, float factors, review calendars, plus rating histories

Opens `index_reconstitution_flow` and `fallen_angel_flow`.

> Subject: Historical index constituent and event data quote, US equities and credit, 2013 to date
>
> Please quote (1) daily historical constituent lists with weights and float factors for your
> flagship US large-cap and small-cap indices and their transition/pre-announcement events from
> January 2013 to date, and (2) issuer rating histories with dates for the US corporate bond
> universe over the same period. Delivery as files with a documented schema. State the licence
> terms for publishing derived, security-level research that does not redistribute your
> constituent lists, and whether announcement timestamps are point-in-time.

## 3. What happens after a yes

- Reviewer: the owner records the engagement in `config/external_review_protocol.json`
  (`outreach_authorized`, receipt fields), sends the packet, and on return runs the importer. If
  the initial gate (precision at least 95 percent, recall at least 80 percent, exact ownership
  agreement at least 90 percent) fails, the identity stops; there is no tuning on returned labels.
- Vendor: on a quote, the owner decides; on purchase, the source enters
  `config/data_source_rights_policy.json` with its exact publication terms before a single row is
  read into the lake, and the family enters feasibility, not return work.

## 4. Research findings, 2026-09-15

Read-only web research by the operating session: nobody was contacted, no form was submitted and
no account was opened. Figures marked (unverified) come from third-party pages, not the vendor.

**Who can sign.** Upwork requires the account holder to be 18 or older or a legal entity
(https://support.upwork.com/hc/en-us/articles/211067778-Who-s-eligible-to-join-and-use-Upwork), and
data licences are normally signed by a company. Each engagement below should be contracted by a
registered company or an adult acting for it.

**Reviewer plan (section 1).** Size: about 18 to 27 hours (48 Item 4 sections at 10 to 15 minutes
each; 30 tender-offer documents estimated at 20 to 30 minutes each). Market rates: paralegal median
USD 30.24 per hour (https://www.bls.gov/ooh/legal/paralegals-and-legal-assistants.htm); law-school
research assistants USD 18 to 23 per hour (https://www.law.uci.edu/portals/ra-student-employment.html).
Channels, in parallel: an Upwork fixed-price job for an SEC filings reviewer (client fee 5 percent
plus a per-contract fee, https://www.upwork.com/pricing/client), and a free Handshake posting for law
students who have taken securities regulation and finance master's students
(https://joinhandshake.com/employers/). Screening: a paid five-document trial on filings outside both
frozen sets, so neither gate is touched. Budget: USD 1,000 to 1,400 fixed for both packets, about
USD 100 for the trial, plus the platform fee. Timeline: week 1 post and shortlist; week 2 trial and
attestation; weeks 3 and 4 labelling; week 5 verify and import. One thing must exist first: the owner's
`outreach_authorized` record. The tender-offer blind packet was built on 2026-09-16
(`artifacts/labeling/tender_offer_item4_blind`, 30 documents, manifest content hash
`sha256:3a620b79...`; handoff archive `artifacts/handoffs/tender_offer_item4_blind.tar.gz`,
`sha256:5abb313b...`), so one engagement can now cover both packets: 48 Item 4 sections for active
ownership and 30 SC 14D9 Item 4 sections for tender offers.

**Rates (section 2a).** Free sources cover only part of the need: the FRED/H.15 ICE swap series stop
on 2016-10-31 (https://fred.stlouisfed.org/series/DSWP10); Bank of England sterling OIS curves start
in 2009 (https://www.bankofengland.co.uk/statistics/yield-curves; the licence for the curves is
unverified); no free official G10 forward points were found. Recommended order: a quote from
BlueGamma (FX forwards and SOFR, ESTR, SONIA, SARON and TONA swap curves by valuation date; price,
depth and licence not public, https://www.bluegamma.io/product/interest-rate-api), then LSEG
Workspace or Datastream (full coverage; USD 1,500 to 3,000 per user per month plus data packages,
unverified, https://www.vendr.com/marketplace/refinitiv). Rejected: Databento (exchange futures only,
a stand-in for the OTC instruments, with CME historical-distribution fees on top,
https://databento.com/pricing); ICE Swap Rate direct (USD 23,000 to 36,000 a year for the swap leg
alone, https://www.ice.com/publicdocs/IBA_MLA_Licensing_Data_Fee_Schedule_2026.pdf). Add to the 2a
request: the daily start date of each series; whether prices are executable, composite or
indicative, and their snapshot time; point-in-time or revised history; how the LIBOR to SOFR
transition is handled; written permission to publish derived statistics, charts, backtests and
instrument-level signal values on a public site and API, surviving termination; and the price for a
non-financial startup with any pass-through fees.

**Index constituents and ratings (section 2b).** The two cheapest point-in-time routes both bar
sharing as licensed: Siblis Research at USD 576 a year
(https://siblisresearch.com/data/historical-component-changes/; its terms prohibit "copying,
distributing or sharing any data", https://siblisresearch.com/terms-of-use/), and Norgate Platinum at
USD 630 a year (S&P 500 from 1957, Russell indices from July 1990; licensed for personal use by
individuals only, https://norgatedata.com/faq.php). Recommended order: Siblis if it grants written
derived-publication rights, else ask Norgate for a commercial exception, else S&P Dow Jones Indices
or FTSE Russell directly (no public prices). Rating histories are free: rating agencies publish XBRL
rating-action histories from June 2012 under SEC Rule 17g-7(b)
(https://www.sec.gov/about/divisions-offices/office-credit-ratings/disclosure-of-credit-rating-histories;
any publication lag and each agency's reuse terms are unverified). The equity index vendors carry no
bond-index eligibility, so `fallen_angel_flow` opens only if ratings plus published index rules are
enough. Add to the 2b request: the index list and start dates; the announcement timestamp and
effective date of each change; whether Russell preliminary lists are kept point-in-time; permanent
identifiers for delisted names; weights and float factors; and written permission for a company to
publish security-level research without the lists themselves, surviving cancellation.

**Per dollar.** The index route opens two families for about USD 600 a year if the publication
permission is granted in writing; credible rates coverage costs five figures a year.
