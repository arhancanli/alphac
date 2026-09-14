# Macro refresh: staging-only integration

Integrated with owner approval on 10 September 2026. This is evidence-reliability
work, not a strategy change, data promotion or new performance result.

## Scheduled behavior

The existing `scripts/macro_vintage_tick.sh` now calls
`scripts/stage_macro_vintage_refresh.py`. Its launchd schedule was not edited,
reloaded or triggered. At integration the job was idle, with its previous exit 1.
The next scheduled invocation uses the edited script.

Each invocation downloads into a unique directory under
`artifacts/macro_refresh_candidates/`, with build logs, full file hashes and
`report.json`. Public-download retries are bounded to three attempts, with
one- and two-second backoffs; the builder subprocess has a 900-second timeout.

- `READY_FOR_REVIEW_NOT_PROMOTED` means the required files and metadata hashes
  passed and all seven vintage tables preserved existing cells, including blanks.
- `QUARANTINED` means acquisition, completeness, history comparison or source
  stability failed. The candidate remains available for diagnosis.
- Neither status promotes files, updates production arrivals, refreshes the active
  lake, changes signals, submits orders or establishes active-data freshness.

Candidate observation timestamps are not production arrival timestamps. Do not
use a staging exit 0 as an active-lake freshness check. Until separately approved
promotion is implemented and performed, consumers continue using the existing
lake and its existing timestamps. A ready candidate still needs source, schema,
freshness and downstream review; it is not comprehensive economic validation.

No retention deletion is automated. Candidate storage can grow and needs review.
The legacy `refresh_macro_vintage.py` remains unchanged and is **not scheduled**;
its default in-place refresh is unsafe on partial failure and must not be used
as a recovery shortcut. Its `--check` mode remains read-only. Direct builder
invocation against the active lake is likewise outside this workflow.

## Receipt correction

Only `validate_published` in the CPI receipt script changed. Later workbooks
added 333 blank historical-vintage cells per CPI series outside the observation
range sealed in the original receipt. The archived-workbook diagnosis found no
changed existing values or removed keys.

Validation uses the original sealed observation range, excludes only blank
extensions outside it, and still requires the original row count and exact
content hash. Populated extensions, modified values, removed original blanks,
duplicate identities and missing identity dates fail. Receipts without range
metadata retain the original strict comparison.

The receipt, portable fetcher and sealing/build routine were not changed.

## Verification

The focused suite passed **32 tests in 12.53 seconds**, including an explicitly
enabled archived-workbook replay for all seven macro series. Network access was
forbidden in these tests; daily and reference CSV inputs were synthetic.
Replay copies only the seven source long tables to temporary storage and writes
all test outputs there. This is not a fresh acquisition or independent replication.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -o addopts= -q \
  -p no:cacheprovider tests/unit/test_macro_corrections.py \
  tests/unit/test_alphavintage_rtdsm_portable_fetch.py
```

The archived replay is opt-in using `ALPHAC_MACRO_REPLAY_ARCHIVE`, pointing to
a known matching seven-workbook archive. Without it, that one test is skipped.
The integration replay used the preserved isolated-review archive at
`/Users/arhancanli/alphac-macro-review.xabapR/evidence/latest-raw`.

An initial integration test run caught an incorrectly placed patch; it was
corrected before final verification. Final diff inspection confirms the sealing
routine is unchanged. Shell syntax and diff whitespace checks passed. The
read-only published-receipt validator returned
`PASS_PUBLIC_MACRO_COMPONENT_PORTABLE`.

Before/after SHA-256 checks matched for all 18 protected files: the receipt,
portable fetcher, lake metadata, production arrival log and 14 tier-2 parquets.
The full engine suite and a new network acquisition were not run.

## Permission boundary

No promotion routine is included. Review and approval are required before any
candidate replaces active data or contributes a production arrival record.
Do not restore the old unsafe scheduled refresh as an automatic rollback.
Execution-cost instrumentation, reviewer coordination, research trials, trading
changes and publication are separate phases requiring owner permission.
