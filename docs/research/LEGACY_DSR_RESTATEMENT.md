# Legacy DSR restatement

This is a correction ledger, not a performance upgrade. Original artifacts remain intact.

Current selection context: **N=228**, identity-aligned **V[SR]=0.0008957471**.

- Restated: 33 variants across 5 families.
- Retired for missing return series: 7 families.
- Current DSR ≥ 0.95: 0 variants.

## Recomputed variants

| Family | Variant | Historical DSR | Current DSR | Status |
|---|---|---:|---:|---|
| alphamax_betaneutral | `LIVE-REPLICA k30_dn_63/BASE` | 0.183185 | 0.162490 | FAIL |
| alphamax_betaneutral | `LIVE-REPLICA k30_dn_63/BASE_asis` | 0.134993 | 0.118102 | FAIL |
| alphamax_betaneutral | `LIVE-REPLICA k30_dn_63/CTRL_NETLONG` | 0.069001 | 0.058845 | FAIL |
| alphamax_betaneutral | `LIVE-REPLICA k30_dn_63/V1_betaneutral` | 0.078945 | 0.067668 | FAIL |
| alphamax_betaneutral | `LIVE-REPLICA k30_dn_63/V2_betahedged` | 0.107465 | 0.093211 | FAIL |
| alphamax_betaneutral | `LIVE-REPLICA k30_dn_63/V2m_hedge_21d` | 0.110626 | 0.096055 | FAIL |
| alphamax_betaneutral | `RESEARCH top-2000 K=100/BASE` | 0.000000 | 0.000000 | FAIL |
| alphamax_betaneutral | `RESEARCH top-2000 K=100/BASE_asis` | 0.000000 | 0.000000 | FAIL |
| alphamax_betaneutral | `RESEARCH top-2000 K=100/CTRL_NETLONG` | 0.000000 | 0.000000 | FAIL |
| alphamax_betaneutral | `RESEARCH top-2000 K=100/V1_betaneutral` | 0.000003 | 0.000001 | FAIL |
| alphamax_betaneutral | `RESEARCH top-2000 K=100/V2_betahedged` | 0.000000 | 0.000000 | FAIL |
| alphamax_betaneutral | `RESEARCH top-2000 K=100/V2m_hedge_21d` | 0.000000 | 0.000000 | FAIL |
| alphamax_construction | `A1` | 0.150387 | 0.136112 | FAIL |
| alphamax_construction | `A2` | 0.209723 | 0.191973 | FAIL |
| alphamax_construction | `G1` | 0.294726 | 0.275058 | FAIL |
| alphamax_construction | `I1` | 0.529216 | 0.504142 | FAIL |
| alphamax_construction | `I2` | 0.141761 | 0.128013 | FAIL |
| alphamax_construction | `I3` | 0.024886 | 0.021383 | FAIL |
| alphamax_construction | `I4` | 0.156486 | 0.141846 | FAIL |
| alphamax_construction | `R0` | 0.150387 | 0.136112 | FAIL |
| alphamax_constructions | `gauntlet_eq_52whigh_252` | 0.000020 | 0.000000 | FAIL |
| alphamax_shorttail | `baseline` | 0.000000 | 0.000000 | FAIL |
| alphamax_shorttail | `cap_1.25x` | 0.000000 | 0.000000 | FAIL |
| alphamax_shorttail | `cap_1.5x` | 0.000000 | 0.000000 | FAIL |
| alphamax_shorttail | `cap_2.0x` | 0.000000 | 0.000000 | FAIL |
| alphamax_shorttail | `daily_reset` | 0.000000 | 0.000000 | FAIL |
| alphamax_shorttail | `stop_100` | 0.000000 | 0.000000 | FAIL |
| alphamax_shorttail | `stop_30` | 0.000000 | 0.000000 | FAIL |
| alphamax_shorttail | `stop_50` | 0.000000 | 0.000000 | FAIL |
| alphamax_shorttail | `stop_50_dn` | 0.000000 | 0.000000 | FAIL |
| alphamax_shorttail | `svol` | 0.000000 | 0.000000 | FAIL |
| alphamax_shorttail | `svol_dn` | 0.000000 | 0.000000 | FAIL |
| econtrend | `locked_primary_oos` | 0.000000 | 0.000000 | FAIL |

## Retired historical DSR claims

- **exp2_crypto_vrp** — The persisted artifact contains summary statistics but no variant-level return series. DSR depends on observations, skew and kurtosis; it cannot be honestly reconstructed from annualized Sharpe.
- **alphamax_hyst_live** — The persisted artifact contains summary statistics but no variant-level return series. DSR depends on observations, skew and kurtosis; it cannot be honestly reconstructed from annualized Sharpe.
- **alphamax_turnover** — The persisted artifact contains summary statistics but no variant-level return series. DSR depends on observations, skew and kurtosis; it cannot be honestly reconstructed from annualized Sharpe.
- **alphamax_volscale** — The persisted artifact contains summary statistics but no variant-level return series. DSR depends on observations, skew and kurtosis; it cannot be honestly reconstructed from annualized Sharpe.
- **alphamax_weighting** — The persisted artifact contains summary statistics but no variant-level return series. DSR depends on observations, skew and kurtosis; it cannot be honestly reconstructed from annualized Sharpe.
- **alphatrend_arp** — The persisted artifact contains summary statistics but no variant-level return series. DSR depends on observations, skew and kurtosis; it cannot be honestly reconstructed from annualized Sharpe.
- **alphatrend_breadth** — The persisted artifact contains summary statistics but no variant-level return series. DSR depends on observations, skew and kurtosis; it cannot be honestly reconstructed from annualized Sharpe.

## Executable-code status

All 12 historical probe paths now use identity-aligned union accounting or fail closed at preflight. There are 0 executable raw-row DSR paths. Separately, 7 summary-only artifact families remain retired and cannot be treated as approved evidence.

Resolved paths:

- `scripts/exp2_crypto_vrp.py`
- `scripts/probe_alphamax_betaneutral.py`
- `scripts/probe_alphamax_construction.py`
- `scripts/probe_alphamax_constructions.py`
- `scripts/probe_alphamax_hyst_live.py`
- `scripts/probe_alphamax_shorttail.py`
- `scripts/probe_alphamax_turnover.py`
- `scripts/probe_alphamax_volscale.py`
- `scripts/probe_alphamax_weighting.py`
- `scripts/probe_alphatrend_arp.py`
- `scripts/probe_alphatrend_breadth.py`
- `scripts/probe_econtrend.py`

## Interpretation boundary

This restates DSR only. It does not upgrade data quality, validation grade, sleeve admissibility or investment performance, and it does not alter original artifacts.
