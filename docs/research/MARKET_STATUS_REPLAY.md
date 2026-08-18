# Point-in-time market-status and outage replay

AlphaForge can now replay explicit venue and instrument market-status intervals inside the
event-driven backtester. This is engineering evidence, not historical outage coverage or return
evidence. No market returns were opened and no hypothesis was spent.

## Enforced behavior

- Enabling status replay triggers a pre-run proof of explicit point-in-time coverage for every
  instrument and every millisecond in the complete backtest interval, before bars are read.
- Instrument-specific status overrides venue-wide status.
- Future-known records and overlapping intervals within one scope fail closed.
- `HALTED`, `OUTAGE`, and `AUCTION_ONLY` block execution even if an OHLCV bar exists.
- `CLOSE_ONLY` blocks risk increases while permitting reduce-only orders, including recall covers.
- Blocks are labeled and counted; no synthetic fill is substituted.
- With no status provider, the existing compatibility path and golden master are unchanged.

## Reviewed ingestion and source lineage

The ingestion boundary accepts strict normalized manifests only when the supplied raw source bytes
match the declared SHA-256 digest. It records source publication, event observation, historical
availability, local capture, and review as separate timestamps rather than collapsing them into a
single misleading date. Unknown fields, impossible timestamp order, digest mismatch, duplicate or
relabeled source identities, non-HTTPS URLs, and future-known use fail closed.

A source row remains visible with one reviewer but cannot qualify for replay. Exact reconciliation
requires dual-reviewed official-exchange and vendor observations with distinct source identities
and bytes. Status, venue/instrument scope, and the complete effective interval must agree. The
reconciled event uses the later observation and availability timestamps, preserving the more
conservative point-in-time boundary.

## Coverage preflight

Before a run relies on status replay, the coverage auditor requires explicit half-open intervals
for each canonical instrument. It accepts reconciled events only and sweeps every effective and
availability boundary. Instrument-specific status retains precedence over venue-wide status. If a
specific event was effective but not yet available, that interval is labeled
`status_not_yet_available`; the auditor does not fall back to a venue-wide OPEN event. If no event
is effective, the interval is labeled `no_effective_status`. Source silence never means OPEN.

Covered segments retain the reconciliation content hash and both source keys. Missing and covered
durations must sum exactly to required milliseconds, and the complete audit is deterministically
content-hashed. This proves completeness only for the explicit requirements and reconciliations in
that artifact; it is not evidence that a broad historical corpus exists.

The source-reconciled provider refuses construction when its declared corpus has gaps and reruns
the audit against the exact instruments and `[start, end)` requested by the engine. A run outside
the reviewed evidence fails before data loading or strategy execution. Passing reviewed runs retain
the deterministic coverage-audit hash in their configuration; synthetic providers must still prove
complete intervals but cannot claim source-reviewed lineage.

## Deliberate boundary

The platform does not bundle a content-verified historical status corpus, production exchange or
vendor adapter, automated source capture, or empirical broad-market coverage evidence. It also
does not model auction price formation or queue position, preserve resting orders across outages,
route across venues, or poll and reconcile live exchange status. Reviewed ingestion, coverage
preflight, and explicit replay prevent impossible fills only when qualified coverage is supplied;
they do not prove that broad coverage exists.

The machine-readable contract is available at
[`/glassbox/market_status_contract.json`](/glassbox/market_status_contract.json).
