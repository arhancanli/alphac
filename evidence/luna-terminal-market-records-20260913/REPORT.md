# LUNA terminal market records

Recovered three checksum-verified official exchange archives forMay12,2022:1minute trade klines,index-price klines andmark-price klines. Each contains1440dayrows and all30timestamps in15:00–15:30UTC. Original files and checksum receipts are retained. OHLC ordering checks pass; no strategy returns were measured.

The trade series closes the interval at0.0071,the index at0.00697000,and the mark at0.00682760. These differing values demonstrate why the last price, index and mark cannot be interchanged without an explicit rule. None is labeled the actual cash settlement.

Binance's currently accessible delisting FAQ describes settlement using index observations sampled every second over the final30minutes: https://www.binance.com/az-AZ/support/faq/detail/dd60dfbf654d4055aa6b217ea6d5ddba . We have not verified that policy's applicable2022version or obtained an actual settlement receipt. The minute files do not reconstruct1800individual observations.

Conditional on equal-duration second sampling and the minute extrema containing all relevant index samples, the mean must lie between the average minute lows0.006944333333333333333333333333and average minute highs0.008040666666666666666666666667. These are mathematical bounds under explicit assumptions, not certified historical settlement bounds. They cannot be promoted to an exact settlement price or used to overwrite old P&L.

## Next action

Implement a source-bound terminal-event interface that distinguishes verified settlement from an explicitly modeled diagnostic scenario, rejects missing or nonfinite settlement inputs, prevents later order execution and preserves losses on the remaining position. Before any scenario returns, preregister the settlement assumption/range, cost treatment and corrected matched baselines. A conservative diagnostic can proceed with disclosed uncertainty; full execution qualification still requires settlement and availability evidence. Do not repeatedly scrape the same FAQ or average minute closes and claim exactness. No live or production mutation; union273; goalactive.
