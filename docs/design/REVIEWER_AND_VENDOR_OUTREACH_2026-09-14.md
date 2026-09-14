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
| tender-offer spread accuracy set | 30 documents | `artifacts/feasibility/tender_offer_spread/frozen_human_labels.csv` (labels empty) | the same packet format is to be built by `build_active_ownership_blind_label_packet.py`'s sibling before sending |

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
