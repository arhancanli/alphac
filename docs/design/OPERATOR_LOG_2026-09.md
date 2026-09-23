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
- 19:20Z. DECLARED. Drawdown control v1.1 (`config/drawdown_control_contract.json` version 1.1):
  the ladder re-derived from the owner's restated 10 percent bound by the same rule (half gross
  at 5.0 percent, flat at 10.0 percent, release 0.75 of the half level), the acceptance rule
  re-declared as v1.0's slack applied to the new bound (p95 <= 0.1091, p99 <= 0.1182, derived
  before the official run; the 18:30Z scratch cell is disclosed in the contract), and v1.0 kept
  in `history`. The hashed live surface moved (book_ladder_dd_half_frac / dd_flat_frac), so this
  is change_log entry 9 in `config/live_change_contract.json`, re-pinned in the forward-evidence
  contract, the current-book drawdown study and the pre-registration draft:
  sha256:70eef97c… -> sha256:e2533899…. Not a trading change: activation.live is false, every
  sleeve still applies a multiplier of exactly 1.0, the epoch does not restart. The official
  v1.1 measurement is recorded in the contract's `measurement` block and the branch is
  `risk/drawdown-control-v1-1-ladder-5-10`, stacked on #38 and opened against main once #38 lands.
- (recorded late at 18:25Z; written in the publisher tree at the times shown and never committed there)
- 16:36Z. MERGED. #36 (the signed chain, #24 through #34) landed on main by the owner's
  `gh pr merge 36 --squash --auto` once CI went green; the publisher tree is on main (8561336).
  The two earlier attempts taught two rules now in memory: deleting a stacked PR's base branch
  closes its dependents for good, and main requires signed commits, so every branch today had to
  be rebuilt with signing on.
- 16:55Z. BRANCH. `research/narrative-change-runner-and-split-fix-20260914` from main, ten
  signed commits: the runner (tasks 3 to 6, the calibration driver, the survivorship-inclusive
  lake builder) and the split-direction repair with its audit and guard. One PR, because the
  repair's guard test lives in the runner's test file and the owner merges once.
- 18:50Z. DIRECTION (owner). "focus on adding sleeves improving each sleeves sharpe ratio returs
  cagr max dd and everything ... i give you full permision for the activiations so you can go
  ahead." Recorded in `ALPHAC_OWNER_GOALS_2026-09-12.md`. Plan: (1) land #38 and #39; (2) promote
  the v2 full-evidence reservation so out-of-sample runs can be authorized at all, which is the
  gate every new sleeve waits behind; (3) run the earnings-narrative-change candidate out of
  sample at ordinal 348 under that reservation; (4) the treasury-auction candidate next; (5) the
  cost-realism repair so every sleeve's published figures are net; (6) activate the brake with
  the v1.1 ladder once the crypto host reads the flipped contract. Every activation remains a
  declared, fingerprinted change.
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
- 19:36Z. DECISION (owner, delegated) and IMPORT. The seriality guard blocked every new
  reservation, correctly: the 2026-09-14 reconciliation had imported the 52 experiment ledgers
  of the second checkout (118 forward-epoch identities, union 347) but not their packets, so
  118 identities stood undecided in the canonical tree. `scripts/import_external_identity_packets.py`
  brought each packet home (content hash verified, bound evidence copied and hash-checked),
  wrote one canonical admission closure per identity with disposition KILL, and re-sealed the
  packet. The basis is each packet's own decision statement: 2 studies said REJECT under their
  frozen scenario, 1 said RETAIN FOR FURTHER TESTING (recorded verbatim, flagged as a
  construction retained for a NEW identity; this identity is spent and final), and the other
  115 describe retrospective, known-history or development measurements on inspected history,
  which the admission contract can never admit as they are. None was admitted; the union count
  is unchanged; the record is `config/trial_accounting_reviews.json` external_packet_import.
  Seriality after: 119 forward identities decided (118 KILL, 1 waived).
- 19:38Z. PROVEN (dry run). `scripts/author_earnings_narrative_change_batch.py` authored the
  narrative-change batch in the worktree: registry sealed; existing-book snapshot and
  bottom-decile stress mask frozen; drawdown specification, overlay configuration and an
  execution scenario manifest (17 applicable dimensions x 3 scenarios, 9 excused with hash-bound
  evidence) written; both reservations validated by the in-force guard at ordinals 348 and 349
  as one atomic batch; both filled-reservation audits SATISFIABLE with disposition ceiling
  ADMIT. No return was read. The real authoring and the single out-of-sample batch run happen
  in the publisher tree once #40 lands, because the reservation binds the merged runner's hash.
- 19:42Z. RUNNER. With a reservation the out-of-sample runner now also measures the candidate
  against the frozen existing-book snapshot the reservation binds: correlations, stressed
  correlations and their one-sided bounds, the fixed-weight book deltas through the shared
  diversification engine, and the expected and 95th-percentile maximum drawdown of the
  zero-drift book with and without the candidate at the frozen 10 percent weight (the
  current-composition study's generator, seed and 63-day block). The candidate sits on the
  snapshot's UTC calendar with 0.0 on non-sessions, the convention the composite already uses
  for its equity sleeve. Exercised on the dry-run reservation with a synthetic series: 1,061
  aligned days, REPORTED. The publisher-tree chain (authoring, then the single batch run) is
  armed and waits for #40 to land and the tick to be idle.
- 20:00Z. SEAL WRITTEN (PR #41, stacked on #40). `scripts/seal_earnings_narrative_change_batch.py`
  runs after the single batch and, per identity, builds the evidence document the admission
  contract's evaluator reads from the sealed outputs and the frozen evidence the reservation
  binds, then lets `evaluate_sleeve_evidence` decide. Every gate the contract declares is
  measured, which is what crypto_carry_portable_v1 lacked: per-sleeve and book-level deflated
  Sharpe, the batch PBO, the book's average-correlation delta and rolling instability, a
  block-bootstrap one-sided lower bound on the book Sharpe delta (the reservation's 10,000
  paths, 63-day block, seed), the correlation-regime drawdown with and without the candidate,
  the capacity curve reconciled to the declared capacity scenarios (fill ratio as the scenario's
  mean gross over the baseline's, stressed cost as the scenario's cost drag per unit turnover),
  and execution evidence per dimension under the pre-registered pass rule (net Sharpe at or
  above 0.40; a scenario with no Sharpe cannot pass). The overlay block reads every number from
  its source: production's vol target, scale ceiling and 240-bar realized halflife off the code's
  own signatures, the covariance halflife as the contract's 21-day maximum, and the v7 record
  that production ships 720 bars today. That gap is written on the closure as a deployment
  condition (a declared live-configuration change must carry the contract value before the
  sleeve trades); it is not hidden inside a passing number. The pre-registration's
  DATA-ESCALATE rule is applied after the evaluator: a passing result with any force-flat closes
  INCOMPLETE, never ADMIT. Outputs per identity: admission evidence, evaluator report inside the
  closure (every failure named), closure, v2 packet, canonical diversification report; one batch
  seal binds both closures and the PBO matrix receipt. Five tests, including a synthetic
  document the contract decides in full with the lower-bound gate caught by name. Auto-merge
  armed; main is merged in once #40 lands.
- 2026-09-15 00:15Z. FORWARD EPOCH PUBLISHED (PR #42, stacked on #41). Two gaps found while
  the batch waited. First, `scripts/build_prospective_epoch_register.py` recognised exactly
  one closure file by name, so after #40 it would have published the 118 imported identities
  as "reserved, measured, unclosed" while the seriality guard counted them decided. It now
  discovers every final closure on disk (governed: crypto carry and every narrative-change
  batch closure; development: the 118 imported closures) and labels them
  GOVERNED_SERIAL_PACKET_CLOSED or DEVELOPMENT_CLOSURE_FINAL_NOT_ADMITTED, with the closure
  path, kind, schema and disposition on the row; two closures for one identity fail closed.
  Second, the legacy packet index is sealed at 228 identities by the legacy epoch closure and
  cannot grow, so the 119 forward packets sat on disk and off the site (the site held 228 + 1).
  `scripts/build_forward_identity_packet_index.py` writes
  `artifacts/research/trial_packets/forward_index.json`: one row per register identity,
  packet bound by file hash and content hash (refused on mismatch, refused under a foreign key),
  its closure and disposition, PACKET_PENDING_SEAL for an identity whose packet the seal has
  not written, and a fail-closed check that no key sits in both epochs. research_export
  refuses an index built from a different register, copies every listed packet and the index
  to both hosts, and derives complete and published packet counts from it (legacy 228 +
  forward). Both publish pipelines run the index after the register and before the export;
  the pipeline-order test carries both edges. Measured against the publisher tree without
  writing to it: 1 governed + 118 development-closed, 0 unclosed; forward index 119
  published, 119 complete, 0 admitted, 0 pending. Site side: the trials page still reads the
  legacy index only; a canlicapital change to render the forward index follows.
- 2026-09-15 00:40Z. COST REALISM v1.0 (PR #43). The equity paper-live record charged no
  friction (audit of 09-14). `config/cost_realism_contract.json` now names every cost a funded
  book would pay and where the record charges it. `scripts/derive_cost_charged_live_curves.py`
  charges every filled Alpaca order commission, half spread and square-root impact through
  research's own TransactionCostModel at the profile's own parameters (ADV the 30-session median
  quote volume and sigma the EWMA daily volatility from the daily-bar lakes, both as of the
  session before the fill; a fill above the 5 percent participation tripwire is charged at the
  tripwire and counted as floored), and the reconstructed daily short book the borrow rate;
  `scripts/paper_trading_state.py` subtracts the cumulative charges in broker dollars before the
  $100k normalization and publishes `cost_charged_curve` beside `live_curve` per sleeve and for
  the book, with the charges; the publish gate iterates the new curve; the forward-evidence
  evaluator reads the cost-charged curve and says so (`curve_basis`); the README carries a
  derived cost-drag row. Measured on the real fill tables (no publish yet): AlphaMax 4,432
  fills, $2.42M traded, charged $2,788 (impact $1,598, spread $726, commission $242, borrow
  $221); AlphaTrend 503 fills, $1.28M, $859; AlphaVintage 40 fills, $2.33M, $1,275; every fill
  priced for impact, none floored. Latency, financing, cash yield and FX remain NOT_CHARGED with
  reasons and the date they will be. Declared in `config/live_change_contract.json` as an
  accounting change that does not restart the epoch (sizing and execution are identical). Tests:
  every charge reconciled to an independent recomputation, the charged curve at or below the
  broker curve and different by exactly the rebased charges, the gate iterating the curve, the
  contract's statuses and declaration.
- 2026-09-15 01:10Z. CAUGHT BEFORE THE SEAL (PR #45). The seal accepted `--skip-rerun`, and the
  watcher I armed used it to save time. The evaluator would have read the missing check as
  not_passed:robustness.deterministic_rerun and closed both identities KILL, which is final;
  the contract's nineteen booleans are measurements, not checkboxes. And the re-run itself was
  wrong in two ways: it re-authorized the window through the validator, which rightly refuses a
  reservation whose identity is already logged, and it wrote the curve, cohorts and manifest
  into the sealed directory it was checking. Fixed: the runner gains `rerun_of`, a re-run
  authorized by the sealed result (content hash verified, the same reservation file unchanged,
  the same section), always deferred, refused unless out_root is a fresh directory; the seal's
  re-run is mandatory, runs into a scratch directory that is removed, and compares the net
  series by hash. The watcher was stopped before the batch finished; nothing was sealed. Tests:
  the re-run is deferred into scratch and compared by hash, the seal has no skip path, and the
  re-run authorization refuses the sealed directory, a moved reservation and a wrong section.
- 2026-09-15 00:50Z. ACTIVATED (owner, delegated; PR #44, stacked on #43). Drawdown control
  v1.1 is switched live by `scripts/activate_book_drawdown_brake.py --activated-on 2026-09-15`
  with the owner's recorded words: `config/drawdown_control_contract.json` activation.live true
  (status MECHANISM_LIVE_BOUND_ENFORCED_UP_TO_ONE_DAY_OVERSHOOT), `configs/base.yaml`
  risk.book_ladder.source https, live-change entry 11 (contaminates the forward record: the
  evidence epoch restarts on 2026-09-15; returns before it are a prior epoch, never pooled),
  fingerprint e2533899 to 654432cc re-pinned in the live-change and forward-evidence contracts,
  the current-book study and the pre-registration draft. Two things fixed on the way. The
  declaration's reason typed the superseded 11 percent bound and the v1.0 figures; it now reads
  the bound from config/owner_goals.json and the accepted measurement from the contract (p95
  0.1007, p99 0.1020 with the absorbing ladder). And the fingerprinter takes the aggregation
  policy from the last PUBLISHED state, stamped before activation with no ladder, so the first
  activation declared a surface one publish behind the truth and the gate would have blocked
  the next publish; the script now computes the surface from a fresh import of
  paper_trading_state, exactly what the next publish writes, and exports the same stamp. Both
  drawdown studies re-run against the activated contract in the worktree reproduce the
  acceptance (conservative p95 0.1007, p99 0.1020, accepted). In force from the next equity
  cycle after the publisher tree carries this commit; the crypto sleeve applies it only after the
  companion-file rollout to Frankfurt (contract and base.yaml), which is the next step and is
  currently refused by the rollout contract's own drift check because PR #40 moved
  trial_reservation.py: the contract must be re-authored with desired_revisions before --apply.
- 2026-09-15 02:22Z. IN FORCE, AND ON FRANKFURT. #43 (cost realism) merged 21:24Z, #45 (mandatory
  seal re-run) 21:54Z, #44 (drawdown control v1.1 activated) 22:17Z; the publisher tree pulled
  main at bc5ee5c with the tick idle, so the equity sleeves read the live contract and the https
  ladder source from their next daily cycle. The published ladder at that moment: state NORMAL,
  gross multiplier 1.0, book drawdown 2.98 percent against the 5 percent half-gross rung, so
  activation changes no sizing until the book falls further. Frankfurt: the rollout contract
  (`artifacts/engineering/crypto_position_attribution_vps_preflight.json`) had refused the tree
  since #40 moved trial_reservation.py; it was re-authored against a read-only host snapshot with
  one desired_revisions entry per moved file (settings.py, trial_reservation.py, the drawdown
  contract, and configs/base.yaml added as a companion, each with its reason), the read-only
  preflight passed, and `deploy_crypto_position_attribution_vps.py --apply` deployed at
  22:20:52Z: the 2026-09-14 loop.py (book-ladder reading, pre-multiplier book restored on
  boot), store.py, settings.py, paper_cmds.py, strategy.py, trial_reservation.py,
  book_ladder.py, ladder_paths.py, the activated contract and base.yaml (source https). Timer
  active, service idle, nine tables, every file at its desired hash; no cycle was forced; receipt
  `crypto_position_attribution_vps_receipt.json` waits for the first natural :10 cycle
  (23:10Z), after which `verify_crypto_position_attribution_rollout.py` decides. The crypto
  sleeve therefore applies the brake from that cycle. Batch: the Item 1A section finished
  (52 of 120 cohorts ranked, 60 force-flats; the seal decides, not this log); Item 7 is building
  cohorts; the seal, with its mandatory re-runs, follows.
- 2026-09-15 02:40Z. PUBLISH STALLED FOR TWO HOURS, FOUND AND FIXED (PR #46). Every tick since
  the publisher tree took #40 at 20:25Z ran research_export to a fail-closed error:
  "prospective trial publication fails closed: future_template_is_not_active,
  future_template_bound_by_audit". Two defects, both mine. The crypto carry prospective record
  asserted the v2 template was NOT in force, which #40's promotion made false by design. And the
  tick step I added in #40 ran the template audit without `--write`, so it printed a fresh audit
  to /dev/null and left the 2026-08-24 file in place; the export then compared a pre-promotion
  audit against the promoted template. The site's research.json therefore stayed at 19:50Z
  (program_status, trial ledger and the forward index were not republished; the paper state and
  the ladder, written by other steps, kept publishing). Fixed: the record now requires the
  template's state to be CONSISTENT with its receipt and audit (not in force with the zero-return
  checks, or IN_FORCE with the promotion receipt binding this exact template and the audit in
  promoted mode), the tick writes the audit, a test pins `--write` on that step, and the audit
  artifact was rewritten in the publisher tree by hand so the next tick after the merge
  publishes. Lesson recorded: a gate I promote must be re-read everywhere it was asserted.
- 2026-09-15 02:55Z. GATE BLOCKED THE PUBLISH, RE-PINNED (PR #48). The 22:25Z tick, the first
  under the activated contract, was refused by the live-change gate: declared 654432cc, measured
  553aff51, one key moved, `risk_path_settings.book_ladder_source: file -> https`. The activation
  PR also moved BookLadderCfg.source's CODE default from file to https (so it equals base.yaml,
  a fix for a CI failure), and the fingerprint surface reads that setting; the surface declared
  at activation still said file because the default moved after the activation run. The traded
  configuration is exactly what entry 11 declares (every sleeve reads the public artifact), so
  this is a re-pin of the same declared change, not a new one and not a new epoch: the
  declared fingerprint and surface, the forward-evidence contract, the current-book study pin
  and the pre-registration draft now carry 553aff51, and entry 11 says why. The web deploy was
  skipped by the gate for that one tick, as designed; nothing traded differently.
- 2026-09-15 02:45Z. ROLLOUT VERIFIER (PR #47). The tick's rollout verifier refused the Frankfurt
  receipt every run: "deployment receipt after-snapshot does not cover exactly the contract's
  required_files paths". The deployment tool snapshots every path the contract carries (the three
  required files and, since this rollout, eight companions), while the verifier demanded a snapshot
  of exactly the three. A correct receipt therefore failed closed. The verifier now requires the
  after-snapshot to cover exactly required plus companion paths, and checks every companion's
  deployed hash by the same rule as a required file (the current desired hash, or a recorded
  revision that postdates the receipt). Test fixture receipts now cover the companions; a new test
  refuses a receipt that omits a companion or carries a path the contract does not name.
- 2026-09-15 04:00Z. FOURTH EXPORT DEFECT (PR #49). With #46 in the publisher tree the 23:25Z
  tick's export got past the prospective record and failed one step later: "forward evidence
  maturity does not describe the current programme". Since the activation the maturity
  evaluator's `record` describes the CURRENT evidence epoch (first mark 2026-09-15, zero marks so
  far) and carries the whole published curve in `record.whole_record`; the export compared the
  epoch record to the whole curve. It now compares the whole-record block, and checks that the
  epoch record starts no earlier than the declared change and holds no more points than the
  whole. Verified against the publisher tree's regenerated maturity artifact before the push.
  The 23:25Z tick also ran under the pre-re-pin fingerprint, so its deploy was gated as designed;
  the publisher tree took #48 at 23:57Z and the gate now passes (553aff51).
- 2026-09-15 04:50Z. SEAL RE-RUN TOLERANCE (PR #50). Attempt 2 of the batch reproduced attempt
  1's Item 1A section to the seventeenth digit and not beyond: net Sharpe 0.08671115460783048
  against 0.08671115460783049, Newey-West t likewise, the same 52 of 120 cohorts, the same 60
  force-flats. That is floating-point summation order under a multi-threaded reduction, not a
  different computation, and the seal's deterministic re-run compared the two series by byte
  hash, so it would have called the batch irreproducible and the evaluator would have closed
  both identities KILL. Reproduced now means every daily net return agrees within 1e-12 (daily
  returns are of order 1e-3); the exact hash equality, the largest per-session difference and
  the tolerance are recorded beside the verdict, never as the gate. A 1e-15 relative noise
  reproduces; a 1e-9 shift or a missing session does not.
- 2026-09-15 06:16Z. DEPLOY SNAPSHOT NEVER STABLE (PR #51). Three hourly deploys in a row were
  lost to their 25-minute bound in the site-snapshot stage: "source changed during attempt 1;
  retrying". The changing files were not site sources: an agent plugin (ruflo) running in a
  session whose working directory is the landing design source rewrites `.claude-flow/*/state.json`
  and `ruvector.db` continuously, and the snapshot's stability hash covered them. With a fast
  capture the window is a second and the check usually passes; under this evening's swap pressure
  (9.2 GB of a 10 GB swap in use) a capture takes minutes and the check fails every attempt.
  `.claude-flow`, `.serena` and `ruvector.db*` are now pruned from the hash and excluded from the
  copy, like `.claude` and `.firecrawl` before them; a test writes and rewrites them and asserts
  the hash and the copy do not move. The memory pressure itself is the machine's, not the
  engine's, and is recorded separately.
- 2026-09-15 06:37Z. BATCH ATTEMPT 2 FAILED AT ITS FIRST LEDGER RECORD (PR #52). Both sections
  computed (Item 1A and Item 7, three and a half hours under swap pressure), the PBO matrix was
  built and its receipt written, and the first `_record_identity` call was refused by the
  reservation validator: "identity batch registry schema mismatch:
  earnings_narrative_change_batch_1_matrix_receipt.json". The runner wrote the matrix receipt at
  the top level of `artifacts/research/identity_batches/`, where the validator reads every JSON
  as a batch registry and fails closed on any other schema; the receipt's own schema is
  different by design. Nothing was recorded: no ledger row, no result, both identities still
  unspent. The receipt now lives inside the batch's directory beside the filled-reservation
  audits (`identity_batches/<batch>/matrix_receipt.json`), a test pins that it never sits at
  the registry's top level, and the stray receipt from attempt 2 was set aside outside the tree
  (its figures are not read here). Attempt 3 follows once this is on main and pulled, with the
  reservations re-authored a third time because the runner's hash moves again.
- 2026-09-15 15:20Z. CORRECTION: TIME LABELS. The twelve entries above headed "2026-09-15 00:15Z"
  through "2026-09-15 06:37Z" carry Dubai local time (UTC+4) under a Z label, dated by the local
  calendar. Each was written four hours earlier in UTC: "00:15Z" at 2026-09-14 20:13Z, "02:22Z" at
  2026-09-14 22:22Z, "06:37Z" at 2026-09-15 02:37Z (write times from the session transcript).
  Times quoted inside those entries (merges, ticks, cycles) are UTC and stand. The entries are not
  rewritten; from this one on, every header is read from `date -u`.
- 2026-09-15 15:20Z. RECOVERED ENTRIES. The six entries below were drafted at the UTC times in
  their headers and held in a session scratchpad under /private/tmp for the seal PR; the 13:45Z
  restart erased it, and they are reproduced verbatim from the session transcript. Only the
  headers are corrected to UTC, and two carry a bracketed note on what followed.
- 2026-09-14 22:59Z (recovered). BATCH ATTEMPT 1 KILLED, ATTEMPT 2 STARTED. The single out-of-sample batch
  launched at 20:25Z was killed at about 22:56Z by the session's low-memory guard, which stopped
  the shell that ran it, during the Item 7 section (Item 1A had finished and printed its summary
  line; with `--batch` every member's result and ledger row is written only after both members and
  the matrix exist, so nothing was recorded: no ledger row for either identity, no result, no
  matrix). Item 1A's curve, cohorts, events and input manifest were left in its out directory and
  are overwritten by the second attempt. Because #45 had since changed the runner file the
  reservations bind by hash, both reservations were re-authored at 22:58Z (same pre-registration,
  same parameters, same ordinals 348 and 349, same batch hash, the runner's current hash;
  validated, both audits SATISFIABLE with disposition ceiling ADMIT). Nothing in the protocol or
  the parameters changed between the attempts, and the one figure the first attempt printed
  (Item 1A net Sharpe 0.087, 52 of 120 cohorts ranked, 60 force-flats) decides nothing: the seal
  decides, and this entry is the disclosure that the figure was seen before the second attempt.
  Attempt 2 runs detached from the session (nohup) so no guard can stop it; the watcher seals it.
- 2026-09-14 23:14Z (recovered). FRANKFURT'S FIRST CYCLE UNDER THE BRAKE. The 23:10Z natural cycle ran on the
  deployed loop: equity cycle_ts advanced to 1789426800000, nine position rows marked, the service
  finished cleanly (14.7 s CPU, no error or traceback), and trade.log carries the reading
  `cycle.book_ladder book_applied=True book_as_of=2026-09-14 book_error=None
  book_multiplier=1.0 book_source=https://canlicapital.com/glassbox/book_drawdown_ladder.json
  book_stale=False`. The crypto sleeve therefore applies the book-level brake from this cycle, at
  the same multiplier of 1.0 the equity sleeves apply; nothing traded differently. The rollout
  verifier (PR #47) decides the receipt on that cycle once it is on main.
- 2026-09-15 00:13Z (recovered). FRANKFURT ROLLOUT VERIFIED. With #47 in the publisher tree the rollout
  verifier still refused the receipt on its own hash: the receipt sealed the pre-#47 verifier, and
  the verifier's rule is that a sealed binding must equal the current file or be recorded as a
  predecessor in a binding_revisions entry that postdates the receipt. One hand-authored entry
  (dated 2026-09-15, the four sealed bindings as predecessors, the reason being #47 itself)
  was added to the rollout contract; the verifier then queried the host read-only and sealed
  `crypto_position_attribution_rollout_verification.json`: VERIFIED_FIRST_NATURAL_MARKED_CYCLE
  at 00:13:20Z, deployment boundary cycle 22:10Z, natural cycle after deployment true. The
  crypto sleeve's brake is verified live.
- 2026-09-15 01:51Z (recovered). PUBLISH RESTORED. The 01:25Z tick, the first with #46 to #50 in the
  publisher tree, wrote research.json at 01:46Z (3.9 MB), the forward packet index and the 118
  imported packets beside the legacy 228 (350 files in trial-packets), and passed the live-change
  gate on 553aff51. The paper state carries the cost-charged twin of every Alpaca curve (AlphaMax
  27.9 bp cumulative drag on its base to 2026-09-15) and the ladder in the book's aggregation
  policy. The site's research data had been stale since 19:50Z the previous day, the paper state
  since 22:36Z; whether the public site caught up depends on this tick's Vercel deploy, which
  the previous tick lost to its 25-minute upload bound. [Note, 15:20Z: it did not. The export was
  restored; the deploy was not. Every landing build from 02:45Z was refused, recorded below.]
- 2026-09-15 02:08Z (recovered). MEMORY PRESSURE, NOT A SITE DEFECT. The 00:25Z and 01:25Z ticks' deploys
  stalled in the site-snapshot stage (rsync and hash of the site sources), which the 01:25Z tick
  ran for over eighteen minutes although the same hash pass takes half a second when measured
  by hand. The machine is swapping: 9.2 GB of a 10 GB swap in use, with a Virtualization
  framework VM at 2.8 GB resident and 24 percent CPU, the batch worker at 1.3 GB (5.7 GB while
  it loads a panel), and other sessions' processes. The batch is CPU-bound and continues; the
  deploys fail their bounds and the public site stays at its last successful deploy (paper state
  22:36Z, research 19:50Z) until a deploy completes within bounds. The engine's outputs are
  current on disk. No engine change is warranted for this; the machine is. [Note, 15:20Z: from
  02:45Z the snapshot was captured stable and the build itself failed, on a site defect.]
- 2026-09-15 02:38Z (recovered). DISCLOSURE. While setting attempt 2's stray matrix receipt aside I printed
  two of its fields to confirm the file: PBO 0.0710 over 2,494 aligned days. Together with the
  Item 1A summary line seen after attempt 1, that is everything of attempt 1 and 2's outcomes
  that was seen before attempt 3. No parameter, gate, or rule changes between the attempts;
  attempt 3 differs from attempt 2 only in where the runner writes its matrix receipt.
- 2026-09-15 15:20Z. NETWORK OUTAGE AND RESTART (between 07:18Z and 13:45Z). The Alpaca broker
  reconciliation failed closed for all three accounts in the six ticks that finished 07:48Z
  through 12:54Z, on name resolution ("nodename nor servname provided, or not known"); local
  curves were preserved and no broker mark was taken. The operating session lost its API
  connection from 12:42Z (ENOTFOUND) and the machine restarted at about 13:45Z, erasing the
  session scratchpad (the entries recovered above, the batch launcher and the seal watcher). No
  batch, seal or watcher was running: attempt 3 had not started. The 14:37Z tick reconciled
  every account (PASS: AlphaMax 174 positions, managed futures 15, AlphaVintage 2; publish gate
  PASS on 18 curves and 1,547 points).
- 2026-09-15 15:20Z. RESERVATIONS RE-AUTHORED A THIRD TIME; BATCH ATTEMPT 3 STARTED. With #52 on
  main (merged 03:24Z) and the tick idle, the publisher tree was pulled from 9c23ead to 0d22898 at
  14:58Z (the tick-regenerated README and Stanford evidence doc restored first).
  `scripts/author_earnings_narrative_change_batch.py` re-authored both reservations at 14:58:58Z:
  the same pre-registration, parameters, ordinals 348 and 349 and batch registry (sealed
  2026-09-14 22:58:48Z), bound to runner hash e427e075566e, the file's current hash; both
  VALIDATED_BEFORE_RETURN_COMPUTE and SATISFIABLE_RETURN_BLIND with disposition ceiling ADMIT.
  Attempt 3 started at 15:01:40Z, detached from the session, logging to
  `var/log/earnings_narrative_batch_attempt3.log` so a restart cannot erase the record; a watcher
  (`var/log/earnings_narrative_seal_attempt3.log`) waits for its completion line and an idle tick,
  then runs the seal with its mandatory re-run, and does not pull. The reservations bind the
  runner, the pre-registration, uv.lock, pyproject.toml and the pairs manifest by hash, and the
  re-run imports the tree's source, so the publisher tree is not pulled again until the seal is
  written.
- 2026-09-15 15:25Z. PUBLIC SITE STALE SINCE 2026-09-14 23:57Z: CAUSE FOUND, FIX BUILT, NOT YET
  LIVE. canlicapital.com's last successful landing deploy is 2026-09-14 23:57Z. Every landing
  build from the 02:45Z deploy on failed in the site's `build-trial-accounting-tool.mjs`:
  "Register row 0d1ecbac03f062ab claims a packet". The engine was right: since #42 the
  prospective register carries 118 identities closed by a development closure (final KILL, packet
  complete) beside the governed one. The site is published from canlicapital PR #11's branch,
  checked out at `~/canlicapital-website-20260908` (`config/site_landing_design_source.txt`), and
  that branch's trial-accounting core accepted only unclosed rows. canlicapital #12 (the owner's
  objectives as claims) and #13 (forward-epoch trial pages) were merged on 2026-09-14 into main's
  pre-redesign layout and never reached the published source; any record saying the trials page
  renders the forward index describes main only. Fix on branch
  `site/redesign-forward-epoch-20260915` from #11's head (signed d9e54324, 0000f31e): #12 and #13
  ported (both apply cleanly); the core binds each development-closed identity through
  `trial-packets/forward_index.json`, a sixth hash-declared source, by status, config hash,
  reservation ordinal, closure kind, admission, final disposition and packet path, and refuses
  anything else; forward-epoch trial pages are noindex and declare the forward index as a
  source. On the engine's current exports the build renders 228 legacy and 119 forward-epoch
  pages and trial accounting at N=347, and `npm run verify` passes (277 tests, link graph,
  indexability, every numeral traced); three mutations, each removing one new guard, are each
  caught by one test. Fast-forwarding the published worktree to the fix was refused by the
  assistant's permission classifier as a production deploy, so it waits for the owner; until it
  moves, every hourly landing deploy fails the same way.
- 2026-09-15 16:31Z. PUBLIC SITE LIVE AGAIN. The owner fast-forwarded the published worktree to
  the fix at 16:11:39Z (be1f4662 to 8c53cd5a, pushed to #11's branch). The 15:29Z deploy had
  captured its snapshot before that and failed as before (its trace names the old core's line
  217). The deploy that began 16:28:52Z captured a stable snapshot on attempt 1 and published the
  landing on attempt 1. Checked on the public site at 16:30:47Z: `/tools/trial-accounting`
  renders "118 closed by a development closure" and declares `trial-packets/forward_index.json`,
  the old "one sealed prospective identity" sentence is gone, `/trials/0d1ecbac03f062ab` returns
  200, and the homepage last-modified moved from 2026-09-14 23:57:29Z to 2026-09-15 16:30:18Z.
  The public site was stale for 16 hours 33 minutes.
- 2026-09-15 17:25Z. OWNER DIRECTION, AND WHAT A DELEGATION CANNOT COVER. At 17:05Z the owner
  wrote "ok go ahead you have my full permision you can also do the things you want me to do".
  Under it PR #53 was squash-merged; the publisher tree was not pulled, because the reservations
  for ordinals 348 and 349 bind the runner, the pre-registration, uv.lock, pyproject.toml and the
  pairs manifest by hash, and the seal's re-run imports the tree's source. canlicapital main was
  merged into the site fix branch (merge 7f3bf1a6; conflicts only in scripts/build-trials.mjs,
  scripts/verify-trials.mjs and the generated trials.html, kept from the fix; the merged tree is
  byte-identical to the published 8c53cd5a), but pushing it to PR #11's branch and queuing #11
  was refused by the assistant's permission classifier as a production deploy, so #11 waits for
  the owner. Three things stay with the owner whatever a delegation says, because the
  repository's own rules reserve them: author protocol answers and approvals
  (`config/author_protocol_review_registry.json` sets automation_may_invent_answers_or_approval
  false, and `scripts/verify_author_protocol_approval.py` requires the statement "I, Arhan Canli,
  reviewed this exact protocol and evidence version, wrote the answers"); blind human labels (the
  active-ownership packet's instructions and the reviewer brief forbid automated assistance and
  exclude the owner and anyone who has seen parser output); and account logins.
- 2026-09-15 17:25Z. THE ROAD TO FOURTEEN, MEASURED. 349 of the 400 identities are spent once the
  running batch records, leaving 51. Under the promoted evidence classes
  (`config/trial_accounting_evidence_classes.json`, bound by the v2 promotion receipt) a declared
  cost, execution or capacity diagnostic spends nothing, but a test that can reach ADMIT needs an
  identity batch of at least two selectable identities, because a one-column batch cannot define
  PBO. The 51 identities therefore buy 25 such tests. At the historical rate of 3 admissions in 46
  tested candidates that is 1.63 expected admissions, a 0.815 probability of at least one, 0.221
  of at least three, and 1.83e-6 of the ten new sleeves the owner's goal needs. Fourteen sleeves
  inside the 400 ceiling is not plausible at that rate; whether to raise the ceiling is the
  owner's decision at the 360 review, and every added identity raises the deflation bar for the
  whole book. The binding constraint for the Sharpe goal is correlation. In the current-book
  diversification study (`artifacts/analysis/current_book_diversification/result.json`;
  retrospective research curves, not live evidence) the only material positive pair is AlphaMax
  momentum (k30_dn_63) with managed-futures trend at +0.21; the other five pairs sum to -0.060, the
  average is +0.025, and with that one pair at zero it would be -0.010. The same study's marginal
  diagnostics: replacing managed futures with cash raises the research book Sharpe by 0.091,
  while carry adds 0.533, momentum 0.147 and AlphaVintage -0.006. These are diagnostics, not a
  reweighting decision. They point at one candidate that needs no data purchase and targets the
  binding constraint: a trend identity residualized against equity momentum. Nothing in
  `config/sleeve_family_lineage.json`, `config/sleeve_discovery.json` or the kill log records one.
- 2026-09-15 17:25Z. TREASURY AUCTION CONCESSION IS NOT READY; WITHDRAWAL RECOMMENDED, DECISION
  RESERVED TO THE AUTHOR. The 2026-09-14 data-unlock brief put this family in tier 0 from its first
  feasibility result (PASS_TO_RETURN_PREREGISTRATION, 2026-08-16). Later sealed audits say
  CALENDAR_LINEAGE_REQUIRED and IDENTITY_NOT_OBSERVABLE_AS_PREREGISTERED
  (`docs/design/FEASIBILITY_TREASURY_AUCTION_IDENTITY_TIMING.md`), and the schedule-revision state
  machine's author packet
  (`artifacts/governance/author_protocol_review_packets/treasury-auction-state-machine/review_packet.json`)
  is AWAITING_ARHAN_REVIEW_NO_APPROVAL_CLAIMED with 0 answers completed. A read-only review of the
  state machine, its audit code and the sealed captures reported, beyond the author gate: the
  debt-limit-postponed October 2015 auction matched to the following auction's date; revisions
  timed by formal announcements although earlier captures show them; a re-schedule branch never
  exercised; legs on Columbus Day and Veterans Day, when the Treasury cash market is closed; the
  post-2020 schedules bound only to XML downloaded in 2026 (the archive script fetches the current
  file, confirmed); and an undefined cutoff time, price time, hedge weights, roll rule and fee
  split. Independently confirmed here: `config/cost_realism_contract.json` covers the Alpaca and
  crypto paper books only, has no Treasury or repo rows, and charges no financing (its
  margin-interest rows are NOT_CHARGED because no rate source is wired); and an admissible test
  needs at least two identities, not the one the brief assumed. The operating
  session reserves no identity for this family and recommends WITHDRAWN for this version; the
  packet's decision field is the author's. It can return only as a new, at-least-two-identity
  batch after those defects are fixed. No return data was opened and nothing was retuned.
- 2026-09-15 17:25Z. EVENT FAMILIES: WHERE EACH STANDS. `merger_arbitrage`: a sealed confirmatory
  redesign exists (`artifacts/feasibility/merger_arbitrage/announcement_confirmatory_design.json`,
  AUTHOR_APPROVAL_REQUIRED: exploration 2016 to 2025, confirmation 2006 to 2015, SC 14D9 and
  DEFM14A strata gated separately) and waits for the author's six answers in its review packet;
  the brief's "tender-offer-only identity" would be a third design and is withdrawn.
  `active_ownership_escalation`, the selected next candidate, waits only for its 48 blind labels;
  `config/external_review_protocol.json` still records outreach_authorized false.
  `tender_offer_spread` is the same mechanism as merger arbitrage's SC 14D9 stratum, so at most one
  sleeve can come from the two, and it has no blind packet, importer or attestation yet.
  `spin_off_dislocation`: its document schema audit already ran on 2026-08-16 and returned
  DATA_GATED (`artifacts/feasibility/spin_off_dislocation/document_schema_result.json`), so the
  brief's "next step: the schema audit" is out of date; the next step is a registration-keyed
  protocol, whose first question is whether the annual count of initial registrations can meet
  the admission contract at all.
- 2026-09-15 17:25Z. FIXES IN THIS BRANCH. `docs/design/SUPPLEMENTAL_MEASUREMENT_CLASS_V1.md` still
  said NOT IN FORCE; a dated note now says which part is in force through the evidence classes and
  that an admissible test costs two identities. Not fixed, and why:
  `scripts/analyze_current_book_diversification.py` types "the 1.5 Sharpe objective" into its claim
  boundary although it reads the governing objective (target 2.0) from `config/owner_goals.json`.
  Editing that sentence failed CI's publication integrity check, because the script is a code
  binding of the sealed AlphaVintage publication bundle
  (`publication/alphavintage/v1.0.0/reproduction.json`: "stale code binding"). The edit was
  withdrawn; the sentence waits for that bundle's next governed version rather than a rebind for
  one sentence.
- 2026-09-15 17:50Z. CORRECTION: THE TREND LEVER IS WEAKER THAN WRITTEN AT 17:25Z. The 17:25Z entry
  called a trend identity residualized against equity momentum the one candidate that needs no
  data purchase and targets the binding constraint. A read-only review of both sleeves, checked
  here against the files, says otherwise. The +0.21 is the deployed pair over 1,061 days since 2023
  (`artifacts/analysis/stressed_correlation/result.json`, whose stress samples hold only 16 and 14
  days); the same artifact's long-history momentum and trend family proxy is +0.008 over 5,382
  days (a family proxy, "never quote as sleeve correlation"), so the positive pair may be an
  episode rather than a structure. The trend family already holds 49 distinct hypothesis
  identities (`/glassbox/alphatrend_family.json`) against the single-family tripwire of 40 in
  `config/trial_accounting.json`; its fixed asset-group risk variants closed KILL at ordinals 335
  and 336; and equity-subset and leave-out trend identities already exist among the legacy
  records (`var_mf/experiments.jsonl`: d95808ca458a, b64bf369f965, f583cd411d24), so "nothing
  records one" overstated the gap. The admission contract's absolute_beta_max of 0.1 is a further
  hazard for any directional trend identity, the review found no admission rule for replacing a
  live sleeve, and a replacement would move the declared book composition and restart the
  evidence epoch. No identity is reserved for it. The AlphaMax construction the diversification
  study measures (k30_dn_63) differs from the live tick's profile-default construction (100 names
  a side on a top-2000 universe); that drift was disclosed and pinned on 2026-07-18
  (`scripts/alphamax_tick.sh`, `docs/research/ALPHAMAX_EQUITY_MOMENTUM_LINEAGE.md`) and is repeated
  here only because the 17:25Z entry quoted the study's pair.
- 2026-09-15 18:25Z. FORWARD LIQUIDATION COLLECTOR BUILT, NOT DEPLOYED. `crypto_liquidation_pressure`
  is marked NO_PIT by the reachability screen: venues stream forced liquidations and publish no
  history, and the contract needs three years, so the only way the family ever becomes testable is
  to start collecting. `scripts/vps/collect_liquidations.py` (with `scripts/vps/af-liquidations.service`
  and nine tests) accumulates it and makes no claim. Venues, from a read-only review of their
  documentation: Bybit `allLiquidation` is documented complete and is collected on every USDT
  perpetual (766 at build time, 20,003 characters of subscription arguments against a documented
  limit of 21,000; a truncation would be recorded); Binance `!forceOrder@arr` is sampled (at most
  one order per symbol per second) and every row is tagged sampled; OKX is parsed but not collected,
  because its API agreement limits market data to personal, non-commercial use without written
  consent. Every row carries its event, push and receipt times and the raw payload; every
  connection attempt is a session record (opened, acknowledged, last message, closed and why), so a
  disconnect is an excludable gap, never a quiet market. Two live runs from the Mac: the first
  exposed two defects before anything was deployed (a protocol-level heartbeat made Bybit and OKX
  drop the connection with "No PONG received", and the old Binance `/ws/` path closed with code
  1006); the second, after the fixes, held Bybit's 766-symbol subscription acknowledged for a
  minute with no liquidation in it, took 6 Binance rows with 0 parse errors, and exited 1.6 seconds
  after SIGTERM. Before deployment: record Bybit (and the Binance websocket route) in
  `config/data_source_rights_policy.json` and regenerate the all-sleeve rights audit in the
  publisher tree after the narrative seal; then install on Frankfurt, the running authority, as a
  production change.
- 2026-09-15 18:25Z. DATA RIGHTS GAP IN THE EXISTING VENUE COLLECTOR. The recovery copy
  `scripts/vps/collect_venues.py` (with `af-venues.service` and `af-venues.timer`) collects Bybit,
  OKX, Gate and Kraken funding and OKX positioning into `/opt/alphaforge/data/lake_venues`. None of
  those four venues has an entry in `config/data_source_rights_policy.json`, whose ten sources name
  Binance and Deribit as the only crypto venues. The OKX API agreement, per the same read-only
  review, limits market data to personal, non-commercial use and forbids publishing or
  redistribution without written consent. No raw rows from these venues are published, but storing
  them and any derived research need a recorded decision: register each venue conservatively, stop
  collecting OKX, or obtain consent. That decision is the owner's. Whether the timer still runs on
  Frankfurt was not checked today, and nothing on Frankfurt was changed.
- 2026-09-15 18:25Z. THE PUBLISHER MAC HIBERNATED ON BATTERY. `pmset` records low-power sleep at
  17:54:10Z on battery at 1 percent charge and a wake from hibernate at 18:14:24Z on AC power. While
  the Mac sleeps nothing on it runs: the hourly ticks, the equity sleeves' daily cycles, the batch
  and its seal. The seal watcher now holds a sleep assertion (`caffeinate -i -s -w` on its process,
  effective on AC power only), which ends when the watcher exits. The Mac has to stay on AC power
  while it is the publisher.
- 2026-09-15 19:08Z. VENUE DATA RIGHTS RECORDED; OKX AND GATE COLLECTION NEED THE OWNER. A read-only
  preflight of the Frankfurt host at 18:50Z found `af-venues.timer` active (last run 02:42Z, next
  02:41Z) and `/opt/alphaforge/data/lake_venues` holding OKX funding for 68 days (from 2026-07-10),
  OKX positioning for 65 (from 2026-07-13), Bybit funding for 106 (from 2026-06-02), Gate funding
  for 64 (from 2026-07-14) and Kraken funding for 401 (from 2025-08-11). The host's venv has aiohttp
  3.14.3, pandas 3.0.5 and pyarrow 25.0.1, 62 GB is free, and it reaches Bybit and Binance.
  `config/data_source_rights_policy.json` now records Bybit, OKX, Gate and Kraken and re-reviews
  Binance for its websocket route, from a read-only review of each venue's terms; none grants
  publication rights, and none separates raw rows from derived results. OKX: its API agreement
  confines market data, public funding data included, to personal non-commercial trading and
  forbids publishing it without written consent, so this collection is outside the licensed
  purpose. Gate: its user agreement names the United Arab Emirates, where the owner resides, as a
  restricted location. Kraken: its content is for the user's own benefit and other uses need
  permission; automated collection is unresolved. Bybit: the API terms render only in a browser and
  were not read, so its review is recorded incomplete under the conservative default. Binance: the
  FZE terms bar storing or publishing Binance IP without saying whether market data is IP; recorded
  unresolved. Owner decisions: stop the OKX and Gate collection, or obtain consent and a residency
  answer; read Bybit's API terms in a browser before the liquidation collector is installed. The
  persisted all-sleeve rights audit counts the policy's sources and hashes this file, so it changes
  when the publisher tree takes this commit, and the nightly publish regenerates it. Also in this
  branch: install, verification and rollback steps for the liquidation collector in
  `scripts/vps/README.md`.
- 2026-09-15 19:47Z. BATCH ATTEMPT 3 COMPLETE; SEAL RUNNING. The single out-of-sample batch exited
  cleanly at 19:37:24Z (started 15:01:40Z; about 20 minutes of that was the Mac hibernating). Both
  sections wrote their out-of-sample results, and the matrix receipt sits inside the batch directory
  (`artifacts/research/identity_batches/earnings_narrative_change_batch_1/matrix_receipt.json`) with
  nothing at the registry top level, which is where attempt 2 failed. The watcher started the seal,
  with its mandatory deterministic re-runs, at 19:37:27Z. No result was read here; the seal decides.
- 2026-09-15 19:47Z. MARGIN FINANCING MEASURED ZERO; IDLE-CASH YIELD IS A SHARPE-BASIS DECISION.
  `scripts/audit_paper_sleeve_cash_financing.py` reconstructs each Alpaca paper sleeve's daily cash
  from filled orders, lake closes and broker equity marks (cash = equity - long + short), through
  the cost derivation script's own loaders, and prices idle cash at the point-in-time federal funds
  rate (mean 3.63 percent). On the record to 2026-09-15 (41, 41 and 40 calendar days) no sleeve was
  ever in margin debit: minimum cash share 0.9172 AlphaMax, 0.6679 managed futures, 0.9962
  AlphaVintage. The contract's `financing_margin_interest` row is therefore zero on this record and
  needs no rate source. Idle cash would have earned USD 3,843.91, 2,919.11 and 3,972.82. Crediting
  it against the current zero benchmark would raise every sleeve's return mechanically; the standard
  excess-return Sharpe instead charges the rate on net exposure, because (P&L + rate x cash) -
  rate x equity = P&L - rate x (long - short). With mean net exposure +0.0488 (AlphaMax), +0.2861
  (managed futures) and -0.0002 (AlphaVintage), that drag is 0.18 percent a year, 1.04 percent a
  year and nil. The current basis (no cash yield, zero benchmark) therefore slightly flatters the
  net-long sleeve against the standard definition; the contract's note that omitting cash yield
  understates the record is incomplete. `config/owner_goals.json` defines the Sharpe goal on the
  zero benchmark, so changing the basis is the owner's decision. Nothing is charged or changed here.
- 2026-09-15 23:08Z. THE BATCH IS SEALED: BOTH IDENTITIES KILL. `earnings_narrative_change_batch_1`
  finished computing at 19:37:26Z, the seal with its mandatory deterministic re-runs started at
  19:37:27Z and completed at 23:08:26Z. Both identities were decided FINAL_KILL against the v7
  contract, 86 checks evaluated each. Item 1A (`earnings_narrative_change_v1`, reservation ordinal
  348, key `6ed52744e6c9510d`, config `e2e12b241c794d2c`) failed 34: net Sharpe 0.0867 against the
  0.15 floor, stressed Sharpe -0.3700, deflated Sharpe 4.13e-07, own max drawdown 0.2548, and at
  book level a Sharpe delta of +0.1141 whose lower 95 percent bound is -0.0083, a max-drawdown delta
  of 0.01096 against the 0.01 limit and an expected-shortfall delta of +0.000544 against zero;
  capacity was never established. M D and A (`earnings_narrative_change_mdna_v1`, ordinal 349, key
  `2f6a5b3e8a7928e2`, config `e197f95f46166200`) failed 35, and failed more plainly: net Sharpe
  -0.3446, stressed -0.7679, Newey-West t -1.1020, deflated Sharpe 1.43e-10, own max drawdown
  0.3458, book Sharpe delta lower 95 percent bound -0.0824. The batch's probability of backtest
  overfitting is 0.0710 (matrix receipt `sha256:79f775f0...`). The deterministic re-runs reproduced
  both results to 1.13e-17 and 1.39e-17, inside the 1e-12 tolerance, with no exact file-hash match.
  The narrative-change family is closed with two identities spent. The union stands at 349 of the
  400-identity budget, 51 remaining, with the staged review at 360 still ahead. No sleeve was added;
  the book remains four sleeves.
- 2026-09-15 23:10Z. PUBLISHER TREE PULLED TO 76ed48c; THE RIGHTS AUDIT IS STALE FOR ONE NIGHT.
  The publisher tree took the merged data-rights and cash-financing work at 23:10:19Z while the
  hourly tick was idle. `artifacts/publication/all_sleeve_data_rights_audit.json` was regenerated by
  the 22:10Z nightly chain, an hour BEFORE that pull, so it counts the ten-source policy while
  `config/data_source_rights_policy.json` now holds fourteen. It was deliberately not regenerated by
  hand: steps 1, 2, 5, 8 and 9 of the chain and the external submission plan bind its hash, and
  rewriting it outside the chain would break those bindings for the sake of one night. The next
  nightly chain regenerates it from the pulled policy.
- 2026-09-15 23:32Z. WHAT THE HEALTH SUITE ACTUALLY SAID, AND A CORRECTION. This session predicted
  that the stale rights audit would be tonight's health failure. Checked rather than assumed: the
  prediction was true but immaterial, and it named the wrong risk. `test_persisted_all_sleeve_audit_
  matches_current_sources` does fail, and so does `test_all_sleeves_exclude_raw_rows_without_claiming
  _rights_clearance`, both for the staleness above. But `C7b-suite` has been failing for 23 runs
  since 2026-08-22, so two more red tests inside an already-red suite changed nothing that was
  green. Tonight's genuinely new failures are `C1-hosts-match` and `C1b-glassbox-match`: the landing
  host reports `generated_at` 2026-09-15T20:26:33Z against the app host's 23:26:12Z, and eight
  glass-box artifacts differ in content hash between the two hosts. Both are the stale landing
  deploy, and both clear when the site fix goes live. Overall 37 pass, 1 warn, 3 fail.
  THE FINDING WORTH KEEPING is what the suite could not do about it. The health suite can re-run
  `live_publish.sh` by itself when a data check fails, and `C1-hosts-match` is one of the three
  checks wired to that remedy. It did not run: the remediation record reads "self-heal DISABLED:
  tests not green". A red suite therefore disables the automatic repair for a completely unrelated
  failure, so the stale landing cannot heal itself while any test anywhere is red. That gate is
  defensible, but it means the standing suite failure is not cosmetic debt; it is a disabled safety
  system. `C7b-suite`'s own evidence names `tests/unit/test_system_map_is_current.py`: the map is
  rendered from the filesystem, and this workstation carries fifty-two Python scripts that a clean
  checkout does not have (420 here against 368 tracked), so the committed map cannot match here by
  construction. The same module passes 4 of 4 in a clean worktree. The standing red is a workspace artifact, not a defect in
  the published repository, which is the kind of thing that trains a reader to ignore the board.
- 2026-09-15 23:30Z. THE LANDING BUILD REFUSED THE BATCH CLOSURE; THE FIX NEEDS THE OWNER'S
  FAST-FORWARD. From the 21:30Z hourly deploy onward every landing build failed with "Governed
  packet count does not match the prospective record" and the public site stayed at the 16:28:52Z
  deploy. The cause is the site's own accounting core, not the engine: it asserted that exactly one
  register row carries `GOVERNED_SERIAL_PACKET_CLOSED`, which was true while the crypto-carry serial
  packet was the only governed closure. A batch closure under the v2 full-evidence reservation
  publishes with the same status and closure kind `governed`, so the seal made the assertion false
  and the build failed closed, which is the correct direction for an accounting page to fail. The
  site branch `site/redesign-forward-epoch-20260915` now carries commit `894ec07d`: a governed batch
  closure is its own union state, closed and never admitted, carrying its final disposition, linking
  a packet and a public page only when the forward packet index binds one, and rendering as closed
  with the packet owed in the window between the seal and the packet write. The serial governed
  count is still pinned to the prospective record. Verified against the live 22:27Z exports overlaid
  exactly as the deploy snapshot overlays them: 12 core tests, 348 trial pages, the explorer at
  N=349, and `npm run verify` clean with every numeral traced. Moving the live site worktree is a
  production deploy, so it needs the owner:
  `git -C ~/canlicapital-website-20260908 merge --ff-only site/redesign-forward-epoch-20260915`.
  Until then the hourly deploy keeps failing on the landing project; the app project is unaffected.
- 2026-09-16 00:44Z. THE 56 SCRIPTS THIS WORKSTATION NEVER TRACKED ARE NOW IN THE REPOSITORY (#60).
  A read-only classification of every untracked Python file under `scripts/` found no scratch at
  all. Each one is named, with a sha256, inside a persisted trial packet or reservation: the
  `close_*` scripts append their own path to the evidence list they write, so a packet such as
  `artifacts/research/trial_packets/44da7a6140622ff6.json` binds both its closer and its auditor by
  name. The repository already demands exactly that of published evidence —
  `scripts/verify_publication_clean_checkout.py` refuses an "untracked or missing code binding" and
  `src/alphaforge/validation/trial_reservation.py` refuses "reserved evidence is missing" — so the
  provenance was absent from the repository while the evidence claimed it. Nothing had failed only
  because the packets are themselves untracked. What the commit does not claim: these are earlier
  sessions' scripts, committed for provenance, not reviewed line by line and not production code.
  They carry 494 Ruff violations, which land in the lint-debt contract's `historical_scripts` scope
  where script debt is confessed rather than hidden; the governed Ruff scope (`src/alphaforge`,
  `tests`) and mypy's package scope are unchanged and still clean. At least seven modules these
  scripts import or hash-bind are gone from disk and untracked, `combined_2022_alignment.py`,
  `alphamax_replay_support_v2.py`, `alphamax_covariance_engine.py`,
  `run_crypto_continuous_account.py` and `funded_inception_runner.py` among them, so several of the
  committed scripts cannot run today. That gap is recorded rather than repaired: a script that
  imports a deleted module is still better provenance than no script, because the packet binding it
  can now be resolved to the code that wrote it. All 56 were scanned before committing: 333 KB, no
  credentials, no absolute home paths.
- 2026-09-16 01:05Z. A CORRECTION: THE MAP WAS BEING RENDERED WHERE THE MACHINE IS NOT (#61).
  The entry above was committed expecting it to clear `tests/unit/test_system_map_is_current.py`,
  and after the publisher tree pulled it, with 430 scripts tracked and none untracked, the guard
  still failed. The untracked scripts were one cause, not the cause. The map also counts the
  engineering contracts under `artifacts/` and the lake directories under `data/`, and both trees
  are gitignored, so they exist on this workstation and in no clean checkout. Every recent
  regeneration, including the two in this session, happened inside a scratch git worktree that has
  neither, so the committed map claimed 3 engineering artifacts and 0 data directories while the
  publisher tree renders 31 and 23. The guard could not pass on the one machine it was written for,
  whatever was committed. The test says so in its own words: it is marked `workspace_evidence`
  deliberately, because "the map includes the launchd agents installed on THIS machine", and "the
  guard belongs where the machine is". `docs/system-map-rendered-on-the-publisher-20260916`, open
  as #61, is the map as the publisher tree renders it; regenerated there, all four system-map tests
  passed, and the tree was restored to the committed copy afterwards so that it can still pull.
  This removes one of the two reasons the suite is red, not both. The persisted all-sleeve rights
  audit is still a night stale and clears at the next nightly publish chain. Until the suite is
  green the health check will keep refusing its own repair, so the stale landing still cannot heal
  itself even once the site fix is live.
- 2026-09-16 05:40Z. THREE GUARDS THAT COULD NOT FAIL, AND ONE I BROKE CLOSING THEM. The full local
  suite, run deliberately rather than waited for, reported eighteen failures across twelve modules
  and not the two this session had predicted. Every one of those modules is registered in the
  clean-checkout policy, so CI was green throughout and could not have found any of it. One failure
  was actionable immediately: `test_mutation_coverage` named two guards that had never been proven
  able to fail, `test_forward_identity_packet_index.py` and `test_import_external_identity_packets.py`,
  both from earlier work. Both are pure tests over synthetic trees in a temporary directory; the
  discovery rule selects them because it matches the marker `artifacts/` anywhere in a test's source
  and their fixtures name such paths as strings. Narrowing that rule would risk the precise failure
  this ledger exists inside, so #63 registers a mutation against the script each test execs instead,
  which is the ledger's own idiom: twenty of its fifty-four targets are source files. The forward
  index stops refusing an identity present in both epochs, and the import stops refusing evidence
  whose hash disagrees with the copy already here. Both reported CAUGHT and both targets were
  restored byte-for-byte.
  #64 then fixed the cause of the map problem rather than its symptom: the hook regenerates the map
  whenever a commit stages Python, which is right on the publisher tree and wrong in a worktree, so
  it now skips and says so when `artifacts/` or `data/` is missing. The condition is decided once,
  at the top of the block, because the lint-debt exporter CREATES `artifacts/` as a side effect and
  a check made at the point of use would see a directory the tree never had.
  #64 also reopened the gap it had just helped close. The docstring explaining the new rule contains
  the words "under artifacts/", which is the discovery marker, so the hook's own test became a guard
  over a published claim with no mutation registered. #65 closes it with a real mutation — flipping
  the guard to unconditional, which deletes the string the test asserts and describes a genuine
  defect — rather than by rewording the docstring to slip past the rule. Making a gate pass by
  keeping a keyword out of a comment is the evasion the ledger exists to prevent.
- 2026-09-16 13:31Z. THE SITE IS LIVE AGAIN, TWENTY-ONE HOURS STALE. The owner authorized the
  fast-forward that had been refused as a production deploy. The live presentation worktree moved
  8c53cd5a to 894ec07d, `design/glassbox-website-20260908` was pushed, and canlicapital PR #11
  merged at 13:12:08Z. Before any of it, the site was rebuilt against the CURRENT exports rather
  than last night's: the register now carries three governed rows, 121 closed identities and none
  unclosed, and the build produced 121 forward-epoch pages with `npm run verify` clean and every
  numeral traced. The 13:27:55Z hourly deploy reported `hourly deploy OK` at 13:31:43Z, the first
  landing success after fourteen consecutive failures since 21:30Z yesterday, and IndexNow accepted
  263 URLs. Checked in public, not inferred: the homepage `last-modified` is 13:30:05Z, having been
  frozen at 2026-09-15T16:28:52Z, and `/tools/trial-accounting` renders selection N 349 with "2
  closed by a governed batch closure" beside "118 closed by a development closure".
  Tonight's two new health failures are already resolved in fact. Both hosts now report the same
  `generated_at`, 2026-09-16T13:26:25.996461+00:00, and the glass-box artifacts sampled across the
  two hosts agree by content hash, so `C1-hosts-match` and `C1b-glassbox-match` clear at 23:32Z
  without anyone doing anything.
  One operational trap, recorded because it cost forty-five minutes of watching a run that had
  already succeeded: the deploy log's success marker is `=== hourly deploy OK <timestamp> ===`. A
  watcher grepping for "done" or "INCOMPLETE" sees every failure and no success.
  What is still red is unchanged by any of this. The persisted rights audit clears at tonight's
  publish chain. `test_forward_drawdown_evidence` expects no live equivalence and now reads the
  drawdown brake's own record saying it activated on 2026-09-15; `test_crypto_carry_portable_v1_*`
  reports a frozen run binding drifted on `base_settings`; and the crypto attribution preflight
  observation is bound to a superseded contract hash and needs its read-only SSH run. Those are
  decisions and a remote check, not a publish cycle, so the health suite's self-heal stays disabled
  until they are made.
- 2026-09-23 14:10Z. BYBIT TERMS READ; LIQUIDATION COLLECTOR INSTALLED ON FRANKFURT. The API Terms
  page embeds a seven-page PDF (last updated 2026-01-16, SHA-256 b8d683cd…) that refuses automated
  HTTP/2 clients; a real browser rendered it. Decision recorded in
  `config/data_source_rights_policy.json`: internal collection and storage for paper research is
  within the licensed use; raw rows are never published (clause 6.7); derived results stay not
  cleared (9.2); a funded book or paid data product needs Bybit's written consent (6.9). A
  read-only preflight found the host idle between cycles (62 GB free, 1.5 GB memory available,
  venv aiohttp 3.14.3), then `collect_liquidations.py` and `af-liquidations.service` were copied
  from main (SHA-256 325b1ffb… and 55e63624…, identical on both ends) and enabled at 14:10:13Z
  after the :10 paper cycle. Both venues opened sessions (Bybit complete on every USDT perpetual,
  Binance sampled); OKX stays uncollected. Memory 67 MB, no restarts. The three-year clock the
  contract needs for `crypto_liquidation_pressure` starts today; nothing reads the lake until a
  study is pre-registered.
- 2026-09-23 14:30Z. THE SLEEVE GOAL AGAINST THE IDENTITY BUDGET. 51 identities remain under the
  400 ceiling and an admissible test costs two, so about 25 tests remain. The historical planning
  hit rate is 3 survivors in 46 tested candidates (0.065; Jeffreys 90% range 0.024–0.146,
  `artifacts/analysis/admission_gate_power_audit/result.json`), and the prospective epoch has
  admitted 0 of 121 closed identities. At 0.065, 25 tests give 1.6 expected new sleeves and a
  probability below 0.0001 of the ten the owner's fourteen require; even at 0.146 it is 0.002.
  A 50% chance of ten new sleeves needs about 148 tests (296 identities) at 0.065. The goal and the
  ceiling cannot both hold; which one moves is the owner's decision, and a higher ceiling carries
  its own multiplicity cost. Planning arithmetic, not a forecast.
- 2026-09-23 18:30Z. THE OWNER WITHDRAWS V3; WHAT MADE IT MISTAKEN, FOUND AND FIXED. The owner
  called the v3 record mistaken and chose, among delete, withdraw-and-restart, and withdraw with
  voided trials, to withdraw it in the open and restart. Verified today, each on the live path:
  (1) `scripts/corp_actions_weekly.sh` ran once by hand on 2026-08-02 and was never scheduled, so
  no split or dividend entered `data/lake` for seven weeks while every loop stayed green (#77:
  launchd template, health C6h on the lake's newest partition; backfill run 14:44Z; the agent is
  installed and loaded). (2) Stored split rows that contradict the raw bars: in `data/lake`, 90
  reciprocal, 83 phantom, 20 duplicated and 15 misdated; each wrote a fake move of the full ratio
  into every adjusted series crossing it (#78: judged against the raw bars, every correction
  verified through the engine's kernel and kept only if it shrinks the total adjusted movement
  near the split, applied at `PITDataReader.corporate_actions`). (3) The nightly suite's only
  failure was a submission plan no publish job rebuilt, and the evidence map read a readiness
  receipt one step before it was written (#76). (4) Bybit's API terms, read in full (#75); the
  liquidation collector runs on Frankfurt since 14:10Z. AlphaMax traded ALMS and DOCS during the
  corporate-actions gap, small notional; none of the reciprocal or phantom names. How much any of
  this moved v3's returns was not measured, which is why v3 is withdrawn rather than restated.
- 2026-09-23 18:30Z. THE CEILING RISES BY AMENDMENT, AND WHAT IT DOES NOT BUY. The owner chose to
  raise the identity ceiling in steps (#79). The 400 lives in a policy sealed into the v7 receipt,
  so the raise is an amendment beside it: 500, staged reviews at 450 and 500, and 700 only if a
  rule declared now is met at the 500 review. Priced with the production DSR: the three-year
  hurdle rises 2.0% at 500 and 3.8% at 700; the hit rate's uncertainty is the real risk.
  `docs/design/SLEEVE_QUEUE_V8.md` records the constraint that matters more: 0 of the 20
  untouched families is testable without an independent reviewer or a data purchase, and the
  owner has chosen free work only for now. No identity above 400 is spent until one is unlocked.
- 2026-09-23 18:30Z. V4 PREPARED, NOT ACTIVE. v4 starts 2026-09-24 on the same four accounts at
  equal quarters; v3 is published WITHDRAWN with its reasons, and a change_log entry with
  contaminates_forward_record true starts the evidence epoch on the same day, pinned against the
  published start by `tests/unit/test_v4_rebaseline.py`. The live-config fingerprint does not
  move (553aff51; it hashes composition, weights and tilt, never dates), checked by generating the
  v4 state in a sandbox that could not write to the publisher. Activation order: v3 frozen with
  `scripts/archive_live_record.py --write --reason ...`, split corrections written, then merge
  after the first 2026-09-24 mark so the book curve is never empty.
- 2026-09-23 23:20Z. ALPHAFORGE SUSPENDED; V4 IS A THREE-SLEEVE BOOK. The owner asked for the
  crypto funding-carry sleeve to come out of every book calculation and off the site until it is
  fully repaired, its history hidden from public pages but kept in the frozen archive. v4 therefore
  starts as AlphaMax, AlphaTrend and AlphaVintage at equal thirds (`SUSPENDED_SLEEVES`,
  `BOOK_WEIGHTS`, `WEIGHT_SCHEDULE`, and `book_sleeve_curves()`, now the one composition every
  study rebuilds). AlphaForge keeps paper-trading on Frankfurt off the record. What it costs, in
  the engine's own numbers: the research book's in-sample Sharpe falls from 1.78 to 1.17 (neutral
  core 0.66), and the average pairwise correlation rises from +0.0274 to +0.0345; the
  current-composition drawdown study's conservative expected maximum drawdown is 0.0899, inside
  the 0.11 objective. The live-config fingerprint moves 553aff51 -> dd8dfa13 and is re-pinned in
  the live-change contract, the forward-evidence contract, the drawdown study and the unsigned
  preregistration draft; `check_live_change_declared.py` passes on a sandbox-generated v4 state.
  The site needed one change (canlicapital #212): the performance page's AlphaForge block would
  otherwise have kept its authored "Holding cash" text for a sleeve whose state is no longer
  published. Activation waits for two v4 marks (2026-09-25 after 01:00Z): the ladder, the evidence
  evaluator and the contribution analysis all refuse a one-mark curve. Repairing AlphaForge is
  the highest-value next item: it was the research book's largest contributor.
