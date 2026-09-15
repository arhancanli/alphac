# Data-unlock brief, 2026-09-14

**Author:** Arhan Canli (operating session under the owner's delegation of 2026-09-14)  
**Purpose:** phase 2 of the plan toward fifteen qualified sleeves: say, for every family the atlas
holds, what one decision by the owner would let a single pre-registered identity test it, and
which of those decisions cost money. Every classification below is read from
`artifacts/analysis/atlas_reachability_screen/result.json` (twenty families) and
`artifacts/feasibility/*/result.json` (eighteen studies); nothing here re-derives a gate.  
**Trial accounting:** zero identities spent. This brief opens no data and runs nothing.

## Corrections, 2026-09-15

This brief was wrong or out of date in the places below. The operator log entries of 2026-09-15
17:25Z carry the evidence; the original text is left as written.

- **Identities per test.** "each of the studies below costs one" is wrong under the rules in force.
  `config/trial_accounting_evidence_classes.json`, bound by the v2 promotion receipt, makes declared
  cost, execution and capacity diagnostics free, but a test that can reach ADMIT needs an identity
  batch of at least two selectable identities. Fifty-one identities remain after ordinals 348 and
  349, which buys 25 such tests.
- **Tier 0 is empty.** `earnings_narrative_change` is the batch at ordinals 348 and 349, declared
  the family's second and final identity (`docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE_MDNA.md`);
  no further identity goes to it. `treasury_auction_concession` is not ready: its later audits say
  CALENDAR_LINEAGE_REQUIRED and IDENTITY_NOT_OBSERVABLE_AS_PREREGISTERED, its schedule-revision
  state machine awaits the author's review with no answers, and a review found defects in the
  revision audit and no Treasury cost model, price data or venue. Withdrawal of that version is
  recommended to the author, whose decision it is.
- **`pre_fomc_announcement_drift` is data-gated, not calendar-gated.** The row in tier 2 read the
  first-stage result. The annual schedule lineage passed on 2026-08-16
  (`artifacts/feasibility/pre_fomc_announcement_drift/annual_schedule_lineage.json`,
  PASS_TO_RETURN_PREREGISTRATION); the blocker is historical quote data
  (`artifacts/feasibility/pre_fomc_announcement_drift/market_data_readiness.json`, DATA_GATED). That
  pass also relies on schedule releases fetched in 2026 rather than contemporaneous captures, does not
  prove the March 2020 cancellation before entry, and leaves early-close control windows untyped, so
  a point-in-time calendar audit would be needed before any return if the quote data were bought.
- **`merger_arbitrage`** already has a sealed confirmatory redesign
  (`artifacts/feasibility/merger_arbitrage/announcement_confirmatory_design.json`: SC 14D9 and
  DEFM14A strata gated separately, 2006 to 2015 held out) awaiting the author's six answers. The
  "tender-offer-only identity" in tier 2 would be a third design and is withdrawn.
  `tender_offer_spread` is the same mechanism as that SC 14D9 stratum, so the two can yield at most
  one sleeve, and its blind packet, importer and attestation do not exist yet.
- **`spin_off_dislocation`'s** document schema audit already ran on 2026-08-16 and returned
  DATA_GATED (`artifacts/feasibility/spin_off_dislocation/document_schema_result.json`); the next
  step is a registration-keyed protocol, not the audit.
- **Decision 1 below is withdrawn** (there is nothing in tier 0 to reserve). Section 4 of
  `docs/design/REVIEWER_AND_VENDOR_OUTREACH_2026-09-14.md` now carries routes, prices and quote
  questions for the reviewer and both purchases.

## The shape of the problem

The reachability screen's own headline: none of the twenty untouched families is blocked on
engineering. Thirteen are blocked on a vendor purchase, two on human labels, one on an identity
redesign, one on history that does not yet exist, two on marks that are not executable, and one
on a record no vendor ever preserved. Separately, two feasibility studies have already passed
to return pre-registration and need no purchase at all. Fifty-three identities remain under the
400 ceiling; under the supplemental-measurement rule (`SUPPLEMENTAL_MEASUREMENT_CLASS_V1.md`,
not yet in force) each of the studies below costs one.

## Tier 0: ready now, no purchase (two identities)

| family | feasibility decision | what one identity tests | source |
| --- | --- | --- | --- |
| `earnings_narrative_change` | `PASS_TO_RETURN_PREREGISTRATION`, all nine document gates true | whether a change in an issuer's own risk and MD&A narrative between filings predicts subsequent returns | EDGAR 10-K/10-Q text, held |
| `treasury_auction_concession` | `PASS_TO_RETURN_PREREGISTRATION`, all six event gates true | whether the pre-auction concession in the on-the-run Treasury reverses after the auction | Treasury auction schedule and results, held |

Both go through the v2 full-evidence reservation (`config/forward_full_evidence_reservation_v2_template.json`)
with every supplemental scenario frozen before the primary result, so a single identity can
reach an admission decision instead of ending INCOMPLETE the way `crypto_carry_portable_v1` did.
These are the first two identities to reserve.

## Tier 1: human labels, then one identity each (owner recruits and pays a reviewer)

| family | state | the unlock |
| --- | --- | --- |
| `active_ownership_escalation` | machine gates pass (160/160 submissions, 150/160 Item 4 sections); the frozen 48-document human audit is 0/48 | an independent reviewer completes the 48 verbatim labels and signs the no-AI, conflict and independence attestation; the importer then decides whether the classifier may run. Selected as the next candidate by `artifacts/analysis/next_sleeve_selection.json` |
| `tender_offer_spread` | parser failed three machine gates; the 30-document accuracy set has zero labels, so the perfect-detector ceiling is unmeasured | the same reviewer labels the 30 documents; only then is parser repair authorized (`feedback_ask_if_the_gate_is_reachable_first`) |

One reviewer, one engagement, both families. Cost: the reviewer's time; the repo holds no quote.

## Tier 2: one more study step, no purchase

| family | state | next step |
| --- | --- | --- |
| `spin_off_dislocation` | `PASS_TO_DOCUMENT_SCHEMA_AUDIT` (40 quarter indexes hash-bound, 50+ initial registrations) | the document schema audit; the earlier language-rate ceiling (0.1122 against a 0.30 gate) says the identity must be redesigned around registrations, not language, before any pre-registration |
| `pre_fomc_announcement_drift` | `CALENDAR_LINEAGE_REQUIRED` | a point-in-time FOMC calendar lineage; free, engineering time only |
| `merger_arbitrage` | record held; `RECORD_HELD_BUT_IDENTITY_REDESIGN_REQUIRED` | a tender-offer-only identity, freshly pre-registered (the 0.8665 SC 14D9 rate is in-sample for that choice) |

## Tier 3: vendor purchases, grouped so one purchase opens the most families

Costs are not in the repository; each line needs a quote. Publication rights matter as much
as access: `config/data_source_rights_policy.json` already forbids redistributing raw rows from
every held source, so a purchase must permit derived, security-level research to be published.

| purchase | families it opens | screen's note |
| --- | --- | --- |
| a rates vendor (forward points, OIS curves, constant-maturity swaps) | `cross_currency_basis`, `swap_spread_dislocation` | Treasury leg held from 1962; the free H.15 swap series was discontinued, so half an identity is not an identity |
| FINRA Enhanced Historical TRACE plus bond reference data (and a CUSIP licence) | `credit_equity_relative_value` | the free portal caps history and forbids commercial display |
| an index provider's historical constituent and eligibility record (S&P, FTSE Russell or MSCI) plus rating histories | `index_reconstitution_flow`, `fallen_angel_flow` | both legs licensed; publication rights must be settled first |
| S&P Global Securities Finance or DataLend | `securities_lending_supply` | the identity is priced off the borrow FEE; held short interest is a different quantity |
| I/B/E/S, FactSet or Visible Alpha estimate history | `analyst_revision_drift` | free consensus is republished, not versioned |
| ICE settlement history | `carbon_allowance_carry` | the registry leg is public; the curve leg is licensed |
| eMBS, Bloomberg or a dealer analytics feed | `mortgage_convexity_pressure` | pool history and prepayment models have no public analogue |
| MSRB Historical Transaction Data plus municipal reference data | `municipal_taxable_basis` | trade fields are sold per collection; call schedules and tax status stay licensed |
| a credit-derivatives vendor | `sovereign_cds_fx_dislocation` | no public analogue at curve granularity |
| an OTC FX options vendor | `fx_option_risk_reversal` | composite quotes are indicative, not executable; the licence is the smaller problem |
| a security-level fixed-income or inflation-swap history | `inflation_breakeven_relative_value` | held FRED series give signal depth, not an executable identity |

If the owner buys one thing, the rates vendor opens two families and completes a leg the repo
already half-holds. The index-provider purchase is second for the same reason. Everything
else opens one family each.

## Not fixable with money today

| family | why | what to do instead |
| --- | --- | --- |
| `dealer_gamma_pressure` | the free expired-contract route works but coverage starts around 2024; the contract requires three years | keep the collector running; it becomes testable in 2027 |
| `crypto_liquidation_pressure` | venues never archived the event record | collect forward from today with the venue collectors this repo already runs; testable once three years exist |
| `catastrophe_bond_event_risk`, `freight_derivative_dislocation` | the marks are indications or panel assessments, not transacted prices | do not buy; a backtest on them measures an opinion |

## What this does not claim

No family here is expected to be profitable, negatively correlated with the book, or admissible.
The breadth arithmetic (`project_alphaforge_breadth_arithmetic`) says the target needs average
pairwise correlation at or below zero, and event-driven families (tiers 0 to 2) are the ones
whose returns are least obviously tied to the four sleeves the book runs; that is a reason to
test them first, not a result. Every identity spent on them counts in selection N.

## Decision requested

1. Reserve the two tier-0 identities now (my recommendation; no money, no owner action beyond the merge).
2. Recruit the reviewer for tier 1 (owner: a person, a fee, a signed attestation).
3. Choose whether to fund the rates vendor and the index provider (two quotes to obtain).
