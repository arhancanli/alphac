# ALPHAC / Canli Capital — autonomous work backlog

**This file is the state.** Each loop iteration reads it, picks the next item, does it, and
writes back. If you are an iteration starting now: go to **HOW TO PICK THE NEXT ITEM** and follow
it exactly. Do not re-plan, do not re-derive the strategy, do not summarise this file back to the
owner. Do the next item.

The owner is asleep. **Ask nothing.** If an item cannot proceed without a decision, mark it
`BLOCKED-OWNER`, write one line saying what the decision is, and move to the next item.

---

## THE GOAL, as re-anchored 2026-08-21

An **honest forward Sharpe of 1.5** across up to fourteen sleeves, with a maximum drawdown near
11% expected, that is **verifiable by an outsider**.

Forward, not in-sample: this book publishes an in-sample equal-risk Sharpe near 1.04 against an
honest forward estimate of 0.3–0.9, so its own measured backtest-to-forward gap is 1.5×–3×. A
target quoted in-sample is quoted in the units that flatter. The implied in-sample band is
2.25 (at 1.5×) to 3.00 (at 2×).

A 2.0–2.5 forward target was published and is **withdrawn**: reaching it needed an average
pairwise correlation of −0.062 against a PSD floor of −0.077, which is 81% of the mathematical
limit. An honest 1.5 needs ρ̄ ≤ **−0.030** at measured quality, or s̄ ≥ 0.601 — both inside the
floor.

> **Corrected 2026-08-22 (C3).** This line read −0.0174 until then, and −0.0174 is the ρ̄ that
> reaches an IN-SAMPLE 2.0, which is a forward 1.33 at the optimistic end of this book's own
> published haircut band. Reaching a forward 1.5 needs in-sample 2.25 and therefore ρ̄ ≤ −0.030,
> which is what `config/sleeve_admission_contract.json` has carried all along as
> `average_pairwise_correlation_objective`. The old figure was a pre-re-anchoring number
> carried across the re-anchoring without being re-derived, and it flattered in the direction
> the paragraph above warns about. Nothing published ever carried it — the site derives this
> from the contract — so the correction is to this file only. s̄ ≥ 0.601 was and is right: it
> is the same in-sample 2.25 reached on the quality lever instead.

**The second half of the goal is the one that matters and it is not a number.** A forward 1.5 that
anyone can check — signed forward record, every killed candidate published, gates that provably
bite, corrections published against ourselves — is rarer than a 2.5 nobody can verify. Work that
increases verifiability counts as progress toward the goal, not as overhead.

### What binds, measured

| | |
|---|---|
| Correlation | **BINDING after all.** A real candidate measured ρ̄ = −0.0203 against the corrected −0.030 requirement — it clears the 2.0 bar it was compared against and misses the forward-1.5 one by 0.010, worth forward 1.37 vs 1.50. |
| Per-sleeve quality s̄ | **BINDING.** Measured 0.469 (live four) / 0.529 (three traded). Needs ≥ 0.601. |
| Sleeve count | Weakest lever. 14 vs 20 barely moves it. |
| Forward record | **14 days old** (reset 2026-08-07). The only instrument that defeats deflation. |
| Evidence today | DSR 0.213 / 0.052 / 0.000. Zero of 33 restated variants clear 0.95. |

---

## STANDING PROHIBITIONS WHILE UNATTENDED

These are not preferences. Violating one costs something that cannot be bought back.

1. **Spend no trials.** Register no hypothesis identity, open no return data on any untested
   family, run no new walk-forward on an unregistered config. The budget is 320 with 158 headroom
   and it is the owner's to spend. Re-measuring an ALREADY-registered identity on a longer window
   is a window-only remeasurement and is permitted.
2. **Change no live trading configuration.** `config/live_change_contract.json` is the gate. A
   default nobody overrides IS the production setting. This includes strategy defaults, book
   weights, sleeve composition, overlay parameters and the drawdown ladder.
3. **Change no allocation.** AlphaVintage keeps its quarter until the owner says otherwise.
4. **Publish no irrevocable public commitment.** Specifically: do not publish the forward
   pre-registration. Draft it, leave it unsigned.
5. **Withdraw nothing that is true and publish nothing that is unmeasured.** If a number is not
   measured, it does not go on the site.
6. **Never weaken a guard to make a suite pass.** If a guard fires, the guard is probably right.
7. **No destructive git.** No force-push, no history rewrite, no branch deletion.
8. **Deploy freely** when the full unit suite is green and `npm run verify` reports 0 errors —
   the deploy is change-gated and reversible, and a stale site is its own defect.

---

## HOW TO PICK THE NEXT ITEM

1. Read **WORK LOG** at the bottom to see what the last iteration did.
2. Scan the tracks **in order A → B → C → D → E → F**. Within a track, top to bottom.
3. Take the first item whose `STATUS:` is `TODO`. Skip `DONE`, `BLOCKED-OWNER`, `IN-PROGRESS`
   *only if* the log shows another iteration is actively on it in the last 30 minutes — otherwise
   an `IN-PROGRESS` item was interrupted and you should resume it.
4. Set it to `IN-PROGRESS`, then do the work.
5. When finished: set `DONE`, append a **WORK LOG** line, commit, and if the site changed, deploy.
6. If the item turns out to be blocked or wrong, set `BLOCKED-OWNER` or `TODO` with a one-line
   note explaining why, and move on. **Never delete an item.**

### Rules that apply to every item

- **Measure, do not assume.** Every claim in a commit message or on the site must be something
  you ran. If you did not measure it, say you did not.
- **Mutation-test every guard you write.** A check that cannot fail is worse than no check.
  Break the thing it guards, watch it fail, restore, watch it pass.
- **Assert every scripted edit.** A `replace` that silently matched nothing has been reported as
  shipped work here before.
- **Reach the state through the real path.** Fixtures pass on states the product cannot enter.
- **Run the full unit suite before committing.** `.venv/bin/python -m pytest tests/unit -q --no-cov`
  It now runs in parallel by default (`-n auto --dist loadfile`). To debug one test, add `-n0`.
- **The lint-debt transient is fixed (F1, 2026-08-22).** Adding a script no longer fails that
  guard: the census counts are floored rather than pinned, the verdict is compared on its own, and
  provenance drift reports itself as PROVENANCE ONLY by name. On a fresh checkout run
  `scripts/install_hooks.sh` once so the pre-commit hook regenerates the contract for any commit
  touching Python. If the verdict test fails, something real changed — do not resync, read it.
- **One item per commit**, with a message that says what was found, not what was done.

### The publish pipeline, in declared order

```
paper_trading_state.py → glassbox_export.py → audit_sleeve_family_lineage.py
  → export_lint_debt_contract.py → research_export.py
```
Then, in `~/meridian`: `npm run build && npm run verify`, and deploy with
`bash scripts/live_deploy_hourly.sh` from `~/alphaforge`.

---

# TRACK A — Protect the forward record

*The clock is the most valuable asset in the project and the least defended. It reset to zero on
2026-08-07. Every day is something that can only be waited for.*

### A1 · Draft the forward pre-registration (DO NOT PUBLISH)
STATUS: DONE — docs/design/FORWARD_PREREGISTRATION_DRAFT.md, unsigned, unpublished
WHY: `docs/design/PRE_REGISTRATION.md` already promises "earn the grade forward: ≥6–12 months
paper-trading the frozen book", but no artifact says WHAT is frozen, FROM when, and judged HOW.
Without it, 14 days of record is data. With it, it is an N=1 forward test whose hurdle is 0.88 at
five years instead of 2.44.
DONE WHEN: `docs/design/FORWARD_PREREGISTRATION_DRAFT.md` exists containing: the exact sleeve set
and weights, the rebalance rule, the overlay configuration, the start date, what counts as pass
and fail at 1/3/5 years, what would VOID the test, and the config fingerprint it is bound to. It
is committed, marked `UNSIGNED — REQUIRES OWNER`, and is NOT referenced from the public site.

### A2 · Extend the live-change fingerprint to the overlay and ladder
STATUS: DONE — 8 risk-path fields added, each mutation-tested through the real config path
WHY: The fingerprint covers `BlendStrategy` defaults and book composition. The overlay's
vol-target, the drawdown ladder's gross multipliers and the per-name `w_max` clip also move the
traded book and are outside it.
DONE WHEN: `scripts/export_live_config_fingerprint.py` covers them, derived not transcribed;
`config/live_change_contract.json` re-declared; the guard mutation-tested against a change to each
newly covered field.

### A3 · Stamp the record with its own provenance
STATUS: DONE — published in paper-state.json and research.json, guarded, mutation-tested
WHY: The published track record does not say which configuration produced it. A future reader
cannot tell whether a stretch of the curve was run under the same book.
DONE WHEN: `paper_trading_state.py` writes the live config fingerprint into the published state,
`research_export` carries it, and a guard asserts the published fingerprint equals the declared
one.

### A4 · Confirm the live-change gate fires in a real tick
STATUS: DONE — observed in two scheduled ticks; BLOCK path still only mutation-tested
WHY: A guard wired into a script is not a guard that ran. `scripts/check_live_change_declared.py`
was added to `live_tick.sh` but has never been observed executing in a scheduled run.
DONE WHEN: `var/log/live_tick.log` shows the check running in a scheduled `:25` tick with its
result, confirmed by reading the log rather than by inference.

### A5 · Record-continuity audit
STATUS: DONE — published, guarded, and it found a systemic gap and crypto AT the threshold
WHY: Nothing measures whether the forward record has gaps. A gap is as damaging as a config change
and is currently invisible.
DONE WHEN: a script reports, per sleeve, every day since go-live with no mark, publishes the gap
count, and a guard fails if the gap rate exceeds a declared threshold.

---

# TRACK B — Per-sleeve quality, the binding constraint

*s̄ measured 0.469; the goal needs ≥ 0.601. This is where the number comes from.*

### B1 · Ledoit–Wolf shrinkage at the EWMA's true effective sample
STATUS: DONE — immaterial today (0.36%), material at short halflife (4.5%); fix BEFORE shortening
WHY: `ledoit_wolf_cc` computes its intensity with `T` = the rows passed, and production passes the
full unweighted 720-row window while the matrix being shrunk is the EWMA. Conservative only while
the EWMA's effective sample exceeds 720. At a 21-day halflife on equity the effective sample is
**60.6 rows** against a T of 720. Flagged 2026-08-21, never measured.
DONE WHEN: measured on the real 17-ETF basket and the equity basket: delta* as coded vs delta* at
the effective sample, across the halflife ladder; published as an artifact; verdict stated on
whether it materially mis-shrinks the live book. **Do not change the live path** — measure and
report.

### B2 · Covariance window study through the LIVE estimator
STATUS: DONE — halflife is the lever, window is not; 720/7 buys 2.29pp for 0.031 Sharpe
WHY: The drawdown sweep simulated an untruncated EWMA. Production is windowed and seeded. The
mapping is now measured (`artifacts/analysis/live_covariance_memory`) but no drawdown study has
been run through the real estimator.
DONE WHEN: the drawdown sweep is re-run with the production `ewma_cov` (window + seed + shrinkage)
in the loop, per sleeve calendar, and the result says what halflife and window actually minimise
expected max drawdown on THIS estimator. Report only; changing the live config is A-track and
owner-gated.

### B3 · Per-sleeve quality decomposition
STATUS: DONE — AlphaTrend's drag is construction; the recoverable component is AlphaForge's cost
WHY: s̄ is an average over four very different sleeves and nothing says which one is dragging or
whether the drag is construction or execution.
DONE WHEN: each sleeve's standalone Sharpe is decomposed into signal, cost and execution
components on its own curve, published, with the largest single recoverable component named.

### B4 · Live-versus-backtest execution gap
STATUS: DONE — NOT measurable yet; power published. Re-run at ~3 months for a 5% gap
WHY: The cheapest possible s̄ is not new research, it is the deployed sleeves delivering what their
backtests claim. Historically this book has run at roughly half its backtest quality.
DONE WHEN: measured per sleeve for the days the live record covers, with the honest caveat about
sample length stated prominently. **If 14–30 days is too short to measure, saying so IS the
result** — publish the power calculation rather than a noisy estimate.

### B5 · Cost model realism check
STATUS: DONE — the one checkable component matches exactly; the fix is a schema field, not a parameter
WHY: `cost_frac_oneway = 0.001` is a flat one-way cost that does not widen in stress. The red-team
artifact already flags this as an open weakness.
DONE WHEN: the live fills are compared against the modelled cost on the days the record covers,
and the gap is published per sleeve.

---

# TRACK C — Correlation and breadth

*Correlation is NOT the binding constraint. Breadth work is therefore lower priority than Track B
— but it is the only route to fourteen sleeves.*

### C1 · Generalise the reachability pre-test into a reusable harness
STATUS: DONE
WHY: On 2026-08-21 all three families "one gate from passing" turned out to be unreachable by
extraction — the gates asked for things the documents do not contain, or blended populations.
That test was written three times by hand.
DONE WHEN: one script takes a family and its failing gate and reports the ceiling a PERFECT
detector would reach, so any family must pass it BEFORE a protocol is written. Applied
retroactively to the three known cases and reproducing their published answers.

### C2 · Reachability screen across the untouched atlas families
STATUS: DONE
WHY: 20 families are `NOVEL_ATLAS` with `return_data_opened: 0`. Writing protocols against them
without a reachability screen repeats the mistake three times over.
DONE WHEN: each is screened on literature and metadata ONLY — no return data, no hypothesis
registered — and ranked by whether its evidence is obtainable at all. Published.

### C3 · Orthogonality prior per family
STATUS: DONE
WHY: The goal needs ρ̄ ≤ −0.030. Families should be ranked by expected orthogonality to the
existing book before any is chosen, not after.
DONE WHEN: a documented prior per family with its reasoning, explicitly labelled as a prior and
not a measurement.

### C4 · Identity-redesign notes for the three failed families
STATUS: DONE
WHY: spin-off, customer-supplier and merger-arb each mis-specified their population. A redesign
must name the document that carries the mechanics before it names a threshold.
DONE WHEN: one note per family saying what document would carry the evidence and what a corrected
identity would look like. **Draft only — registering it spends a trial.**

---

# TRACK D — The site, its explanation, and reach

*99 indexable URLs, 13 topic hubs, 80 papers. The corpus is strong; the explanation is thin.*

### D0 · Surface the twelve published-but-invisible measurements
STATUS: DONE
WHY: Found 2026-08-22 while wiring C1's artifact into the publish path. Twelve analysis artifacts
are copied to `/glassbox/*.json` and embedded in `research.json`, and `js/research.js` renders
NONE of them: admission_dry_run, book_without_alphavintage, spinoff_prorata_gate,
feasibility_gate_reachability, reachability_harness, live_covariance_memory, record_continuity,
ledoit_wolf_effective_sample, drawdown_live_estimator, sleeve_quality_decomposition,
execution_gap_power, cost_model_realism. Every one is a real measurement — several are the
corrections and the nulls, which are the site's whole argument — and a reader reaches them only by
guessing a JSON URL. This is the same shape as the defect C1 found (published to one place, not
the other) and it is larger: the strongest evidence on the site is the least visible, and unlinked
JSON earns no search ranking at all.
DONE WHEN: each artifact is rendered on a page a reader can reach by clicking, with its claim
boundary shown beside its numbers, and every one is reachable from `/research` or `/systems` in at
most two clicks. The renderer must be driven by what `research.json` CONTAINS rather than by a
hard-coded list, so the next artifact appears without a site edit — otherwise this item recurs.
On-page audit still 0 errors.

### D1 · Make /systems explain the engine end to end
STATUS: DONE
WHY: The page lists components. A reader cannot follow how a signal becomes a position becomes a
published number.
DONE WHEN: the page walks the whole path — lake → factor → portfolio → overlay → execution →
publication — with each stage linking to the artifact that proves it, and the on-page audit still
reports 0 errors.

### D2 · Give each topic hub a real essay introduction
STATUS: DONE
WHY: Each hub carries one paragraph. A hub is a page that should rank for its subject, and one
paragraph over a link list is thin.
DONE WHEN: each of the 13 hubs opens with 3–6 paragraphs of genuine subject content — what the
mechanism is, what the literature supports, what this book found — written, not templated.

### D3 · A "how to verify us" page
STATUS: DONE
WHY: The reproduce kit exists and works (23/23 hashes, 2/2 signatures, golden master). Nothing on
the site explains it to someone who has not already found it.
DONE WHEN: a page walks an outsider through L1/L2/L3 with the exact commands, linked from the
homepage and the glass box, in the sitemap.

### D4 · Founder page
STATUS: DONE
WHY: 80 papers resolve authorship to a `Person` @id that has no page behind it.
DONE WHEN: a page exists with the `Person` markup, what the work is, and links to the corpus.
State only what is verifiable — no credentials, affiliations or awards that cannot be checked.

### D5 · Methodology / FAQ page
STATUS: DONE
WHY: The long-tail questions — what is a deflated Sharpe, why publish failures, what is a kill
log, what is point-in-time data — are exactly what the corpus answers and nothing indexes.
DONE WHEN: a page answers them in the project's own words, each linking to the paper that
demonstrates it.

### D6 · Internal-link reachability audit
STATUS: DONE
WHY: Nothing asserts every paper is reachable from the homepage in a bounded number of clicks.
DONE WHEN: a script builds the internal link graph from `dist/` and fails if any indexable page is
more than three clicks from `/`, wired into `npm run verify`.

### D7 · Re-submit IndexNow after every publish
STATUS: DONE
WHY: 99 URLs were submitted once by hand. New pages will not be.
DONE WHEN: `npm run indexnow` runs as part of the deploy path, and a failure is loud rather than
silent.

### D8 · Title-length residual
STATUS: DONE
WHY: 22 pages carry titles over 65 characters because the documents' real names are long.
DONE WHEN: either a defensible short-title field is added at the source, or the residual is
documented as accepted with the reason, so the warning stops being noise.

---

# TRACK E — Verification machinery

*This is what makes the goal's second half real. It is not overhead.*

### E1 · Mutation-test every guard that has never been mutated
STATUS: DONE
WHY: Several guards have never been proven able to fail. A check that cannot fail is worse than no
check, and this repository has shipped that failure repeatedly.
DONE WHEN: every test under `tests/unit/` that guards a published claim has a recorded mutation
result. Produce a table of guard → mutation → observed failure. Any guard that cannot be made to
fail is a finding.

### E2 · Complete the four unfinished audit dimensions
STATUS: DONE
WHY: An adversarial audit was stopped after two of six dimensions reported. Never completed:
contract satisfiability beyond the pairs already fixed, guards-that-cannot-fire, published-claims
versus artifacts, and unit/numerical correctness.
DONE WHEN: each is worked by hand and its findings recorded — confirmed or refuted, with the
refutations kept.

### E3 · Every published number traces to an artifact
STATUS: DONE — guard shipped and in `npm run verify`; 10 residual numerals are BLOCKED-OWNER below
WHY: The kill papers have this guarantee. The rest of the site does not.
DONE WHEN: a guard extracts numerals from the rendered site and reports any that cannot be traced
to a glassbox artifact. Expect false positives on dates and version numbers; handle them by rule,
not by exemption list.

### E3b · Ten published numbers trace to nothing (BLOCKED-OWNER)
STATUS: BLOCKED-OWNER — each is a hand-written figure with no artifact anywhere in the repository;
removing one would withdraw something that may be true, and manufacturing an artifact for it would
be worse. The owner has to say, for each, either what run produced it or that it should go.
`npm run verify` is RED until then, by design: the alternative is a green gate on a site that
publishes numbers a reader cannot check.

  /progress                                    2,820
  /progress, /systems                          8,436   ("survivorship-free US stocks")
  /research/alphavintage-missing-release-correction    -25.1, 0.3382071994
  /research/engineering-quality                3,760
  /research/options-execution-foundation       26853, 59573
  /research/prereg-earnings-narrative-change   24.6

⚠️ Was TEN on 2026-08-22 13:50, then EIGHT: `-252` and `22.5` dropped off without anybody fixing
them, because publishing the claim-coverage map added its own numbers to the traceable universe.
E5 fixed the dilution for the 31 pages whose generator declares its sources — those are now traced
against ONLY those artifacts and report **zero** findings. These eight sit on pages that declare
nothing, where the whole-corpus fallback is all there is; the audit reports them in their own
bucket so the weaker basis is visible rather than blended into one total. `8,436` came back when
the fallback was tightened, which is the point.

### E5 · The number-trace universe dilutes itself
STATUS: DONE
WHY: `audit-published-numbers.mjs` traces a page's numerals against EVERY number in EVERY published
artifact, and that corpus grows on every publish. Two genuinely untraceable figures started tracing
within two hours of E3 shipping, purely because a new artifact happened to contain matching values.
A guard that weakens each time the record grows is one that expires.
DONE WHEN: a page's numerals are traced against the artifacts THAT PAGE references — exact for
measurement pages, which name their source — with the whole-corpus fallback used only where a page
declares no source, and that fallback reported separately so its weakness is visible.

### E4 · Claim-coverage map
STATUS: DONE
WHY: Nothing says which published claims have a guard and which do not. Split coverage reads as
coverage.
DONE WHEN: a published map of claim → guard → last-run, with unguarded claims named.

---

# TRACK F — Housekeeping that protects everything else

### F1 · Make the lint-debt resync automatic
STATUS: DONE
WHY: `test_persisted_contract_matches_builder_and_content_hash` fails after any script edit and
has been hand-resynced ~10 times in one day. A test that routinely fails for a benign reason
trains its reader to ignore a real failure.
DONE WHEN: the contract regenerates as part of the pre-commit or test path, or the test
distinguishes a benign staleness from a real violation and says which.

### F2 · Full-suite runtime
STATUS: DONE
WHY: The unit suite takes ~2.5 minutes and is run many times per session.
DONE WHEN: the slowest tests are identified and either parallelised or justified, with the before
and after recorded.

### F3 · A system map for a future reader
STATUS: TODO
WHY: The repo has ~40 analysis scripts, 6 contracts and two publish pipelines. Nothing explains
the whole to someone arriving cold.
DONE WHEN: `docs/design/SYSTEM_MAP.md` exists, derived from the actual files rather than memory.

---

# BLOCKED — owner decisions, do not act on these

- **EIA API key** (free, `eia.gov/opendata/register.php`) — unblocks `electricity_load_weather`.
- **Databento** (paid) — unblocks `natural_gas_storage_weather`.
- **AlphaVintage allocation** — carries 25% of the book; the production evaluator rejects it, and
  removing it costs 39% more drawdown and 15% of the diversification ratio. Measurement published;
  the call is the owner's.
- **Signing the forward pre-registration** (A1) — an irrevocable public commitment.
- **Spending trials** on any new family — 158 headroom, owner's to release.

---

# WORK LOG

*Append one line per completed item. Newest at the bottom. This is how the next iteration knows
where it is.*

- `2026-08-21 21:05` — Backlog created. State: all TODO except the five owner-blocked items above.
  Prior session shipped: contract v6 (four unsatisfiable gates fixed), trial budget 160→320,
  objective re-anchored to honest forward 1.5, 80 research papers + 13 topic hubs published (99
  URLs, was 6), www→apex 301, live-change ceremony built and blocking, covariance memory measured
  and one published claim corrected. Full suite green, reproduce kit 23/23, site audit 0 errors.
- `2026-08-21 21:20` — **A1 DONE.** Forward pre-registration drafted at
  `docs/design/FORWARD_PREREGISTRATION_DRAFT.md`. Freezes the four-sleeve book at equal quarters
  plus the disclosed +10% tilt, the sizing configuration bound to fingerprint `e79dd975…`, the
  10% vol-target overlay, and the 2026-08-07 start. Judgement thresholds are `1.96/sqrt(T)` —
  1.960 at 1y, 1.132 at 3y, 0.877 at 5y, 0.620 at 10y — measured on the NEUTRAL CORE with the
  tilt excluded, and stated explicitly as *not* the 1.5 target so clearing them cannot be read as
  reaching it. INCONCLUSIVE named as the expected outcome for years. Five void conditions written
  down, including any change to AlphaVintage's allocation. Verified NOT referenced from either
  publish script. Suite green. **Unsigned — signing is owner-blocked.**
- `2026-08-21 21:40` — **A2 DONE.** The fingerprint claimed to cover "how the live book trades"
  and did not: the overlay's `vol_target_ann` / `vol_scale_max` / `gross_max`, the ladder's
  `dd_halve_gross` / `dd_flat_halt` / `flat_cooldown_bars`, `staleness_max_bars` and the
  inviolable per-name `w_max` are read off `Settings` (strategy.py:198-231) rather than passed to
  the constructor, so a guard built by inspecting the constructor signature could not see them
  however carefully written. All eight now read through `Settings` and
  `PortfolioConstraints.from_settings`, so a config change reaches the fingerprint by the same
  path it reaches the book. Re-declared (`ec06c65b…`) as a COVERAGE change — every value recorded
  is the value already running, and no live configuration was touched.
  Mutation-tested twice: all 8 fields individually, and `vol_target_ann` 0.15 → 0.22 edited in
  `config/settings.py` itself, which the tick-time gate blocks while naming the field.
  New invariant `test_every_field_in_the_surface_actually_moves_the_fingerprint` asserts over the
  WHOLE surface that a recorded field reaches the hash, so a setting added tomorrow is checked the
  day it appears. It fired on its own first run — the mutation helper could not perturb a dict, so
  it accused `sleeves` and `strategic_tilt_mix` of being uncovered when they are not. The helper
  was measuring itself; every branch now actually changes the value. Suite green.
- `2026-08-21 21:55` — **A3 DONE.** The published record now carries the fingerprint of the
  configuration that produced it, in `paper-state.json` on both hosts and in `research.json`.
  Measured by the same function the tick-time gate uses, so the stamp cannot disagree with the
  guard, and the DECLARED value is carried beside the measured one so a disagreement is visible
  in the artifact rather than only in a test.
  The design choice that matters: `matches_declaration` is published as a BOOLEAN and never used
  to refuse to write the record. Refusing to publish because a configuration changed would
  destroy the record in order to protect it — a marked discontinuity is recoverable, a hole in
  the forward record is not, and a hole is the same harm the ceremony exists to prevent. A guard
  reads the source and fails if the stamp ever appears on a `raise`, `assert` or `sys.exit` line.
  Three guards added, all mutation-tested: publishing a record stamped under a foreign
  fingerprint fails, and removing the stamp entirely fails two. Suite green.
- `2026-08-22 01:45` — **A4 DONE, by reading the log rather than inferring it.** The gate ran in
  two scheduled `:25` ticks: `var/log/live_tick.log:227907` inside the tick that started
  `20:25:03Z`, and `:227946` inside `21:25:03Z`. Stronger than the item asked for — the
  fingerprint CHANGED between them (`e79dd975…` → `ec06c65b…`, A2's coverage extension), which
  proves the tick reads the live value rather than a cached one.
  ⚠️ **Only the PASS path is confirmed in production.** The BLOCK path has never fired in a real
  tick because the configuration has never disagreed; it is confirmed by mutation test only. That
  distinction is recorded rather than glossed.
  Also fixed while here: the deploy-skip message hard-coded "(deploy skipped by the
  retracted-claim gate)" and there are two gates on that branch now, so a live-change block would
  have named the wrong cause and sent the next reader to the wrong file. It now names whichever
  gate blocked, or both. All four combinations exercised against the real logic. Suite green.
- `2026-08-22 01:55` — **A5 DONE, and it found something.** `scripts/audit_record_continuity.py`
  measures every day since go-live with no mark, per sleeve, and it does NOT count them the same
  way for all four: a weekend absence is legitimate for a sleeve that does not trade weekends and
  a real gap for one that trades 24/7. Counting them identically would make the equity sleeves
  look permanently broken and hide a genuine crypto hole.
  ⚠️ **Two findings on a 15-day-old record.** `2026-08-10`, a MONDAY, has no mark on ANY sleeve —
  systemic, the tick did not run. And the crypto sleeve sits at **exactly 20.0%**, the declared
  threshold, so one more missed day fails it. Published at `/glassbox/record_continuity.json`.
  Threshold is DECLARED at 20% rather than fitted; a guard asserts it does not equal the worst
  observed rate, which is what a fitted bar looks like.
  Six guards, mutation-tested (a 35% gap rate fails the gate). Wired into BOTH publish jobs — the
  pipeline-order test caught that I had added it to the hourly tick only, which is the exact
  split-coverage defect where two jobs each cover what the other checks. Edge declared. Suite green.
- `2026-08-22 02:10` — **B1 DONE.** Measured on the real 17-ETF basket, 720 sessions, published
  at `/glassbox/ledoit_wolf_effective_sample.json`. Live path unchanged.
  **The approximation is non-conservative at EVERY halflife, not just short ones**, and the
  documented reasoning is why: it assumed the EWMA's effective sample could EXCEED the 720-row
  window. A windowed estimator's effective sample is bounded BY the window — measured, it peaks
  at 635 rows and is 514 at the production setting, so delta* is understated everywhere
  (1.13x–11.88x).
  **But the channel matters more than the direction.** The constant-correlation target shares S's
  diagonal, so this shrinkage cannot change a variance and inverse-vol weights — what the
  production `rank` allocator sizes on — are mathematically INVARIANT to it. My first impact
  measurement returned 0.000000 at every halflife, which is what a measurement that cannot move
  looks like rather than a finding; I investigated instead of reporting it. The error reaches the
  book only through the off-diagonal, i.e. the overlay's ex-ante vol.
  **Verdict graded by materiality, not direction:** 0.36% mean ex-ante vol error at production
  (immaterial), 4.46% mean and 38.1% worst case at a 21-bar halflife (material). **Fix it BEFORE
  shortening the covariance halflife, not after** — which is now a precondition on B2. Suite green.
- `2026-08-22 02:30` — **B2 DONE.** The original sweep updates covariance with an UNTRUNCATED
  recursion — infinite memory, no window, no seed. Re-run through a vectorized twin of the
  PRODUCTION estimator, asserted equal to `ewma_cov` on real states (max abs error 1.4e-19) before
  any result was reported. Published at `/glassbox/drawdown_live_estimator.json`.
  **THE HALFLIFE IS THE LEVER AND THE WINDOW IS NOT.** Inside the production 720-bar window,
  expected max drawdown falls monotonically: 10.25% at halflife 720, 9.45% at 63, 8.38% at 21,
  7.96% at 7. Shortening the WINDOW buys nothing on top — 168/21 gives 8.52% against 720/21's
  8.38%, inside the standard error. This confirms the corrected reading and finally settles the
  claim I published and withdrew earlier today.
  **Priced.** 720/21 buys 1.87pp for **0.0103 Sharpe** at 10bp; 720/7 buys 2.29pp for 0.0306.
  720/21 is the better ratio. ⚠️ No configuration holds p95 at or under 11% — best is 13.5%.
  ⚠️ **Precondition recorded:** at a 21-bar halflife the Ledoit-Wolf error (B1) is 4.46% of
  ex-ante vol and worse at 7. Fix B1 BEFORE shortening. Any change is owner-gated and VOIDS the
  forward pre-registration draft. Suite green.
- `2026-08-22 02:50` — **B3 DONE.** Published at `/glassbox/sleeve_quality_decomposition.json`.
  | sleeve | net SR | commission | spread | funding | signal residual |
  |---|---|---|---|---|---|
  | AlphaMax | 0.907 | 0.003 | 0.017 | — | 0.927 |
  | AlphaForge | 0.677 | 0.145 | 0.130 | **0.382** | 0.569 |
  | AlphaTrend | **0.327** | 0.021 | 0.104 | — | 0.451 |
  **AlphaTrend is the weakest and its drag is CONSTRUCTION, not execution** — its whole cost
  burden is 0.125 Sharpe points, so recovering every penny still leaves it at 0.451.
  **The largest recoverable component is AlphaForge's transaction cost: 0.275 Sharpe points**,
  driven by 33.2x annual turnover. Recovering half is worth 0.137 on that sleeve.
  ⚠️ **The boundary is the finding as much as the numbers.** `fees_paid` in every summary.txt is
  COMMISSION ONLY — measured at 1bp equity / 5bp crypto — while spread and impact are applied to
  the FILL PRICE and never recorded as a line item. So spread is MODELLED from declared bps and
  market impact is NOT SEPARABLE at all; it sits inside the residual. Anyone reading `fees_paid`
  as total transaction cost understates it badly.
  Also caught: a closure over the loop variables would have computed every sleeve with the LAST
  sleeve's equity, vol and horizon — and the numbers would still have looked plausible. Suite green.
- `2026-08-22 03:05` — **B4 DONE, and the answer is "not yet".** Published at
  `/glassbox/execution_gap_power.json`. Overlap between live marks and a walk-forward covering
  the live period exists for TWO sleeves only — the blessed research curves end 2026-06-01 by
  design, before go-live, so they cannot answer this at any record length. That overlap is 5 and
  9 days: **four and eight return observations**.
  Observed: AlphaMax **−11.81% ± 10.48%** annualised (−1.13 SE), AlphaTrend **−2.84% ± 8.68%**
  (−0.33 SE). Both negative, neither distinguishable from noise. Recorded as OBSERVATIONS, not
  estimates.
  **The deliverable is the power, and it is actionable.** The tracking difference
  `d = r_live − r_backtest` answers this far sooner than either Sharpe, because both run the same
  signal on the same days and the difference series is much less noisy than either level.
  A **5% annual gap becomes visible in 3–4 months** — that is when to re-run this. A **1% gap
  needs 6.7–9.2 years** and is not answerable by waiting; it would have to be attacked by
  measuring fills against their decision prices directly.
  Suite green.
- `2026-08-22 03:20` — **B5 DONE. Track B complete.** Published at
  `/glassbox/cost_model_realism.json`.
  **What matched:** crypto commission, MEASURED at **5.00bp** against a modelled taker fee of
  **5.0bp** — exact. The one cost component in the book that can be checked against reality
  checks out. Crypto slippage against `modeled_price` averages −3.18bp (favourable), all taker,
  book never exhausted.
  ⚠️ **The latency finding.** Median submit-to-fill across the equity sleeves is **5.5 HOURS** —
  orders go in after the close and fill at the next open. The model represents latency as a flat
  2bp add-on, which is a microstructure quantity. An overnight gap is not a spread; it is
  unhedged exposure with a fat-tailed cost. Not evidence the model is wrong by an amount —
  evidence it models this component as the wrong KIND of thing.
  ⚠️ **Zero crypto fills since go-live** (last 2026-07-30) against a weekly rebalance over a
  15-day record. Surfaced, not diagnosed.
  **What cannot be asked, and the fix.** Equity slippage is not computable: the fills record
  `limit_price`, a PADDED marketable limit, so a fill "beating" it by 54bp is beating the padding.
  Equity commission has no fee column at all. **THE FIX IS ONE FIELD — record the reference mid at
  `submitted_ts`** — which turns implementation shortfall from unanswerable into a daily
  measurement and costs nothing to capture. No cost parameter should move on this evidence; the
  schema should. Suite green.
- `2026-08-22 00:35` — **C1 DONE.** `scripts/reachability_harness.py`. Takes a family and its
  failing gate and answers whether the gate is reachable AT ALL before any protocol is written:
  four verdicts from three numbers (measured rate, gate, ceiling) plus a heterogeneity test for
  the case where one threshold is applied across populations that do not share the obligation it
  tests. Re-derives all three hand-worked answers — spin-off `0.1633` vs a `0.1122` ceiling and
  `0.30` gate, customer-supplier `0.3533` vs `0.3714` and `0.50`, merger-arb `0.6702` vs a `0.80`
  gate that blends two filing populations — and REFUSES TO RUN if any of them stops reproducing.
  **What deliberately does not generalise: the ceiling probe.** What a perfect detector would find
  is a property of the mechanism, so each family must supply its own; the harness makes that a
  required argument rather than inventing one, because a harness that guessed the ceiling would be
  a rubber stamp — it would clear everything, which is precisely the move (widen the detector until
  the number clears) the pre-test exists to prevent. The BLENDED verdict carries its own warning in
  the artifact: a clearing subgroup is not permission to narrow the universe, because selecting it
  after observing that it passes makes its rate in-sample for that decision.
  `tests/unit/test_reachability_harness.py` exercises every branch on constructed cases, not only
  the three registered families — a verdict function that returned UNREACHABLE for everything would
  have reproduced two of the three published answers and looked correct — and mutation-tests the
  drift guard by flipping an expected verdict and asserting the run aborts.
  ⚠️ **A real defect found on the way, in the publish path rather than the research.** Wiring the
  new artifact into `research_export.py` meant editing THREE hand-mirrored lists (bundle key,
  primary-host copy, app-host copy), and one of them had already drifted:
  `legacy-dsr-restatement.md` — the paper restating every Sharpe the deflation correction touched
  — was being published to the app host and **not to the primary site**. Nothing could have caught
  it. The paper is not linked from `research.json`, so its absence broke no link, failed no build
  and returned no 404; the primary site was simply missing a document, silently, until two
  directories were diffed by hand. Fixed, and `tests/unit/test_glassbox_write_paths.py` now
  compares the two blocks as SETS of (public name, source) copy pairs — an invariant over the
  class, not a list of today's filenames. It pins a floor on each side first, because the cheapest
  way to satisfy `A == B` is for a broken parser to make both empty; it pins the
  `literature_dir`-inside-`app_literature_dir` substring trap that would fold one host's writes
  into the other's set; and it excludes computed writes by the rule that only file-sourced writes
  are copies, rather than by an exemption list that would rot. Verified against the pre-fix source:
  the guard reports exactly the one-sided write.
  Full unit suite green, `ruff` clean on the new files, retracted-claim gate PASS, reproduce kit
  23/23 content hashes + 2/2 signatures + golden master. 0 trials — the harness reads frozen
  artifacts read-only and authorises no candidate.
- `2026-08-22 01:20` — **C2 DONE.** `scripts/atlas_reachability_screen.py`, published at
  `/glassbox/atlas_reachability_screen.json`. All twenty untouched `NOVEL_ATLAS` families screened
  on obtainability alone — no return data, no hypothesis, 0 trials.
  **The decisive part needs no judgement.** The contract requires 756 daily OOS observations,
  which is **3.0 years**; a candidate's return series cannot outlast the source that produces it,
  so any family whose best source has less history than that is out of reach on arithmetic before
  anyone argues about the idea. Both the 756 and the family list are read from the contract and
  the atlas rather than typed, and the history of all seven sources this repo holds is re-derived
  from the lake on every run: EDGAR indexes 15.75y, FRED 10y breakevens 23.63y, FINRA short
  interest 8.54y, crypto perp funding 6.00y, Deribit option snapshots **0.16y**.
  **The result: 6 of 20 are blocked on engineering. The other 14 are not, and no amount of work
  closes them.** Ten are vendor-licensed — a spending decision with a number attached, not a
  research question. Two trade on prices that are *assessed or indicated rather than transacted*
  (Baltic route assessments, cat-bond broker sheets): the record is obtainable and a backtest on
  it would measure a price nobody could have traded, which is worse than a null because it
  produces a number. One, `crypto_liquidation_pressure`, has **no point-in-time record at all** —
  venues stream forced liquidations and archive at most a rolling window, so it cannot be bought
  or scraped after the fact, only collected forward starting now; the contract minimum is then a
  three-year WAIT, and that wait is the finding.
  ⚠️ **The trap the screen was built to catch, and did.** `securities_lending_supply` is priced off
  the borrow FEE. This repo holds FINRA short interest — available, correlated, and a different
  quantity: the size of the position, not its cost. A screen reporting "we have short interest"
  would have sent the next iteration to work on a family whose mechanism we cannot price. The
  verdict is VENDOR and the note says why the held proxy does not substitute.
  Best find: `inflation_breakeven_relative_value` is reachable **today** on data already held —
  daily breakevens from 2003-01-02, unrevised market quantities, so point-in-time by construction
  rather than by careful handling. Narrower than it looks and the artifact says so: what is held
  supports the breakeven-versus-realised formulation and NOT the swap-versus-breakeven one.
  Measured and judged are separated per FIELD rather than in a disclaimer — every row about a
  record we do not hold is stamped `JUDGEMENT_NOT_VERIFIED_THIS_RUN` and carries the concrete
  check that would settle it, with a test asserting no such row can exist without one.
  `tests/unit/test_atlas_reachability_screen.py` (11 tests) breaks the derivation in both
  directions — a family added to the atlas fails the screen, a family that opens return data fails
  it too — pins that the arithmetic outranks the obtainability class (a two-year source we hold is
  held and useless, and must not read as held) and that it does NOT rescue a vendor or marks
  verdict, and proves an absent lake measures as absent rather than as a span of zero.
  Full unit suite green, ruff clean, retracted-claim gate PASS, reproduce kit 23/23. Deployed.
- `2026-08-22 02:05` — **C3 DONE.** `scripts/orthogonality_prior.py`, published at
  `/glassbox/orthogonality_prior.json`. A rule stated before scoring and applied by code, never
  case by case: shares a factor family with a live sleeve → LIKELY_CORRELATED; else shares a
  crisis direction → UNCERTAIN; else driven by something other than a price → STRONGLY_ORTHOGONAL;
  else LIKELY_ORTHOGONAL. Every row stamped `PRIOR_NOT_A_MEASUREMENT`.
  **Asset class is deliberately NOT in the rule, and the evidence is why.** Four sleeves give six
  pairs; at 1061 common days the Fisher SE is 0.0307, so only two resolve — and they are exactly
  the two that are structurally distinctive. The pair sharing a FACTOR family (AlphaMax × AlphaTrend,
  both momentum, different asset classes) is **+0.210 at 6.9 SE**, the largest in the book. The
  pair sharing an ASSET CLASS (AlphaMax × AlphaVintage, both US equity, different factors) is
  **−0.062**, negative. The four sharing neither are all inside 1.5 SE of zero. Factor overlap
  produced correlation; asset-class overlap produced the opposite of it.
  **The result: 1 of 20 remaining families is structurally orthogonal on this rule.** Five share a
  factor outright and fourteen lose money in the same event as AlphaForge. The atlas's remaining
  families are disproportionately carry and basis trades in twenty different wrappers — breadth
  measured in asset classes is not breadth, and `carbon_allowance_carry` is the clean illustration:
  nothing about European carbon resembles crypto perpetuals and it is the same trade.
  ⚠️ **The collision worth acting on.** `inflation_breakeven_relative_value` is the ONE family C2
  found reachable today on data already held — and it is priced off CPI, which is exactly what
  AlphaVintage trades. The cheapest family to work on is the one that diversifies least. An
  ordering built on obtainability alone would have put it first.
  ⚠️⚠️ **A correction to this file, found by doing the arithmetic instead of quoting it.** THE GOAL
  section said an honest 1.5 needs ρ̄ ≤ −0.0174. It does not: −0.0174 gives in-sample 1.995, which
  is forward **1.33** at the optimistic end of this book's own haircut band. Forward 1.5 needs
  in-sample 2.25 and therefore **ρ̄ ≤ −0.030** — the figure `sleeve_admission_contract.json` has
  carried as `average_pairwise_correlation_objective` all along. −0.0174 was a pre-re-anchoring
  number carried across the re-anchoring without being re-derived, and it flattered in exactly the
  direction the paragraph above it warns about. Consequence: the "what binds" table said
  correlation was NOT binding because a real candidate measured −0.0203 against −0.0174. Against
  the correct −0.030 that candidate **misses**, at forward 1.37 against 1.50. Correlation is
  binding after all. Nothing published ever carried −0.0174 — the site derives this from the
  contract — so the correction is to this file only. s̄ ≥ 0.601 was and stays right.
  **And the ordering has a job because the gate cannot do it.** Every new pair landing exactly on
  the contract's 0.00 correlation gate gives a book ρ̄ of +0.0017 and a forward Sharpe of **1.16**.
  The 85 new pairs must average **−0.0340**. The gate is necessary and not sufficient by 0.34 of
  forward Sharpe, and a pre-measurement ordering is the only lever that acts on the difference.
  This extends `breadth_acquisition`, which reached the same conclusion against the superseded 0.15
  gate.
  Published UNCALIBRATED and says so: two informative pairs is one observation per structural cell,
  a direction rather than a coefficient. The weakest joint is named in the artifact — the crisis
  axis decides fourteen of the twenty rankings and this book holds one SHORT_LIQUIDITY sleeve, so
  no pair tests it. What would calibrate it is breadth, which is the uncomfortable ordering: the
  prior is least testable exactly while it is most needed.
  `tests/unit/test_orthogonality_prior.py` (13 tests) derives coverage from the atlas in both
  directions, exercises the rule branch that is EMPTY in today's data, pins the precedence, and
  mutation-tests that the measured pairs are classified by the SAME sleeve table the families are
  scored against — retag AlphaTrend's factor and the shared-factor flag flips, so the artifact
  cannot argue from one taxonomy and rank by another. The required new-pair average round-trips
  back to the objective, and the gate-is-insufficient claim is recomputed rather than transcribed.
  Full unit suite green, ruff clean, retracted-claim gate PASS, reproduce kit 23/23. Deployed.
- `2026-08-22 02:55` — **C4 DONE.** `docs/design/IDENTITY_REDESIGN_NOTES.md`, published at
  `/research/identity-redesign-notes.md`. Three notes, **DRAFT, nothing registered, and no note
  proposes a threshold** — a test enforces that last part against the SHAPE of a proposal rather
  than a phrase list, so it cannot be rephrased around.
  **The three failures turned out to be one failure, three times.** Every protocol specified a
  LANGUAGE test where the identity needed a STRUCTURAL fact: a form type, a timestamp, or a
  counterparty named on a contract. Narrative prose is the least reliable carrier of any of them —
  an issuer writes the narrative, while the structure is imposed on them and does not move when a
  drafting convention changes. Each note therefore names the document that carries the evidence
  BEFORE it says anything about a threshold, which is the ordering the whole item is about.
  **Spin-off — measured, not argued.** A Form 10 is a REGISTRATION statement; the distribution
  ratio and record date are not settled when it is filed, which is why its information statement
  carries `[•]` where the ratio will go. The protocol asked a document to state a fact that did not
  exist on the day it was written. The universe it was trying to rediscover by reading prose is
  declared by the form type: `scripts/audit_spinoff_form_universe.py` counts **386 initial Form
  10-12B registrations over 2010–2025, mean 24.1/yr**, straight out of the sixty-four EDGAR master
  indexes already held — metadata, zero parsing, no look-ahead. The unwelcome half is published in
  the same artifact: 386 events in sixteen years is thin, and that bound belongs in the
  pre-registration rather than in a footnote after a disappointing result.
  ⚠️ **The obvious alternative was CHECKED and does not exist.** The tempting route was to take the
  event universe from the corporate-action feed we already hold. Sampling 600 instruments, the lake
  carries exactly two action types — `dividend` and `split` — and **nothing resembling a
  distribution**. Unmeasured, the note would have proposed a route that is not there and would have
  read just as confidently.
  **Customer-supplier.** The disclosure obligation is to report the CONCENTRATION, not the
  counterparty: an issuer must say a customer is material, and nothing requires them to say which.
  The gate asked the narrative for something the rule producing the narrative never required. The
  contract names its counterparty on its face, so the redesign keys on material-contract exhibit
  metadata — and the note explicitly refuses to carry the 50% threshold across to the new surface,
  because the naming rate in exhibit descriptions **has not been measured** and assuming it would
  repeat the original error with a new document.
  **Merger-arb.** The gate tested for the PRESENCE OF A DOCUMENT when the identity needs a
  TIMESTAMP, and several documents supply one. Requiring one specific form is a specification error
  dressed as a data-quality gate. The note restates in bold that this is not permission to keep the
  tender-offer stratum: 0.8665 is now in-sample for that choice and cannot be its own evidence.
  ⚠️ **A guard that passed and should not have, caught by mutation-testing it.** The first version
  asserted each artifact figure APPEARS in the note. That is the weak direction: `37.1%` is quoted
  twice, and corrupting one of them passed — as did changing `386` to `586`. Both were demonstrated
  before the fix. The check now runs the other way: **every measurement-shaped token in the prose
  must be derivable from an artifact**, with two declared non-measurements (an SEC item number and
  the drafting date). Re-mutated afterwards — all four previously-missed corruptions now fail.
  Writing that check also found an invented number in the note itself: an illustrative "23% of
  revenue" with nothing behind it, in a document arguing against exactly that. Removed.
  Full unit suite green, ruff clean, retracted-claim gate PASS, reproduce kit 23/23. 0 trials.
- `2026-08-22 03:50` — **D0 DONE.** `/measurements` plus **21 generated pages**, one per artifact.
  The twelve named in this item turned out to be twenty-one once the rule was written to find them
  rather than list them: `scripts/build-measurements.mjs` discovers anything in `research.json`
  carrying a canli schema or a claim boundary, at the top level or one level in. **The next artifact
  the exporter adds gets a page with no site edit at all** — which is the whole point, because a
  hand-kept list is exactly how this site once published a six-URL sitemap for thirty-four
  documents.
  **Built, not fetched.** Rendering these client-side would have put the evidence back out of reach
  of the thing that ranks it — the shared nav is assembled by `shell.js`, so a crawler reading the
  delivered HTML sees no link there at all. The numbers are in the HTML. Site URLs **99 → 123**.
  **The claim boundary is the most prominent element under the title on every page**, in its own
  framed block, above the numbers it qualifies. A measurement published without its limits is the
  failure this record exists to avoid, so on these pages the limits are not a footnote. Where an
  artifact carries no boundary field the page says so rather than inventing one.
  Reuses the research-paper shell (`css/paper.css`) rather than forking a second document design;
  the only new components are the boundary block, a facts list and a table, and no token is
  redefined. Each page is `Dataset` JSON-LD with a `DataDownload` pointing at the raw artifact, the
  index is a `CollectionPage`, and the sitemap entries are derived from what landed on disk.
  Reachability: STATIC links added on `/research` and `/open` (not nav-only), plus nav and footer
  entries — so every measurement is two clicks from `/research`, and the verifier proves it rather
  than assuming it.
  ⚠️ **The guard lives in the EXISTING gate, not a new one.** `verify-papers.mjs` now re-runs the
  builder's own discovery rule against the SHIPPED `research.json` and checks one page per artifact,
  each with a self-canonical, Dataset markup, a rendered claim boundary, a sitemap entry, and a link
  from the index. Adding a second job would have recreated the split-coverage defect that let the
  retracted claim survive: two gates, each assuming the other checked the file. There is a floor of
  12 on the discovery count for the same reason the paper checks have one — a rule that stops
  matching makes every assertion below it pass vacuously, which is the exact shape of the bug.
  Mutation-tested three ways, all caught, and clean state passes: deleting a page fails the count
  AND the per-artifact check; stripping the boundary heading fails; adding an artifact to
  `research.json` fails with the unrendered artifact named.
  `npm run verify` **0 errors**, 123 URLs, 82 papers + 13 hubs + 21 measurements. The 23 warnings
  are all pre-existing paper titles over 65 chars — that is D8, untouched here.
- `2026-08-22 04:35` — **D1 DONE.** `/systems` gains chapter **07 / End to end**: one funding rate
  followed the whole way — lake → factor → portfolio → overlay → execution → publication — with
  **the artifact that measured each stage linked from that stage**. Thirteen proof links, all
  resolving.
  The six chapters already on the page describe stages one at a time, which is why a reader could
  finish it and still not answer the only question that decides whether the rest is worth
  believing: what happens between an observation and a number on this site, and where could it go
  wrong. Each row now states the stage, **the failure mode that stage is exposed to**, and the
  measurement that would show it: a lookahead-stamped series, a factor the book already owns, an
  unmeasured estimator halflife, a brake tuned on a simulation of a different estimator, a cost
  model that flatters, a record with a hole in it.
  **Deliberately a list, not a diagram.** A diagram asserts that the stages connect; a link lets
  the reader check. Where the evidence is narrower than the stage, the row says so instead of
  borrowing a nearby number's confidence — the lake row reads "for one data layer rather than all
  of them", because that is what the artifact covers.
  It is NOT marked `data-stage`, so the pipeline spine and the tentpole pin still track the six
  engine stages rather than gaining a phantom seventh; the rail and the chapter array were extended
  together so the counter stays aligned.
  ⚠️ **Guarded in the existing gate again, not a new one.** `verify-papers.mjs` now checks the walk
  by NAMED stage rather than by count — a walk that silently dropped Execution would still be six
  rows long if another stage were split in two — that every row carries its own proof, and that
  every proof link resolves to a built page. A proof link that 404s is worse than no link: it
  invites the reader to verify and then wastes the attempt.
  Mutation-tested four ways, all caught: a broken proof link, a renamed stage, a row stripped of its
  proof, and the whole walk deleted. ⚠️ The third one first reported NOT CAUGHT — and the guard was
  fine; the BSD `sed` I mutated with had silently matched nothing. Re-run with an asserted edit it
  fails correctly. An un-asserted replace passing for a working guard is the same defect class this
  file already warns about, met from the other side.
  `npm run verify` **0 errors**, 123 URLs. The 23 warnings remain the pre-existing paper titles
  (D8), untouched.
- `2026-08-22 05:25` — **D2 DONE.** All 13 hubs now open with a written essay — **52 distinct
  paragraphs, ~3,660 words**, four per hub, none shared between any two. Each answers the three
  questions the item asked for: what the mechanism is, what the published evidence supports, and
  what THIS book found — which is consistently less than the literature would suggest and is
  written that way.
  Some of the more useful things now stated in prose rather than implied by a link list: that a
  kill log's real function is to be the DENOMINATOR, because deflation is only possible if the
  trial count is honest; that the equity cluster is "not virgin ground, and an edge found here is
  much more likely to be a construction artifact than a discovery", with the surviving momentum
  sleeve named against ten published kills around it; that crypto funding carry is "a
  liquidity-provision trade wearing a yield's clothing"; that the event-driven failures share one
  shape — a language test where the identity needed a structural fact; and that the one fully
  checkable cost component matched **exactly at 5.00bp against a modelled 5.0**, while equity
  slippage is not computable at all because the fills record a padded limit, so "a fill that
  appears to beat it is beating the padding".
  Every figure quoted is read from a published artifact; where a claim is qualitative it is left
  qualitative rather than given an invented number.
  ⚠️ **The guard that matters is the anti-template one.** Length checks alone would be satisfied by
  boilerplate with the subject noun swapped, which is exactly what a hub essay degenerates into and
  exactly what would deserve to rank for nothing. `verify-papers.mjs` now collects every essay
  paragraph across every hub and fails if any paragraph appears on two — plus ≥3 paragraphs and
  ≥180 words per hub, the standfirst explicitly NOT counting toward either (it is what the item
  was raised about), and a floor of 39 distinct paragraphs site-wide so a broken extractor cannot
  make the whole check pass vacuously.
  Mutation-tested three ways, all caught, clean state passes: two paragraphs deleted from one hub,
  a paragraph copied from one hub to another, and an essay removed entirely. Each mutation asserts
  it actually applied — after last item's BSD `sed` no-op, an un-asserted edit reporting NOT CAUGHT
  is now indistinguishable from a broken guard, so the harness refuses to report either.
  `npm run verify` **0 errors**, 123 URLs.
- `2026-08-22 06:15` — **D3 DONE.** `/verify`, generated by `scripts/build-verify.mjs` from what
  is actually published — 23 hashed artifacts, 2 signed commitments, 403 chain entries, the public
  key — so the page cannot go stale in the one direction that matters. A hard-coded "23" would be
  wrong the first time the exporter adds an artifact, and **an instruction that does not work is
  worse than no instruction**: the reader spends their one attempt on it and concludes the record
  is fake rather than the page stale.
  Three levels with copy-pasteable commands: L1 recomputes all 23 content hashes from files curled
  off the live site with **stdlib Python only** — no repo, no install; L2 adds `cryptography`,
  checks both Ed25519 commitments and re-derives all 403 links of the append-only chain; L3 clones
  the repo and runs the golden master. Every command was executed end-to-end from a clean
  directory before the page shipped, not written from the docstring.
  ⚠️ **A real gap found by writing the page.** The kit's own L2 output says "verify it with
  `scripts/verify_transparency.py`" — **and that script was never published.** The one instruction
  the verifier hands an outsider pointed at a file only we had. It is now copied to both hosts by
  `live_publish.sh` alongside `reproduce.py`, and confirmed to run standalone against a downloaded
  `transparency_log.json`: PASS, 403 entries, chain intact.
  **The best section is the one about what it cannot prove**, and it is on the page rather than in
  a footnote: a matching hash makes a number unedited, not correct; a valid chain proves nothing
  about what was recorded before the chain began, and that limit does not shrink with time; a
  deterministic engine is not an accurate one; and none of it is a return, because this book trades
  on paper. A verification page listing only what it establishes is marketing.
  ⚠️ **The guard caught its own first version.** The download check matched literal `glassbox/<name>`
  paths and found **three** files — because the command is a shell loop and the names live in
  `for f in … ; do`. The floor fired, correctly. Lowering it would have made the check pass while
  checking almost nothing; reading the list the reader actually pastes brought it to 28.
  Also guards: all three level sections present by id, the limits section present, the paper-trading
  statement present, every named download actually published, **every internal link resolving**
  (which had already caught a dead link to a topic hub that is not built because it has too few
  members), sitemap entry, and STATIC links from the homepage and the glass box — the shared nav is
  assembled at runtime, so a link that exists only there is invisible to a crawler.
  Mutation-tested five ways, all caught, clean state passes: an unpublished download, the limits
  section removed, a dead link, a missing level, and the homepage losing its static link.
  `npm run verify` **0 errors**, 124 URLs.
- `2026-08-22 07:10` — **D4 DONE.** `/founder`, generated by `scripts/build-founder.mjs`. The
  Person `@id` that 82 papers resolve their authorship to now points at a page that describes the
  author instead of at the homepage that merely declares the entity.
  **The distinctive part is what is NOT on it, and the page says why.** No degrees, no former
  employers, no awards, no AUM — "a credential is a claim you would have to take on trust, and the
  entire argument of this record is that you should not have to take anything on trust. If a line
  of biography would change how you read the numbers, it is doing work the numbers should be doing
  themselves." The only personal claim on the page is the Ed25519-signed founder commitment —
  USD 1,000 at first live deployment, same book, same terms — with the four commands to check the
  signature printed underneath it. The page also says the number is small on purpose: "it is what
  I can actually commit, stated exactly, rather than a figure chosen to impress."
  Every figure is derived at build time (82 papers, 13 hubs, 21 measurements, 46 kills against 3
  survivors, 162 of 320 identities, 403 chain entries) and the builder **refuses to publish if any
  derived fact comes back empty** — a zero on a founder page reads as modesty rather than as a bug.
  ⚠️ **A live defect found while writing it, on the page I shipped an hour earlier.** `/verify`'s
  L3 said `git clone …/alphaforge.git`. **That repository does not exist — 404.** The real public
  remote is `alphac`. It was on the one page whose entire subject is that our instructions work,
  which is the worst place for a broken one. The internal-link guard could not see it because the
  URL is EXTERNAL. Fixed, and `tests/unit/test_published_clone_url.py` now pins the published
  string to `git remote get-url origin` — the truth lives where the repo does. It also checks the
  `cd` target separately, because the broken version's two halves AGREED with each other and both
  named a repository that does not exist, so agreement is not evidence. Mutation-tested three ways,
  all caught.
  ⚠️ **The first version of the number-trace guard was nearly vacuous and a mutation proved it.**
  It built the allowed-value set by walking whole artifacts — files carrying thousands of numbers —
  so a stale corpus count of **84 against a true 82 matched something somewhere and passed**. The
  verifier now re-derives twelve NAMED facts independently and checks the page's numbers against
  only those. Re-mutated: 84, an inflated 60 kills and a 100,000 commitment all fail.
  Also guarded: ProfilePage + Person `@id` markup, the homepage entity resolving here, every
  internal link, the sitemap entry, a static homepage link, and a **credential-shape check** — PhD/
  MSc/MBA, "graduated from", "formerly at", "years of experience", "awarded" — written against the
  class rather than a word list the page could be rephrased around.
  `npm run verify` **0 errors**, 125 URLs.
- `2026-08-22 08:05` — **D5 DONE.** `/methodology`, generated by `scripts/build-methodology.mjs`:
  **12 questions, 25 evidence links**, `FAQPage` structured data, and the rule that makes it worth
  reading — *every answer links to the document where the principle had to be paid for, not merely
  asserted*. An FAQ that explains a principle without pointing at what it cost is a brochure.
  The questions are the long-tail ones the corpus already answers and nothing indexed: what a
  deflated Sharpe is, why failures are published, what point-in-time data changes, what
  pre-registration stops, why feasibility is decided before return data is opened, how a strategy
  can be real and untradeable, why correlation binds, whether this is real money, whether we have
  been wrong, what the admission gate requires, how to check any of it, and who is behind it.
  The strongest answer is the deflation one, because it is the one that costs us: recomputed
  against the current selection count of **162**, **33 variants were restated and 0 clear the 0.95
  gate** — every figure of those derived from `legacy_dsr_restatement.json` and `deflation.json`
  at build time rather than typed. Same discipline throughout: the builder **refuses to publish if
  a derived fact comes back empty**, with `clearing = 0` exempted BY NAME rather than by loosening
  the check for everything, because that zero is the finding.
  Guarded in the existing gate: the `FAQPage` markup must describe the page a reader actually sees
  (question count matched to rendered headings, off by exactly the one non-question section), every
  answer must carry an evidence line, every evidence link must resolve to a built page, a floor of
  15 distinct cited documents, sitemap entry, and STATIC links from the homepage and `/research`.
  Mutation-tested four ways, all caught, clean state passes: a dead evidence link, an answer
  stripped of its evidence, the structured data dropping a question — which fired **two** checks,
  the markup mismatch and the evidence count, exactly as intended — and `/research` losing its
  static link.
  `npm run verify` **0 errors**, 126 URLs.
- `2026-08-22 08:55` — **D6 DONE.** `scripts/audit-link-graph.mjs`, wired into `npm run verify`.
  It builds the internal link graph from `dist/`, breadth-first searches from `/`, and fails if any
  indexable page is unreachable or more than three clicks away.
  **It found the defect immediately: 22 pages beyond the bound — 14 at four clicks, 8 at five.**
  Root cause was not depth, it was that **`/research` linked eleven papers and NOT ONE of the
  thirteen topic hubs that are its own taxonomy**. The hubs existed, were in the sitemap, had
  essays written for them yesterday — and the library page did not link a single one, so they were
  reachable only by chance through another paper's related-work section, with their exclusive
  members stranded behind them. A library that does not link its own index is the defect; the depth
  was only how it showed up.
  Fixed by generating a Browse-by-topic block on `/research` from the hubs `build-papers.mjs`
  actually renders, between asserted sentinels — a silent no-op there would restore the defect
  invisibly. **Result: 126 pages, 1,309 internal links, depth 0:1 / 1:8 / 2:45 / 3:72, nothing
  beyond three.**
  The graph is built from STATIC HTML only, deliberately: the shared nav and footer are assembled
  at runtime by `shell.js`, so a link that exists only there is invisible both to a crawler reading
  the delivered document and to a reader with JS off. That is why every item this week added static
  links rather than relying on the nav. It also checks graph and sitemap agree in BOTH directions —
  an orphan page ranks for nothing, and a sitemap entry with no page is a 404 we advertised.
  ⚠️⚠️ **A mutation caught a bug in the audit itself, and it was the vacuous-pass one.** Neutralising
  every `href` on the site to `data-href` did NOT fail the audit, because `data-href="/x"` CONTAINS
  `href="/x"` and the extractor's pattern had no left boundary. So it happily counted 1,309 links
  on a site that had none — the exact substring trap as `literature_dir` inside
  `app_literature_dir`, met a third time. Anchored, re-mutated: now reports **0 internal links**
  and fires the floor, plus every page as an orphan. Without that mutation the audit would have
  shipped unable to detect its own blindness.
  Four mutations, all now caught: `/research` losing its hub links (reproduces the original 4-click
  defect), a page unlinked everywhere, a sitemap entry with no page, and the extractor going blind.
  `npm run verify` **0 errors**, 126 URLs, every one within three clicks.
- `2026-08-22 09:35` — **D7 DONE.** `scripts/lib/indexnow.sh`, sourced by **both** deploy paths —
  the hourly change-gated one and the nightly ceremony. A push channel that runs only when somebody
  remembers is not a push channel: 99 URLs were submitted once by hand, and the 27 pages published
  since would have waited for a crawler to rediscover the sitemap on its own.
  **One shared file, not two copies, and the test enforces that.** This repo has been bitten twice
  by identical logic in two hand-mirrored places — the retracted-claim gate the hourly job ran and
  the nightly one did not, and the glassbox copy list where one host got a paper the other did not.
  Both looked correct in every file anyone opened. So the guard requires the shared file, both
  callers to SOURCE it, and neither to carry its own submission.
  **Loud but not fatal, and "not fatal" is not allowed to mean "not noticed".** IndexNow is a
  notification to third parties, not a correctness gate on what we published, so a network blip
  must not mark a good publication as failed. Instead every attempt writes a marker with its status
  and count, a success stamps a separate `.ok` file, and `indexnow_warn_if_stale` puts a warning at
  the top of every subsequent publish once the last SUCCESS is over 26 hours old. One failure is a
  line in a log; a run of them is a line the next run cannot avoid printing.
  Gated on the landing deploy actually succeeding — announcing URLs after a failed deploy
  advertises pages that may not be there — and bounded, because an unbounded external call in this
  repo once hung for 28 hours.
  All four behaviours exercised against a fake submitter: never-submitted, a failing submitter
  (loud, marker written, exit 0), a succeeding one (count and `.ok` stamp), and a stale success
  correctly reported at 73h. Then run for real through the helper: **126 URLs accepted, HTTP 200.**
  ⚠️ **A mutation caught a weak assertion in my own guard.** Deleting the `. …/indexnow.sh` source
  line did NOT fail the test, because the path also appears in a nearby COMMENT and the check was a
  plain substring test. Anchored to the source directive itself; re-mutated, both deletion and
  commenting-out now fail. That is the third time this week a presence check turned out not to
  check the thing it named.
  Six mutations, all now caught: submit call removed, staleness report removed, helper not sourced
  (twice), submission ungated from the deploy result, and the network call unbounded.
- `2026-08-22 10:30` — **D8 DONE. The site is now 0 errors AND 0 warnings**, from 23 warnings that
  had been printing on every build for a week.
  Took the first option, not the second: **a search result headline is not a document's name.**
  "Managed-Futures fast-trend / real-futures breadth (campaign): a killed candidate" is the right
  name for that document and the wrong thing to truncate mid-word in a result. So a paper may
  declare `**Short title:** …` in its markdown, used for `<title>` ONLY — the H1, the Open Graph
  title and the structured-data headline all keep the real name. Twenty-three short titles written
  by hand, each ≤49 chars so the brand suffix still fits.
  Authored at the SOURCE in each case, which meant nine of them in `~/alphaforge/docs/design/`
  rather than in the site: those files are overwritten by `research_export.py` on every publish, so
  editing the site's copies would have looked right and vanished at the next tick.
  **The residual is now an ERROR, not a warning.** It was a warning while 23 pages carried long
  titles, and a warning that fires 23 times a build is noise a reader learns to scroll past — which
  is exactly how it survived a week. Tightened only once the count was actually zero.
  ⚠️ **The guard's first version could not see the mechanism's real danger.** A short title that
  replaces the H1 would RENAME the document, and the check for that was a conjunction of two
  presence tests — the H1 marker exists, and the real name appears somewhere on the page. Pointing
  the H1 at the short title passed it, because the real name still appeared in Open Graph and
  structured data. Now it reads the heading's actual contents and compares. Re-mutated: it names
  both titles and says the document has been renamed.
  ⚠️ **Two process failures worth recording, both mine.** First: the initial batch edit reported
  "inserted" for all fourteen files from a function's return value, and **not one had landed on
  disk** — an un-asserted write reporting success, the exact defect class this file already warns
  about. Redone with a per-file assertion that reads the file back. Second: my mutation harness
  restored a file with `git checkout --`, which **discarded uncommitted work** — it wiped the
  builder changes I had just made, and the next verify passed only because it was reading a stale
  `dist/`. Restore from a copy the harness made, never from git, whenever the file has uncommitted
  changes.
  Four mutations, all caught: a long-titled paper with no short title, a short title that is not
  short, the H1 renamed, and the extractor going blind.
  `npm run verify` **0 errors, 0 warnings**, 126 URLs, all within three clicks.
- `2026-08-22 11:40` — **E1 DONE.** `scripts/mutation_ledger.py`, published at
  `/glassbox/mutation_ledger.json`. **All 20 guards over published claims now have a recorded
  mutation result: 20/20 behaved as expected, 1 negative control, 0 findings outstanding.** For
  each it breaks the thing the guard watches, runs that guard alone, records the outcome, restores
  the file and **verifies the restoration by hash** before continuing.
  Coverage is DERIVED from `tests/unit` by one rule, not listed — and `tests/unit/
  test_mutation_coverage.py` runs that rule in milliseconds on every commit, so a guard added
  without a mutation fails immediately instead of joining the unmutated majority until the next
  deliberate run. Mutation-tested: a new unmutated guard file fails it.
  ⚠️⚠️ **The most useful result was about MY OWN mutations, not the guards.** The first pass
  reported **five survivors**. Every one was my mutation aiming at the wrong thing: the frontier
  guard reads the correlation GATE, not the objective; the chain-label guard watches what the PAGE
  calls the number, not the chain file; the kill-paper guard regenerates each paper from its entry,
  so moving the entry moves both sides together and it watches the GENERATOR; the sleeve-claims
  guard watches DISCLOSURE LANGUAGE, not numbers; the lineage guard runs over fixtures and watches
  the audit's LOGIC. **A mutation that misses is indistinguishable from a guard that cannot fail**,
  and a harness that reported those five as findings would have been worse than useless — it would
  have sent someone to "fix" five guards that were already correct. Every retarget is recorded in
  the artifact with what it first aimed at and why that was wrong.
  ⚠️ **One genuinely weak guard, found and fixed.** `test_a_killed_sleeve_is_disclosed_as_killed`
  asserted `"KILLED" in text` over a five-hundred-line script. Stripping the word from every string
  a reader sees still passed, because **four of the seven mentions are source comments** — and a
  comment discloses nothing to anybody outside this repo. Scoped to non-comment published copy;
  the mutation now catches it. Straight from the "guards scoped page-wide cannot fail" class.
  **A negative control is declared and required.** One registered mutation edits a COMMENT and
  nothing else, and must NOT be caught. Without it a harness reporting CAUGHT for everything looks
  strongest exactly when it is broken — if the runner fails for reasons unrelated to the mutation,
  every line reads as a pass. `test_mutation_coverage.py` fails if no control exists.
  ⚠️⚠️ **And it found the real cause of D8's disappearing edits.** During this item the short titles
  vanished from the 14 kill papers for the second time. The cause: **the kill papers are
  GENERATED** — `research_export.py` regenerates all 46 on every publish, so hand-editing
  `public/research/*.md` was always going to be erased. Fixed at the generator, which now emits a
  short title **derived** from the readable name by three declared trims (drop a trailing
  parenthetical, then a trailing comma clause, then a slash half) rather than from a list a new
  kill would not be on. **55 short titles now, up from 23**, and the site is still 0 errors,
  0 warnings. My D8 note above is corrected by this: hand-editing generated output was the wrong
  fix and it looked right twice.
- `2026-08-22 12:40` — **E2 DONE.** All four dimensions worked and published, **with the
  refutations kept**: `/glassbox/guards_that_cannot_fire.json` and
  `/glassbox/contract_and_unit_audit.json`. An audit that reports only its hits cannot be told
  apart from one that did not run.
  **Guards-that-cannot-fire** — a structural scan of 589 files for four shapes: a guard excluded
  from the environment meant to run it, an assertion inside a loop that can run zero times, an
  exemption naming a path that is not there, and an existence-guarded block whose path does not
  exist. **One confirmed finding, fixed**: `test_no_trading_tick_invokes_the_weekly_job` globbed
  `scripts/*.sh` and asserted inside the loop — a glob returning nothing would have passed it
  having checked nothing. Floor added; the detector was then re-run against the un-floored version
  and still finds it.
  ⚠️⚠️ **Two of my own detectors were wrong, and the audit's self-check caught one of them.**
  Shape B first reported **133 findings**, almost all `for name in SPEC_NAMES` over module-level
  constants that cannot be empty — a finding list that is mostly false is worse than no audit, the
  same defect as the 23 warnings D8 just cleared. Narrowed to collections DISCOVERED at runtime:
  133 → 1. Shape D reported **7**, every one its own arithmetic: it joined quoted path segments
  onto `REPO` regardless of whether the constant was rooted at `Path.home()` or a data directory.
  Restricted to unambiguously `REPO /`-rooted constants: 7 → 0.
  ⚠️ **And the self-check found a third.** Every shape reports zero, and zero is what a scanner
  that has gone blind reports — so each detector is now run against a PLANTED instance and the
  audit refuses to publish a clean result it cannot demonstrate it earned. Shape B failed its own
  planted case: `_asserts_non_empty` counted ANY assertion mentioning the name, so `assert
  item.name` — inside the loop, and silent about how many items there were — read as proof the
  collection was non-empty. Narrowed to non-emptiness assertions OUTSIDE the loop.
  **Contract satisfiability, beyond the two pairs the loader already rejects.** Two confirmed:
  ⚠️ the **upper-95 correlation gate can never be decisive** — at 504 observations the SE is 0.0447,
  so the bound only exceeds 0.10 once the point estimate passes +0.0265, which already fails the
  0.00 point gate. Both are satisfiable together, so the loader is right not to reject them; but
  the contract reads as carrying two independent correlation hurdles and carries one.
  ⚠️ the **book deflated-Sharpe gate of 0.95 is unreachable in practice today**: the best figure
  this book has measured is **0.2112** blended and **0.5093** for the best single restated variant.
  Satisfiable by a better book, not by any candidate — which belongs beside the gate rather than
  being discovered by whoever tries. The t-ratio floor is recorded **UNDECIDABLE** rather than
  quietly counted as satisfied: "we did not check this" and "this is fine" must not look the same.
  **Published claims vs artifacts: REFUTED** — all 9 narrative figures are present in the evidence
  the bundle carries — with a second CONFIRMED finding beside it saying nine is too few for the
  dimension to mean much, and that the strong property is E3's and has NOT been established here.
  **Units: REFUTED** over **723** unit-declaring fields, against rules encoding real defect classes
  (a basis-point field over 10,000, a percent over 1,000, a day count over 20,000 — the count
  labelled as a duration that overstated a record eight-fold). Proven not blind: a planted
  5,000,000 `_pct` field is detected, and the clean result returns when it is removed.
- `2026-08-22 13:50` — **E3 DONE.** `meridian/scripts/audit-published-numbers.mjs`, wired into
  `npm run verify`. It reads every numeral a READER can see across **132 pages — 2,706 of them** —
  and traces each against **44,690 numbers in 68 published artifacts**.
  **Traced by rule, never by exemption list**, because an exemption list is how a check stops
  checking: EXACT (verbatim in an artifact), ROUNDED (some artifact value rounds to the token *at
  the token's own precision*), PERCENT, DATE, IDENTIFIER (a DOI, an arXiv id, a URL component, a
  hex digest), STRUCTURE (a count of what the built site contains, recomputed here).
  ⚠️ **The ROUNDED rule is the one that matters, and the first run without it reported 573 false
  positives.** A page showing `0.4689` and an artifact holding `0.46893918…` are the same number;
  a verbatim check calls that untraceable. Two more tokenisation rules followed from real
  misreads: exponential notation is ONE numeral, not two (an artifact holding `3e-06` was
  contributing the tokens `3` and `06`), and **a hyphen between two digits is a range, not a minus
  sign** — reading `1961-1970` as the number −1970 invented an unpublished claim out of a date
  range. 573 → 45 → 25 → 18.
  **Then it found real ones.** Seven were closed by publishing the artifacts the
  repurchase-issuance feasibility PAPER quotes — its issuer counts, overlap fraction and semantics
  sample were on the site and their evidence was not, so every figure in it was uncheckable. Now
  published on both hosts.
  ⚠️ **And two dead slots on `/research`.** The page rendered "Combined DSR (N=69)" and "Combined
  DSR (N=518)" against fields the exporter stopped emitting — a permanent em-dash beside labels
  advertising selection counts of 69 and 518, while the published trial ledger stands at **162**.
  Removed and replaced with the deflation verdict the bundle actually carries. Withdrawing nothing
  true: no value was being shown, only a contradictory label.
  **Ten remain and they are the owner's**, recorded as E3b above rather than exempted. Each is a
  hand-written figure with no artifact anywhere in the repository — including "8,436
  survivorship-free US stocks", which appears on both `/progress` and `/systems`. **`npm run
  verify` is RED until they are resolved, deliberately**: a green gate on a site publishing numbers
  a reader cannot check is the thing this whole record exists not to be.
  Mutation-tested three ways, all caught: a hand-typed `91.37%` planted on `/verify` is named and
  located; an emptied artifact universe fires the floor rather than reporting 1,149 findings as if
  they were real; and the clean-state result returns unchanged.
  Also fixed on the way: the three newly published audits humanised to 75-79 character titles and
  failed the on-page gate, so the measurements builder now shortens a nested title to its leaf —
  **but only when no other artifact's leaf humanises the same way**, computed over the whole set so
  uniqueness is a property of the run rather than an assumption.
- `2026-08-22 14:35` — **E4 DONE.** `scripts/build_claim_coverage_map.py`, published at
  `/glassbox/claim_coverage_map.json`. **68 published artifacts, 0 unguarded, 48 with a named
  guard** — and the finding: **8 are guarded ONLY by the host mirror.**
  Five mechanisms, and the map says plainly that they are not equal. NAMED_GUARD (a test that
  mentions this artifact) is the strongest. CONTENT_HASH proves it was not edited after publication
  and **nothing about whether it is right**. SIGNATURE covers the two commitments and the chain.
  RENDERED_PAGE means the site verifier checks it renders with a claim boundary. HOST_MIRROR is the
  weakest and the map says why: *it verifies two copies agree and nothing about what they say — if
  the contents went stale, both hosts would publish the same wrong thing and every check would
  pass.* That is the residue of "split coverage reads as coverage", now named rather than implied.
  **Last-run is OBSERVED, not asserted**: the map runs the unit suite, the reproduce kit, the
  retracted-claim gate and the site verifiers and records each exit. Today: PASS, PASS, PASS, and
  **FAIL for the site verifiers**, which is E3b's ten-now-eight untraceable numerals showing up
  exactly where they should.
  ⚠️ **The first run recorded the unit suite as FAILING and that was the map's fault, not the
  suite's.** Adding a script leaves the lint-debt contract stale until the exporter reruns, and the
  publish path reruns it before anything is checked — so observing the suite in a state the publish
  never ships would have published a failure describing nothing real. The map now rebuilds in the
  publish pipeline's declared order first, and says so in the artifact.
  `tests/unit/test_claim_coverage.py` runs the SET question in milliseconds on every commit: every
  published artifact has at least one mechanism, the mirror-only count may fall but not rise, and
  both floors are pinned so an empty scan cannot pass. Mutation-tested: publishing an unguarded
  artifact fails it by name.
  ⚠️⚠️ **And it exposed a real weakness in E3, shipped two hours earlier.** The number-trace guard
  checks a page's numerals against EVERY number in EVERY artifact — a corpus that grows on every
  publish. Publishing this very map added enough numbers that **two genuinely untraceable figures
  started tracing by coincidence**, with nobody fixing them. E3b's list is corrected from ten to
  eight with that reason attached rather than quietly updated, and E5 is opened to trace each page
  against the artifacts it actually references. A guard that weakens each time the record grows is
  a guard with an expiry date.
  ⚠️ **The substring-indentation trap again, on my own edit.** Anchoring a replacement on
  `"    for _name, _path in REPURCHASE_AUDITS:"` matched twice, because the eight-space version
  contains the four-space one. The assertion caught it and nothing was written; redone
  line-anchored. This repository has that exact trap written down.
- `2026-08-22 15:45` — **E5 DONE.** The number-trace guard no longer weakens as the record grows.
  **A page is scoped to the artifacts its GENERATOR declares**, via `<meta name="canli:sources">`
  emitted by the measurement, founder, methodology and verify builders. **31 pages scoped, and
  they report ZERO untraceable numerals.** The other 102 declare nothing and fall back to the whole
  corpus, reported in a separate bucket with its own count so the weaker basis is visible instead
  of blended into one reassuring total.
  ⚠️ **The first scoping rule made things worse, and measuring it is what showed that.** Treating
  any glassbox LINK in prose as a declaration scoped research papers to the single artifact they
  happened to cite while they quoted figures from three others — **159 findings, nearly all false**.
  A link is a citation; it is not a statement that it is the only source. Partial declaration is
  worse than none, so the scope now comes only from a generator saying "these are all of them".
  **Four real defects fell out of doing this**, none of which the old whole-corpus guard could see:
  ⚠️ **Four measurement pages linked a raw artifact that does not exist.** The "check it yourself"
  link was derived by guessing the filename from the bundle key, and four keys do not predict their
  file — on the pages whose entire purpose is that a reader can check. Fixed at the source by
  naming bundle keys after the files they publish, with `published_as` declared by the exporter for
  the one that genuinely differs (`trial_accounting` → `trial_ledger.json`), and the builder now
  **throws** rather than emitting a link it has not verified.
  ⚠️ **`&#39;` was being read as the number 39.** The scanner stripped named entities and not
  numeric ones, so every escaped apostrophe contributed a figure — reported on three measurement
  pages as a claim tracing to nothing, when it is punctuation.
  ⚠️ **Numerals inside field NAMES are labels.** A page rendering `projected_book_sharpe_at_14_
  sleeves` prints "14", and the value scanner cannot see it because the lookbehind that stops
  `1961-1970` reading as a negative also rejects a digit glued into an identifier. Those are now
  admitted as verbatim — **on the scoped path only**: folding them into the corpus made `8,436`
  start tracing to a digit sequence inside an unrelated identifier, which is the exact dilution
  this item exists to stop. Container sizes are admitted the same way, because a page reporting
  "2 further fields" is counting the artifact's own keys.
  ⚠️ **A slug moved and the `/systems` walk caught it.** Renaming the bundle keys moved a
  measurement page, and the end-to-end walk's link guard failed the build naming the dead link.
  That guard was written two days ago for exactly this.
  Mutation-tested: a figure planted on a scoped page is caught in the scoped bucket and named;
  removing a page's declaration moves it to the fallback and the counts shift by one.
  `npm run verify`: **0 errors, 0 warnings** on the site checks; the numbers audit remains RED on
  the eight E3b figures, which is their honest state.
- `2026-08-22 16:30` — **F1 DONE.** The guard that had been hand-resynced about ten times in one
  day now fails only when something real changed. **Both halves of the DONE WHEN, not one.**
  **The split.** The contract carries two kinds of content and the old single equality assertion
  treated them alike. `status`, per-scope `violations` and `files_with_violations`, the claim
  boundary and the trial accounting are a CLAIM — compared exactly, and a production violation
  appearing still fails. `python_files` is a CENSUS that moves by one whenever any script is added,
  and `source_sha256` is PROVENANCE that moves whenever a covered file is edited. Those are no
  longer conflated with the verdict: the census is **floored** rather than pinned, so a scope that
  collapsed to zero still fails while +1 does not, and provenance drift now fails with a message
  beginning **PROVENANCE ONLY**, naming the changed files and the one command that fixes it.
  Nothing is weaker. Demonstrated rather than asserted: with one script added, the old equality
  returned False (`historical_scripts.python_files` 195 → 196) and the new split passes; with
  production violations moved 0 → 3 in a *consistently rehashed* artifact, only the verdict test
  fails; a hand-edit without rehashing fails the content-hash test.
  **The other half: stop the drift happening.** `scripts/hooks/pre-commit` regenerates the contract
  for any commit that touches Python, and `scripts/install_hooks.sh` points `core.hooksPath` at it.
  Hooks live in the repository because `.git/hooks` is not tracked — **a hook that exists only in
  one working copy exists for exactly one clone**, which is how this class of thing quietly stops
  running. Proven end to end: a contract corrupted to `python_files: 1` was regenerated to 195 by
  the hook, and the hook exits clean on a commit with no Python, because a hook that errors on an
  ordinary commit is one somebody deletes.
  `tests/unit/test_hooks_are_tracked_and_installed.py` pins that the hook is tracked, executable,
  invokes the exporter, is CONDITIONAL on Python being staged, and runs clean with nothing staged.
  It deliberately does not assert the hook is installed HERE — that is a local setting a fresh
  checkout will not have, and asserting it would fail for everyone else.
- `2026-08-22 17:25` — **F2 DONE.** The suite runs in parallel by default — `-n auto --dist
  loadfile` in `pyproject.toml` — and the slowest tests are identified and justified rather than
  trimmed.
  **Measured back to back on the same machine under the same load**, because that is the only
  comparison worth anything here: **serial 194s and 219s; parallel 110s, 134s, 134s. About 1.6x.**
  ⚠️ **The first parallel run said 49 seconds and I did not believe it, correctly.** Repeats came
  back at 102-136s and one at 218s serial, so the honest reading is that this machine has variable
  background load and a before/after taken twenty minutes apart measures the machine, not the
  change. The paired runs above are the evidence; the 49s is recorded here as the number that did
  not reproduce.
  `--dist loadfile`, not the default `load`: every test in a file goes to one worker, so a
  module-scoped fixture is built once and any file whose tests share state keeps its ordering. A
  scan for tests writing outside a temp directory returned ten candidates and all ten proved to be
  `tmp_path`-derived on inspection — the detector's context window, not real shared state.
  **The slowest are justified, and the justification is already in the source.** `test_pbo.py`
  (~37s) enumerates the FULL C(16,8) rather than sub-sampling, and its comment says why: on an
  adverse seed the sub-sampled statistic drags toward 0.65 and the property stops holding.
  `test_regime_hmm.py` (~27s) fits a separate HMM per property — two-state recovery, three-state
  recovery, determinism, truncation invariance, a collapsed cluster — so there is no repeated fit
  to hoist. `test_bounded_sh.py` (6s) sleeps on purpose: its subject IS a timeout, and a fast
  version of it would prove nothing.
  Verified that the change does not break the two things that would have made it a false win:
  coverage still reports under xdist (83% on the CI selection, unchanged shape), and the CI
  invocation `-m 'not network and not workspace_evidence'` runs clean.
  ⚠️ Editing `pyproject.toml` fired the new PROVENANCE ONLY message from F1 within the hour, naming
  the one changed file. That is the guard behaving as designed on its first real outing.
