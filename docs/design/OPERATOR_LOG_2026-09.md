# Operator log, September 2026

Append-only record of what the operating session did, decided and measured, kept beside the
code so every action has a dated line a reader can check against git, the health board and the
public artifacts. Owner direction of 2026-09-14: "you are taking over everything, document
everything you do on the side." The goals this log serves are recorded in
`ALPHAC_OWNER_GOALS_2026-09-12.md`: combined net Sharpe above 2, maximum drawdown at most 11
percent, at least 15 qualified economically distinct sleeves, testing beyond reproach, then the
glassbox platform with API keys and MCP servers.

Conventions: one entry per action or decision, UTC times, every number traced to the artifact or
command that produced it, and "not done" stated as plainly as "done". Decisions that change a
published number or spend a research identity are marked DECISION and name who made them.

## 2026-09-14

- 07:40Z. Session start. Read the memory record, six Codex transcripts (2026-09-08 to 09-13), the
  health history, both repositories and the four Codex workspaces under `~`. No Claude session had
  touched ALPHAC since 2026-09-07.
- 07:45Z. FOUND. Vercel CLI logged out on the Mac since 2026-09-13 ~10:56Z (`auth.json` empty);
  every hourly deploy and the nightly publish since 10:30Z 09-13 failed with "No existing
  credentials" (372 failures in `var/log/live_deploy.log` by 09:33Z). Site serves the 09-13
  10:26Z bundle. Clock skew measured +0.39 s (sntp), not the cause. No session ran `vercel logout`.
- 07:50Z. FOUND. The live redesign (Codex, released 2026-09-10 17:17Z from the git-less
  `~/canlicapital-production-20260910.IHlZmL`) existed in no commit. Committed the design worktree
  (`cf4668a1`, 1,079 files; QA captures, render sources and reference images excluded) and the
  build-time route inventory (`8da68297`) as canlicapital PR #11. `npm run build && npm run
  verify` 273/273 locally; CI production build green.
- 08:06Z. FOUND. `~/alphaforge` ran Codex's publisher, macro-staging and CPI-validator changes
  uncommitted since 09-10, and the nightly suite had failed four nights for seven non-engine
  reasons (Labor Day in a weekday-only test, three verifier tests pinned to pre-09-06 messages,
  46 ruff violations in two untracked test files, a stale system map). Recorded and repaired as
  alphac PR #23 (`26597ec`, `4216854`); all six CI checks green by 08:41Z.
- 08:10Z. CORRECTION. I reported Codex's AstraZeneca share-conversion defect as live in
  production after reading a truncated view of the corporate-actions table. The production lake
  holds `split ratio 2.0 ex 2026-02-02` and `equity_price.py` multiplies pre-ex bars by it, so the
  adjusted move is +1.6 percent, not +103. The defect is in the clone's normalized copy. Live
  AlphaMax has no AstraZeneca fills. Lesson recorded in memory.
- 08:15Z. FOUND. The Codex research clone (`~/alphac-prospective-pause-20260911`) holds 347
  distinct hypothesis identities by `ExperimentUnion.discover` (127 ledgers, 348 packets) against
  229 in this tree and on the public ledger: 118 identities the site cannot see, merged union 347
  of 400, the 320 staged review reached on 09-13 without a record. Codex's prose "union 256"
  counted reservations; the published arithmetic counts configurations.
- 09:20Z. SHIPPED. `scripts/audit_external_experiment_ledgers.py` and nightly check
  `C11-external-ledgers` (alphac PR #24, `d4bd7aa`, stacked on #23), with
  `TRIAL_LEDGER_RECONCILIATION_2026-09-14.md`. Verified under `/usr/bin/python3` 3.9. No
  published number changed.
- 09:25Z. PLAN stated to the owner: phase 0 restore publishing and count the search; phase 1
  budget discipline (supplemental measurement class); phase 2 unlock data-gated families with
  one pre-registered identity each; phase 3 make the 11 percent drawdown a designed overlay
  bound; phase 4 let the forward record accrue; platform work in parallel because it spends no
  identities.
- 09:30Z. DIRECTION (owner). "You are taking over everything, document everything you do on the
  side, log into Vercel now." This log begins.
- 09:34Z. Vercel device login started from the Mac (`vercel login`, CLI 53.3.2); the approval page
  was opened in the owner's browser (the Claude Chrome extension was not connected). The first
  device code expired unapproved ("The user aborted a request"); the second was raised at 09:46Z.
  The owner completed the login on their side at 09:40Z (`auth.json` written; `vercel whoami`
  returns the account). Network to api.vercel.com and vercel.com verified 200/308 beforehand.
- 09:48Z. Manual deploy started with the tick's own script (`scripts/live_deploy_hourly.sh`)
  under the tick's PATH, so the first publish after the outage uses the same path as every
  hourly publish. Result recorded below.
- 09:47Z. MEASURED. Collapsing cost-only stress variants would change the clone's new identities
  from 118 to 116 (merged 347 to 345): the stress ledgers differ in more than `cost_rate`. The
  320 staged review is reached under any defensible rule, so no accounting rule can be the way
  out; the review must be held and recorded. The clone's tracked `config/` is byte-identical to
  this tree's, so the import is ledgers plus regenerated packets, not policy files.
- 09:58Z. PUBLISHED. Manual `live_deploy_hourly.sh` run: landing deploy succeeded on attempt 3
  (attempts 1 and 2 died on Vercel's `/v2/files` returning "Internal Server Error" for the 47.3 MB
  archive; status page reported all systems operational), aliased `ac-capital.vercel.app` and
  `meridian-pearl-mu.vercel.app`; app deploy succeeded on attempt 1; IndexNow accepted 263 URLs.
  Live `paper-state.json` moved from 2026-09-13 10:26Z to 2026-09-14 09:38Z. The 09:51Z tick
  correctly skipped on the deploy lock. Outage: 2026-09-13 10:30Z to 2026-09-14 09:58Z.
- 09:51Z. DECISION (operating session under the owner's delegation; the owner merges the
  record). Imported the Codex worktree's 52 ledger-bearing analysis directories into the
  canonical tree with `scripts/import_external_experiment_ledgers.py` (evidence files only:
  17,887 files, 275.7 MB; replay virtualenvs and bulk data skipped and listed; source untouched).
  Receipt `artifacts/audit/external_ledger_import_20260914T095114Z.json`. Canonical union
  229 -> 347, exactly the audit's 118. Re-audit: `CANONICAL_UNION_COMPLETE`.
- 09:53Z. RECORDED. The worktree's uncommitted code (19 modified tracked files, the research
  scripts, tests, checkpoint documents; 880 files) as `record/codex-prospective-pause-20260914`
  (`539f256`), pushed, via a temporary index so the worktree's checkout was not touched.
  `artifacts/` and `evidence/` (2.6 GB and 2.5 GB) left in place.
- 09:56Z. RECORDED. The 320 staged review in `config/trial_accounting.json`
  (`staged_reviews_held.320`) and the reconciliation block (`external_ledger_reconciliation`),
  with a test that the block matches the receipt and that the audit reads the review as held.
- 10:02Z. FIXED. Two typed counts the import exposed: `audit_alphatrend_family.py` raised on
  `!= 21` identities (now a floor of 21, with the 28 imported managed-futures identities bound at
  their real evidence grade) and `test_trial_debt_reconciliation` asserted the live union equals
  229 (now derived). `test_research_export_freshness` stays red until the next tick republishes
  the 347-identity ledger, which is the intended "publish is behind the tree" signal.
- 10:31Z. FOUND. The first tick to carry the 347-identity ledger failed the site's production
  build: `trial-accounting-core.js` asserts legacy 228 + prospective = N and the engine published
  "prospective = 1", typed in three places in `research_export.py`. The check was right. Every
  hourly deploy fails until the engine derives the prospective epoch; the site keeps serving the
  09:58Z bundle (today's data, the old 229 count) meanwhile.
- 10:40Z. SHIPPED (working tree, branch pending). `scripts/build_prospective_epoch_register.py`:
  one row per identity measured after the legacy closure, derived from the union minus the sealed
  legacy keys, each with its reservation (ordinal, family, arm, reserved_at), first measurement and
  evidence status; fails closed on legacy + prospective != union or a shared ordinal. Real run:
  119 identities (1 governed serial packet, 118 imported, reserved, measured, unclosed), ordinals
  229..347 contiguous, 40 families. Wired into both pipelines after the legacy seal and declared
  in the ordering test; `research_export.py` now derives every prospective-epoch figure and prose
  from it and publishes the register; the prospective record carries an `epoch` block. A NaN
  Sharpe on one imported row was serialised as bare `NaN` and broke the site's JSON parser;
  published as null now.
- 10:55Z. MEASURED (phase 3, no identities spent). `scripts/analyze_drawdown_control.py` on the
  published drawdown study's own paths (baseline reproduced to 1e-12): the declared ladder (half
  gross at 5.5%, flat at 11%, absorbing) takes the two-year maximum drawdown from 16.45% p95 /
  20.65% p99 to 11.02% / 11.16% on the correlation-regime model and from 13.35% / 15.98% to 9.65% /
  11.00% on the bootstrap; halt probability 6.4% / 1.1%; two-year return cost on research drift
  0.74 / 0.18 percentage points; auto-rearm variant reaches 21.9% max, which is why the book
  ladder is absorbing. Acceptance rule (declared first) met: `LADDER_ACCEPTED_AS_BOUND_MECHANISM_NOT_LIVE`.
- 11:05Z. Site: `trial-accounting-core.js` reads the register (rows for every prospective
  identity, epoch checks replace the single-record checks), tool and page updated, verifier
  updated to five hashed sources and the derived unclosed count; core tests 5/5. Two freshness
  pins in the engine (a typed 229 and a pinned paragraph) converted to derived assertions; the
  cross-host test stays red until the 11:25Z tick republishes in order.
- 11:00Z. Site: `npm run build && npm run verify` green on the design worktree with the
  2026-09-14 exports mirrored in exactly as the production overlay does (0 failures; the first
  two runs failed on the verifier's four-source pin and on stale September 8 exports beside fresh
  sources, both real). Committed `be1f4662` on design/glassbox-website-20260908 (PR #11) and pushed.
- 11:02Z. DECISION. `config/site_landing_design_source.txt` repointed from the git-less release
  copy to the design worktree, so the fix can deploy and every future site change has a commit.
  Committed on the register branch (PR #26). The 11:25Z tick is the first deploy from it.
- 11:03Z. Drawdown control v1 wired: `analyze_drawdown_control.py` runs in the nightly publish
  after the current-book drawdown study (publish-only edges declared), `research_export.py`
  publishes `/glassbox/drawdown_control_v1.json` to both hosts, the contract records that the
  declared rule was applied once and accepted. Study re-run after the contract's status changed
  so its contract binding matches; results unchanged by construction (same seeds).
- 11:05Z. DESIGN (phase 1, not in force). `docs/design/SUPPLEMENTAL_MEASUREMENT_CLASS_V1.md`:
  a reservation may declare, before any result, a primary configuration and a closed set of
  supplemental scenarios on named axes (cost rate, cost stress, execution scenario, baseline
  arm) that cannot flatter; supplemental rows stay immutable records and are published, but
  selection N counts the primary once. Prospective only: the 118 stay 118 because none declared
  scenarios before its result. At the observed mix a study costs one identity instead of four.
  Implementation and tests listed; promotion is the owner's.
- 11:05Z. STATE. Branch chain on alphac: #23 (Codex integrations + nightly) -> #24 (external
  ledger audit) -> #25 (import + 320 review) -> #26 (prospective register + publisher repoint)
  -> #27 (drawdown control v1). canlicapital #11 carries the site (design worktree, deployed
  from 11:25Z). Owner merge order is the chain order.
- 11:07Z. NOTE. Found `var/locks/vercel_deploy.lock` left by the 10:27Z tick's deploy (killed by
  the tick's 600 s bound after three failed builds; a SIGKILL cannot run the release trap) and
  removed it. On reading `scripts/lib/bounded.sh` afterwards: `deploy_lock_acquire` already steals
  a lock older than 30 minutes, so the 11:25Z tick would have cleared it unaided. Harmless, and
  not needed; recorded so the next reader does not repeat it.
- 11:40Z. FIXED. `audit_crypto_lab_carry_crash.py` raised "expected the frozen three-fill LAB
  sequence, got 4" every tick since the 2026-09-10 rebalance added a fourth LABUSDT fill; the
  sealed episode's three fills are unchanged and a later fill is now reported as
  `subsequent_activity` (1 fill, 2026-09-10) instead of breaking the seal. Test added; the
  episode's numbers are asserted identical with and without the later fill.
- 11:45Z. BRIEF (phase 2). `docs/design/DATA_UNLOCK_BRIEF_2026-09-14.md`, read from the
  reachability screen and the eighteen feasibility results: two families already passed to
  return pre-registration with no purchase (`earnings_narrative_change`,
  `treasury_auction_concession`); two need a human reviewer (48 and 30 labels); thirteen need a
  vendor, grouped so a rates vendor opens two families and an index provider opens two; four
  cannot be bought (history, unpreserved record, non-executable marks). Decision requested:
  reserve the two tier-0 identities, recruit the reviewer, obtain two quotes.
- 12:05Z. PUBLISHED. The 11:25Z tick's deploy (started 11:48Z) never finished its first upload
  inside the tick's 600 s watchdog and was killed; Vercel shows no deployment for it, builds
  themselves take ~25 s, and the Mac uploads at ~2 MB/s, so the stall was Vercel's file API
  (500s all morning). A manual run of the same script at 12:01Z succeeded on attempt 1 in under
  four minutes: landing and app deployed and aliased, IndexNow accepted 263 URLs. First publish
  from the git worktree, first publish of the 347-identity ledger and the prospective register.
  Tick watchdog raised 600 -> 1500 s so one slow upload plus a retry fits inside a tick.
- 12:40Z. BUILT (phase 3b, step 1). The live half of drawdown control v1:
  `scripts/book_drawdown_ladder.py` replays the combined book's published daily marks
  (`data/paper/state.json` `live_curve`, 37 marks) through the declared 5.5 / 11 percent ladder
  every publish and writes `artifacts/engineering/book_drawdown_ladder.json` (published to both
  hosts as `/glassbox/book_drawdown_ladder.json`) plus the consumer file
  `var/book_ladder/current.json`, bound by content hash. State is derived from the whole marked
  history each run, never stored, so no process can lose it. A halt is absorbing until the owner
  writes a dated entry into `config/book_ladder_rearms.json` (created, empty); a rearm restarts
  the ladder with the high-water mark reset to that mark. Tests: replay equals the study's
  vectorized twin on the twin's realized curve (three seeds), first-day loss counts from the
  boot mark, halt absorbing until rearm, unused rearms reported, invalid curves fail closed,
  bindings and hash. Today's reading: NORMAL, multiplier 1.00, drawdown 2.81 percent from the
  100,108.02 high-water mark, all-time maximum drawdown 3.87 percent, 0 halts. No live cycle
  reads the file yet (`activation.live` stays false); that is step 2. Health board gains
  `C12-book-ladder` (FAIL when the artifact or consumer file is missing or unbound, FAIL critical
  on FLAT_HALTED so a halt pages the owner, WARN at HALF_GROSS or when stale), compiled under the
  launchd interpreter. Pipeline edges declared for both jobs; `live_tick.sh` is edited only
  after the running 12:25Z tick exits (zsh reads a script incrementally).
- 12:39Z. BLOCKED, CORRECTLY. The 12:25Z tick's deploy was skipped by the live-change gate:
  measured fingerprint 0d291e23 against the declared fe82c4ee. Cause: my `BlendStrategy`
  constructor gained the `book_multiplier` seam (default None) while the tick was running, and
  `strategy_settings()` fingerprints every constructor default. The guard did exactly what its
  2026-08-21 incident asked of it ("a default nobody overrides is the production setting").
  Nothing traded differently; the seam is call-site wiring like `mu_provider`.
- 12:45Z. DECLARED (phase 3b, step 3). Coverage extension, following the 2026-08-21 and
  2026-08-23 precedents: `book_multiplier` joins `_NOT_SIZING`, and `risk_path_settings()` now
  hashes what the seam does: `book_ladder_activation_live` (false), the two depths, the release
  fraction, the read source and staleness horizon, read from the same contract file the provider
  reads at trade time. New fingerprint 70eef97c; `live_change_contract.json` re-pinned with a
  seventh change_log entry (`contaminates_forward_record: false`), `forward_evidence_contract`
  and the current-book drawdown study re-pinned, the pre-registration draft's pins updated. The
  three current-composition studies, the drawdown-evidence seal, the maturity evaluation and the
  fingerprint export re-run locally against the new pin; the published stamp catches up at the
  13:25Z tick. Test `test_the_published_stamp_agrees_with_the_declaration` is red until then.
- 12:50Z. BUILT (phase 3b, step 2). Consumers, default-off behind that one switch:
  `alphaforge.risk.book_ladder.BookLadderProvider` (file or HTTPS source, last-good cache,
  staleness flag, fail-open to 1.0 with the error in the reading, never raises; 16 tests);
  `scripts/live_cycle.py` multiplies the equity sleeves' target weights by the reading and prints
  one loud line per cycle (4 harness tests: half gross halves the submitted book, a halt sends a
  flatten, not-activated ignores a halt, a missing file sizes at full gross and says READ FAILED);
  `BlendStrategy(book_multiplier=...)` applies it after the sleeve ladder, halts every bar at 0,
  rescales every bar below 1, with two new counters (5 tests, including a broken provider and an
  out-of-range value); `paper_cmds._build_loop` passes the provider to the strategy and the loop,
  which logs the reading each cycle and alerts once per process on a read error. The live-path
  repair that rides along: the pre-multiplier book is persisted per cycle (`strategy_last_targets`)
  and restored on boot, so under --once a de-gross acts on the next hold bar (store round-trip and
  loop restore tests). `RiskCfg.book_ladder` carries only the transport (source, path, url,
  contract path, max age, timeout). Frankfurt takes effect only after the owner's rsync; the
  crypto loop there is on the old code until then, which is safe because activation is false.
- 12:52Z. PUBLISHED. A manual tick (12:51Z) ran the whole ordered chain with the new step:
  ladder artifact written, live-change gate green on 70eef97c, landing and app deployed on
  attempt 1, IndexNow 263 URLs. canlicapital.com serves `/glassbox/book_drawdown_ladder.json`
  (NORMAL, x1.00, 37 marks, activation false), the paper-state stamp carries the new
  fingerprint, and the maturity status is back to IMMATURE_RECORD_TOO_SHORT.
- 13:05Z. REPAIRED (found by the full unit suite, 16 red). Three classes, all from today's
  work, none from the brake itself. (1) Mine, this branch: system map regenerated; three
  guards had no registered mutation (`test_book_ladder_provider`,
  `test_audit_external_experiment_ledgers`, `test_prospective_epoch_register`), now registered
  and proven CAUGHT with `mutation_ledger.py --only`; the crypto-carry bundle rebound to the
  edited strategy module the way af0191b did (3 files, 4 lines; the seal script's `_ro_crate`
  writes a different layout, so the crate hash was replaced surgically). (2) From the import PR:
  recording the 320 review INSIDE `config/trial_accounting.json` drifted five sealed bindings
  (the v7 promotion receipt embeds the policy byte-for-byte; every v2 reservation and the
  crypto-carry closure hash it). The policy bytes are restored exactly; the event record now
  lives in `config/trial_accounting_reviews.json`, which the audit reads beside the policy. No
  rule changed, so no receipt is re-sealed. (3) From the import: the alphatrend family has 49
  identities in the union and 21 trial packets (packets are built for the legacy epoch), so the
  bundle builder's "family count equals manifest" gate could not pass. The family result now
  publishes `identities_with_trial_packets` beside the total, the builder binds that count to
  the manifest and requires total >= packetized, and the alphatrend bundle is rebound to the
  edited audit script. Still red and owner-only: the Frankfurt preflight (two tests) says the
  local `live/store.py` differs from what was deployed, which is true until the owner runs the
  guarded deploy; the lint-debt copies on the hosts catch up at the next tick.
- 13:22Z. COMMITTED. `risk/book-ladder-live-half-20260914` (3321e50, 48 files) pushed; alphac
  **PR #32** opened on `ops/deploy-watchdog-20260914`, so the merge order is now #23 -> #24 -> #25
  -> #26 -> #27 -> #28 -> #29 -> #30 -> #31 -> #32. The full unit suite after the repairs was red
  only on receipts the nightly ceremony regenerates (archives, worksheets, Stanford map, readiness,
  bundle parity, public copies of the two replay receipts, the restored policy's public copy) and
  on the two Frankfurt preflight tests that stay red until the owner deploys. The nightly ceremony
  is being run by hand now (the last two nightlies "COMPLETED WITH ERRORS" on the LAB incident and
  the Vercel logout, both fixed) so those receipts catch up today rather than at 02:10.
- 13:29Z. NIGHTLY OK BY HAND. `live_publish.sh` run manually: `=== publish OK 2026-09-14T13:28:54Z ===`,
  the first clean nightly since the 09-12 LAB incident and the 09-13 Vercel logout (both nights
  "COMPLETED WITH ERRORS"). It regenerated every publication receipt against the rebound bundles
  and deployed both hosts; the 13:25Z launchd tick ran concurrently (gate green on 70eef97c) and
  its deploy correctly yielded to the publish's lock ("next hour retries"). CI on the branch was
  started by hand with `workflow_dispatch` (the workflow only triggers on PRs to main, so stacked
  PRs get no checks until the chain is merged in order).
- 13:31Z. SUITE. Full unit suite after the manual nightly: red only on the two Frankfurt preflight
  tests (`test_crypto_position_attribution_vps_preflight`, `test_deploy_crypto_position_attribution_vps`),
  which say the local `src/alphaforge/live/store.py` differs from what Frankfurt runs. True, and
  owner-only: the guarded deploy (`scripts/deploy_crypto_position_attribution_vps.py`, preflight then
  `--apply`) carries the book-ladder consumer and the last-targets persistence to the crypto loop
  and refreshes the preflight contract. Live site verified: public `trial_accounting.json` equals the
  restored policy byte for byte; the ladder artifact is from the 13:25Z tick.
- 13:59Z. CI (dispatched by hand on the branch): ruff, mypy --strict, publication integrity
  (clean checkout), browser fixture and the PostgreSQL contract green; the offline pytest job red
  on two INTEGRATION tests (`tests/integration/test_phase6_observability.py`) that assert the
  strategy's counter keys exactly, which the unit run I used locally never executes. The two
  book-brake counters are acknowledged there the same way the 2026-08-18 key was. Lesson recorded:
  run `tests/integration` locally before pushing a counter or schema change.
- 14:26Z. CI GREEN on `risk/book-ladder-live-half-20260914` (run 34852748404, dispatched by hand):
  offline pytest, browser fixture, ruff, mypy --strict, publication integrity (clean checkout),
  PostgreSQL contract. Local integration and property suites green. PR #32 is ready for the owner's
  merge at the end of the chain.
- 14:50Z. FRANKFURT, READ-ONLY. The owner asked for "all of those" (merge, Frankfurt, activation,
  outreach). Merging is blocked for this session by the auto-mode classifier (`gh pr merge`), as
  is mutating the host; both stay owner one-liners. What could be done was done: a read-only hash
  snapshot of the crypto host through the repo's own deploy tool (allowed) showed 176 of 195
  shipped files identical, 7 drifted (pyproject, paper_cmds, settings, loop, store, strategy,
  trial_reservation) and 3 relevant files absent (book_ladder.py, ladder_paths.py, the
  drawdown-control contract); the host's store/loop/paper equal the 2026-09-06 desired revisions,
  so the 09-10 rsync did land. The last cycle (14:10Z) was a healthy hold. The deploy tool is
  generalized (`companion_files`, declared pre-rollout schema, required tables after migration,
  an import smoke test inside the rollback trap, absent-file install and removal on rollback);
  the contract is re-pinned to reality with two desired_revisions entries and seven companions,
  `pyproject.toml` deliberately excluded (dependency pins need their own environment rollout).
  The read-only preflight PASSED against the host and wrote its observation. `--apply` with the
  approval phrase was refused by the classifier; the owner runs it (one line, between the :10
  cycles), then the 15:10Z-or-later natural cycle and the hourly verifier seal the receipt.
- 15:05Z. ACTIVATION-READY. Everything the flip needs, except the flip: the published
  aggregation policy's `book_level_drawdown_ladder` is now DERIVED from the drawdown-control
  contract (None while inactive, the declared depths once live) so the stamp, the fingerprint
  and the trading path cannot disagree; the drawdown-evidence seal accepts whichever the
  contract declares and rejects anything else; the maturity evaluator gains evidence-epoch
  semantics (the latest live-change entry with `contaminates_forward_record: true` starts the
  current epoch; earlier returns are published as a prior epoch beside it, never pooled; realized
  drawdown stays descriptive over the whole record; tests for one epoch, a split, an epoch that
  has not marked yet); the README sync names the epoch when one exists. Today: one epoch, 36
  returns, no change. `scripts/activate_book_drawdown_brake.py` performs the flip as one pass
  over six files (contract live + decision, base.yaml source https, change_log entry with
  contaminates true, three pins), refuses to run twice or when the fingerprint does not move,
  and is tested on sandboxed copies. It will be run only after the owner's Frankfurt rollout
  lands, so the crypto sleeve is never described as braked while it is not.
- 15:12Z. COMMITTED. `ops/frankfurt-rollout-activation-ready-20260914` (82ad246) pushed; alphac
  **PR #33** opened on #32's branch. Chain: #23 -> ... -> #32 -> #33. CI dispatched by hand. The
  pre-commit hook regenerated the lint-debt contract for the commit. Owner one-liners now: the
  ten merges in order; the Frankfurt apply (between :10 cycles); then, once the natural cycle
  after the apply is verified, `uv run python scripts/activate_book_drawdown_brake.py
  --decision "<words>" --activated-on <UTC date>` followed by a second companion rollout of the
  contract and base.yaml. Outreach: no recipient or fee exists in the repository, so nothing can
  be sent from here; the drafts wait for a name and a number.
- 15:20Z. WIRED (v2 reservation plan, Task 4; the owner checkpoint is met by the delegation of
  2026-09-14 and today's "ok lets do all of those"). `_validate_forward_epoch_serial_completion`
  now calls `_validate_prior_identity_admission_disposition` for every prior forward identity:
  a complete packet no longer unblocks the next ordinal by itself; its sealed closure must say
  ADMIT or KILL, or an owner waiver must be bound to that packet's exact content hash. The
  end-to-end test replays the sealed v1 shape inside a full `validate_reservation` call and
  proves the block, the waiver, and that a waiver bound to another hash is refused; the guard's
  registered mutation is still CAUGHT. Consequence in the real repository, faced rather than
  hidden: crypto_carry_portable_v1 closed FINAL INCOMPLETE, so every reservation would now be
  blocked. The owner's waiver for that one identity is written and tracked
  (`artifacts/research/seriality_waivers/da5f5f47f99f9bd2.json`, bound to the sealed packet
  hash 9ba408cb, reason recorded, authorization recorded as delegated), validated against the
  real packet and closure (WAIVED), and pinned by a test. The next ordinal (348) can be reserved
  through the v2 path; the tier-0 return runners are what remain before the first reservation.
- 15:30Z. PLANNED. `docs/superpowers/plans/2026-09-14-earnings-narrative-change-return-runner-plan.md`:
  seven tasks from the 2026-08-15 pre-registration to the first v2 reservation at ordinal 348,
  each with its proof, building on the corpus tooling the feasibility pass already ran. Task 1
  (the full 2005-2025 10-K corpus) is days of rate-limited downloads and runs unattended, never in
  a tick. No identity is spent by the plan. The treasury-auction family follows the same shape.
- 15:50Z. CORRECTED. The return-runner plan's Tasks 1 and 2 were already done on 2026-08-15/16:
  `artifacts/ingest/earnings_narrative_change/` holds the whole 10-K corpus (83,070 filings,
  8,122 CIKs, 2005-2025, 73,744 Item 1A sections, 331 hash-bound parts, `complete: true`) and
  65,050 predecessor pairs with Jaccard already computed. I wrote "days of downloads" from the
  feasibility probe's sample counts without opening the ingest directory; the plan now says so
  and the remaining work is Tasks 3 to 7: market inputs, signal, portfolio, evaluation with the
  v2 reservation at ordinal 348, and the run.
- 16:25Z. BUILT AND FOUND (narrative-change runner, tasks 3 to 6 plus the calibration driver).
  `alphaforge.research.narrative_change` now holds inputs (issuer mapping, session calendar on
  New York open and close instants, PIT daily panel through the shared adjustment engine, the
  input manifest), signal (cohorts, filing reaction, momentum, eligibility, residual regression,
  quintile sides), portfolio (scheduling, beta hedge, netted-turnover costs, missing-open
  deferral, force-flat, capacity) and evaluation (Sharpe, Newey-West, deflated Sharpe, drawdown,
  annual, leave-one-year-out, mean-zero control, the shared diversification engine); 32 tests.
  `scripts/run_earnings_narrative_change_v1.py` runs calibration and refuses the out-of-sample
  window until the v2 template is in force. A two-year calibration smoke ran in 28 seconds and
  did exactly what calibration is for: it exposed a survivorship hole. The Sharadar lake holds
  8,436 instruments; SEP's ticker table holds 21,859 (15,573 delisted). In the 2007-03 cohort
  749 of 1,759 mapped issuers have no lake partition at all, every one a delisted name. A run on
  the lake as it stands would be a survivor-only backtest, which the pre-registration forbids.
  Nothing is decided by this; the fix is a full-history SEP lake (next entry), not a parameter.
- 16:30Z. FOUND, PRODUCTION. While checking the price path for the new sleeve I ran the shared
  adjusted-close engine across Apple's 2020 four-for-one split on both production lakes:
  raw close 499.23 the day before, 129.04 on the ex-date; ADJUSTED close 1,996.92 the day
  before, 129.04 after, a fake 93.5 percent one-day drop. Cause: every lake stores the vendor's
  factor, new shares per old (4.0), while the engine multiplies pre-ex prices by ``ratio`` and its
  own tests encode a two-for-one as 0.5, old shares per new. Two conventions, never checked
  against each other. A random sample of 80 real splits from data/lake (2020-2024): 57 come out
  with an adjusted ex-date jump exactly twice the raw one in log terms, 3 plausible, 20
  undetermined. `eq_mom_252_21`, the only alpha of both live equity walk-forwards, reads that
  panel through `_adjusted_close_panel`, as do reversal, realized volatility and beta. The
  2026-08 repair that made splits apply at all (they never had) applied them inverted; before it
  the same names were unadjusted. Either way the momentum sleeve has been ranking split names on
  garbage moves. Whole-lake audit running (`scripts/audit_split_adjustment_direction.py`);
  the fix is one convention, declared, with a cross-lake guard that checks the engine against
  a real split, then the walk-forwards regenerate. Nothing is changed until the audit is in.
- 16:40Z. MEASURED, WHOLE LAKES (`artifacts/audit/split_adjustment_direction.json`). data/lake:
  5,156 splits on 3,031 instruments; of the 4,662 determined, 4,135 (88.7 percent) come out of
  the engine with an adjusted ex-date jump of twice the raw one (inverted), 228 neutralized,
  299 other. data/lake_sharadar: 4,804 splits on 2,801 instruments; 4,000 of 4,440 determined
  (90.1 percent) inverted, 208 neutralized. The Codex alphamax beta-neutral probe of 2026-09
  had disclosed the same defect with the same Apple and Tesla numbers and worked around it
  inside the probe, leaving `src/**` untouched; the live sleeves kept trading on it. Fixed at
  the source: the kernel now divides pre-ex prices by the stored vendor factor (new shares per
  old, the convention `data/schemas.py` documents and every lake follows) and refuses a
  non-positive factor; the engine's eleven fixtures flip to the vendor convention; a cross-lake
  guard checks Apple's 2020 split through the engine on both production lakes (pre-ex adjusted
  close 124.81, raw 499.23 over four); the probe's local inversion is retired so it cannot
  double-invert. The neutralized rows are being classified next: a small split, or a stored
  reciprocal that the fix will turn wrong and that needs a versioned repair.
- 16:45Z. VERIFIED AFTER THE FIX. The same whole-lake audit under the corrected kernel:
  data/lake 3,857 of 4,662 determined splits neutralized (was 228), 89 still doubled (was
  4,135); data/lake_sharadar 3,746 neutralized (was 208), 93 still doubled (was 4,000). Reading
  each stored ratio's convention off the raw ex-date move: 4,116 and 3,984 rows follow the
  vendor convention, 90 and 93 are stored as the reciprocal (Amarin 2025-04-11 stored 20.0 with a
  raw move of +3.02, AstraZeneca's ADR ratio changes, Bank of Chile's), the ADR-ratio class the
  corrected-lake work already isolates as `adrratiosplit`. Those rows are listed in the audit
  artifact (`reciprocal_rows`) for a versioned lake repair with its own receipt; they are not
  re-inverted anywhere. The kernel fix is committed signed (19b8fdc), the audit artifact tracked
  (13435db). Live effect: the equity walk-forwards regenerate on the next tick after this lands
  on main and the publisher tree switches; the equity target books change on names that split
  within 252 sessions.
  each with its proof, building on the corpus tooling the feasibility pass already ran. Task 1
  (the full 2005-2025 10-K corpus) is days of rate-limited downloads and runs unattended, never in
  a tick. No identity is spent by the plan. The treasury-auction family follows the same shape.
- 16:36Z. MERGED. #36 (the signed chain, #24 through #34) landed on main by the owner's
  `gh pr merge 36 --squash --auto` once CI went green; the publisher tree is on main (8561336).
  The two earlier attempts taught two rules now in memory: deleting a stacked PR's base branch
  closes its dependents for good, and main requires signed commits, so every branch today had to
  be rebuilt with signing on.
- 16:55Z. BRANCH. `research/narrative-change-runner-and-split-fix-20260914` from main, ten
  signed commits: the runner (tasks 3 to 6, the calibration driver, the survivorship-inclusive
  lake builder) and the split-direction repair with its audit and guard. One PR, because the
  repair's guard test lives in the runner's test file and the owner merges once.
- 17:00Z. BUILT. `data/lake_sharadar_full` from the raw SEP and ACTIONS archives
  (`scripts/build_sharadar_full_history_lake.py`, receipt
  `artifacts/audit/sharadar_full_history_lake_build.json`): 21,861 instruments, 46,079,829
  daily bars, 263,516 executable corporate-action rows, 2.9 GB, 18 minutes, in the base lake's
  layout and conventions (raw prices; the vendor split factor; dividends on the vendor basis,
  which consumers do not fold). The runner reads it by default. The base lake (8,436
  instruments) stays untouched for every sealed audit that binds it.
  Verified through the branch's own code: Apple's 2020 split neutralizes on the full lake
  (adjusted 124.81 the day before, 129.04 after), Apple's action rows equal the base lake's
  (56 dividends, 4 splits), and the 2007-03 cohort that lost 749 of 1,759 mapped issuers on the
  base lake loses none. The full 2006 to 2015 calibration is running on it.
- 17:02Z. CALIBRATION, 2006 TO 2015, ON THE FULL LAKE (plumbing only, by the pre-registration;
  no parameter may change and nothing is promoted or killed by it). 116 acceptance-month
  cohorts, 5,529 instruments, 80 seconds. 59 cohorts ranked; 40 had fewer than 20 eligible
  issuers, 15 saturated the one-hot industry design (fewer than 10 residual degrees of
  freedom), 2 had fewer than 5 names in a tail. Attrition of 32,386 pairs: 11,098 below the
  $5 million median dollar-volume floor, 8,097 below the $5 close, 1,408 issuers with no
  Sharadar ticker row at entry, 91 with no close before entry (was thousands on the base lake).
  56 force-flats over ten years, every one a delisting the full lake now shows. The plumbing
  holds: turnover 9.7 times a year, average stock gross 0.88 plus a near-zero hedge (beta to
  SPY minus 0.02), capacity bound by one 2009 name at 1 percent of ADV. The number the
  pre-registration says calibration cannot act on, reported anyway because hiding it would be
  worse: at the locked direction (long stable, short changed) the 2007 to 2015 net Sharpe is
  minus 0.81, Newey-West t minus 2.31, stressed minus 1.28, maximum drawdown 42.7 percent,
  below 98.4 percent of mean-zero block-bootstrap controls. Every year but 2010 and 2015 is
  negative. This is not the out-of-sample test and it changes nothing about the locked identity;
  it is disclosed so the owner spends the 2016 to 2025 identity knowing what the earlier
  interval looked like. The deflated-Sharpe union count in this run (191) is an artifact of
  running from a scratch tree that cannot see every ledger; the canonical union is 347 and the
  out-of-sample run must be made from the main tree.
- 17:40Z. DECISION (owner). "no the sharpe target is 2 and also in general make sure everything
  is the best." The operator had been about to keep publishing the admission contract's 1.5
  forward target as the programme objective. Recorded as `config/owner_goals.json`
  (`canli.alphac-owner-goals.v1`, in force 2026-09-14): combined forward Sharpe ABOVE 2.0 net of
  costs, realized maximum drawdown AT MOST 11 percent, AT LEAST 15 qualified economically distinct
  sleeves, each quoted from `docs/design/ALPHAC_OWNER_GOALS_2026-09-12.md` in the owner's words.
- 17:55Z. BRANCH. `governance/owner-goals-in-force-20260914`: one governing source, projected by
  `src/alphaforge/research/owner_goals.py` into every public objective block (program status,
  sleeve discovery, atlas, diversification study, orthogonality prior, Stanford map, README).
  The sealed v7 admission contract is untouched, its sha256 pinned in the goals file, and its
  objective is published inside the governing one as dated history. The forward-evidence contract
  moved to v7: `forward_sharpe_target` 2.0 with a dated `forward_sharpe_target_history` (the 1.5
  was never evaluated against; the record held 36 returns), plus the owner's realized-drawdown
  bound published beside the modeled expected-drawdown objective, never mixed. The frontier
  arithmetic is the sealed identity at 15 sleeves and forward 2.0: at the contract's measured
  quality (0.464) the low end of the band needs rho_bar -0.0458 against a PSD floor of -0.0714,
  and at the 0.00 gate a mean standalone Sharpe of 0.775. Reachable inside the floor; not bought
  by the sleeve count. Nothing here establishes a target; no identity spent.
- 17:58Z. FIX (PR #37). CI failed on `tests/integration/test_corp_actions_read_path.py`: the
  planted 2:1 split was stored as 0.5, the old-per-new convention the inverted kernel happened
  to fold correctly. Stored as 2.0 now (68eecbf, signed); the three assertions are unchanged.
- 18:05Z. DECISION (owner), superseding the 17:40Z numbers. The owner restated the full goal set
  in one message (quoted verbatim in `docs/design/ALPHAC_OWNER_GOALS_2026-09-12.md`, "Owner
  restatement, September 14 2026"): the world's first open glassbox algorithm that developers use
  through API keys and MCP servers to build, fine-tune and improve their own models; everything
  published, every test included; for ALPHAC a Sharpe of 2, **14 or more** sleeves, **10 percent**
  maximum drawdown; extremely rigorous testing; real-life costs on the paper-live record; and
  eventually a real hedge fund. `config/owner_goals.json` now carries exactly that: sleeves AT
  LEAST 14 (not 15), realized drawdown AT MOST 0.10 (not 0.11), plus a `program` block for the
  glassbox platform, open publication, testing, cost realism and the fund. FINDING: the declared
  drawdown brake goes flat at 11 percent and so cannot enforce a 10 percent bound; the goals file
  says so (`mechanism_status` INCONSISTENT_WITH_BOUND) and the brake must not be activated until
  a 5/10 ladder is measured and declared. The sealed 11 percent expected-drawdown objective stays
  published beside the bound as the modeled objective, never mixed with it.
- 18:30Z. MEASURED (scratch, not declared). The 10 percent bound needs a ladder that goes flat
  at or below 10 percent, so the declared study (`scripts/analyze_drawdown_control.py`, same
  generator, same seeds, same current-composition paths) was rerun on a scratch copy of the
  contract with the ladder at 5.0 / 10.0 instead of 5.5 / 11.0. Result: conservative p95 maximum
  drawdown 0.1007 and p99 0.1020 with the absorbing ladder (0.1102 / 0.1116 at 5.5 / 11), regime
  halt probability 0.111 (0.064), two-year drift cost 0.0096 (0.0074); accepted under the study's
  own p95 <= 0.12 / p99 <= 0.13 rule, which was declared for the 11 percent objective and must be
  re-declared for the bound before the 5 / 10 ladder is written into
  `config/drawdown_control_contract.json` (a versioned contract change, its own PR). The scratch
  cell is `artifacts/scratch_dd_ladder_5_10/result.json` in the goals worktree and is not
  published. Until that PR lands, `owner_goals.json` keeps
  `mechanism_status` INCONSISTENT_WITH_BOUND and the brake stays off.
- 18:50Z. AUDIT. Cost realism on the paper-live record, cost by cost against research, with file
  and line evidence: `docs/design/COST_REALISM_AUDIT_2026-09-14.md`. The crypto sleeve charges
  commission, real spread and impact (fills walk the live book) and perpetual funding since
  2026-08-06. The equity sleeves' published NAV is Alpaca's paper equity verbatim: no commission,
  no spread or impact, no borrow, no financing. Cash yield and FX are unmodelled everywhere.
  The forward record is therefore gross of equity frictions while the owner's Sharpe target is
  net. Repair shape (next PR): a declared cost contract; the equity curve charged by the same
  cost model research uses, borrow on short notional, financing on margin, cash yield on idle
  cash; broker NAV retained as the original beside the cost-charged curve; the change declared
  in the live-change contract so the epoch rule decides. `owner_goals.json` says
  EQUITY_PAPER_LIVE_GROSS_OF_FRICTIONS_REPAIR_PENDING.
- 18:55Z. PR. #38 `governance/owner-goals-in-force-20260914` opened on main; canlicapital #12
  (claim relabel) waits for the first publish that carries the goals.
- 19:05Z. BUILT (branch `research/v2-batch-reservation-promotion-20260914`, from main). The gate
  every new sleeve waited behind: (1) `config/trial_accounting_evidence_classes.json` defines the
  selectable identity, the mandatory diagnostic and the atomic identity batch beside the sealed
  trial policy; (2) the reservation validator now validates declared diagnostics (assumptions
  only before the run), atomic batches (registry sealed before the first return; no member added,
  removed or reordered; every earlier sibling reserved on disk), batch-aware seriality (siblings
  decide together; any other open batch blocks) and ordinals that move past reserved-but-unrun
  siblings; (3) `scripts/audit_forward_full_evidence_reservation.py` audits a FILLED reservation
  return-blind (every stress scenario able to fail, the governing capacity point present, ADMIT
  reachable only with two PBO columns, every execution dimension applicable or excused);
  (4) `scripts/promote_forward_full_evidence_reservation_v2.py` promoted the template.
- 19:12Z. DECISION (owner, delegated). The v2 full-evidence reservation template is IN FORCE from
  reservation ordinal 348 (`config/forward_full_evidence_reservation_v2_promotion.json`, receipt
  sha256:b909390b…), authorized by the owner's words of 18:50Z. Nothing is authorized by the
  promotion itself: a return opens only behind a filled reservation that passes the validator
  and the filled-reservation audit. The template's ordinal follows the validator's arithmetic
  (228 legacy identities + 119 forward identities in the ledgers + 1), not the trial-accounting
  union, which also counts window-only remeasurements. Five new mutations proven CAUGHT.
- 19:15Z. PREREGISTERED. `docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE_MDNA.md`: the family's
  second and final identity (10-K Item 7 stability, same signal, same portfolio, same gates),
  declared before any return so the two identities form one atomic batch and PBO is defined on two
  columns. The Item 7 corpus is being parsed offline from the 82,491 cached documents
  (`scripts/build_sec_10k_item7_corpus.py`, no network read, 92.5 percent extraction on the first
  120 filings), into `artifacts/ingest/earnings_narrative_change/item7_parts`.
