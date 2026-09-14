# Causal AlphaTrend parity gates

Both corrected variants pass 12 fixed timing-boundary samples and 252 uninterrupted allocation contexts each. All prefix weights and forecasts match the corresponding full-history values exactly. Live-interface forecasts match the frozen tolerance. No portfolio returns were computed in this diagnostic; IC training labels were computed as necessary to test timing.

Five new unit tests cover release timing, every synthetic prefix, missing prices and sessions, future-price perturbations, grid-anchor enforcement and cold-start/missing IC behavior. The full related suite passed 83 tests.

See `protocol.json` and `result.json` for source bindings and individual samples. These gates establish sampled correctness, not operational live readiness or universal parity across changing historical membership.
