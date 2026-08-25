# ALPHAC sleeve-discovery program

The governing objective is an honest forward Sharpe of 1.5 across up to 14 economically distinct sleeves, with approximately 11% expected maximum drawdown as a research objective. The implied in-sample support band is 2.25 to 3.0 after applying the book's published backtest-to-forward haircut; it is not a second forward target. Fourteen is reached only if at least ten new identities independently pass every gate; otherwise the book remains smaller. These are research targets, not forecasts, promises, or admission evidence. Results outside the ranges are published as measured. The previous 2.0 to 2.5 target was withdrawn on 2026-08-21 because its units were ambiguous and its forward interpretation was not reachable at measured sleeve quality.

The exact current-composition study measures average pairwise correlation of +0.0248 over 1,061 synchronized rows, with a 95% moving-block-bootstrap upper bound of +0.0487. The uncertainty ceiling passes, but the governing point gate of 0.00 does not, and this retrospective research study does not establish live-forward diversification. That creates mathematical room for a stronger portfolio, but it does not prove that future correlations remain low. New sleeves must add a return source, not merely another parameterization of price momentum.

## Admission sequence

1. **Pre-register.** Name the economic mechanism, data vintages, rebalance clock, costs, capacity model, variants and kill condition before reading the final holdout.
2. **Run the key-free screen.** Test data contracts, timestamps, neutralization and rough economics with public or already licensed data. This screen can kill an idea but cannot promote it.
3. **Authorize data spend.** Request a dataset or credential only when the screen shows that the missing information is genuinely decision-making. Store all secrets outside source and artifacts.
4. **Walk forward once.** Purge and embargo overlaps, record every variant in the union experiment ledger, and preserve its complete return curve whether it survives or dies.
5. **Deflate and stress.** Require DSR at least 0.95, PBO below 0.20, net costs, capacity, beta decomposition, crisis replay and correlation stability.
6. **Shadow deploy.** A candidate that clears research runs in a separate paper account or isolated strategy namespace. It does not enter ALPHAC until execution reconciliation passes.
7. **Admit prospectively.** Weight changes take effect from a dated schedule. Historical portfolio results are never recomputed as though the sleeve had always existed.

## Diversification gates

The ordinary common-window average pairwise correlation must be at most 0.00, no pair may exceed 0.35, and stressed pairwise correlation must remain at most 0.50. The average-correlation 95% upper bound must be at most 0.10; the pair and stressed upper bounds must independently remain below their 0.35 and 0.50 ceilings, with at least 504 aligned correlation observations, 756 OOS observations and 63 stressed observations. These are admission ceilings rather than optimizer targets. The portfolio objective is an average pairwise correlation near -0.03, but that objective is not a gate and cannot qualify a result. Crisis-conditional dependence and co-tail loss are mandatory; a low unconditional point estimate cannot pass.

Every execution `TESTED_PASS` is hash-bound to evidence and at least three scenarios. Capacity is
reconciled to a strictly increasing curve whose points carry capital, net Sharpe, stressed fill
ratio and stressed cost; three empty placeholders cannot pass. Non-finite metrics, booleans in
numeric fields and placeholder lineage hashes fail closed.

Diversification evidence must come from the shared deterministic implementation in
`alphaforge.validation.diversification`. It accepts only exactly aligned finite OOS simple returns,
an upstream-predeclared stress mask and fixed candidate weight; it uses a seeded 21-observation
circular moving-block bootstrap with 2,000 samples. The complete report is SHA-256 bound into the
candidate lineage.

The combined portfolio is evaluated before and after the candidate with fixed, pre-declared sizing. A sleeve can be admitted for drawdown convexity even with modest standalone Sharpe, but that exception must be explicit and cannot be described as proven alpha.

## Current research queue

The machine-readable queue is [`config/sleeve_discovery.json`](../config/sleeve_discovery.json).
Its nine active mechanisms are earnings-narrative change, analyst-revision drift, options
dispersion, merger arbitrage, index-reconstitution flow, electricity load/weather dislocation,
securities-lending supply, credit-equity relative value and active-ownership escalation. These are distinct data-generating
mechanisms rather than renamed versions of the existing price, carry, trend or macro sleeves.

The earnings-narrative candidate has passed its filing-only feasibility gate without opening a
return or spending a hypothesis. On the unchanged deterministic sample, parser v2 downloaded all
361 filings, extracted 10-K Item 1A at 90.82%, 10-K MD&A at 93.88% and 10-Q MD&A at 96.96%, and
passed a second adversarial heading-boundary review. The first return identity is now locked in
`docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md`: long stable versus short changed annual Item 1A
language, one lexical measure, one 63-session horizon, delayed entry, and fixed filing-reaction,
momentum and accession-time SIC controls. The full metadata manifest contains 83,070 unamended
10-Ks from 8,701 issuers, follows 2,309 archived SEC submission pages, has zero metadata failures
and zero duplicate `(CIK, accession)` identities. Of those, 82,491 filings across 8,122 issuers
have the history needed to form annual pairs; their resumable source-text ingest is in progress.
The locked OOS runner is implemented behind a machine-enforced return barrier and cannot load
prices until both the corpus and immediate-predecessor pair artifacts declare completion. It also
forces terminal histories flat at their final observed bar and downgrades any otherwise passing
result with such an event to `DATA-ESCALATE` pending dedicated delisting returns.
This status is an engineering result, not evidence of alpha; the honest trial count remains
unchanged until the OOS return is opened.

The first fresh v2 candidate, clustered insider purchases, has completed its one-shot OOS probe
and is retired as a published kill. It achieved real diversification (average correlation
-0.064; maximum pair +0.057) and passed beta, stress-correlation and $5 million capacity gates,
but net Sharpe was -0.243, Newey-West t was -0.79, DSR was effectively zero and a fixed 10%
allocation reduced combined-book Sharpe by 0.072. The sign is not inverted and its parameters are
not retuned. The full curve, event ledger, weights and machine-readable result are preserved under
`artifacts/probe/insider_purchase_clusters/`.

An implementation audit before publication found that the preliminary pass had combined adjusted
log returns under a simple-return curve contract. Correcting that deterministic arithmetic changed
the preliminary net Sharpe from -0.993 to -0.243 but did not change the KILL. Both values and the
reason for the correction remain in the result artifact; the corrected implementation also raised
immutable union execution records from 200 to 201 and conservatively raised distinct hypothesis
identities from 135 to 136. Those are different accounting concepts and are now published
separately.

The active campaign spends at most 24 new hypothesis identities; the current queue allocates all 24.
Date-window refreshes of an unchanged hypothesis remain visible but do not become fake new
identities. If the budget is exhausted, the program pauses for a formal review before another
candidate is tested.

An August 2026 deflation audit closed a second consistency defect in that accounting. Production
walk-forward verdicts now append only to their active profile ledger but read the verified union
of all four profile ledgers. Both DSR inputs use the same selection unit: the first immutable
record for each hypothesis identity. Operational window remeasurements remain in the audit trail
but can change neither selection `N` nor selection `V[SR]`. At the correction snapshot the union
contained 205 immutable records, 138 identities and 67 window-only remeasurements. The aligned
per-period Sharpe variance was 0.00098719 versus 0.00072998 over raw records, so the correction
raised rather than relaxed the current deflation penalty. The CLI, grand-matrix analysis and new
screen-stage probe path share this implementation; verdict provenance lists every ledger read.

The follow-on historical screen audit then disproved the apparent 22-identity headroom. Eight
complete `alphamax_construction` walk-forward arms and sixteen persisted
`alphamax_weighting` grid cells had explicitly reported zero trials burned despite measuring
distinct return configurations. All 24 are now charged through an idempotent forensic import;
none collided with the existing union. That correction produced the historical 162-identity
snapshot preserved in `artifacts/audit/trial_debt_reconciliation.json`.

On 2026-08-22, a second scope audit found four durable experiment ledgers filed beneath
`artifacts/` that the canonical `var*` discovery glob had omitted. Restoring their 12 existing
hypotheses—without running an experiment—brings the current union to 244 immutable records and
174 identities across 14 families. A third source-bound audit then recovered 54 additional named
parameter configurations from seven persisted summary-only studies, including 32 return-generating
AlphaMax robustness cells and two post-hoc AlphaTrend selector procedures. No experiment was rerun.
The current union is 298 immutable records and 228 identities; the owner-authorized prospective
v7 ceiling is 400, leaving 172 identities, with hard reviews staged at 320, 360 and 400 and research
status `ACTIVE_STAGED_PROSPECTIVE_BUDGET`. The superseded 320 ceiling would have left 92 identities;
it remains in the audit rationale rather than being presented as current. Both corrections and the
prospective promotion are machine-readable in `config/trial_accounting.json`, and withdrawn
archive-broken-price ledgers remain excluded.

The first legacy-DSR restatement is now complete without opening a holdout or registering another
hypothesis. Persisted daily return series supported a current-union recomputation for 33 variants
across five historical families. All 33 fail the DSR 0.95 gate at current N=228 and
identity-aligned `V[SR]=0.0008957471`. Seven other families retain summary statistics but not their variant-level
return series; their historical DSR claims are retired rather than approximated because DSR also
depends on observations, skew and kurtosis. Original artifacts remain unchanged. The complete
hash-linked correction table and evidence gaps are published locally in
`docs/research/LEGACY_DSR_RESTATEMENT.md` and
`artifacts/audit/legacy_dsr_restatement.json`.

All twelve historical probe paths now calculate future DSR against the identity-aligned union or
fail closed before computation when an unregistered hypothesis is forbidden by the campaign
pause. A static policy guard prevents regression to raw ledger-row counts. The seven summary-only
historical artifact families remain retired: repairing executable code does not reconstruct their
missing return series or rehabilitate their old DSR output.

The second fresh candidate, EIA petroleum inventory scarcity, is also retired as a published
kill. The probe preserved 782 accepted contemporaneous WPSR Table 4 releases and quarantined one
release whose published difference contradicted its current and prior levels. Its average
correlation to the four sleeves was +0.0002 and its maximum pair correlation was +0.0321, but net
Sharpe was -0.589, Newey-West t was -1.84, DSR was effectively zero, and 2x-cost Sharpe was
-0.998. Both USO and UGA standalone legs lost money; the mean-zero and leave-one-year-out book
checks failed. UGA liquidity also limited fifth-percentile proxy capacity to about $14.9 thousand
at 1% ADV. No sign or threshold was changed after measurement. The full result is preserved under
`artifacts/probe/eia_petroleum_inventory/`.

The replacement electricity load/weather mechanism completed a key-free source audit without
reading returns or spending a hypothesis. EIA-930 has the required demand and day-ahead forecast
fields, but EIA explicitly permits corrections to replace historical submissions; its bulk file is
not a release-vintage archive. NOAA's 2000-2019 GEFSv12 archive is a retrospective reforecast, not
the operational forecast seen by traders. The candidate is therefore data-gated pending original
EIA-930 vintages, operational weather vintages and executable CME power-futures quote history. The
boundary and fixed PJM Western Hub market set are recorded in
`docs/design/FEASIBILITY_ELECTRICITY_LOAD_WEATHER.md`; no Alpaca credential is useful for this
futures-specific gate.

The merger-arbitrage metadata screen is likewise `DATA_GATED` without spending a return identity.
It scanned 2,794,953 cached official SEC filing records and found 1,965 high-precision target
anchors across 1,798 CIKs. Later Item 2.01/1.02 outcome coverage was 91.76%, but only 67.02% linked
to the locked prior Item 1.01 announcement window, below the declared 80% gate. Target tender
filings performed better (86.65%), but the aggregate protocol was not narrowed after observation.
A future tender-only document contract or licensed PIT deal database must be declared separately.

That separate tender-only contract has now also closed `DATA_GATED`. On the frozen 100-file
`SC 14D9` sample, immutable downloads and Item 4 extraction passed, but only 10.64% of extracted
sections yielded a unique canonical cash price, 74.47% were ambiguous, and recommendation posture
resolved in only 22.34%. The parser was not retuned after the result. Merger arbitrage therefore
still requires a licensed point-in-time deal-state source or an independently labelled extraction
program before any spread return may be opened; this branch also spent zero return identities.

The active-ownership escalation family has passed a separately declared schema-aware metadata
gate without opening documents or returns. Its first protocol correctly failed after exposing the
2025 `SCHEDULE 13D` form-name transition and the SEC index's dual subject/reporting-owner CIK
associations. V2 preserved that failure, included both exact initial form names, and audited 800
immutable headers. It found 22,353 unique accessions, 100% target/filer/acceptance lineage, and 378
contemporaneous domestic-common mappings; the 47.25% mapping rate has a 43.81% Wilson 95% lower
bound and every annual cell had at least 15 mapped filings. This authorizes only the locked Item 4
document feasibility stage. Zero return identities have been spent.

That document stage is now closed `DATA_GATED`. Parser v1 resolved 159/160 submissions but
extracted Item 4 from only 125/160 (78.13%). A separately declared v2 corrected only official
legacy-heading variants and structured `<item4><transactionPurpose>` XML while keeping the same
sample and 90% gate. It improved coverage to 139/160 (86.88%) but still failed. One accession with
two exact-form primary documents remained deliberately unresolved. No parser v3, manual-label
rescue, price query, or return test was opened; the family now requires independent labels or a
licensed point-in-time ownership/activism feed.

## Credentials and datasets

Alpaca can execute the US-equity, ETF and approved-options candidates in paper and later live
environments. It does not replace point-in-time estimates, transcripts, historical option chains,
deal histories, index announcements, futures contracts, securities-lending records or corporate
bond data. Paid data is requested only after a key-free feasibility pass proves that the missing
field is decision-making.

Keys are requested one provider at a time, named by environment variable, after a candidate reaches the relevant gate. They are never pasted into code, JSON, website bundles, research publications or chat logs.
