# Open-interest semantics and volume consistency — 2026-09-13

## Measured result

All eight fixed five-minute kline archives and checksums were acquired in 16 requests with zero retries. Same symbols/dates as the completed OI pilot; no expanded date selection. Base-unit OI differences were compared against base-unit traded volume for 2,296 within-day intervals. Six primary discrepancies occur, all on June 1, 2026: three BTC and three ETH. Independent pandas reconstruction agrees with every Decimal-based flag. No signal or portfolio return was computed.

The fixed primary convention compares consecutive OI snapshots at a,b against the kline starting at a. The predeclared wider diagnostic includes the bar starting at b as well. All six discrepancies disappear under that wider envelope. This is not an accepted timestamp correction: the extra volume occurs after the labeled interval and could hide an error. No shift was fitted or selected. Five-minute archive use is therefore timing-unresolved, not certified. A pass in this small sample would not establish source accuracy across the full horizon either.

## Source semantics and mechanism

Binance's current Open Interest Statistics API documents timestamp as period end and access to the latest month; it does not prove that archive create_time equals that field or the original publication time. Daily archive availability and later possible archive updates are separate issues. A synthetic availability lag cannot turn current-vintage data into verified historical publication evidence.

The study by Giagkiozis and Said motivates a volume consistency constraint: outstanding-contract changes need supporting traded quantity. Our bar diagnostic is not their tick-data study, and discrepancies do not identify which feed or boundary convention is wrong. An OI decrease does not distinguish liquidation from voluntary closure. Every new contract has both a long and a short; increasing OI alone does not identify signed speculative demand.

Local carry_dynamics.py already implements crowding fade and funding slope. Its comments claiming orthogonality by construction are not empirical proof. BIS crypto-carry research supports a leverage-demand/arbitrage-capital interpretation of carry; that does not establish a new independent return premium from OI. No distinct sleeve is admitted by changing the input name.

## Decision and next research action

STOP five-minute execution and liquidation-proxy proposals based on these archives. Do not run further sample-date, time-shift or source-schema sweeps. Source feasibility is closed at this resolution with explicit limitations.

A slower OI model remains a possible *existing crypto sleeve enhancement*, not automatically a new family. Next work must choose and preregister one incremental predictive hypothesis with funding and price-momentum controls, causal training-only fitting, fixed lag and holding period, costs and a chronological evaluation split. A new measured input can justify that controlled test, but does not authorize sign/window searches or relabel prior failures. If a defensible hypothesis cannot be specified, park this input and select another economic mechanism. Do not acquire the full archive before that decision. Any retrospective result must remain current-vintage research and cannot satisfy prospective qualification.

Current portfolio reference and trial count are unchanged: main normal/stress excess Sharpe 0.74241347/0.41886531, 336 measured trials plus the preserved unmeasured failed reservation, zero new qualified sleeves. Prior goal turn was progress (independent source pilot); this turn adds observed timing inconsistencies and closes the high-frequency use case. Capture session66942 exited0; no live job.

## Sources read

- Binance USD-M market-data docs, Open Interest Statistics section, https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data (2026-09-13).
- Binance public archive README, https://raw.githubusercontent.com/binance/binance-public-data/master/README.md (2026-09-13).
- Giagkiozis and Said, Reconciling Open Interest with Traded Volume in Perpetual Swaps, v2, https://arxiv.org/html/2310.14973v2 (2024; read2026-09-13).
- BIS Working Paper1087, Crypto carry, publication summary, https://www.bis.org/publications/working-paper-1087-crypto-carry (read2026-09-13).
- Local src/alphaforge/features/library/carry_dynamics.py; config/sleeve_family_lineage.json; scripts/atlas_reachability_screen.py.
