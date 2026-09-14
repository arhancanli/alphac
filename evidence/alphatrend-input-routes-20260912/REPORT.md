# AlphaTrend separated input boundary

Implemented a diagnostic input boundary with three explicit routes:

- Feature bars expose synthetic wealth OHLC and raw volume.
- Execution bars expose raw OHLC and raw volume.
- Label requests read only raw entry/exit opens and call the guarded explicit
  holdings/dividend-receivable label implementation.

The boundary validates unique symbol/session keys, numeric finite prices, OHLC
ordering and volume. Returned views and constructor inputs are copied so caller
mutation cannot silently contaminate later routes. Feature/execution views exclude
sessions beyond their requested session cutoff. This is a session filter, not an
independent real-time availability attestation. Exact label endpoints are required;
there is no interpolation for missing entries or exits.

All 238 retained bars route exactly: synthetic features equal the synthetic
source columns, and execution prices equal the raw source columns. Seventeen
one-session checks exercised label wiring; these are accounting diagnostics, not
new strategy horizons or performance variants. The prior 119 fixed 21-session
label checks remain the economic label-validation evidence.

85 tests passed across routing, labels, release guards, price bridges, capture,
producer and journal. New tests use deliberately different raw/synthetic levels
to detect wrong routing, and check mutation isolation, cutoff filtering and bad
input rejection. Ruff and whitespace checks pass for this phase.

The boundary is not wired into FeatureEngine, SignalService or the backtest
engine. Those paths currently share a lake reader; integrating the new convention
also requires explicit split/dividend handling in raw-price execution accounting.
Passing routing tests does not establish that complete engine integration.

The [history inventory](../alphatrend-raw-inventory-20260912/REPORT.md) does not
establish the required full raw/action prefix. Candidate registration and return
testing remain pending. No new hypothesis, strategy return computation, producer
activation or broker order; union remains 238.
