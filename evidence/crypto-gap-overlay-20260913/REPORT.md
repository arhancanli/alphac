# Isolated crypto repairs and material lifecycle finding

Built four isolated2022hourly partitions adding exactly360checksum-verified missing bars:FTM120,LRC72,LUNA120,WAVES48. Every existing row remains exactly equal after merge and parquet round-trip. Original production file hashes remain unchanged. Recovered rows use current ingestion timestamps; no source availability is backdated. Basic OHLC ordering, timestamp uniqueness, hourly endpoints and nonnegative volume/trade fields were checked. Zero quality flags mean no parser flags, not independent historical execution certification.

The overlay supplies patched partitions only, not a complete executable lake.449post-delisting LUNA hours remain absent. Existing trailing zero-trade bars are preserved as source records and must be blocked by execution status, not accepted as fills. The intrahour15:30termination and settlement value require explicit treatment.

## Existing run affected

The retained crypto carry leg01 has six simulated LUNA fills at or after the announced2022-05-12 15:30UTCtermination, totaling$1,931.5104317280482notional. Positions also remain marked after that boundary. This is a legacy backtest artifact, not a report of real trading. The original files and performance results are preserved; no losses or fills are deleted. This evidence reinforces that the retained crypto/combined curves are development references, not qualified executable crisis evidence.

Source boundary: https://www.binance.com/en/support/announcement/detail/ef3ce76d5c2d45ee9b6dc3f281cde744 . Exact settlement price and contemporaneous notice receipt remain unverified.

## Status handling

Existing StaticMarketStatusProvider already rejects future-known historical events. A LUNA HALTED interval is stored with the actual current observation/availability time and linked source-note hash. Its historical query correctly raises LookaheadError. It is evidence, not permission to backdate knowledge. Twelve existing market-status tests pass. No redundant status implementation or production default was added.

## Next phase

Before return registration, choose and freeze a transparent execution/settlement treatment supported by records, including the boundary-crossing bar and remaining LUNA holdings. A corrected retrospective diagnostic may explicitly model historical notice availability, but cannot label it witnessed point-in-time evidence. Do not replay the old path as qualified or silently remove post-boundary losses. Archive actual settlement/last-trade evidence if obtainable; otherwise retain that limitation rather than fabricate a price. All long-term goals remain active; no new return identity or sleeve; union273.
