# When a Forward Sharpe Ratio Becomes Evidence

A forward Sharpe ratio should not become a headline merely because a short paper-trading curve can
produce one. This paper defines the precommitted evidence states used by ALPHAC: when a point
estimate may be shown, when a target is only observed, and what must be true before the target can
be described as statistically established.

**Author:** Arhan Canli  
**Affiliation:** Canli Capital / AlphaC Algorithms  
**Version:** 1.0, 2026  
**Capital boundary:** Alpaca and AlphaForge paper trading only; no real capital  
**Machine contract:** `/glassbox/forward_evidence_contract.json`  
**Current evaluation:** `/glassbox/forward_evidence_maturity.json`

## Abstract

The easiest time to report an extraordinary risk-adjusted return is when the record is shortest.
Sampling error is widest, the worst regime may not have occurred, and one favorable sequence can
dominate the estimate. ALPHAC therefore separates four states: an immature record, an
estimate-eligible record, a point target that has been observed but not established, and a target
that has cleared a frozen sample-length and Probabilistic Sharpe Ratio threshold. The rule requires
252 observed daily returns before publishing a mature point estimate and 756 before statistical
establishment is possible. Establishment additionally requires an annualized point Sharpe of at
least 1.5 and at least 0.95 probability, under the non-normal Probabilistic Sharpe Ratio formula,
that the true annualized Sharpe exceeds 1.5. Configuration continuity, record continuity, and a
fresh passing broker reconciliation are mandatory provenance gates. Realized drawdown, modeled
expected maximum drawdown, and modeled tail drawdown are reported as different quantities. The
standard is deliberately harder to satisfy than displaying a computed ratio because its purpose is
to prevent a target from becoming an achievement through presentation alone.

## 1. The claim being controlled

A Sharpe ratio is a ratio of estimated mean excess return to estimated return volatility. Both
terms are uncertain, and their ratio is especially unstable over a short record. Annualization does
not create information: multiplying a daily ratio by the square root of 365 changes its unit, not
the number of observations supporting it.

The controlled claim is therefore not “a Sharpe ratio can be calculated.” It is whether the public
record supports one of these progressively stronger statements:

1. the record exists but is too short for a mature estimate;
2. a mature point estimate may be published;
3. the point estimate is at or above the governing target; or
4. the evidence supports the stronger claim that the true Sharpe exceeds the target with the
   precommitted probability and sample length.

These statements are not interchangeable. In particular, a point estimate at or above 1.5 is an
observation about the sample. It is not statistical establishment of a forward Sharpe of 1.5.

## 2. Return series and annualization

The input is the flagship paper curve: strictly increasing UTC dates and finite, strictly positive
equity marks. For consecutive published marks (E_{t-1}) and (E_t), the simple return is

\[
r_t = \frac{E_t}{E_{t-1}} - 1.
\]

Missing calendar dates are not filled with synthetic zero returns. A fabricated zero would alter
both the mean and variance while pretending that a mark existed. Instead, the observed
mark-to-mark series is evaluated and a separate continuity audit must pass. This keeps the
performance calculation and the missing-record question visible as two distinct checks.

For (T) observed returns, the per-period Sharpe is

\[
SR_d = \frac{\bar r}{s_r},
\]

where (s_r) is the sample standard deviation with one degree-of-freedom correction. The reported
annualized point estimate is

\[
SR_{ann} = SR_d\sqrt{365}.
\]

The 365-day convention matches the flagship's cross-asset paper calendar and the engine's frozen
daily analytics convention. It is a reporting convention only. The probabilistic calculation uses
the per-period ratio and the actual return count.

## 3. Probability that Sharpe exceeds the target

The Probabilistic Sharpe Ratio accounts for finite sample length and non-normal return moments. Let
(\gamma_3) be sample skewness and (\gamma_4) non-excess kurtosis, where a Gaussian distribution
has kurtosis 3. Against per-period benchmark (SR^*), the probability is

\[
PSR(SR^*) = \Phi\left(
\frac{(SR_d-SR^*)\sqrt{T-1}}
{\sqrt{1-\gamma_3 SR_d + \frac{\gamma_4-1}{4}SR_d^2}}
\right).
\]

ALPHAC sets (SR^*=1.5/\sqrt{365}). This is stricter and more relevant than testing only whether
Sharpe is positive. A probability that the true Sharpe exceeds zero may establish a positive edge;
it does not establish that the governing 1.5 target has been reached.

The implementation calls the same tested Probabilistic Sharpe Ratio routine used by the research
engine. It does not feed an annualized ratio into a per-period formula. The annualized target is
converted to the daily benchmark first, and (T) remains the count of daily return observations.

## 4. Frozen evidence states

| State | Minimum evidence | Permitted public claim |
|---|---:|---|
| `IMMATURE_RECORD_TOO_SHORT` | Fewer than 252 returns | Publish cumulative return and realized drawdown, but no mature Sharpe point estimate. |
| `ESTIMATE_ELIGIBLE_TARGET_NOT_OBSERVED` | At least 252 returns | Publish the point estimate and probability; state that the 1.5 target is not observed. |
| `TARGET_OBSERVED_NOT_ESTABLISHED` | Point Sharpe at least 1.5, but the establishment conditions are incomplete | State that the sample point estimate crossed the target and explicitly state that it is not established. |
| `TARGET_STATISTICALLY_ESTABLISHED` | At least 756 returns, point Sharpe at least 1.5, and (PSR(1.5)\ge0.95) | State that the forward paper record statistically establishes the target under this contract, while retaining the paper-capital boundary. |
| `FAIL_CLOSED_PROVENANCE` | Any mandatory provenance check fails | Suppress establishment regardless of the calculated ratio and publish the failed checks. |

The 252-return estimate threshold prevents a few weeks or months of noise from becoming a polished
annual figure. The 756-return establishment threshold aligns the live claim with the research
program's three-year minimum out-of-sample evidence horizon. Neither number is selected from the
observed result. Both were frozen while the current record remained immature.

## 5. Provenance is part of the statistic

A return series cannot establish the performance of a specification unless the specification and
record are identifiable. Every one of the following checks is mandatory:

- every constituent is labelled `PAPER_ONLY`;
- the measured live-configuration fingerprint matches its declaration and the fingerprint frozen
  for the evidence epoch;
- the record-continuity artifact has the required schema, a valid content hash, covers the latest
  flagship mark, and passes its declared gap policy;
- the Alpaca reconciliation has the required schema and a valid content hash;
- all dedicated Alpaca paper accounts reconcile, remain distinct, and report a passing status;
- broker evidence is no more than 36 hours old and is not materially earlier than the paper state;
- the current signed transparency-chain head has the required v2 schema, every link and Ed25519
  signature validates, every prospectively disclosed payload rehashes exactly, and the head payload
  equals the canonical daily paper state evaluated for Sharpe; and
- the locally simulated crypto account's latest cycle carries a complete order-book mark for every
  position, uses no entry-price fallback, reconciles cash plus marked market value to account
  equity, and covers the flagship's latest published date; and
- the expected-drawdown study has the required model schema.

If any check fails, the evaluator retains the underlying numerical state for diagnosis but changes
the public maturity state to `FAIL_CLOSED_PROVENANCE`. A strong return cannot compensate for an
unidentified configuration, stale broker evidence, or a discontinuous curve.

The transparency requirement is prospective and does not manufacture historical completeness.
Entries before the declared payload-disclosure boundary contain opaque signed hashes; their
underlying snapshots cannot be reconstructed from the public chain. OpenTimestamps checkpoints
add timing evidence for selected heads, but do not prove broker truth or replace payload disclosure.

The position-attribution requirement is also prospective. Rows written before the mark-aware
schema retain null mark and P&L fields; they are not backfilled from aggregate equity. Until the
first genuine complete cycle is persisted, the public maturity state is
`FAIL_CLOSED_PROVENANCE` with the shorter-record numerical state retained underneath it.

Any trading configuration change starts a new evidence epoch. Returns from materially different
specifications cannot be pooled silently. The live-change declaration records the boundary, and a
new contract must state whether any prior observations remain admissible for a new claim.

## 6. Three drawdown quantities, not one

The public record distinguishes:

1. **Realized live maximum drawdown:** the deepest peak-to-trough decline observed in the paper
   curve to date. It is descriptive and generally understates long-horizon risk when the record is
   short.
2. **Study-cell expected maximum drawdown:** the mean maximum drawdown across the declared
   simulation paths for one explicitly parameterized study cell. It can be compared with the 11%
   portfolio objective only after a production-equivalence audit establishes that the study cell
   represents the current live book.
3. **Study-cell p95 maximum drawdown:** the 95th percentile across those paths. It must appear
   beside the expected value because an acceptable mean can coexist with an unacceptable tail.

The expected maximum-drawdown objective is not a stop-loss and does not imply that losses are
bounded at 11%. A realized drawdown below 11% does not establish the modeled objective, and a model
estimate below 11% does not guarantee future realized losses.

The sealed current study uses 96 two-year paths, fourteen daily sleeves and a 10% annualized
book-level volatility target. The declared live paper composite has four sleeves, mixed hourly and
daily timebases, fixed weights and no second book-level volatility target or drawdown ladder after
constituent sizing. Constituents using `BlendStrategy` have their own 15% target; that setting is
not an ALPHAC-level target. Production shrinkage is also absent from the study. The study's 10.25%
expectation and 18.76% p95 are therefore published as study-cell results, not estimates of the
current live book.

A second, predeclared current-composition study maps the exact four fixed weights and strategic
overlay with no ALPHAC-level volatility target. It removes the selected-window mean and reports
both a 10,000-path circular block bootstrap and a 10,000-path 0.50-correlation stress-regime model.
Its conservative expected maximum drawdown is 9.32%, inside the 11% objective; its p95 is 16.45%,
outside it. This is stronger configuration mapping, not live establishment: the common history
begins after COVID and 2022 and the models do not replay constituent instruments, execution gaps
or dynamic ladder state.
`/glassbox/forward_drawdown_evidence.json` records the failed equivalence checks and binds the study,
contracts and implementation sources by SHA-256. The maturity report labels the objective
`LIVE_EXPECTED_MAX_DRAWDOWN_NOT_ESTABLISHED`.

## 7. Diversification evidence is a separate gate

The exact current-composition diversification study uses the same four fixed-weight sleeve curves,
missing-mark policy and strategic overlay as the current drawdown study. Sleeve correlation is
computed from the four sleeve returns; the overlay remains separate. The 1,061-row research window
produces an average pairwise correlation of +0.0248 and a synchronized 10,000-sample, 63-row block-
bootstrap upper 95% bound of +0.0487. The largest ordinary pair is +0.2098 and its upper bound is
+0.3025.

The prospective contract requires an average point no greater than 0.00 and an average upper bound
no greater than +0.10. The current point therefore **fails** even though its confidence bound,
ordinary-pair and stressed-design comparisons pass. Existing sleeves are not retroactively
adjudicated, and “near zero” is not used as a substitute for the signed gate. The study reports a
1.8153 sleeve-only diversification ratio, 3.8988 effective independent sleeves and fixed-to-cash
marginal historical book-Sharpe diagnostics, all labelled research simulation rather than forward
evidence. The research curves end before the broker-reconciled record begins, so live-forward
diversification remains unestablished.

## 8. Reproduction and mutation checks

The evaluator is `scripts/evaluate_forward_evidence_maturity.py`. It reads twelve authorities:

- `config/forward_evidence_contract.json`;
- `data/paper/state.json`;
- `artifacts/engineering/record_continuity.json`;
- `artifacts/engineering/alpaca_broker_reconciliation.json`;
- `artifacts/analysis/drawdown_live_estimator/result.json`;
- `artifacts/analysis/current_book_drawdown/result.json`;
- `artifacts/analysis/current_book_diversification/result.json`;
- `artifacts/engineering/forward_drawdown_evidence.json`;
- `meridian/public/glassbox/transparency_log.json`;
- `artifacts/engineering/crypto_position_attribution.json`;
- `artifacts/engineering/crypto_position_attribution_rollout_verification.json`; and
- this methodology paper.

It emits `artifacts/engineering/forward_evidence_maturity.json`, including SHA-256 bindings to the
contract, state, continuity report, broker reconciliation, drawdown and diversification studies,
sealed drawdown evidence, transparency chain, crypto position attribution, rollout verification,
and this paper. The result carries a content hash over its canonical body and is copied byte-for-
byte to both public hosts.

For crypto attribution, completeness is not inferred from populated columns alone. The evaluator
independently recomputes every position's market value as quantity times mark and unrealized P&L as
quantity times the difference between mark and average entry. Non-finite values, non-positive
prices, fallback marks, per-position arithmetic residuals, or failure of cash plus reconstructed
market value to equal recorded account equity all fail the Sharpe provenance gate closed. A flat
cycle is retained as a valid account observation but cannot certify a position-mark path it did not
exercise; certification waits for a non-empty natural cycle.

Runtime rollout is a separate mandatory authority. Before deployment it deterministically states
`NO_DEPLOYMENT_RECEIPT`, performs no Frankfurt query, and fails provenance closed. After a
hash-bound deployment receipt exists, it can pass only on a strictly later, non-empty natural cycle
with the complete attribution verdict above. The first successful receipt is then frozen for that
exact deployment receipt, preventing later cycles from rewriting the historical claim about what
first proved the runtime.

Run the focused verification with:

```text
uv run python scripts/evaluate_forward_evidence_maturity.py
uv run pytest -q tests/unit/test_forward_drawdown_evidence.py tests/unit/test_forward_evidence_maturity.py
```

The tests construct synthetic curves for every evidence state. They also mutate the configuration
fingerprint, continuity verdict, broker verdict, chain signature, disclosed head payload, and
crypto-attribution completeness. Drawdown-specific mutations alter the simulation design, selected
study cell, quantile ordering and declared live configuration. Every mutation must fail closed. The
test for statistical establishment uses a sufficiently long synthetic series; it does not weaken
the 756-return gate to make a short fixture pass.

## 9. Limits

This standard governs the language used for one continuous paper-trading specification. It does
not turn paper execution into funded performance, prove that fills scale to institutional capital,
eliminate non-stationarity, or guarantee that a statistically established historical ratio will
persist. PSR uses observed skewness and kurtosis but cannot summarize every form of path dependence
or regime change. The broker reconciliation is self-published and broker-derived, not a third-party
attestation.

The standard also does not substitute for trial deflation in research. A selected backtest must
still carry the full search context through Deflated Sharpe Ratio and the union trial ledger. The
forward paper specification is evaluated as a predeclared continuous record; it is not permission
to select the best live variant after observing several.

## Claim boundary

This is a methodology and disclosure standard authored by Arhan Canli. It defines when ALPHAC may
describe a paper-trading Sharpe target as observed or statistically established. It makes no claim
that the current record has established the target, no claim of real-money performance, and no
guarantee of future returns or maximum loss.

## References

- Bailey, David H., and Marcos López de Prado. “The Sharpe Ratio Efficient Frontier.” *Journal of
  Risk* 15, no. 2 (2012).
- Bailey, David H., and Marcos López de Prado. “The Deflated Sharpe Ratio: Correcting for Selection
  Bias, Backtest Overfitting, and Non-Normality.” *Journal of Portfolio Management* 40, no. 5
  (2014): 94–107. <https://doi.org/10.3905/jpm.2014.40.5.094>
- Sharpe, William F. “Mutual Fund Performance.” *Journal of Business* 39, no. 1 (1966): 119–138.
  <https://doi.org/10.1086/294846>
