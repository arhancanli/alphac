# Corrected AlphaTrend observation producer

The corrected-candidate journal and producer orchestrator are implemented. The frozen-history adapter produces exact archived signals on August 20 and 21, 2026, commits four CAPTURE/DECISION events, and reconstructs both allocation decisions exactly in a separate process. No live epoch or broker execution is activated.

## What is implemented

`CausalTrendJournal` pins candidate 59901461092dd7a6 and verifies the configuration identity and full producer binding fingerprint. It inherits the original journal's immutable event lifecycle and deadline/clock controls, leaving the older recorder and its evidence reproducible.

`CausalTrendProducer` verifies bound inputs before capture and again around computation. Signal computation occurs only after CAPTURE commits. It rejects fewer than five finite forecasts, calculates targets with a stateful allocator, and stores the completed-session count and last session. Recovery rebuilds an allocator from committed signals and input contexts and requires exact target agreement. After failed or late computations, it discards mutated allocator state and rebuilds from committed decisions. Another producer instance's committed work is recovered before proceeding. A gap after a successful decision requires an explicit new epoch; it does not silently reset the strategy.

The historical adapter runs the real corrected SignalService and BlendStrategy. It binds the frozen data, instrument store, settings and adapter sources. The two contexts deliberately use a fixed empty $100,000 diagnostic book with no simulated fills. Thus this verifies signal/target production and state reconstruction, not a broker-linked portfolio trajectory or trading performance.

## Evidence and limits

Both sampled expected-return vectors match the preserved corrected candidate exactly (maximum absolute error zero). `fresh_process_recovery.json` proves recovery in a separate OS process without replacing committed signals or appending events. Eighteen targeted tests cover candidate substitution, callback ordering, restart, failed computation, stale producer state, deadline misses, missing forecasts, session gaps and inherited journal controls.

The first diagnostic attempt is preserved in the sibling directory without `_completed`. Its adapter supplied an end cutoff only 1ms past the session label, before the feature engine considered the daily bar complete. It produced null forecasts and then failed parity comparison. The corrected adapter uses the next-session model-coordinate cutoff while excluding next-session bars, and the producer now refuses an empty decision. That diagnostic's synthetic clock is not real receipt-time or latency evidence.

The adapter remains frozen-history-only. A live feed adapter must establish actual receive-time availability, full history/adjustment consistency, source identity and a verified allocation context before activation. Callback bindings check local content consistency; they do not authenticate vendor history or independently prove publication time. The current host clock failure, latest SIP quote denial and FXE/FXY/USO shortability constraints remain as reported in the readiness evidence; no new broker checks were made here.

No new AlphaTrend return trial was measured. No orders, live observations, service deployment or account changes occurred. The next step is a separately bound live input adapter and runtime readiness validation on the intended host.
