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
