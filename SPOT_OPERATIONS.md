# Spot restart operations

The restart is not activated. These commands inspect local state or reconcile an
existing decision; neither can place an order or start a new account epoch.
Run from this worktree with its Python environment and `PYTHONPATH=src`.

```sh
PYTHONPATH=src /Users/arhancanli/alphaforge/.venv/bin/python scripts/operate_alphaforge_spot.py status --journal /absolute/path/to/spot.sqlite
```

Status opens an existing database read-only and reports the latest 100 decisions
plus counts over all decisions. It does not create a missing journal or migrate an
unrecognized schema. An unacknowledged attempt is potentially transmitted, even
if the process crashed before receiving a response. Terminal status means local
evidence was recorded; it does not reverify broker balances or late corrections.

For explicit recovery of a sealed decision, use the exact account binding, epoch
and decision timestamp reported by status, with a fixed UTC activity cutoff:

```sh
PYTHONPATH=src /Users/arhancanli/alphaforge/.venv/bin/python scripts/operate_alphaforge_spot.py recover --journal /absolute/path/to/spot.sqlite --account-binding ACCOUNT_DIGEST --epoch EPOCH --decision-ms DECISION_MS --until 2026-09-11T12:00:00Z
```

The cutoff above is illustrative; choose a valid elapsed window for the actual
decision. Credentials are loaded only from
`~/.config/alphaforge/alpaca_spot.env`, never from the managed-futures account.
Recovery permanently stops further submissions for the batch, reads authenticated
broker evidence, and updates local terminal evidence only if conservation checks
pass. Fees may post later; incomplete evidence must be retried with an appropriate
later cutoff. Missing broker orders never authorize resend.

A missing baseline requires separate explicit recovery analysis; this command
does not fabricate one. Malformed or unavailable state returns exit code 2 with
`OPERATION_BLOCKED`; no decision clearance is implied. The source-bound readiness
provider, verified history and installed scheduler remain unfinished.

## Daily history collection

The preparation API supports `histories=None` with a `history_receipt_path`. It
collects 200 completed daily closes from Alpaca US hourly bars and persists a
receipt before reserving any plan. Use a new receipt filename per observation;
existing files are never overwritten. This API does not grant submission
permission. Source/account routing, calibrated clock checks and evidence-bound
runtime readiness still need verification before activation.

## Current activation blockers

The dedicated credential file is not present. Configure
`~/.config/alphaforge/alpaca_spot.env` with the dedicated paper account's
`APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, and
`APCA_API_BASE_URL=https://paper-api.alpaca.markets`. Keep credentials out of chat.

Current host-clock measurements fail the 50 ms offset / 100 ms uncertainty
policy. Resolve automatic time synchronization during appropriate maintenance
for existing scheduled paper jobs; do not step their clock casually. The new
submission gate uses `/usr/bin/sntp -t 3 -n 1 time.apple.com` only to observe
time. This command does not adjust the clock. A fresh passing observation and
the remaining account, research and service checks are required before activation.
