# A hash-bound prospective test of cross-sectional perpetual-futures carry

**Author:** Arhan Canli, Founder, System Architect, and Quantitative Researcher, Canli Capital  
**Research system:** ALPHAC / AlphaForge  
**Trial:** `crypto_carry_portable_v1`  
**Hypothesis identity:** `da5f5f47f99f9bd2`  
**Evidence date:** 2026-08-24  
**Status:** working paper; historical simulation; admission incomplete; not externally submitted or
peer reviewed; not an investment solicitation

## Abstract

This paper reports the first ALPHAC crypto-carry identity whose data decision, code, environment,
trial parameters, and private execution inputs were frozen before its return path was computed.
The experiment tests whether a weekly, cross-sectional funding-rate signal in USD Tether
(USDT)-margined perpetual futures produces useful net out-of-sample returns under the current
AlphaForge engine.
The data rule admitted 57 instruments from checksum-verified official archives and excluded
`ICPUSDT` before return computation because 14 required monthly funding archives were absent. The
runner then stitched 25 purged and embargoed walk-forward legs from 8 February 2022 through 1 June
2026.

The single registered path produced an annualized daily Sharpe ratio of 0.9689, 10.84% CAGR,
11.01% annualized volatility, 12.30% daily maximum drawdown, and 55.88% total return after the
implemented costs. The probabilistic Sharpe ratio (PSR) was 0.9776. The deflated Sharpe ratio
(DSR) was 0.0914 against 229 union identities: an important warning about the project-wide search
burden, but not a standalone admission gate under the reservation-bound v7 contract. Sixteen of 25 individual legs
had positive Sharpe; the median leg Sharpe was 0.4756. The minimum leave-one-calendar-year-out
Sharpe was 0.6232, while the partial 2022 segment itself was negative.

The candidate is **not admitted**. Its disposition is `INCOMPLETE`, not `ADMIT` and not `KILL`,
because the preregistered stress, capacity, execution-scenario, diversification, book-contribution,
and book-drawdown evidence is not yet complete. The probability of backtest overfitting (PBO) is
undefined for the single registered path
because no eligible path matrix was generated; it is reported as null rather than zero. At the
primary-result seal, the next forward identity remained mechanically blocked pending a complete
packet. This result demonstrates a promising frozen simulation and a strict research-governance
process, not a validated sleeve or expected future performance.

## 1. Contribution and claim boundary

The contribution is primarily methodological. The experiment joins five controls that the earlier
crypto-carry result did not preserve together:

1. a source-completeness rule decided before returns;
2. a point-in-time universe reconstructed from instrument lifecycles;
3. an exact preregistration and one-identity reservation;
4. a pre-execution snapshot of every derived decision and execution input; and
5. a deterministic result receipt that reconciles the equity curve, walk-forward report, ledger,
   snapshot, code, environment, and governing contract.

The paper supports the following narrow claims:

- exactly one registered historical simulation was executed for this identity;
- the immutable path and same-path diagnostics have the values reported here;
- all 781 private snapshot files rehash to the pre-execution manifest;
- no post-result gate was changed; and
- required admission evidence remains missing, so the candidate is not admitted.

It does not establish live or forward performance, independently reproduced performance,
capacity, diversification, expected book drawdown, peer review, external publication, or future
return. The raw and derived market rows are not licensed for public redistribution. A checksum
proves byte identity, not economic correctness.

## 2. Hypothesis and related literature

Perpetual futures use recurring funding transfers to keep a non-expiring contract near its spot
index. Positive funding ordinarily transfers value from longs to shorts; negative funding reverses
the direction. Persistent funding can therefore represent compensation for supplying balance
sheet to crowded positioning, but it can also proxy for crash exposure, constrained arbitrage,
liquidation risk, and speculative demand.

For instrument \(i\) at decision time \(t\), the registered signal is the negative mean of the 21
most recent funding settlements available to the system, annualized by the implementation:

\[
c_{i,t}=-\operatorname{mean}(f_{i,t-20},\ldots,f_{i,t})\times 3\times365.
\]

The negative sign ranks expensive positive-funding contracts toward the short side and
negative-funding contracts toward the long side. The factor is a cross-sectional ranking input;
its annualization scale does not itself create return. Funding information becomes available five
minutes after its recorded settlement timestamp in the portable data model.

The economic prior is consistent with work on perpetual-futures pricing, constrained arbitrage,
and crypto basis. He, Manela, Ross, and von Wachter describe how funding, margin, liquidation, and
trading frictions jointly anchor perpetuals rather than create riskless convergence. Ackerer,
Hugonnier, and Jermann formalize no-arbitrage pricing for perpetual futures. Schmeling, Schrimpf,
and Todorov document large and time-varying crypto carry linked to trend chasing and scarce
arbitrage capital. Chi and coauthors find basis prominent among the crypto-futures signals they
study. These papers motivate the test; none validates ALPHAC's data, portfolio construction,
costs, or result.

The falsifiable alternative is that the spread is unstable, selected from a large research union,
insufficient after stress and impact, positively exposed to the existing book, or operationally
untradeable. Any of those outcomes prevents admission even when the primary Sharpe is positive.

## 3. Prospective design

### 3.1 Identity and trial accounting

The preregistration was frozen before portable-v1 returns were computed. It fixed family account
`crypto_carry`, return identity `crypto_carry_portable_v1`, config hash `50d9e8b059fee773`, and
hypothesis identity `da5f5f47f99f9bd2`. Reservation ordinal 229 charged one hypothesis. The
runner's execution token authorized exactly one primary return trial; the ledger contains one
matching immutable record and no unregistered variant was used to replace it.

The 228 earlier identities remain a retired historical epoch. This trial enters the prospective
v7 epoch and the complete 229-identity union used by the runtime DSR calculation. The seriality
rule requires this trial's complete, hash-valid packet before a future identity can be reserved.

### 3.2 Data decision before returns

The source authority was a fresh cache of checksum-verified official Binance public archives.
Eligibility required every official object declared by the data contract. Fourteen monthly
funding objects for `ICPUSDT`, covering July 2021 through August 2022, were unavailable; the symbol
was excluded before the return engine ran. No local or API gap-fill substituted for the missing
official objects. Fifty-seven instruments remained.

The fresh official OHLCV archives disagreed with the older frozen local state at 1,256 overlapping
rows. This trial deliberately uses the current official bytes and is therefore a new prospective
identity, not an exact replication of the historical selected artifact. Instrument lifecycle
metadata removes observations outside listing and delisting intervals. The resulting private lake
contains 2,137,040 OHLCV rows, 272,846 funding rows, and 108 point-in-time universe intervals when
read through the production interfaces.

The exchange metadata history remains a limitation. Fresh historical `exchangeInfo` snapshots
were not available, so the earliest observed metadata version is made valid from the run start
while retaining its original validity timestamp as lineage. That rule was frozen and disclosed
before returns, but it prevents an independent historical-metadata claim.

### 3.3 Walk-forward and execution model

The trial configuration was fixed as follows:

| Parameter | Registered value |
|---|---:|
| Declared data window | 2021-06-01 to 2026-06-01 UTC |
| Training window | 6,048 hourly bars |
| Test window | 1,512 hourly bars |
| Purge / embargo | 72 / 168 bars |
| Walk-forward legs | 25 |
| Signal | `carry_fund_21` |
| Allocator | cross-sectional rank |
| Rebalance interval | 168 hours |
| No-trade band | 0.001 of equity |
| Initial simulated capital | $100,000 |
| Machine-learning (ML) / regime gates | off / off |

The current event-driven engine fills under its next-open model. The frozen base configuration
declares 5 basis points of perpetual taker fees, a default 2.5-basis-point half-spread, 2 basis
points of latency cost, square-root market impact, and a 1% average-daily-volume (ADV) order cap.
Portfolio limits include
1.0 gross exposure, 0.5 absolute net exposure, a 0.15 per-position limit, a 0.15 annualized
volatility target, and a 1.5 maximum volatility scale. The risk state halves gross at 10% account
drawdown and flattens at 15%, followed by a 336-hour cooldown.

These are simulated execution assumptions. The result does not contain broker fills or evidence
that the model matches realizable queue position, venue fragmentation, outage behavior, or market
impact at larger capital.

### 3.4 Pre-execution input snapshot

After the derived signal frame was computed but before the first execution leg, the runner sealed:

- 2,454,144 derived signal rows;
- 108 universe intervals and 57 instrument metadata rows;
- 603 raw OHLCV and funding partitions;
- the resolved run declaration; and
- 174 source and environment files.

The complete snapshot contains 781 files and 102,831,710 bytes. Its inventory root is
`c8b573712103907130a301f22d578feb07e31de0939339450f766b2d037df822`.
The snapshot is private because redistribution rights are not established. Its public receipt
exposes hashes, counts, and methods only.

## 4. Primary result

The stitched out-of-sample path begins after the first training window, on 8 February 2022, and
ends on 1 June 2026. Headline ratios use Coordinated Universal Time (UTC) day-last equity and daily
simple returns; hourly ratios are diagnostics.

| Measure | Immutable value |
|---|---:|
| Daily return observations | 1,574 |
| Initial / final simulated equity | $100,000.00 / $155,880.82 |
| Total return / CAGR | 55.88% / 10.84% |
| Annualized Sharpe | 0.9689 |
| Annualized volatility | 11.01% |
| Sortino / Calmar | 1.4336 / 0.8813 |
| Daily / hourly-bar maximum drawdown | 12.30% / 13.50% |
| Annual turnover | 31.44x |
| Fees paid | $7,398.00 |
| Net funding cashflow | $18,408.38 |
| PSR / DSR | 0.9776 / 0.0914 |

The daily maximum drawdown ran from the 18 June 2022 peak to the 12 August 2023 trough. The risk
counters report 16,591 half-gross bars, no halted-flat bars, 225 rebalances, and 225 fallback uses.
The result is therefore not a frictionless funding accrual: it depends materially on the optimizer,
risk state, price path, turnover, and funding cashflows.

### 4.1 PSR and DSR answer different questions

PSR 0.9776 measures evidence that the path's Sharpe exceeds zero under the implemented
non-normality adjustment. DSR 0.0914 instead compares it with an expected maximum Sharpe after the
recorded search burden. The runtime report used all 229 union identities and an expected maximum
per-period Sharpe of 0.08437. The observed annual Sharpe can therefore look promising while the
deflated probability remains low.

The generic walk-forward report also emits `clears_dsr_gate: false` for a 0.95 indicator. That
field is not the governing per-sleeve decision rule here. The reservation-bound v7 contract says
per-sleeve DSR must be measured and published but is not itself gated at 0.95; incremental
admission is determined by the full conjunction of standalone, stress, execution, capacity, and
book-contribution evidence. Calling this trial a DSR KILL would silently reintroduce a gate the
contract removed. Suppressing the low DSR would be equally misleading. This paper does neither.

### 4.2 Temporal and leg stability

Sixteen of 25 walk-forward legs had positive Sharpe and nine were nonpositive. Leg Sharpe ranged
from -2.4817 to 6.6152, with median 0.4756. Short legs make the extrema noisy, so they are reported
as diagnostics rather than independent trials or confidence intervals.

| UTC calendar segment | Daily observations | Compounded return | Annualized Sharpe |
|---|---:|---:|---:|
| 2022 partial | 326 | -6.79% | -0.5857 |
| 2023 | 365 | 2.18% | 0.2989 |
| 2024 | 366 | 19.63% | 1.7475 |
| 2025 | 365 | 11.57% | 0.9781 |
| 2026 partial | 152 | 21.40% | 3.7872 |

The result is not uniformly positive through time. Its strongest annualized segment is also a
partial year. Removing one calendar year at a time leaves annualized Sharpe between 0.6232 and
1.4346; the minimum occurs when the partial 2026 segment is excluded. This same-path diagnostic
is encouraging but does not substitute for a preregistered regime stress or a path matrix.

## 5. Admission audit and unresolved evidence

The primary path clears two directly evaluated v7 thresholds: net Sharpe is above 0.15 and 1,574
daily observations exceed the 756-observation minimum. DSR is present, satisfying its measurement
requirement. Those facts are necessary and insufficient.

The following evidence is not yet established for this identity:

- Newey-West significance and autocorrelation-inflation ratio under a frozen lag rule;
- stressed-cost and stressed-execution Sharpe;
- an execution-scenario bundle for the applicable operational dimensions;
- a monotone capacity curve with at least three capital points and a $500,000 floor decision;
- ordinary and crisis-conditional correlation with the existing book, including one-sided 95%
  bounds;
- candidate-to-book average correlation and the change in the book's average pairwise
  correlation;
- point and bootstrap-lower-bound book Sharpe contribution;
- leave-one-period-out book Sharpe contribution;
- expected-shortfall and maximum-drawdown deltas;
- expected and 95th-percentile book maximum drawdown; and
- full-union book DSR and overlay replay.

PBO is null with status `NOT_DEFINED_SINGLE_REGISTERED_IDENTITY_NO_PATH_MATRIX`. A single path
does not supply the cross-configuration matrix required by combinatorially symmetric
cross-validation (CSCV). Reporting null is not a pass; it also is not the fabricated value zero.

The observed 12.30% candidate maximum drawdown is not directly comparable with the program's 11%
**expected book maximum drawdown** objective. One is the deepest realized decline on this
candidate simulation; the other is a distributional estimand for the combined book. The book
quantity remains unmeasured.

The formal disposition is therefore:

```text
INCOMPLETE / NOT ADMITTED
```

It is not `KILL` because no measured applicable gate has yet been shown to fail in the sealed
receipt. It is not `ADMIT` because the listed required gates are unmeasured. The final evidence
packet may close the identity as permanently incomplete, but packet completion cannot convert the
candidate into an admission. No threshold has been altered after observing the result.

## 6. Relationship to the historical crypto-carry result

The earlier selected `crypto_carry_wk` artifact reported Sharpe 0.6766, 19.60% maximum drawdown,
and final simulated equity of $138,236.27 over the same ending date. A current-state attempt to
replay that historical configuration produced Sharpe 0.1065 and final equity $103,335.16. The old
run had not sealed exact code and derived inputs, so its multi-year difference is not uniquely
attributable.

Portable v1 does not repair or overwrite that artifact. It differs in its current official input
bytes, 57-name eligible set, prospective v7 reservation, and exact pre-execution snapshot. Its
Sharpe of 0.9689 is a new first measurement, not evidence that the historical 0.6766 was correct.
The historical correction remains open and independently visible in the family lineage paper.

## 7. Reproducibility and data-rights boundary

The publication-safe result receipt is
`artifacts/research/crypto_carry_portable_v1_result.json`. It binds the preregistration, reservation,
run configuration, v7 contract, exact ledger record, result inventory, and verified private input
snapshot. Its initial content hash is
`sha256:00c516f5c5465e399aff5a03f99e65897c370c88482a4387c3e34ac0668a3c7f`.

The receipt can be regenerated and compared without computing a new return path:

```bash
uv run python scripts/seal_crypto_carry_portable_v1_result.py --check
```

This command rehashes every private snapshot leaf, recomputes the same-path diagnostics from the
sealed equity curve, and fails if any bound result, ledger record, source, environment, or contract
byte has drifted. It is an integrity verification, not an independent return reproduction.

An external reader can inspect the public-safe receipts and source but cannot independently replay
the market path from the intended public bundle because the underlying archive rows and derived
signal frame are private. Public redistribution remains prohibited unless each source's rights are
established. An exact clean-environment replay from a rights-cleared input package and an
independent human reproduction are still required before those statuses can be claimed.

## 8. Threats to validity

The central threats are explicit:

- **Selection burden:** the low DSR shows that one attractive path must be interpreted in the
  context of a large research union.
- **Single registered path:** no path matrix exists for PBO, and no parameter perturbation may be
  invented post-result without a new identity.
- **Metadata approximation:** early historical instrument metadata uses a frozen deterministic
  fallback rather than contemporaneously archived exchange snapshots.
- **Model risk:** fills, spreads, latency, impact, funding timing, risk controls, and venue behavior
  are simulated.
- **Capacity unknown:** scaling can alter impact and portfolio decisions nonlinearly.
- **Portfolio interaction unknown:** standalone Sharpe does not establish negative correlation or
  positive book contribution.
- **Data redistribution:** private inputs prevent public push-button reproduction today.
- **No forward evidence:** this is historical walk-forward evidence, not a broker-reconciled live
  record.

These limitations define the next research work; they are not footnotes that a positive Sharpe can
cancel.

## 9. Conclusion

Portable v1 is the strongest ALPHAC crypto-carry result in provenance quality, not yet in admission
status. One registered and fully input-snapshotted simulation produced Sharpe 0.9689 with 12.30%
maximum drawdown and positive leave-one-year-out diagnostics. The same result also produced DSR
0.0914 under the complete union burden and lacks the stress, capacity, execution, diversification,
and book-risk evidence required by the governing contract.

The correct scientific conclusion is neither promotional success nor automatic rejection. It is a
promising, immutable primary measurement held at `INCOMPLETE / NOT ADMITTED` while the missing
tests remain missing. The work is credible only if that boundary survives publication unchanged.

## References

1. Ackerer, D., Hugonnier, J., & Jermann, U. J. *Perpetual Futures Pricing*.
   [NBER Working Paper 32936](https://doi.org/10.3386/w32936).
2. Chi, Y., Hao, W., Hu, J., & Ran, Z. (2023). *An empirical investigation on risk factors in
   cryptocurrency futures*.
   [Journal of Futures Markets](https://doi.org/10.1002/fut.22425).
3. He, Z., Manela, A., Ross, O., & von Wachter, V. *Fundamentals of Perpetual Futures*.
   [arXiv:2212.06888](https://arxiv.org/abs/2212.06888).
4. Schmeling, M., Schrimpf, A., & Todorov, K. *Crypto Carry*.
   [SSRN 4268371](https://doi.org/10.2139/ssrn.4268371).
5. Bailey, D. H., & López de Prado, M. (2014). *The Deflated Sharpe Ratio: Correcting for
   Selection Bias, Backtest Overfitting, and Non-Normality*.
   [Journal of Portfolio Management](https://doi.org/10.3905/jpm.2014.40.5.094).
6. Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2017). *The Probability of
   Backtest Overfitting*.
   [Journal of Computational Finance](https://doi.org/10.21314/JCF.2016.322).

## Authorship and credit

Arhan Canli conceived the ALPHAC research program, designed and implemented the AlphaForge system,
specified the prospective trial and governance controls, assembled and audited the evidence, and
is the accountable author of this paper. Tool-assisted drafting or engineering does not transfer
authorship or responsibility. Canli Capital is the project identity; no institutional affiliation,
peer review, external replication, or investment endorsement is implied.
