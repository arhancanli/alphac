# Point-in-time market-status and outage replay

AlphaForge can now replay explicit venue and instrument market-status intervals inside the
event-driven backtester. This is engineering evidence, not historical outage coverage or return
evidence. No market returns were opened and no hypothesis was spent.

## Enforced behavior

- Every enabled fill attempt requires explicit point-in-time status coverage.
- Instrument-specific status overrides venue-wide status.
- Future-known records and overlapping intervals within one scope fail closed.
- `HALTED`, `OUTAGE`, and `AUCTION_ONLY` block execution even if an OHLCV bar exists.
- `CLOSE_ONLY` blocks risk increases while permitting reduce-only orders, including recall covers.
- Blocks are labeled and counted; no synthetic fill is substituted.
- With no status provider, the existing compatibility path and golden master are unchanged.

## Deliberate boundary

The platform does not yet ingest and reconcile historical exchange-status feeds, model auction
price formation or queue position, preserve resting orders across outages, route across venues,
or poll and reconcile live exchange status. Explicit replay prevents impossible fills only when
coverage is supplied.

The machine-readable contract is available at
[`/glassbox/market_status_contract.json`](/glassbox/market_status_contract.json).
