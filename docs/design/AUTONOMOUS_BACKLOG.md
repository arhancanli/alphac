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
