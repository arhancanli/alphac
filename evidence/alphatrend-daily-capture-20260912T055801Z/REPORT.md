# AlphaTrend raw daily-input capture

One bounded GET to Alpaca SIP daily bars returned HTTP 200 and all 17 expected
ETF bars for September 11, 2026. The new adapter saved exact response bytes before
JSON parsing, receipt metadata and its SHA256, and validated the full universe,
no pagination, one bar per symbol, New York midnight session timestamps, finite
numeric values and consistent positive OHLCV. No IEX substitution or retry occurs.

The capture is acquisition evidence only. It does not join raw SIP prices to the
frozen historical panel, attest the host clock, establish corporate-action
adjustment parity, populate account context or activate the signal producer.
Those gates remain explicit in normalized.json, with runtime_ready false.
Local receipt times and content hashes are not independent timestamp evidence.
The earlier latest-quote 403 and unavailable borrow for some ETFs remain separate
execution constraints; this daily capture does not retest or resolve them.

Validation: 32 tests passed across the new capture adapter, corrected producer and
original observation journal. Capture cases exercise pagination, missing/extra
symbols, duplicate bars, incorrect timestamps, invalid prices/volume, immutable
capture directories, pre-close rejection, and retention of denied or malformed
responses without normalized output. Ruff passes for the adapter, capture runner
and new tests. Production files, historical evidence and broker state unchanged.
No new return trials; hypothesis union remains 238.

Next: audit the missing historical sessions and raw/adjusted price continuity
before connecting this acquisition layer to causal signal computation.
