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
limit. An honest 1.5 needs ρ̄ ≤ −0.0174 at measured quality, or s̄ ≥ 0.601 — both inside the floor.

**The second half of the goal is the one that matters and it is not a number.** A forward 1.5 that
anyone can check — signed forward record, every killed candidate published, gates that provably
bite, corrections published against ourselves — is rarer than a 2.5 nobody can verify. Work that
increases verifiability counts as progress toward the goal, not as overhead.

### What binds, measured

| | |
|---|---|
| Correlation | **NOT binding.** A real candidate measured ρ̄ = −0.0203 against a −0.0174 requirement. |
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
- **The lint-debt test failing after you add a script is a known transient.** Resync with the
  publish pipeline in declared order, do not edit the test.
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
STATUS: TODO
WHY: A guard wired into a script is not a guard that ran. `scripts/check_live_change_declared.py`
was added to `live_tick.sh` but has never been observed executing in a scheduled run.
DONE WHEN: `var/log/live_tick.log` shows the check running in a scheduled `:25` tick with its
result, confirmed by reading the log rather than by inference.

### A5 · Record-continuity audit
STATUS: TODO
WHY: Nothing measures whether the forward record has gaps. A gap is as damaging as a config change
and is currently invisible.
DONE WHEN: a script reports, per sleeve, every day since go-live with no mark, publishes the gap
count, and a guard fails if the gap rate exceeds a declared threshold.

---

# TRACK B — Per-sleeve quality, the binding constraint

*s̄ measured 0.469; the goal needs ≥ 0.601. This is where the number comes from.*

### B1 · Ledoit–Wolf shrinkage at the EWMA's true effective sample
STATUS: TODO
WHY: `ledoit_wolf_cc` computes its intensity with `T` = the rows passed, and production passes the
full unweighted 720-row window while the matrix being shrunk is the EWMA. Conservative only while
the EWMA's effective sample exceeds 720. At a 21-day halflife on equity the effective sample is
**60.6 rows** against a T of 720. Flagged 2026-08-21, never measured.
DONE WHEN: measured on the real 17-ETF basket and the equity basket: delta* as coded vs delta* at
the effective sample, across the halflife ladder; published as an artifact; verdict stated on
whether it materially mis-shrinks the live book. **Do not change the live path** — measure and
report.

### B2 · Covariance window study through the LIVE estimator
STATUS: TODO
WHY: The drawdown sweep simulated an untruncated EWMA. Production is windowed and seeded. The
mapping is now measured (`artifacts/analysis/live_covariance_memory`) but no drawdown study has
been run through the real estimator.
DONE WHEN: the drawdown sweep is re-run with the production `ewma_cov` (window + seed + shrinkage)
in the loop, per sleeve calendar, and the result says what halflife and window actually minimise
expected max drawdown on THIS estimator. Report only; changing the live config is A-track and
owner-gated.

### B3 · Per-sleeve quality decomposition
STATUS: TODO
WHY: s̄ is an average over four very different sleeves and nothing says which one is dragging or
whether the drag is construction or execution.
DONE WHEN: each sleeve's standalone Sharpe is decomposed into signal, cost and execution
components on its own curve, published, with the largest single recoverable component named.

### B4 · Live-versus-backtest execution gap
STATUS: TODO
WHY: The cheapest possible s̄ is not new research, it is the deployed sleeves delivering what their
backtests claim. Historically this book has run at roughly half its backtest quality.
DONE WHEN: measured per sleeve for the days the live record covers, with the honest caveat about
sample length stated prominently. **If 14–30 days is too short to measure, saying so IS the
result** — publish the power calculation rather than a noisy estimate.

### B5 · Cost model realism check
STATUS: TODO
WHY: `cost_frac_oneway = 0.001` is a flat one-way cost that does not widen in stress. The red-team
artifact already flags this as an open weakness.
DONE WHEN: the live fills are compared against the modelled cost on the days the record covers,
and the gap is published per sleeve.

---

# TRACK C — Correlation and breadth

*Correlation is NOT the binding constraint. Breadth work is therefore lower priority than Track B
— but it is the only route to fourteen sleeves.*

### C1 · Generalise the reachability pre-test into a reusable harness
STATUS: TODO
WHY: On 2026-08-21 all three families "one gate from passing" turned out to be unreachable by
extraction — the gates asked for things the documents do not contain, or blended populations.
That test was written three times by hand.
DONE WHEN: one script takes a family and its failing gate and reports the ceiling a PERFECT
detector would reach, so any family must pass it BEFORE a protocol is written. Applied
retroactively to the three known cases and reproducing their published answers.

### C2 · Reachability screen across the untouched atlas families
STATUS: TODO
WHY: 20 families are `NOVEL_ATLAS` with `return_data_opened: 0`. Writing protocols against them
without a reachability screen repeats the mistake three times over.
DONE WHEN: each is screened on literature and metadata ONLY — no return data, no hypothesis
registered — and ranked by whether its evidence is obtainable at all. Published.

### C3 · Orthogonality prior per family
STATUS: TODO
WHY: The goal needs ρ̄ ≤ −0.0174. Families should be ranked by expected orthogonality to the
existing book before any is chosen, not after.
DONE WHEN: a documented prior per family with its reasoning, explicitly labelled as a prior and
not a measurement.

### C4 · Identity-redesign notes for the three failed families
STATUS: TODO
WHY: spin-off, customer-supplier and merger-arb each mis-specified their population. A redesign
must name the document that carries the mechanics before it names a threshold.
DONE WHEN: one note per family saying what document would carry the evidence and what a corrected
identity would look like. **Draft only — registering it spends a trial.**

---

# TRACK D — The site, its explanation, and reach

*99 indexable URLs, 13 topic hubs, 80 papers. The corpus is strong; the explanation is thin.*

### D1 · Make /systems explain the engine end to end
STATUS: TODO
WHY: The page lists components. A reader cannot follow how a signal becomes a position becomes a
published number.
DONE WHEN: the page walks the whole path — lake → factor → portfolio → overlay → execution →
publication — with each stage linking to the artifact that proves it, and the on-page audit still
reports 0 errors.

### D2 · Give each topic hub a real essay introduction
STATUS: TODO
WHY: Each hub carries one paragraph. A hub is a page that should rank for its subject, and one
paragraph over a link list is thin.
DONE WHEN: each of the 13 hubs opens with 3–6 paragraphs of genuine subject content — what the
mechanism is, what the literature supports, what this book found — written, not templated.

### D3 · A "how to verify us" page
STATUS: TODO
WHY: The reproduce kit exists and works (23/23 hashes, 2/2 signatures, golden master). Nothing on
the site explains it to someone who has not already found it.
DONE WHEN: a page walks an outsider through L1/L2/L3 with the exact commands, linked from the
homepage and the glass box, in the sitemap.

### D4 · Founder page
STATUS: TODO
WHY: 80 papers resolve authorship to a `Person` @id that has no page behind it.
DONE WHEN: a page exists with the `Person` markup, what the work is, and links to the corpus.
State only what is verifiable — no credentials, affiliations or awards that cannot be checked.

### D5 · Methodology / FAQ page
STATUS: TODO
WHY: The long-tail questions — what is a deflated Sharpe, why publish failures, what is a kill
log, what is point-in-time data — are exactly what the corpus answers and nothing indexes.
DONE WHEN: a page answers them in the project's own words, each linking to the paper that
demonstrates it.

### D6 · Internal-link reachability audit
STATUS: TODO
WHY: Nothing asserts every paper is reachable from the homepage in a bounded number of clicks.
DONE WHEN: a script builds the internal link graph from `dist/` and fails if any indexable page is
more than three clicks from `/`, wired into `npm run verify`.

### D7 · Re-submit IndexNow after every publish
STATUS: TODO
WHY: 99 URLs were submitted once by hand. New pages will not be.
DONE WHEN: `npm run indexnow` runs as part of the deploy path, and a failure is loud rather than
silent.

### D8 · Title-length residual
STATUS: TODO
WHY: 22 pages carry titles over 65 characters because the documents' real names are long.
DONE WHEN: either a defensible short-title field is added at the source, or the residual is
documented as accepted with the reason, so the warning stops being noise.

---

# TRACK E — Verification machinery

*This is what makes the goal's second half real. It is not overhead.*

### E1 · Mutation-test every guard that has never been mutated
STATUS: TODO
WHY: Several guards have never been proven able to fail. A check that cannot fail is worse than no
check, and this repository has shipped that failure repeatedly.
DONE WHEN: every test under `tests/unit/` that guards a published claim has a recorded mutation
result. Produce a table of guard → mutation → observed failure. Any guard that cannot be made to
fail is a finding.

### E2 · Complete the four unfinished audit dimensions
STATUS: TODO
WHY: An adversarial audit was stopped after two of six dimensions reported. Never completed:
contract satisfiability beyond the pairs already fixed, guards-that-cannot-fire, published-claims
versus artifacts, and unit/numerical correctness.
DONE WHEN: each is worked by hand and its findings recorded — confirmed or refuted, with the
refutations kept.

### E3 · Every published number traces to an artifact
STATUS: TODO
WHY: The kill papers have this guarantee. The rest of the site does not.
DONE WHEN: a guard extracts numerals from the rendered site and reports any that cannot be traced
to a glassbox artifact. Expect false positives on dates and version numbers; handle them by rule,
not by exemption list.

### E4 · Claim-coverage map
STATUS: TODO
WHY: Nothing says which published claims have a guard and which do not. Split coverage reads as
coverage.
DONE WHEN: a published map of claim → guard → last-run, with unguarded claims named.

---

# TRACK F — Housekeeping that protects everything else

### F1 · Make the lint-debt resync automatic
STATUS: TODO
WHY: `test_persisted_contract_matches_builder_and_content_hash` fails after any script edit and
has been hand-resynced ~10 times in one day. A test that routinely fails for a benign reason
trains its reader to ignore a real failure.
DONE WHEN: the contract regenerates as part of the pre-commit or test path, or the test
distinguishes a benign staleness from a real violation and says which.

### F2 · Full-suite runtime
STATUS: TODO
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
