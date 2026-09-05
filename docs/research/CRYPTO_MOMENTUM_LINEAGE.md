# Crypto momentum: complete trial lineage and failed sleeve-admission evidence

**Short title:** AlphaForge crypto momentum: complete trial lineage  
**Author:** Arhan Canli, Founder, System Architect, and Quantitative Researcher, Canli Capital  
**Research system:** ALPHAC / AlphaForge  
**Family key:** `crypto_momentum`  
**Status:** public research record; not peer reviewed; not an investment solicitation  
**Evidence date:** 2026-08-22

## Abstract

AlphaForge tested cross-sectional and time-series momentum in perpetual-futures prices. This paper
reconciles all 18 charged crypto-momentum hypothesis identities recorded from 2026-06-20 through
2026-06-25. The best persisted result, a 21-day time-series momentum signal rebalanced weekly, had
annualized Sharpe 0.4863, total return 26.83%, and maximum drawdown 17.02% from 2022-02-08 through
2026-06-01. Its artifact-era Deflated Sharpe Ratio was only 0.0684. The worst result, a seven-day
cross-sectional signal rebalanced daily, had Sharpe -1.1690, total return -42.39%, and maximum
drawdown 50.64%. All 18 artifacts failed their recorded DSR gate.

A separate 2021–2026 diagnostic combined three momentum signals and measured Sharpe 0.0780. Its
full-sample correlation with a carry diagnostic was +0.0444 and stress correlation was negative,
but the combined Sharpe was only 0.0556 and even the reported decorrelated ceiling was 0.1206.
Diversification without standalone edge does not earn a sleeve slot. No persisted momentum
capacity sweep exists. This family is research-only: it is not validated, admitted, live, or part
of an Alpaca paper account.

## Claim boundary

This paper establishes only that:

1. the economic hypotheses and implemented formulas can be stated precisely;
2. all 18 charged identities are joined to immutable ledger rows and persisted artifacts;
3. positive, negative, selection-adjusted, and diversification evidence is published together;
4. every persisted artifact failed its original DSR gate; and
5. overlap with existing price-trend families is explicitly resolved.

It does **not** establish a forward Sharpe, expected maximum drawdown, useful capacity, independent
alpha source, future return, live execution record, or investable product. Artifact-era DSR values
use the selection context stored when each run was produced; this paper does not mislabel them as
restatements against the current 228-identity union.

## Economic hypotheses

The cross-sectional hypothesis is that assets with stronger recent returns than peers continue to
outperform those with weaker returns over the next holding interval. The time-series hypothesis is
that an asset's own normalized trailing return predicts the sign and relative strength of its next
return. Possible mechanisms include slow information diffusion, investor attention, behavioral
underreaction, trend-chasing flows, and compensation for crash or liquidity risk. None makes
momentum a law; rapid reversals, crowded exits, trading costs, and changing market structure are
direct falsifiers.

The primary literature supplies a prior and an overlap map, not validation of ALPHAC:

- Moskowitz, Ooi, and Pedersen document time-series momentum across conventional futures and
  forwards ([Journal of Financial Economics](https://doi.org/10.1016/j.jfineco.2011.11.003)).
- Liu and Tsyvinski identify crypto-specific momentum and investor-attention effects while showing
  that standard asset-pricing factors do not fully explain crypto returns
  ([Review of Financial Studies](https://doi.org/10.1093/rfs/hhaa113)).
- Liu, Tsyvinski, and Wu construct crypto market, size, and momentum factors
  ([Journal of Finance](https://doi.org/10.1111/jofi.13119)).
- Grobys and Sapkota test momentum in cryptocurrency markets
  ([Economics Letters](https://doi.org/10.1016/j.econlet.2019.03.028)).
- Chi and coauthors study cross-sectional risk factors in cryptocurrency futures and emphasize
  that signal frequency matters ([Journal of Futures Markets](https://doi.org/10.1002/fut.22425)).

These studies do not validate AlphaForge's universe history, feature timestamps, transaction-cost
model, trial search, or implementation.

## Exact ALPHAC implementation

Let `C(i,t)` be the point-in-time close for instrument `i` at hourly decision bar `t`. Missing
history remains missing rather than being backfilled from the future.

For long horizon `L` and short skip `S`, cross-sectional momentum is:

```text
mom_xs_L_S(i,t) = ln(C(i,t-S) / C(i,t-L))
```

The charged variants use `L=168` with `S=24`; `L=504` with `S=48`; and `L=2160` with `S=168`.
They correspond approximately to seven-day/one-day-skip, 21-day/two-day-skip, and
90-day/seven-day-skip signals on hourly bars.
The values are ranked across the complete point-in-time universe at each decision.

For horizon `L`, time-series momentum is:

```text
mom_ts_L(i,t) = ln(C(i,t) / C(i,t-L)) / (EWMA_vol_168(i,t) * sqrt(L))
```

The charged horizons are 168, 504, and 2160 hourly bars. The denominator scales trailing returns
by a 168-hour exponentially weighted volatility estimate. Positive values imply long direction and
negative values short direction before portfolio construction. Normalization does not eliminate
gap risk or make signals comparable when data quality differs across instruments.

Most artifacts use rank allocation over 58 Binance perpetual contracts, with 25 walk-forward
legs, 6,048 training bars, 1,512 test bars, 72 purge bars, and 168 embargo bars. Charged variants
change signal horizon, blend, allocator, rebalance cadence, or half-universe split. Such changes
remain distinct hypotheses even when they share one economic mechanism.

## Complete trial lineage

The public family packet binds 18 immutable identities to `crypto_momentum`:

| Machine-label group | Charged identities | Question tested |
|---|---:|---|
| `mom_ts_504` | 9 | 21-day trend across daily, 3-day, weekly, 2-week, long-only-rank, and split-universe variants |
| `mom_xs_504_48` | 2 | 21-day cross-sectional momentum at daily and weekly cadence |
| `mom_ts_2160` | 2 | 90-day time-series trend under daily and weekly cadence |
| `mom_xs_2160_168` | 1 | 90-day cross-sectional momentum with a seven-day skip |
| `mom_xs_168_24` | 1 | Seven-day cross-sectional momentum with a one-day skip |
| `mom_ts_168 + mom_ts_504 + mom_ts_2160` | 1 | Multi-horizon time-series blend |
| `mom_ts_504 + mom_xs_504_48` | 1 | Weekly time-series/cross-sectional blend |
| `mom_xs_504_48 + mom_xs_2160_168 + mom_ts_504` | 1 | Recovered legacy diversification diagnostic |
| **Total** | **18** | Every identity remains charged to the global search burden |

Seventeen identities came from the original `var*` research profiles. The eighteenth was recovered
from `artifacts/exp1/20260625T075446Z/experiments.jsonl` when canonical discovery was corrected to
include durable artifact ledgers. This correction ran no experiment. The recovered artifact names
3,358 configured instruments across both `BINANCE` and `XUSE` namespaces, unlike the cleaner
58-contract crypto panels. It is retained as a diagnostic, not treated as a direct replication.

The machine-readable source is
[`/glassbox/crypto_momentum_family.json`](/glassbox/crypto_momentum_family.json). It includes every
hypothesis key, immutable ledger source, source hash, compact configuration, persisted result, and
artifact-era validation verdict. The global identity join remains available at
[`/glassbox/trial_packet_manifest.json`](/glassbox/trial_packet_manifest.json).

## Results

### Best persisted specification

The strongest artifact is weekly `mom_ts_504` with rank allocation:

| Measure | Persisted value |
|---|---:|
| Initial / final simulated equity | $100,000 / $126,825.13 |
| Total return / CAGR | 26.83% / 5.67% |
| Annualized Sharpe / volatility | 0.4863 / 12.38% |
| Maximum drawdown | 17.02% |
| Annual turnover | 30.32x |
| Fees paid | $7,274.25 |
| Net funding cashflow | +$975.14 |
| Artifact-era DSR / gate | 0.0684 / failed |

This is the maximum Sharpe among the 18 persisted identities, not an independently chosen
confirmatory result. It fails the governing DSR threshold and its drawdown exceeds the program's
11% expected-maximum-drawdown objective.

### Worst persisted specification

Daily `mom_xs_168_24` is the clearest falsification:

| Measure | Persisted value |
|---|---:|
| Initial / final simulated equity | $100,000 / $57,605.73 |
| Total return / CAGR | -42.39% / -12.01% |
| Annualized Sharpe / volatility | -1.1690 / 10.47% |
| Maximum drawdown | 50.64% |
| Annual turnover | 129.02x |
| Fees paid | $22,178.23 |
| Artifact-era DSR / gate | 0.0000001665 / failed |

The difference between the best and worst identities is specification sensitivity, not evidence
that the best setting has isolated a stable law. Across the complete family, annualized Sharpe
ranges from -1.1690 to +0.4863 and maximum drawdown ranges from 15.15% to 50.64%. Zero of 18
persisted validations clears its artifact-era DSR gate.

## Diversification diagnostic: low correlation is insufficient

The recovered `exp1` momentum blend measured annualized Sharpe 0.0780, maximum drawdown 20.94%,
and artifact-era DSR 0.5607. Against its carry diagnostic, full-sample correlation was +0.0444;
correlation was -0.5768 on the combined book's worst 2.5% of days and -0.6290 when either sleeve
was in its worst 2.5%. Those correlations appear attractive in isolation.

But the equal combination produced Sharpe only 0.0556 and maximum drawdown 12.82%. Even the
artifact's decorrelated Sharpe ceiling was only 0.1206. Negative stress correlation cannot rescue
two weak expected-return processes. The test therefore supports a null: momentum does not earn a
separate sleeve slot merely because it sometimes offsets carry.

## Capacity and execution boundary

No persisted crypto-momentum capacity sweep changes capital while holding the momentum return
hypothesis fixed. Capacity is therefore **unmeasured**, not zero and not positive. Turnover as high
as 129.02x, fees, venue concentration, order-book depth, funding, and crowding make extrapolation
especially unsafe.

There is also no continuous broker-reconciled forward record for this crypto-momentum family.
AlphaForge's incumbent paper experiment is funding carry; AlphaMax and AlphaTrend already express
related price-trend mechanisms in equities and managed futures. Crypto momentum is not an Alpaca
paper sleeve, not an AlphaVintage result, and not included in published live returns.

## Overlap and sleeve decision

Crypto momentum, AlphaMax equity momentum, and AlphaTrend managed-futures trend differ in market,
formation horizon, and portfolio construction, but all monetize persistence in prices. They are
not automatically three independent economic mechanisms. Under the research taxonomy, the 18
crypto variants form one family and at most one sleeve candidate.

An independent sleeve claim would require a preregistered forward specification, a clean
crypto-only point-in-time universe, net positive standalone evidence after current union
deflation, measured capacity, and contemporaneous return correlations against the actual live
books, including stress windows. None is presently established.

## Reproduction map

- `src/alphaforge/features/library/momentum.py`: signal formulas and point-in-time feature code.
- `docs/design/alphaDesign.md`: original momentum specification and research contract.
- `var*/experiments.jsonl` and `artifacts/exp1/20260625T075446Z/experiments.jsonl`: immutable
  charged identities.
- `artifacts/cpanel/*/walkforward.json` and
  `artifacts/walkforward/crypto_mom_base/walkforward.json`: original persisted simulations.
- `artifacts/exp1/20260625T075446Z/momentum/walkforward.json` and `exp1_metrics.json`: recovered
  momentum/diversification diagnostic.
- `scripts/audit_crypto_momentum_family.py`: deterministic ledger-to-artifact audit.
- `artifacts/research/crypto_momentum_family.json`: generated family evidence packet.
- [`/glassbox/crypto_momentum_family.json`](/glassbox/crypto_momentum_family.json): stable public
  machine-readable packet.

Reproduction requires the pinned project environment and underlying market-data lake. The public
packet proves the claims made here and hashes their source artifacts; it does not imply that every
venue or vendor dataset may be redistributed.

## Packet completeness

This family paper verifies shared identity, authorship, mechanism, literature, family accounting,
and stable-publication sections for 18 identities. It does not retroactively manufacture exact
identity-level preregistrations, full return bundles, environment snapshots, or capacity studies.
All 18 trial packets therefore remain incomplete until every required section is proved. A family
paper is meaningful coverage, not a completed identity packet.

## Decision

**Research decision:** reject sleeve admission. Preserve all 18 identities, including the severe
negative result and the recovered mixed-universe diagnostic. Do not search additional momentum
variants without a new mechanism and explicit family budget.

**Live decision:** do not add crypto momentum to the paper book. It has no broker-reconciled
forward record, no measured capacity, and no independently validated edge.

**Publication decision:** publish the complete family null under Arhan Canli's authorship. The
credible accomplishment is not the 0.4863 selected Sharpe; it is a record that makes the selected
result, failed deflation, 50.64% adverse drawdown, overlap, and non-admission equally inspectable.
