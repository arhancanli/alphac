# Electricity load/weather spread — key-free feasibility decision

**Decision date:** 2026-08-15  
**Decision:** DATA-GATED; no return trial or hypothesis identity spent.

## Economic mechanism

Unexpected weather-driven electricity demand can change the marginal generation stack and the
value of regional power relative to its marginal fuel. The proposed sleeve is not a directional
weather bet: it must trade a regional power/fuel dislocation, neutralize generic natural-gas trend
and seasonality, and use only forecasts available before the execution timestamp.

## What the official-source audit established

- Form EIA-930 contains hourly actual demand and next-day demand forecasts by balancing authority.
  Respondents submit prior-day forecasts and operating data by 07:00 Eastern.
- EIA publishes bulk operating history without an API key, including history before 2019. The
  current EBA archive is a mutable latest-state file, not an append-only release-vintage archive.
- EIA explicitly says balancing authorities can revise historical submissions and that corrected
  values replace the historical record. A backtest downloaded today therefore cannot prove what
  forecast value was visible at the original decision time.
- NOAA's GEFSv12 reforecast archive provides a fixed-model retrospective weather dataset for
  2000-2019. It is useful for model and schema feasibility, but it is not the operational forecast
  market participants observed and cannot by itself establish tradable point-in-time performance.
- CME lists financially settled PJM Western Hub peak and off-peak futures. The 1 MW monthly
  contracts began Globex listing in July 2026; older power contracts are predominantly
  block-market instruments. Free price proxies cannot establish executable historical spreads.
- PJM Data Miner exposes public operating and market data, but its stated terms prohibit
  redistribution of data or derived information without membership. It is not a suitable source
  for the open research book without a separate license review.

## Fixed production market set

The first admissible production study is deliberately narrow:

1. PJM Western Hub day-ahead peak monthly power futures;
2. PJM Western Hub day-ahead off-peak monthly power futures; and
3. Henry Hub natural-gas futures as the marginal-fuel control, not as a substitute outcome.

ERCOT, MISO, nodal prices, electricity-sector equities, UNG and utility ETFs are excluded from the
first study. Adding them would change the hypothesis or introduce non-executable proxy risk.

## Data required before preregistration

- Append-only EIA-930 forecast snapshots captured with receipt timestamps, or a licensed archive
  that retains every original forecast vintage and correction.
- Operational NOAA forecast vintages with initialization and availability timestamps. GEFS
  reforecasts may be used only as a calibration control and must be labeled retrospective.
- CME DataMine trade, settlement, open-interest and bid/ask history for the exact power and gas
  contracts, plus point-in-time contract specifications and roll metadata.
- Written confirmation that the intended broker supports the exact power contracts and order
  types. An Alpaca key does not solve this requirement because Alpaca is not the execution venue
  for the fixed power-futures set.
- A redistribution/license review before any PJM-sourced value or derived statistic is published.

## Promotion and kill boundary

Do not preregister or inspect returns until the data above are present. Then lock one regional
construction, release clock, weather-to-load model, roll rule, costs, block constraints, capacity
curve and trend/seasonality controls. Kill if original vintages cannot be reconstructed, if quoted
liquidity cannot support the declared AUM, or if residual returns reduce to natural-gas trend,
ordinary seasonality or a short-volatility power premium.

## Primary official references

- EIA Form 930 data and quality notes: https://www.eia.gov/electricity/gridmonitor/about
- EIA open-data bulk manifest: https://www.eia.gov/opendata/bulk/manifest.txt
- EIA API documentation: https://www.eia.gov/opendata/documentation.php
- NOAA GEFSv12 reforecast archive: https://registry.opendata.aws/noaa-gefs-reforecast/
- NOAA GEFS archive specifications: https://www.ncei.noaa.gov/products/weather-climate-models/global-ensemble-forecast
- PJM Data Miner terms notice: https://www.pjm.com/markets-and-operations/etools/data-miner-2.aspx
- CME PJM contract listings: https://www.cmegroup.com/markets/energy/electricity.html

## Sealed collection checkpoint — 2026-08-16

`scripts/audit_electricity_load_weather_feasibility.py` now binds a fixed PJM, ERCOT, MISO and
ISO-NE panel with actual-demand (`D`) and day-ahead-demand-forecast (`DF`) series for 2019–2025.
It requests only EIA-930 schema and load/forecast values—never power or fuel prices, positions, or
returns—and fails closed unless all eight identities and required fields are present.

The public `DEMO_KEY` returned persistent rate limiting during the sealed run. Bounded retry and
`Retry-After` handling were exercised, but the collector refused to emit partial coverage. The
machine result is therefore `DATA_GATED` with `source_collection_complete=false` and blocker
`official_eia_collection_rate_limited_or_unavailable`. This is an operational collection failure,
not evidence against the economic mechanism and not permission to weaken the source contract.

Even a successful rerun cannot authorize returns: the EIA schema lacks an explicit forecast issue
or revision-vintage timestamp and an unambiguous timezone/DST-fold field; full historical
missingness/revision auditing and an operational NOAA vintage corpus also remain mandatory. Zero
return hypotheses were spent.
