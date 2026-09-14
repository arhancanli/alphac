# Crypto2022 extension input grid

Timestamp-only inspection of2021–2022 found787,866hourly rows and99,939funding rows across the configured58instrument set. Exact timestamp duplicates:0. Against recorded membership intervals,809of359,280expected active hourly marks are missing:FTM120,LRC72,LUNA569,WAVES48. All identified active gaps are in2022; the configured membership universe and historical availability remain unqualified.

## Funding interpretation

The initial strict >8hour gap count is not a missing-event count: millisecond event jitter makes it misleading. A descriptive8hour bucket check instead finds56missing active buckets,allLUNA, and75extra SOL events within buckets. No exact event duplicates exist. Extra SOL events must not be deduplicated against an assumed universal cadence. Historical cadence/lifecycle verification remains required.

All99,939rows store availability exactly300,000ms after the event timestamp. Local ccxt_source.py defines this five-minute delay as a configured publication-lag assumption; it is not an observed historical receipt. The source comment claiming a timing guarantee is not independent evidence of such a guarantee. Preserve event timestamps and use availability-aware joins, with timing sensitivity in any return specification.

## Recoverable archive probe

One isolated public-exchange archive was fetched: https://data.binance.vision/data/futures/um/daily/klines/FTMUSDT/1h/FTMUSDT-1h-2022-02-26.zip . Its published CHECKSUM matches SHA256, and all24missing hourly timestamps for that day are present. Raw records are retained; only timestamps were inspected. This establishes a recoverable source for that one day, not an executed repair or validation of all809gaps. Production data is unchanged.

## Next action

Acquire checksum-bound archives for the remaining finite missing-day queue, separating absent files from available records. LUNA's post-May13interval must be checked against lifecycle/trading-status evidence, not filled with synthetic prices or dropped after losses. SOL cadence likewise needs source evidence. Then seal an isolated repaired input snapshot and extension protocol; do not claim original-input reproduction or untouchedOOS. No new return identity; union273.
