# Canli Capital Clarity and Institutional Research Roadmap

**Date:** 2026-08-26

**Owner and principal investigator:** Arhan Canli

**Status:** Proposed governing reset, planning complete, implementation not started

**Audience:** Arhan Canli, technical reviewers, research collaborators and future public contributors

**Relationship to the existing plan:** This document narrows and extends
`CANLI_CAPITAL_PRODUCT_FOUNDRY_AND_AUTHORITY_PLAN_2026_08_26.md`. It supersedes that document where
the public information architecture, roadmap order or advisor proposals conflict. It does not
weaken any truth, performance, admission, security, authorship or external-validation gate.

## 1. Exact objective

Make Canli Capital the clearest public evidence system for systematic research, then extend it with
useful open infrastructure and carefully bounded advanced research. A first-time visitor should
understand the product in less than 10 seconds. A technical reader should be able to inspect,
download and reproduce selected claims without learning the internal route map. A research idea
should never become a public capability merely because it sounds advanced.

The product sentence is:

> Canli Capital is a public research and verification platform where you can inspect a live
> paper-traded systematic portfolio, trace every decision and reproduce selected research.

The public promise is:

> See what happened. See why it happened. Check the evidence yourself.

The project is not a fund, a copy-trading service, a performance guarantee or a claim that every
advanced method improves investment results.

## 2. Why a reset is necessary

The current system has strong evidence but a weak first-time mental model. The primary navigation
exposes Live, Research, Trials, Systems, Methodology and Verify as peer concepts. The expanded menu
adds Corrections, Status, Founder, Open data and Measurements. A visitor must therefore understand
11 internal nouns before choosing where to begin.

That is an information-architecture failure. It is not solved by adding more animation, more
technical language or more pages. The next public release must reduce the number of concepts shown
at once, preserve deep routes for search and technical use, and explain every artifact from the
visitor's perspective.

## 3. Governing doctrine

1. **Clarity before surface area.** No new public category ships until it has one owner, one user
   job, one canonical route and one measurable reason to exist.
2. **Evidence before prestige language.** Institutional, revolutionary, peer reviewed, validated,
   live and proven are evidence states, not adjectives.
3. **Advanced is not automatically better.** A simpler model with an inspectable failure boundary
   is preferred to an opaque model with a stronger in-sample result.
4. **Research and control are separate.** An experimental model may challenge the production rule.
   It may not silently become the production rule.
5. **Every public capability has a machine twin.** The explanatory page, schema, version, data
   source, downloadable object and claim boundary must agree.
6. **Every new search surface must help a reader.** No doorway pages, keyword farms, synthetic
   backlinks or pages that restate the same idea under different titles.
7. **Arhan's authorship stays explicit.** Public research, software, judgment calls, corrections and
   contribution boundaries identify Arhan Canli accurately.

## 4. Advisor proposal decision ledger

The advisor list is an idea inventory. It is not a list of capabilities that may be claimed today.

| Proposal | Decision | Correct implementation | Promotion evidence |
|---|---|---|---|
| Reproducible public code | Ship now | Publish non-secret validators, schemas, calculators and bounded replay packages on GitHub | Clean install, tests, license, threat review and an external issue or review path |
| Granular public APIs | Ship now | Versioned REST first, optional event stream later, with observed, simulated and planned labels in every response | Schema tests, rate limits, privacy review, uptime receipt and public documentation |
| Interactive simulation sandboxes | Ship now | Evidence-bound educational tools using fixed source artifacts and shareable state | Deterministic outputs, no hidden optimizer, accessible controls and explicit non-admission boundary |
| Cryptographic audit trail | Extend current system | Bind parameters, trials, broker observations, corrections and publication objects to the signed chain | Complete source binding and independent verifier success; never call it proof of truth or completeness |
| Open paper-reporting standard | Flagship priority | Publish a schema, vocabulary, conformance suite and reference renderer for paper-trading evidence | Versioned specification, test vectors, independent implementation attempt and governed change process |
| Failure-log whitepapers | Ship continuously | Group related killed identities into mechanism papers with complete search accounting | Manuscript audit, source bundle, rights review and external criticism |
| PBO and CSCV hardening | Ship where valid | Add trial-family accounting, dependence-aware effective trial counts, CSCV diagnostics and prospective gates | Simulations and known-answer tests show calibration under the intended sample structure |
| Cross-sleeve polarity detection | Build as a shadow guard | Monitor factor, beta, liquidity, volatility and crisis-state overlap before changing weights | Prospective alerts, mutation tests, false-positive analysis and predeclared activation rule |
| Horizon-matched execution realism | Build by strategy horizon | Model decision-to-fill delay, spread, impact, borrow, financing, venue state and order type at the frequency actually traded | Broker reconciliation and held-out fill error by sleeve |
| Alternative data | Research program | Begin with licensed, point-in-time shipping, supply-chain or credit feasibility studies, one source at a time | Legal use, stable identity, timestamp lineage, coverage, cost and negative-result publication |
| Multilingual financial language models | Research challenger | Benchmark retrieval and extraction on frozen filings and policy documents before training any specialized model | Human-labeled evaluation, temporal split, citation trace, calibration, drift and cost comparison against simple baselines |
| Illiquid and esoteric assets | Defer to stress research | Use them to test execution and liquidity assumptions, not to inflate the tradable universe | Legally obtainable point-in-time data, contract lifecycle, pricing, borrow, margin, capacity and venue access |
| Synthetic market regimes | Replace the GAN-first proposal | Use block bootstrap, regime resampling, structural scenarios, agent-based tests and generative models as separate challengers | Tail calibration, dependence preservation, failure tests and no claim that synthetic years are historical evidence |
| Reinforcement-learning allocation | Research only | Run a shadow challenger against the fixed allocator with no broker authority | Preregistered state, action and reward; held-out superiority; turnover and tail controls; interpretability; safe fallback |
| Microsecond queue simulation | Reject as a universal goal | Use queue models only for strategies whose decision horizon and order type make queue position material | Exchange-level message data, clock quality and measured error against actual fills |
| Fellowships, grants and hackathons | Defer | Start with a small governed reproduction challenge after external review capacity exists | Code of conduct, data rights, minor safety, judging, conflicts, budget and publication rules |

### Claims that are explicitly prohibited

- Cryptography makes the record mathematically irrefutable.
- Synthetic data creates thousands of years of genuine market evidence.
- PBO or CSCV eliminates false positives.
- Reinforcement learning is inherently superior to fixed allocation.
- Microsecond simulation improves medium-frequency execution evidence.
- Alternative data is alpha before a preregistered result exists.
- A public repository, DOI, arXiv record or favorable comment is peer review.

## 5. Public information architecture reset

The primary navigation has 4 items and 1 action:

```text
Canli Capital
├── Live Record     What happened in the paper portfolio?
├── Research        What was tested, rejected, corrected or retained?
├── Tools           How can I inspect, simulate, download or verify it?
├── About           What is this project, who built it and what are its limits?
└── Verify Latest   Direct action on the newest signed record
```

### Route ownership

| Visitor route | Single job | Contains or points to | Primary action |
|---|---|---|---|
| `/` | Explain the project and route the visitor | Current paper state, one evidence story and 3 audience paths | View the live record |
| `/live` | Show the observed paper record | Equity, positions, decisions, broker state, risk and incidents | Inspect one decision |
| `/research` | Organize the research record | Papers, killed work, corrections, topics and review status | Open a paper packet |
| `/tools` | Consolidate technical interaction | Trial accounting, DSR, chain verifier, APIs, schemas and sandboxes | Use a tool |
| `/about` | Explain institution, method and authorship | Product definition, methodology, systems, Foundry, founder and boundaries | Review the method |
| `/verify` | Verify one exact record | Browser verifier, command-line verifier and limits | Verify latest |

### Existing deep routes

The existing routes remain stable for backlinks, citations and technical readers. They move out of
primary navigation and become owned children:

- `/trials`, `/measurements`, `/open` and `/verify` belong to `/tools`.
- `/systems`, `/foundry` and `/methodology` belong to `/about`.
- `/progress`, `/review` and publication records belong to `/research`.
- `/performance` becomes a status view under `/live`, not a second interpretation of performance.
- `/founder` remains a canonical authorship page and is linked from `/about` and every paper.

No route is deleted until its canonical, internal links, sitemap state and redirect decision are
recorded. A route with distinct search intent may remain indexable even when it leaves navigation.

## 6. Homepage contract

The homepage should contain 6 sections, not a tour of the entire repository.

1. **Hero:** product sentence, paper-capital boundary and `View the live record` action.
2. **Current state:** paper start, current observation count, broker-connected sleeves, capital at
   risk and validation state, all sourced from artifacts.
3. **One evidence interaction:** follow one real decision from frozen identity to signed record.
4. **Choose a path:** investor or observer, researcher, or technical verifier.
5. **Featured research:** one flagship paper, one failure paper and one correction.
6. **Authorship and boundary:** Arhan Canli, GitHub, review state, no managed capital and no advice.

The current Evidence Core remains the signature object only if it explains the same decision shown
in section 3. Decorative 3D complexity that does not improve comprehension is removed.

### Ten-second comprehension gate

In an unmoderated test, at least 8 of 10 first-time readers should correctly answer:

1. What is Canli Capital?
2. Is the portfolio funded or paper traded?
3. What can I inspect?
4. Where do I go to reproduce or verify something?

No public launch claims that this gate passed until the dated test and responses exist.

## 7. SEO and public-evidence contract

Every major shipped capability receives one useful, canonical search object. SEO is the discoverable
shape of real work, not a second layer of promotional copy.

### Required public objects

| Capability | Canonical page | Machine object | Link-worthy object | Structured data |
|---|---|---|---|---|
| Paper-trading record | `/live` | `/api/v1/record` | Dated evidence snapshot | `Dataset` and `WebApplication` where applicable |
| Reporting standard | `/standards/paper-evidence` | JSON Schema and test vectors | Open specification and validator | `TechArticle` and `SoftwareSourceCode` |
| Public API | `/developers` | OpenAPI document | Interactive API explorer | `WebAPI` or `SoftwareApplication` |
| Trial accounting | `/tools/trial-accounting` | Versioned union JSON | Complete denominator explorer | `SoftwareApplication` |
| PBO and selection | `/tools/selection-risk` | Scenario contract | Calculator and worked examples | `SoftwareApplication` |
| Portfolio overlap | `/tools/portfolio-overlap` | Source-bound exposure matrix | Stress explorer | `SoftwareApplication` |
| Failure research | `/research/topics/killed-candidates` | Citation and evidence bundle | Publication-grade mechanism papers | `ScholarlyArticle` |
| Alternative-data protocol | One paper per source | Manifest and coverage report | Negative or positive feasibility result | `ScholarlyArticle` and `Dataset` |
| Language-model benchmark | One benchmark page | Evaluation set manifest and scorecard | Reproducible extraction benchmark | `Dataset` and `SoftwareSourceCode` |

### Search acceptance gates

1. Search Console ownership is verified and the canonical sitemap is submitted.
2. Every indexable route has one intent, one canonical and distinct useful content.
3. Existing authority is preserved with stable URLs or explicit permanent redirects.
4. Every indexable page is reachable within 3 clicks from `/`.
5. No internal links point to old shells, duplicate intent pages or metadata-free source copies.
6. Titles, descriptions, headings, breadcrumbs, Open Graph and structured data agree.
7. Public APIs and schemas are linked from human explanations and version changelogs.
8. Backlinks are pursued through useful specifications, tools, datasets, papers and reviews, never
   through purchased links or automated outreach volume.
9. Search visibility is measured by indexed pages, valid rich-result coverage, qualified queries,
   citations, external reproductions and useful referring domains. Raw page count is not a goal.

## 8. Data and infrastructure architecture

The current storage choices are retained until measured load disproves them.

| Layer | Governing choice | Reason |
|---|---|---|
| Research lake | Partitioned Parquet with DuckDB reads | Existing point-in-time design, portable files and efficient research scans |
| Live operational state | SQLite WAL with verified off-box backup | Current single-writer paper loops and deterministic recovery |
| Foundry control plane | Private PostgreSQL with narrow roles | Multi-worker leases, lifecycle transitions and isolated publisher state |
| Public artifacts | Versioned static JSON, Parquet extracts and immutable bundles | Cacheable, inspectable and inexpensive to serve |
| Public API read model | Sanitized materialized snapshots | Prevents public traffic from reaching research or broker databases |
| Object storage | Add only for immutable source and publication objects | Useful for retention and delivery, never a substitute for metadata contracts |
| ClickHouse | Deferred | Introduce only when measured public analytics or event volume exceeds snapshot and PostgreSQL capacity |
| ArcticDB | Deferred | Current Parquet lineage is already integrated and portable; migration needs a measured benefit |

No public endpoint receives a broker credential, research database credential or write path. The
publisher exports an allowlisted snapshot into a separate public read plane.

## 9. Open API and reporting standard

### API v1

The first version is REST because stable snapshots are easier to cache, inspect and cite than an
always-on stream.

Proposed endpoints:

- `GET /api/v1/status`
- `GET /api/v1/record`
- `GET /api/v1/sleeves`
- `GET /api/v1/decisions`
- `GET /api/v1/trials/summary`
- `GET /api/v1/trials/{identity}`
- `GET /api/v1/research`
- `GET /api/v1/corrections`
- `GET /api/v1/chain/head`

Every response includes schema version, generated timestamp, source hashes, capital kind, claim
class, units, missing-field reasons and a canonical human page. Pagination and filters live in the
URL. Rate limits and caching are public. Empty data returns an explicit state, never a fabricated
zero.

WebSocket or server-sent events are phase 2. They ship only when a real user needs lower latency and
the update source has a stable event contract.

### Open paper-evidence standard

The standard begins as `canli.paper-evidence.v0`. It defines:

1. Capital type and execution provenance.
2. Strategy and sleeve identity.
3. Start, end and observation schedule.
4. Gross and net return assumptions.
5. Costs, turnover, financing, borrow and slippage.
6. Trial count, selection adjustment and preregistration state.
7. Risk, drawdown and exposure definitions.
8. Corrections, supersession and incident state.
9. Artifact hashes, signatures and source bindings.
10. Missing evidence and claim maturity.

The first release includes JSON Schema, examples, invalid fixtures, a validator CLI, a browser
validator, a mapping from the current ALPHAC record and a governance process. It is presented as a
proposed open standard until an independent implementation and public feedback exist.

## 10. Interactive research tools

The tools hub should answer questions, not invite visitors to optimize a strategy on the website.

### Priority tools

1. **Trial Accounting Explorer:** already shipped; preserve complete-union accounting.
2. **Deflated Sharpe Calculator:** already shipped; add reporting-standard import and export.
3. **Evidence Chain Explorer:** already shipped; add standard-record verification.
4. **Selection Risk Lab:** show PBO and CSCV behavior on declared synthetic examples and released
   trial families.
5. **Portfolio Overlap Lab:** alter weight caps and stress correlations on a frozen evidence packet;
   never imply the resulting Sharpe is a forecast.
6. **Execution Reality Lab:** compare idealized, spread, delay, impact and outage assumptions for a
   fixed strategy packet.

### Sandbox safety contract

- The URL stores every input.
- The output identifies the exact source packet and formula version.
- The original observed result remains visually separate from user-created scenarios.
- The tool cannot write to the trial ledger, broker, Foundry queue or public record.
- Exported scenarios say `USER_GENERATED_SCENARIO_NOT_RESEARCH_EVIDENCE`.
- Keyboard, mobile and reduced-motion paths receive equal functionality.

## 11. Machine learning and advanced research

### Financial-language benchmark before a financial LLM

Start with one bounded task, such as extracting central-bank decision, direction, effective date and
cited sentence from multilingual official releases. Compare:

1. deterministic rules
2. general-purpose retrieval and extraction
3. a small task-specific model
4. a larger financial-language model

Use time-separated documents, double-labeled evaluation data, disagreement adjudication, citation
accuracy, calibration, latency, cost and drift. Real-time use remains shadow-only until prospective
error evidence exists.

### Synthetic regimes

Create a scenario suite rather than one generator:

1. historical replay and crisis windows
2. moving-block bootstrap
3. volatility and correlation regime resampling
4. structural macro shocks
5. agent-based liquidity stress
6. generative challenger, including a GAN only if it beats simpler diagnostics

Synthetic paths test sensitivity. They do not add historical observations, establish probability
or validate a sleeve.

### Reinforcement-learning allocation

The RL allocator is a sealed challenger with:

- fixed state variables available at decision time
- bounded actions and turnover
- predeclared reward and risk penalty
- training, validation and untouched test eras
- static equal-weight and constrained optimization baselines
- crisis and distribution-shift tests
- deterministic fallback
- no broker credentials and no promotion authority

Promotion requires prospective evidence under the same trial budget as any other allocator. A
negative result is published.

## 12. Risk and execution program

### Selection-risk controls

PBO and CSCV are diagnostics, not magic gates. The implementation must state the number of paths,
dependence assumptions, minimum sample, family definition and invalid-use conditions. When the
sample cannot support CSCV, the system says unavailable rather than returning a precise number.

### Cross-sleeve polarity guard

The guard observes:

- rolling return correlation with uncertainty
- equity, duration, dollar, volatility and liquidity beta
- directional crowding by instrument and venue
- common loss under named historical and synthetic stresses
- factor-sign inversion and crisis-state convergence

The first release alerts only. Automatic resizing requires a separate preregistered rule, shadow
history, false-alert analysis, interaction tests with existing risk limits and a reversible rollout.

### Execution fidelity by horizon

| Strategy horizon | Required evidence |
|---|---|
| Daily or slower | Decision timestamp, next executable price, spread, fees, borrow, financing, corporate actions and outage state |
| Intraday medium frequency | Quote or bar state, delay distribution, order type, depth proxy, partial fills and impact calibration |
| High frequency | Message-level order book, clock synchronization, queue model, venue rules and measured queue-position error |

No high-frequency fidelity claim is made for a strategy that does not have the data or operational
path required to test it.

## 13. Academic and community program

### Publication order

1. Complete Arhan's technical audit for each flagship manuscript.
2. Obtain a fresh-context reader.
3. Commission methods and reproducibility review.
4. Answer every finding in a versioned response matrix.
5. Complete a clean external reproduction attempt.
6. Resolve data rights and choose an exact repository or preprint route.
7. Publish the immutable version and its distinct reproduction object.
8. Request open review against that exact version.

The failure-log program groups related killed trials into papers about mechanisms and measurement
errors. It does not manufacture one paper per failed parameter setting.

### Community launch gate

No fellowship, grant or hackathon is announced until all of the following exist:

- one independently reviewed public specification or paper
- one independently attempted reproduction
- contributor license and data-rights rules
- code of conduct and minor-safety policy
- conflict, compensation and judging policy
- bounded problem statements that cannot reach broker credentials
- capacity to answer and preserve findings

The first community event should be a small reproduction challenge, not a global fellowship claim.

## 14. Execution roadmap

### Phase 0: freeze and simplify, week 1

1. Approve this decision ledger.
2. Freeze new top-level routes.
3. Build a route inventory with owner, search intent, canonical, parent and redirect state.
4. Test the current homepage with 10 first-time readers.
5. Write the 4-path navigation and 6-section homepage contract.
6. Preserve a before snapshot and measured confusion findings.

**Exit:** no unresolved top-level concept, duplicate route job or unsupported advisor claim.

### Phase 1: clarity release, weeks 2 to 4

1. Ship `/live`, `/tools` and `/about` hubs.
2. Replace primary navigation across every shell.
3. Shorten the homepage to the 6-section contract.
4. Move deep technical routes under their owning hubs without breaking URLs.
5. Add permanent redirects only where intent is truly identical.
6. Run browser, accessibility, performance, link, canonical and structured-data QA.
7. Repeat the 10-second comprehension test.

**Exit:** at least 8 of 10 readers answer the 4 comprehension questions correctly; zero old-shell
destinations; primary navigation has exactly 4 concepts and 1 verification action.

### Phase 2: open infrastructure, weeks 4 to 8

1. Publish API v1 and OpenAPI documentation.
2. Publish `canli.paper-evidence.v0` and conformance fixtures.
3. Release validator CLI and browser validator.
4. Map the live paper record and one failure paper into the standard.
5. Invite bounded technical criticism through the governed review process.

**Exit:** clean consumer example, rate-limit test, security review, schema test suite and one external
implementation attempt requested. External completion remains a separate state.

### Phase 3: risk workbenches, weeks 7 to 12

1. Ship Selection Risk Lab.
2. Ship Portfolio Overlap Lab.
3. Ship Execution Reality Lab for current sleeve horizons.
4. Start polarity detection in alert-only shadow mode.
5. Publish every formula, invalid-use condition and test vector.

**Exit:** deterministic scenario links, accessibility pass, no broker path, known-answer tests and
no tool language that turns a scenario into expected performance.

### Phase 4: advanced research challengers, weeks 10 to 20

1. Run one alternative-data feasibility protocol.
2. Build one multilingual extraction benchmark.
3. Build the synthetic-regime comparison suite.
4. Register an RL allocation challenger only after its baseline and safety contract are complete.
5. Publish negative findings and costs.

**Exit:** each program has a frozen identity, legal-use record, baseline, holdout, cost record,
claim boundary and publication decision.

### Phase 5: external authority, ongoing

1. Complete author audits and fresh-context reading.
2. Assign and complete real external reviews.
3. Obtain external reproduction attempts.
4. Publish revised papers and response matrices.
5. Pursue search visibility through real tools, specifications, datasets and citations.
6. Launch a bounded reproduction challenge only after the community gate passes.

## 15. Scorecard

| Dimension | Current evidenced state | Next earned state |
|---|---:|---|
| Primary navigation concepts | 6 plus expanded menu | 4 plus one verification action |
| First-time comprehension | Not yet measured | 8 of 10 pass the dated test |
| Editable em-dash forms | 0 on the committed public migration | Remain 0 |
| Public authority tools | 3 | 6, after evidence-bound workbenches ship |
| Public API | No stable v1 claimed | REST v1 with OpenAPI and security receipt |
| Open reporting standard | Not published | v0 schema, validator and examples |
| Independent reviews | 0 | First governed methods and reproducibility reviews |
| Independent replications | 0 | First external attempt, pass or fail |
| Foundry cloud receipts | 0 of 11 | 11 of 11 before operational claim |
| Search Console ownership | Not evidenced | Verified ownership and submitted sitemap |
| Forward Sharpe maturity | Objective not achieved | Earned only under the existing forward gate |

## 16. Quality and release gates

Every release must pass:

1. Artifact and numerical provenance.
2. Observed, simulated, scenario, research-only and planned labels.
3. No managed-capital or investment-advice ambiguity.
4. No secret, broker, private database or unlicensed raw-data exposure.
5. Deterministic build and exact-commit preview.
6. Unit, integration, mutation and adversarial tests appropriate to the change.
7. Desktop, mobile, keyboard and reduced-motion browser QA.
8. WCAG 2.2 AA target, semantic controls, visible focus and meaningful media alternatives.
9. Core Web Vitals budget and no unnecessary 3D or video on critical paths.
10. Canonical, sitemap, internal-link, structured-data and visible-copy agreement.
11. No editable em-dash forms and no silent mutation of immutable archives.
12. Arhan Canli attribution and exact contribution boundary.
13. Public status that distinguishes preparation, outreach, review, replication, submission and
    acceptance.

## 17. Authorization boundaries

This plan authorizes local planning, code, tests, static artifacts, exact-commit previews and scoped
Git commits. It does not authorize:

- DigitalOcean resource creation or billable services
- paid data acquisition
- reviewer contact or compensation
- competition registration
- external account creation
- DOI minting, preprint submission or journal submission
- production promotion
- changes to broker credentials or capital state
- automated allocation authority

Each external or billable action requires a separate explicit owner decision after its exact target,
cost, reversibility and claim boundary are known.

## 18. Completion definition

This roadmap is complete only when the product is easier to understand and the advanced additions
are more truthful, not merely more numerous. Completion requires:

1. the 4-path product architecture live across every public shell
2. a measured comprehension pass
3. a stable public API and proposed reporting standard
4. evidence-bound selection, overlap and execution tools
5. advanced research kept behind preregistered challenger gates
6. independent review and reproduction states reported exactly
7. search authority earned from useful public objects
8. no weakened Sharpe, drawdown, sleeve, trial or evidence gate
9. no unsupported institutional, revolutionary or leadership claim
10. a public record that clearly credits Arhan Canli for the work he actually performed

## 19. Immediate next actions

1. Approve or amend the proposal decision ledger.
2. Generate the complete route and search-intent inventory from the current public build.
3. Draft the `/`, `/live`, `/research`, `/tools` and `/about` wireframes and copy map.
4. Define the comprehension-test script and immutable result format.
5. Specify `canli.paper-evidence.v0` before adding API endpoints.
6. Keep all advanced research proposals in `PLANNED_RESEARCH_ONLY` state until their individual
   protocols exist.

## 20. Continuity after chat compaction

This file is the durable source of truth for the clarity reset and advisor proposal ledger. After a
chat compaction, re-read this file and the prior governing plan before acting. Do not infer that a
planned capability was built, deployed, reviewed, indexed, submitted or validated. Report progress
from commits, receipts, tests and public artifacts only.
