# Electricity load/weather dislocation: literature and implementation boundary

**Reviewed:** 2026-08-16  
**Family:** `electricity_load_weather_spread`  
**Claim state:** mechanism supported; investable return untested  
**Return identities spent:** zero

## Abstract

Power must balance continuously, while demand and renewable output depend on weather. Forecast
updates therefore change expected scarcity, commitment, balancing demand, and the marginal fuel
stack. This supports a plausible short-horizon relative-value mechanism, but not a generic
“weather predicts power” return claim. A defensible study must preserve the operational forecast
vintage available before the trade, the local market clock, physical constraints, and executable
power/fuel instruments.

## Key evidence

Maciejowska, Uniejewski, and Weron's review explains why electricity prices have unusual short-run
dynamics and why probabilistic forecasts and economic—not only statistical—evaluation are
necessary. It supports the forecasting problem, not a specific profitable rule.

- [Maciejowska, Uniejewski, and Weron, *Forecasting Electricity Prices*](https://arxiv.org/abs/2204.11735)

Kiesel and coauthors study speculative intraday trading driven by renewable-production forecast
updates. Their controlled out-of-sample evidence supports the mechanism that public forecast
revisions can move intraday prices, but it is a European continuous-market design and cannot be
ported directly to US listed monthly power futures.

- [*Intraday power trading: toward an arms race in weather forecasting?*](https://link.springer.com/article/10.1007/s00291-022-00698-5)

Ruhnau shows that the economic value of a generation forecast depends on how forecast errors
co-move with prices; lower RMSE alone need not produce better trading economics. This motivates
ALPHAC's prohibition on selecting a weather model by forecast accuracy and then assuming the same
ranking survives costs and market impact.

- [Ruhnau, *Economic implications of forecasting electricity generation from variable renewable energy sources*](https://doi.org/10.1016/j.renene.2020.06.110)

The EIA-930 route publishes hourly actual demand and day-ahead demand forecasts by balancing
authority. Its public API schema is useful for source feasibility, but delivery period is not a
forecast issue timestamp or immutable revision identifier.

- [EIA Open Data API](https://www.eia.gov/opendata/index.php/api)
- [EIA electricity data guide](https://www.eia.gov/electricity/data/guide/pdf/guide.pdf)

NOAA/NCEI archives operational and retrospective forecast products. Reanalysis and reforecast
products are useful controls, but retrospective model output is not evidence of what a trader
observed in real time. Operational initialization, dissemination latency, model changes, and
archive completeness must remain explicit.

- [NOAA/NCEI Climate Forecast System archive](https://www.ncei.noaa.gov/products/weather-climate-models/climate-forecast-system)
- [NOAA archive dataset selection](https://www.ncei.noaa.gov/has/HAS.DsSelect)

## ALPHAC boundary

The first admissible identity remains PJM Western Hub peak/off-peak power relative to Henry Hub
fuel, with natural-gas trend and calendar seasonality neutralized. ERCOT, nodal prices, utility
equities, and ETF proxies are not pooled into the same trial. No direction, model, threshold,
holding period, Sharpe ratio, or admission claim is supported yet.

The family is economically distinct from the killed generic futures carry and commodity
positioning tests, but independence is not presumed. Any later return test must report conditional
correlation and co-expected-shortfall against AlphaTrend, natural-gas shocks, short-volatility
exposure, and extreme-weather periods.

## Rerun inputs

- workflow requested: `firecrawl-research-papers`
- collection result: Firecrawl unavailable because `FIRECRAWL_API_KEY` was not configured
- fallback: primary papers plus official EIA and NOAA documentation
- output: markdown literature boundary
- return data opened: no
- return hypotheses spent: zero
