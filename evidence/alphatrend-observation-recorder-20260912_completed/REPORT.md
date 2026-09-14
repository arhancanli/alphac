# AlphaTrend recorder and forward-parity check

**Recorder implemented; candidate placed on research hold.** The storage and recovery checks pass, but two strategy-semantic mismatches prevent treating the retained historical candidate as an equivalent forward runtime. No return trial or trading activation occurred.

## What works

- Captures commit before computation; decisions cannot replace earlier session records.
- Actual exchange close/next-open deadlines cover holidays and early closes.
- Late, failed and interrupted decisions remain explicit; no zero-return backfill.
- Epoch/config binding, allocation-state continuity, serialized writers and hash chaining are tested.
- The historical journal contains 252 decision captures and 252 terminal records, all labeled REPLAY_DIAGNOSTIC.
- The full archived forecast frame reproduces exactly. Six declared calendar-transition samples match the as-of signal seam and known-history reconstruction to the stated tolerance.

## Failed availability check

Calendar samples did not necessarily coincide with blend-weight updates. A separately declared supplement tested the six latest update-grid dates, using only history through the completed signal session. All six weight vectors differed from the archived calculation. The labels enter at the next open and exit 21 sessions later; the current one-grid-step IC lag makes that final exit open available too early for a prior-close decision. This affects the shared signal weighting used by both baseline and candidate.

| Update date | Maximum weight difference | Maximum annualized mu difference | Direction changes |
| --- | ---: | ---: | ---: |
| 2026-03-18 | 0.071703 | 0.002040 | 1 |
| 2026-04-17 | 0.145683 | 0.006870 | 0 |
| 2026-05-18 | 0.168335 | 0.007930 | 1 |
| 2026-06-17 | 0.089404 | 0.004577 | 0 |
| 2026-07-20 | 0.120136 | 0.012079 | 3 |
| 2026-08-18 | 0.135208 | 0.009887 | 0 |

These are signal diagnostics, not newly measured strategy returns. The old 0.677 and double-cost 0.542 Sharpe figures must not be cited as forward-valid performance. They are preserved and not replaced or silently edited. The magnitude of any corrected performance difference is unknown until a new registered evaluation.

## Failed allocation equivalence

On the first two archived legs, 26 of 252 contexts produced different target maps. Maximum absolute target-weight difference was 0.34. The first mismatch is at the second leg entry. Research load_leg resets the rebalance schedule because the archived leg restarts flat; the continuous provider preserves its cadence. This is a model-semantics difference, not a numerical tolerance issue.

The provider path can be recovered exactly from recorded contexts and the frozen input snapshot using a fresh strategy instance. That is recovery parity within the provider path; it does not make it equivalent to the research book. Archived contexts and the engine metadata fallback are retrospective diagnostic assumptions, not verified historical instrument or receipt availability.

## Evidence and remaining work

The first harness stopped because it omitted the archived engine metadata fallback. The second stopped on the actual allocation mismatch. Both attempts are preserved; the completed harness reports mismatches rather than suppressing them. No parameter or return-result tuning was performed.

Next, freeze an explicit label-release rule that admits an IC observation only after its exit price has been received. Preserve the session-grid phase and missing-data semantics. Define continuous position and rebalance behavior instead of silently reproducing artificial flat leg resets. Test those semantics before registering any new baseline/candidate return comparison. Do not solve parity by giving the forward recorder tomorrow's open or retroactively rewriting observations.

No account, vendor entitlement, host clock or remote service was re-probed. The recorder does not authenticate provider bytes or a supplied clock attestation and is not a broker submission guard. No SHADOW_PROSPECTIVE epoch was started. A trusted producer, independent timestamp evidence and explicit readiness clearance still need implementation/verification.

[Recorder usage](../../TREND_OBSERVATION_RECORDER.md) · [Parity results](result.json) · [Weight maturity](weight_maturity_result.json) · [Research hold](candidate_hold.json)
