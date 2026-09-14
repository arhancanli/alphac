# Positive confirmed targets: implementation phase

Distinct from rejected cost-threshold cash retention (trial231). Added opt-in strategy using the existing post-sizing hook; no production defaults changed. Positive weights retain their sizes, negative weights become zero, and stored risk targets and audits receive the mask. Direction confirmation continues unchanged.

Tests exercise the real synthetic-price/raw-execution engine with actual rejected negative targets, saved risk weights, signal/settings bindings and cadence. No historical candidate returns measured, no trial reservation yet; union remains256. The frozen specification requires matched primary/stress standalone replays followed by registered combined comparisons.
