# Crypto open-interest archive pilot — 2026-09-13

Source feasibility phase completed; no signal, return trial, or qualified sleeve added.

The fixed BTCUSDT/ETHUSDT sample on 2022-01-01, 2022-11-09, 2023-01-01 and 2026-06-01 returned all eight archives and checksums within the 16-request, zero-retry bound. Independent offline reconstruction verifies 2,304 rows, exact 288-point daily five-minute timestamp sets, unique timestamps, correct symbols, SHA256 agreement and finite positive open-interest quantity and value throughout this sample.

Both June 2026 archives are unordered: BTC has 48 adjacent timestamp reversals and ETH 53. A row-position shift or unsorted rolling window would therefore be invalid. The first/last rows reported by capture are physical file order, not chronological endpoints. All sampled days span 00:00–23:55 after sorting. Both January 2022 archives have all four ancillary ratio fields empty; November 2022 has both top-trader ratio fields empty. No backfill from future observations or zero substitution is permitted.

The official public-data README states daily archives become available the following day and warns that archives can subsequently be updated. These statements describe archive distribution, not the original intraday dissemination time of each metric. Current downloads and valid checksums do not prove original historical vintages. Source: https://raw.githubusercontent.com/binance/binance-public-data/master/README.md (read 2026-09-13, checksum and updates sections).

## Research decision

Proceed to a bounded economic-mechanism and timestamp-semantics review before bulk acquisition or returns. Open interest is a newly accessible input in this pilot, not evidence of a new independent alpha family. Its decline cannot label forced liquidations; changes cannot be treated as signed net buying, and dollar-value changes include price movements. Existing funding-crowding and momentum failures remain closed. The liquidation-pressure lane still requires actual event evidence and is not reopened by this archive.

The next design must state a falsifiable economic prediction and matched existing-feature control, establish whether it duplicates a previously rejected family, and freeze signal direction, observation/availability lag, horizon and missing-data rules before looking at forecast performance. If no distinct mechanism is defensible, stop this candidate before a return trial. Do not download years of data simply because the pilot is available.

Any later retrospective archive experiment must disclose current-vintage inputs and modeled availability; it cannot qualify as untouched point-in-time evidence. Strict timestamp sorting and uniqueness checks precede differencing; quantity and value remain separate; missing intervals invalidate the affected signal window rather than being interpolated across gaps. Full-horizon coverage must be audited before evaluation. Separate prospective capture or documented historical dissemination evidence is needed for timing qualification.

## Portfolio state

Retained BIL reference is unchanged: main normal excess Sharpe 0.74241347, stress 0.41886531. Measured union remains 336, with the failed unmeasured reservation preserved. No additional sleeve qualified. The previous status-only turn was no progress; this turn adds independent source evidence and a concrete input-ordering requirement. Capture is terminal (complete capture.json and all eight archives); no new capture process started.
