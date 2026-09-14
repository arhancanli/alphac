# AlphaTrend observation recorder

The isolated recorder is implemented and tested. **The directional candidate is
on research hold**, because the prospective parity audit found label-availability
and rebalance-boundary mismatches. Do not activate it from the earlier Sharpe or
cost-stress results. This module is a storage primitive, not a live signal producer,
broker adapter, market-data authenticator or approved trading runtime.

`alphaforge.validation.trend_observation.TrendObservationJournal` creates a SQLite
journal bound to one candidate fingerprint and epoch. `observe` commits CAPTURE
with input evidence and prior allocation state before invoking a computation
callback. It then appends DECISION, FAILED or MISSED. The same session cannot be
retried. A process interrupted after capture must be marked missed with
`abandon_pending`; it cannot be supplied replacement outputs. `miss` records
unavailable inputs without invented prices or zero returns.

The recorder uses actual XNYS session closes and next-session market opens,
including holidays and early closes. Both capture and completion must precede the
next market open to produce a decision. SHADOW_PROSPECTIVE mode additionally
requires recent bounded clock evidence. Those timestamps and provider statements
are caller-supplied evidence, not independently authenticated by the journal.
Every receipt explicitly says execution_authorized=false.

A callback returns exactly `signals` (finite mu values or explicit nulls),
`targets` (finite proposed weights), and `allocation_state` (a JSON mapping).
Its inputs should include complete or content-bound immutable bars, vendor/source
identity, event and receive timestamps, declared cutoff, exact model version,
causal blend state, instrument metadata and allocation context. The producer must
validate these before asking the recorder to commit. An arbitrary supplied
fingerprint is not proof that a producer ran the associated code.

States continue only from the last committed decision. SQLite IMMEDIATE
transactions serialize reservations, and update/delete triggers plus a SHA256
chain detect ordinary alterations. A local administrator can still rewrite the
entire journal and checkpoint; independent prospective timestamps/disclosures
remain a separate requirement. Failed/missed observations never advance state.

The completed diagnostic journal contains 252 archived contexts and 504 events,
explicitly marked REPLAY_DIAGNOSTIC. It is not a historical forward record.
Allocation state was rebuilt from persisted CAPTURE contexts and frozen price
inputs in a fresh strategy instance. This verifies replay recovery of the
continuous provider path, not parity with the leg-reset research book.

Read-only inspection:

```sh
PYTHONPATH=src /Users/arhancanli/alphaforge/.venv/bin/python -B \
  scripts/inspect_trend_observations.py \
  evidence/alphatrend-observation-recorder-20260912_completed/replay_observations.sqlite
```

No recorder or collector was installed as a service. No new prospective epoch,
orders, strategy-return trial or public disclosure was created. Inputs still need
a trusted collection path, and recovery from missing sessions needs a declared
continuous runtime policy before use. Do not copy historical replay timestamps
into a prospective epoch.

See the [parity report](evidence/alphatrend-observation-recorder-20260912_completed/REPORT.md)
for the failed research-to-forward checks and the required correction sequence.
