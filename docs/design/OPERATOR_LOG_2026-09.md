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
