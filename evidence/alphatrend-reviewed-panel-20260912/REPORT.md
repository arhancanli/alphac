# Reviewed panel rebuild — September 12, 2026

Corrected USO's April 9, 2020 raw open from $5.41 to $5.40 and rebuilt all
93,444 research rows across 17 ETFs using the latest reviewed actions. Two
historical price disputes and four payment-date disputes remain unresolved.

## Price evidence

A bounded authenticated read from Alpaca's historical bars API, with explicit
`feed=sip` and `adjustment=raw`, returned USO's April 8 and April 9, 2020 bars.
April 9 is O/H/L/C 5.40/5.78/4.80/4.98. The archived Yahoo OHLC implies the same
raw open within $0.000001, after comparing on the common close/share basis.
Both sources agree with the existing high, low and close. The single changed
raw field is therefore the open. All other raw prices and volumes are unchanged.
The old evidence is preserved, and the original source panel is not overwritten.

Volume is a separate disagreement: the source has 302,312,816 shares versus SIP
304,930,827. This remains disclosed and unresolved; the rebuild retains the source
volume. Resolving the open does not prove full tape correctness or volume accuracy.

Two other bounded Alpaca requests for DBA January 8, 2007 and UUP June 20, 2007
returned HTTP 200 with empty bar sets. Empty responses do not validate either
source price. Both flags remain set. All three requests were read-only; no
subscription changes, orders or paid data purchases occurred. Raw responses,
sanitized parameters, hashes and actual receipt times are saved in
`../alphatrend-price-repair-20260912/`.

## Rebuild and validation

The unchanged full-panel builder was invoked with isolated output paths and the
latest reviewed inputs. The 1,355 actions comprise 1,345 retained dividends and
10 splits. This incorporates the three earlier cash corrections and three
archived event exclusions (two QQQ, one EFA), each retaining its prior adjudication.
The rebuild is current-vintage diagnostic data, not historically available evidence.

- All 1,355 actions apply exactly once; 2,286 sampled bridge checks pass.
- Independent close-accounting relative error is at most 8.55e-15.
- All 93,444 calendar rows remain; the zero-volume UUP row remains recorded.
- Exactly one raw open changes; raw high, low, close and volume are unchanged.
- All 64,532 rows in the 12 unaffected symbols are exactly unchanged.
- USO signal closes are unchanged; its 5,138 rows pass the feature-input route.
- Full-history feature routing still refuses the two unresolved price flags.
- 23 bridge, routing and cash-correction tests pass; Ruff passes.

The builder's `raw_prices_and_volume_unchanged` result refers to its input
`reviewed_raw_ohlcv.parquet`, not the older uncorrected source. This report and
`validation.json` explicitly identify the one raw field changed from that source.
The panel provides diagnostic raw-volume estimates; the volume discrepancy does
not receive an implicit production approval from the price-flag change.

## Remaining blockers

Price disputes: DBA 2007-01-08 and UUP 2007-06-20. The four dividend payment
disputes are SPY 2006-06-16 and FXE 2007-04-02, 2008-07-01, 2011-10-03.
Additional searches did not establish authoritative resolutions for those dates.
They retain their earlier quarantine decisions. Historical publication-time
requirements and cash precision reviews remain open as well.

No actual strategy forecasts, IC, returns or portfolio performance were computed.
The runner remains unready, no trading profile changed, and the hypothesis union
remains 238. The Sharpe 2 and 14+ qualified-sleeve objectives are still unmet.
Further data confirmation is needed to finish the remaining repairs; none of
those records has been silently guessed or treated as clean.
