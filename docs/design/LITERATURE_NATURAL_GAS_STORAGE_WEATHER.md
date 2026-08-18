# Natural-gas storage/weather residual — literature and claim boundary

**Reviewed:** 2026-08-16  
**Research state:** source feasibility only; no futures prices or returns opened.

## Economic mechanism

Weekly working-gas inventory changes combine weather-driven demand, production, imports/exports,
and operational flows. A storage change is economically informative only relative to what was
knowable before the storage week. The candidate therefore asks whether a first-release EIA storage
residual—after conditioning on a frozen NOAA ensemble forecast—contains short-lived information
not captured by natural-gas trend or curve carry.

The forecast vintage is load-bearing. Using observed weather, a later model rerun, revised EIA
history, or an analyst consensus collected after the storage week would turn the test into a
different and potentially look-ahead-biased identity.

## Prior evidence and limitations

- EIA's Weekly Natural Gas Storage Report is an official weekly estimate with published sampling
  uncertainty, revision policy, and a standard Thursday release convention with holiday
  exceptions. Current history is not automatically first-release history.
- NOAA's public GEFS archive contains timestamped ensemble forecast runs. Model/version and file
  layout changed materially in September 2020, so one contemporary path cannot be projected
  backward.
- Mu (2007), *Weather, storage, and natural gas price dynamics*, documents the joint importance of
  weather and inventories for natural-gas prices. It motivates conditioning but does not establish
  a modern executable event sleeve. DOI: https://doi.org/10.1016/j.eneco.2006.04.003

Original studies and government data do not supply ALPHAC's required first-release hashes,
forecast-vintage manifest, futures rolls, bid/ask execution, limit events, capacity, untouched
holdout, family-wise DSR, or portfolio-diversification evidence.

## Official sources

- EIA WNGSR current report and machine-readable files: https://ir.eia.gov/ngs/ngs.html
- EIA methodology: https://ir.eia.gov/ngs/methodology.html
- EIA revision policy: https://ir.eia.gov/ngs/revisions.html
- EIA release schedule: https://ir.eia.gov/ngs/schedule.html
- NOAA GEFS archive: https://registry.opendata.aws/noaa-gefs/
- CME Henry Hub Natural Gas futures:
  https://www.cmegroup.com/markets/energy/natural-gas/natural-gas.html

## Family-wise trial accounting

This candidate overlaps the already killed `commodity_inventory_seasonal` petroleum identity. The
new weather-conditioned storage residual is a distinct configuration, not a fresh family. If
returns are ever opened, the family trial count starts at **at least two**, the prior negative
result remains published, and no sign flip or product substitution erases it.
