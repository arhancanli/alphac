# ALPHAC / Canli Capital master plan

**Owner, founder, system architect and publication author:** Arhan Canli  
**Program:** ALPHAC / AlphaC Algorithms  
**Public record:** [canlicapital.com](https://canlicapital.com)  
**Status date:** 2026-08-24  
**Status:** active, evidence-gated research and Alpaca paper trading

## Mission

Build the most credible and technically impressive independently verifiable quantitative-investing
project in public: a cross-asset portfolio whose returns, failures, assumptions, code lineage and
live paper record can be checked by an outsider without trusting its founder.

“Revolutionary” is not a marketing adjective in this program. It means combining three properties
that are rarely present together:

1. a genuinely ambitious multi-sleeve portfolio;
2. research controls strong enough to reject attractive results; and
3. a public record that makes both successes and failures reproducible.

The project does not become revolutionary by asserting a Sharpe ratio. It becomes revolutionary if
Arhan Canli builds a result that survives deflation, costs, stress, forward trading and independent
inspection—and publishes the complete path that produced it.

## Governing objectives

The machine-readable authority is `config/sleeve_admission_contract.json`. Public pages and derived
artifacts must project from it; they may not maintain handwritten copies of its numbers.

| Objective | Governing definition | Current interpretation |
|---|---|---|
| Forward Sharpe | **1.5** | An earned forward objective, not a present result or promise. |
| Research Sharpe band | **2.25–3.0** | The in-sample support band implied by the book's measured 1.5×–3× backtest-to-forward haircut. It must always be labelled in-sample. |
| Sleeve breadth | **Up to 14**, requiring at least 10 new admissions | Fourteen is not a quota. Every new identity must independently clear the contract; otherwise the final book is smaller. |
| Expected maximum drawdown | **≤11%** | A portfolio-design objective for expected maximum drawdown, including the overlay. It is not a loss limit. |
| Tail drawdown | Publish the 95th percentile | No tested configuration has held the 95th-percentile maximum drawdown to 11%; this must remain visible beside the expected figure. |
| Average pairwise correlation | Gate **≤0.00**; objective near **−0.03** | Correlation and average sleeve quality are the binding levers. Sleeve count alone cannot deliver the target. |
| Trial budget | **400 identities**; 229 observed | The remaining 171 identities buy permission to test, never permission to admit. Hard reviews remain staged at 320, 360 and 400, and a family pauses at its own declared tripwire. |

The previously published 2.0–2.5 forward objective is superseded. It remains in the correction
history, not as a current target. Restoring it would require a new owner decision, new arithmetic
and an explicit versioned contract—not a copy change on the website.

## Non-negotiable rules

- Never report a simulation as live, paper as funded, a target as achieved, or an estimate as a
  risk limit.
- Never tune a gate to admit a candidate. Change a gate only through a versioned satisfiability
  analysis that applies prospectively to every candidate.
- Never spend a return identity before mechanism, point-in-time lineage, execution assumptions,
  family accounting, variants and kill criteria are pre-registered.
- Publish killed trials with the same care as admitted sleeves.
- Do not splice account resets, strategy changes or missing marks into one continuous live curve.
- Keep the strategic beta overlay separate from alpha sleeves in attribution, risk and prose.
- Credentials stay in environment variables or a managed secret store. Rotate any credential ever
  exposed in chat or plaintext before relying on it.
- Arhan Canli receives explicit authorship and responsibility credit. Tools may be disclosed as
  tools; they do not replace the human author or absorb accountability for the claims.

## Current evidence baseline

As of the status date:

- The current Alpaca paper record began on 2026-08-07 with separate $1 million paper accounts per
  sleeve. The flagship has 15 published marks and 14 return observations; the frozen evidence
  contract requires 252 observations before publishing a mature point estimate and 756 before an
  observed target can qualify for statistical establishment.
- The public book contains four paper sleeves: funding carry, US-equity momentum,
  managed-futures trend and point-in-time macro surprise, plus a separately disclosed 10% strategic
  long overlay split between BTC and SPY.
- The exact current-composition study measures average pairwise sleeve correlation at +0.0248
  over 1,061 synchronized rows; its 95% moving-block-bootstrap upper bound is +0.0487. The
  uncertainty gate passes, but the governing point gate of ≤0.00 and the −0.03 objective do not.
  This is research simulation, not established live-forward diversification. The honest forward
  Sharpe expectation remains 0.3–0.9; the 1.5 target has not been achieved.
- The durable union ledger contains 229 distinct hypothesis identities: 228 retired historical
  identities and one prospective portable crypto-carry identity. The owner-authorized ceiling is
  400. The v7 promotion retained hard reviews at 320, 360 and 400 after the
  exact planning audit showed that the former 320 ceiling left only 92 identities and a 7.70%
  planning probability of at least ten successes under the explicitly uncertain historical-rate
  assumption. Before the portable trial, 172-identity headroom implied 69.04% under that assumption.
  The current 171-identity headroom implies 68.35%; neither figure is a forecast and neither relaxes
  an admission gate. Two 2026-08-22 corrections recovered
  12 artifact-ledger identities and 54 named summary-only configurations without running a new
  experiment.
- Every legacy identity has a stable public evidence page. Only 2 of 228 packets are complete;
  226 retain explicit, audited historical evidence debt. The sealed legacy epoch retires all 228
  identities, makes zero admission-eligible or reusable, and binds the exact packet manifest.
  Genuinely new identities are permitted only through the prospective pre-result reservation
  contract; existing-identity remeasurements cannot create admission eligibility.
- The offline correctness suite contains 3,960 selected tests and currently passes at 86% package
  coverage. Wall-clock performance guards run in a separate serial lane so scheduler contention
  cannot masquerade as engine regression.
- Historical DSR restatement leaves zero of 33 recoverable variants above the 0.95 gate. This is a
  research finding, not something to hide.
- All 16 sleeve-lineage records now have checksum-bound preparation bundles and machine-validated
  archival PDFs. The 70-page corpus has an internal visual-inspection receipt; 13 changed
  crypto-carry and macro-trend pages were re-inspected on 2026-08-24 and the other 57 pages were
  carried forward
  only after exact PDF, validation-receipt and page-count equality against the archived prior
  receipt. This is internal presentation QA, not peer review.
- Crypto carry has an open material reproducibility correction. Its selected historical artifact
  reports Sharpe 0.6766 and maximum drawdown 19.60%, while the exact-timestamp current-state replay
  reports Sharpe 0.1065 and maximum drawdown 20.98%. The first sizing divergence is exactly
  attributable to mutable EOS universe membership. Every surviving source and replay ledger is now
  checksum-bound and compared: overlapping decision prices, marks, and funding rates are exact, but
  holdings and risk states diverge. The omitted historical code and derived-input snapshots make a
  unique additive multi-year causal split structurally unidentifiable. A prospective private input
  snapshot is now atomically enforced before every persisted walk-forward, but cannot repair the
  historical omission. The public paper and preparation bundle preserve both records and block
  external submission while the correction remains open.
- The first prospective v7 identity, `crypto_carry_portable_v1`, has executed exactly once. Its
  registered historical walk-forward simulation reports Sharpe 0.9689, CAGR 10.84%, maximum
  drawdown 12.30%, final simulated equity $155,880.82, PSR 0.9776 and DSR 0.0914 over 1,574 daily
  returns. The v7 contract requires per-sleeve DSR measurement but does not gate a sleeve at 0.95,
  so the generic runner's failed 0.95 indicator is published but cannot be relabeled as the
  governing KILL rule. The current disposition is `INCOMPLETE / NOT ADMITTED`: stress, execution,
  capacity, diversification, book-contribution and book-drawdown evidence remains unmeasured, and
  PBO is null because the single registered path did not produce an eligible path matrix. The
  result receipt and working paper are sealed, but the identity packet intentionally remains
  incomplete and mechanically blocks the next forward identity.
- The portable trial's data provenance remains exact. Before return computation, the source gate
  rehashed 5,965 available official archive objects (100,990,618 bytes), their
  checksum sidecars and 116 normalized objects. All 14 unavailable required archives belong to
  ICPUSDT; the pre-result contract therefore excludes that symbol by a deterministic source-
  availability rule, retains 57 instruments and the full 25-leg window, and labels the candidate a
  new prospective identity rather than a replication. The isolated private lake contains 2,409,886
  lifecycle-valid market rows in 706 hash-bound leaves and 108 rebuilt PIT universe intervals. A
  clean repeat build produced the same manifest, leaf-inventory root and SQLite metadata hash, and
  production PIT readback reconciled 2,137,040 OHLCV rows plus 272,846 funding rows. The runner
  then froze 781 execution-input files totaling 102,831,710 bytes before the first leg. These data
  facts support provenance; they do not independently validate the return result or authorize
  redistribution of the private rows.
- The public publication inventory releases 32 exact result objects (31 unique source paths), and
  13 audit-only commands pass both the current environment and an isolated frozen-dependency
  environment without changing result or experiment-ledger hashes. Five Wave 1 preparation
  archives pass deterministic construction, safe extraction, checksum and conservative data-rights
  checks. No paper is submission-ready and no external submission, DOI, peer review or independent
  replication is claimed.

These are snapshots, not constants. The live site must derive changing values from canonical
artifacts and display an `as of` timestamp and provenance for each one.

The immediate crypto-carry priority is to finish the registered identity's admission evidence
without spending or disguising another hypothesis. Before any stress or capacity path is computed,
a supplemental protocol must classify each requested calculation under the trial-accounting policy,
freeze every scenario and fail if a return-changing mutation requires a new identity. The current
packet stays incomplete and the next identity stays blocked until the required measurements support
an honest `ADMIT`, `KILL`, or final `INCOMPLETE` decision. The surviving historical path has already
been exhaustively delimited; forcing an additive split from missing bytes would be false precision.

## Workstreams and acceptance criteria

### 1. One governed truth

Create a public program-status contract that composes, without retyping:

- the sleeve-admission objective and gates;
- union trial accounting;
- the live configuration fingerprint;
- broker-reconciled Alpaca equity and cash-flow series;
- sleeve inventory and admission state;
- paper corpus and trial-packet coverage; and
- explicit claim labels: `TARGET`, `SIMULATION`, `PAPER_LIVE`, `MEASURED`, `ESTIMATE`,
  `CORRECTED`, or `WITHDRAWN`.

Acceptance: changing any governing source either updates every public consumer or fails publication.
No homepage, performance page, progress page, methodology page, structured-data object or social
preview may contradict the contract.

### 2. Forward-record integrity and Alpaca presentation

The website should show the flagship and each sleeve with:

- account inception and any rebaseline boundaries;
- starting equity, current equity, net deposits/withdrawals and time-weighted return;
- broker mark time, publication time and freshness state;
- realized volatility, drawdown, exposure, turnover and attribution where statistically meaningful;
- a clear `Alpaca paper account — no real money` badge;
- downloadable daily marks, orders/fills where disclosure is safe, continuity report, config
  fingerprint and chain proof; and
- separate panels for live paper results, simulations and forward objectives.

Acceptance: a broker snapshot, local execution ledger and published aggregate reconcile within a
declared tolerance, or the site fails closed and displays the discrepancy instead of a return.
The public maturity state must be derived from `config/forward_evidence_contract.json`: a point
Sharpe of at least 1.5 is only “observed,” while “statistically established” additionally requires
756 returns and at least 0.95 PSR probability that the true annualized Sharpe exceeds 1.5. Realized
drawdown, modeled expected maximum drawdown and modeled p95 drawdown remain separately labelled.

### 3. Fourteen-sleeve discovery campaign

Research is a funnel, not a beauty contest:

1. map at least 200 economically distinct candidate cells;
2. resolve overlap with all previously tested families;
3. complete literature and key-free data feasibility;
4. freeze the family identity and trial budget;
5. pre-register the return experiment;
6. run point-in-time, net-of-cost, walk-forward evaluation;
7. apply all admission, diversification, capacity, stress and book-level deflation gates; and
8. admit, kill or data-gate without discretionary rescue.

Research priority is determined by expected portfolio value: plausible independent mechanism,
obtainable point-in-time lineage, executable economics and a credible route to negative or near-zero
book correlation. Adding variants to exhausted price-momentum families is low priority.

Acceptance: a sleeve joins only when its signed admission packet clears the contract in force. The
program may end below fourteen; that is an honest result.

### 4. Drawdown engineering

Treat the 11% objective as a portfolio-engineering problem involving covariance responsiveness,
unlevered realized-vol comparison, correlation-regime shifts, overlay tail risk, execution gaps and
capacity—not as a leverage knob.

Acceptance: expected maximum drawdown is at or below 11% in the declared study, the 95th percentile
is published beside it, the live implementation is parameter-identical to the measured one, and a
configuration mutation causes the live-change guard to fail.

### 5. One paper for every trial and every sleeve

Every return identity receives a permanent trial packet:

- title, author (Arhan Canli), date and version;
- economic mechanism and falsifiable hypothesis;
- cited literature and novelty/overlap decision;
- pre-registration and immutable hashes;
- point-in-time data manifest and survivorship controls;
- execution and cost model;
- family and union trial accounting;
- complete result, uncertainty, stress, capacity and diversification evidence;
- admission or kill decision with failed gates named;
- code commit, environment lock and reproduction command; and
- machine-readable JSON plus a stable HTML paper, with PDF/archival DOI added for publication-grade
  releases where appropriate.

Acceptance: in the prospective research epoch, every new identity reserves its paper, packet and
hashed inputs before return computation, and must publish the complete result packet before another
identity can advance. The legacy epoch is never represented as complete: all 228 identities remain
bound to their exact packets, all 226 incomplete packets remain visibly incomplete, and the sealed
retirement contract keeps every legacy identity ineligible and non-reusable. Sleeve research records
additionally require live operations, risk and change-history sections.

### 6. Institutional-grade website

The live experience should make the evidence legible before it makes it beautiful:

- immediate flagship status and paper-trading disclosure;
- a live-return console with uncertainty and provenance;
- sleeve cards that expose mechanism, role, correlation contribution and evidence grade;
- a visual research funnel from atlas to data-gated, killed and admitted outcomes;
- an interactive book frontier showing what combinations of sleeve quality and correlation can
  reach the target;
- a verification path that works from a clean machine; and
- refined typography, motion and responsive behavior without compromising accessibility or speed.

Acceptance: zero broken internal links, zero contradictory claims, WCAG 2.2 AA, strong Core Web
Vitals, complete metadata/structured data, reproducible build, and visual QA across mobile and desktop.

### 7. Arhan Canli authorship and professional proof

Every public research object resolves to a stable `Person` identity for Arhan Canli. The founder
page, citation metadata, software metadata, paper bylines, schema.org authorship and repository
history must agree. Claims about credentials, employment, AUM or awards are excluded unless they
can be independently verified.

Acceptance: a reader can answer, with evidence, who conceived, built, governed and is responsible
for ALPHAC. Authorship is prominent but never substitutes for proof.

### 8. Ethical SEO dominance

Win search visibility through the deepest original evidence corpus in the niche:

- one canonical URL per paper, measurement, sleeve and methodology concept;
- topic hubs for deflated Sharpe, point-in-time data, walk-forward validation, quant research
  failures, portfolio diversification, Alpaca paper trading and reproducible backtesting;
- `Person`, `Organization`, `ScholarlyArticle`, `Dataset`, `SoftwareSourceCode`, `FAQPage` and
  breadcrumb structured data where semantically correct;
- descriptive titles, abstracts, internal links, sitemaps, canonical tags and fast static output;
- original charts and downloadable datasets that earn citations; and
- Search Console/Bing measurement by impressions, qualified clicks, indexed pages, backlinks and
  branded/non-branded query growth.

Acceptance: no doorway pages, generated keyword sludge, fake reviews, fabricated credentials or
performance language. Rankings are an outcome of authority and usefulness, not a substitute for them.

### 9. External proof

The final accomplishment requires evidence that cannot be manufactured quickly:

- a continuous, sufficiently long forward paper record under a frozen configuration;
- independently runnable reproduction kits;
- archived releases and signed provenance;
- publication-grade synthesis papers; and
- outside review that can reproduce selected claims and identify limits.

Acceptance: independent reviewers can reproduce the declared artifacts, verify record continuity
and explain what the evidence does and does not establish.

## Execution sequence

### Phase 0 — credibility floor

Green tests, deterministic exports, credential rotation, branch reconciliation and a publication
diff gate. No design flourish outranks a broken claim.

### Phase 1 — canonical public truth

Ship the program-status contract, derive all target/trial/sleeve fields from governing sources,
reconcile Alpaca marks and remove stale crypto-only or superseded-target copy from every route.

### Phase 2 — publication system

Make trial packets mandatory, backfill the corpus, add stable paper URLs and archival metadata, and
ensure every numerical sentence traces to a named artifact field.

### Phase 3 — flagship experience and SEO

Rebuild the public narrative around the live record, research frontier and verification path;
complete accessibility, performance, structured-data, content-hub and indexation work.

### Phase 4 — governed research campaign

Acquire data in expected-value order, run only pre-registered identities, publish every outcome and
admit only candidates that improve the book under the contract.

### Phase 5 — earned result

Accumulate the forward record, publish scheduled reviews at one, three and five years, seek external
reproduction and submit the strongest sleeve and system papers for durable third-party publication.

## Program scorecard

The status page should report these without hand editing:

| Dimension | Required measure |
|---|---|
| Performance | Forward TWR, Sharpe with confidence interval, expected and realized drawdown, p95 drawdown estimate |
| Breadth | Current sleeves / 14; new admissions / 10 |
| Diversification | Average correlation, upper 95% bound, stressed pairwise correlation, marginal book Sharpe |
| Research | Identities spent / 400, complete packets / identities, admitted, killed, data-gated |
| Execution | Reconciliation status, stale marks, rejects, slippage, continuity gaps |
| Reproducibility | Hash coverage, signature checks, deterministic reruns, unresolved evidence gaps |
| Product | Build/verify status, accessibility, performance, broken links, claim contradictions |
| SEO | Indexed canonical pages, impressions, qualified clicks, referring domains, top query clusters |
| Attribution | Papers carrying Arhan Canli byline, valid Person references, citation consistency |

## Definition of done

This program is complete only when the public project is internally consistent, externally
reproducible and honest about uncertainty; every trial has a paper; every live return is broker-
reconciled; Arhan Canli's authorship is unambiguous; the research campaign has either admitted up
to fourteen qualifying sleeves or truthfully established that fewer survive; and the forward record
has had enough time to judge the 1.5 Sharpe objective without presenting noise as achievement.

Anything less may still be excellent work. It is not yet the accomplishment defined here.
