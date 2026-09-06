# AlphaMax equity momentum: signal, trial lineage, and evidence boundary

**Short title:** AlphaMax equity momentum: complete trial lineage

**Author:** Arhan Canli, Founder, System Architect, and Quantitative Researcher, Canli Capital  
**Research system:** ALPHAC / AlphaForge  
**Family key:** `alphamax_equity_momentum`  
**Status:** public research record; not peer reviewed; not an investment solicitation  
**Evidence date:** 2026-08-24

## Abstract

AlphaMax is ALPHAC's US-equity long/short momentum program. Its canonical signal is 12-minus-1
cross-sectional momentum: rank securities by split-adjusted return from approximately twelve
months ago through one month ago, then hold a dollar-neutral long/short portfolio. This paper
does not present a single favourable backtest as proof. It reconciles the entire charged family:
115 distinct hypothesis identities recorded from 2026-06-20 through 2026-08-17 across the primary
and Sharadar research ledgers.

The evidence is deliberately uncomfortable. A frozen 2023–2026 construction reported net Sharpe
0.91 and maximum drawdown 8.68% in the persisted deployed-path artifact. The later, preregistered
2005–2026 replication reported net Sharpe approximately -0.05 and a drawdown exceeding one third, failing
its DSR and return gates. Construction studies did not rescue the family: a 4-by-4 weighting and
breadth grid failed its family-wise Reality Check, and beta-neutral, volatility-scaling, and
short-tail modifications were not adopted. The correct claim is therefore not “momentum is
proven.” It is that AlphaMax is a live paper research sleeve with a plausible mechanism, a selected
short-window survivor, a failed deep-history replication, and an explicit forward burden of proof.

## Claim boundary

This paper supports four claims only:

1. The economic hypothesis and implementation can be stated precisely.
2. Every charged identity in this family is enumerated in the public machine-readable manifest.
3. Positive, null, and negative results are preserved together, including later corrections.
4. Current paper trading is forward evidence collection, not external attestation and not proof of
   the governing Sharpe or drawdown objectives.

It does **not** establish a forward Sharpe, expected maximum drawdown, future return, investment
capacity, or live-money performance. The program remains paper-only and not externally attested.

## Economic mechanism and falsifiable hypothesis

The hypothesis is delayed cross-sectional price adjustment: stocks with high intermediate-horizon
returns continue to outperform recent losers for a limited horizon. ALPHAC excludes the most recent
month because short-horizon reversal can contaminate the continuation signal. The mechanism is
falsified for this implementation if a point-in-time, survivorship-aware, net-of-cost walk-forward
cannot produce positive and statistically defensible returns after the complete family-wide search
is charged.

The literature motivates a prior, not a result:

- Jegadeesh and Titman document intermediate-horizon return continuation and later partial
  reversal in US equities ([Journal of Finance, 1993](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x)).
- Asness, Moskowitz, and Pedersen find common momentum structure across asset classes and connect
  it to funding-liquidity risk ([Journal of Finance, 2013](https://doi.org/10.1111/jofi.12021)).
- Daniel and Moskowitz show that momentum can crash during panic-state rebounds, making tail and
  regime tests load-bearing rather than decorative
  ([Journal of Financial Economics, 2016](https://doi.org/10.1016/j.jfineco.2015.12.002)).
- Barroso and Santa-Clara study volatility management as a response to momentum's time-varying
  risk ([Journal of Financial Economics, 2015](https://doi.org/10.1016/j.jfineco.2014.11.010)).
- Korajczyk and Sadka demonstrate that trading costs and capacity materially constrain momentum
  implementations ([Journal of Finance, 2004](https://doi.org/10.1111/j.1540-6261.2004.00656.x)).
- Novy-Marx isolates the intermediate horizon as the principal source of the effect
  ([Journal of Financial Economics, 2012](https://doi.org/10.1016/j.jfineco.2011.05.003)).

These papers do not validate ALPHAC's data, universe, execution, or selected configuration.

## Literature and overlap decision

The literature supports treating intermediate-horizon momentum as one economic family. It does not
support counting each allocator, universe, cadence, quality overlay, volatility forecast, or breadth
choice as an independent sleeve. ALPHAC therefore assigns all 115 identities below to one family,
charges every implementation to the union trial denominator, and grants the family at most one
portfolio-sleeve slot. Residual momentum, reversal overlays, and quality-conditioned momentum are
not credited as diversification unless future evidence demonstrates both an independent mechanism
and sufficiently low out-of-sample return correlation. None does so here.

## Exact ALPHAC implementation

The canonical feature is `eq_mom_252_21`:

```text
signal(i,t) = ln(adjusted_close(i,t-21) / adjusted_close(i,t-252))
```

The factor is computed on the equity session grid and cross-sectionally standardized inside the
point-in-time eligible universe. Corporate actions must be knowable by the decision timestamp;
universe membership is applied before cross-sectional transforms. Portfolio weights decided using
information through session `t` become effective on `t+1`, preventing same-close execution.

The pre-registered deep-history specification fixed a top-200 liquidity universe with hysteresis,
30 names per side, dollar neutrality, quarterly rebalancing, a trailing-126-session 12% volatility
target, 2.0-times gross cap, purged anchored-expanding walk-forward, and explicit equity costs. A
later operational construction used a wider top-2000 universe, 100 names per side, inverse-volatility
leg weights, quarterly signal horizon, and explicit commission, spread, latency, and borrow costs.
Those are different hypotheses. The ledger correctly charges changes in universe, breadth, cadence,
allocator, or signal; only `start`/`end` rolling-window changes are exempt from the hypothesis count.

## Trial lineage

The public manifest binds this family key to 115 distinct identities. The grouping below is an
accounting view, not permission to collapse the denominator.

| Identity group | Charged identities | Research question |
|---|---:|---|
| Canonical `eq_mom_252_21` | 23 | Universe, cadence, horizon, and walk-forward implementations |
| Weighting × breadth forensic grids | 48 | The 16-cell primary grid plus 16 no-drift and 16 volatility-guard return configurations |
| Construction forensic arms | 8 | Cadence, breadth, universe, and train/test attribution |
| Live-window hysteresis arms | 6 | Exit-band and minimum-hold settings on the selected K=30 construction |
| Deep-history turnover arms | 8 | Monthly/quarterly cadence crossed with baseline, hysteresis, hold, and combined settings |
| Volatility-scaling overlays | 5 | Whether alternative ex-ante risk forecasts improve the sleeve |
| Momentum + short reversal | 5 | Whether recent reversal repairs the core signal |
| Momentum + operating margin | 5 | Whether quality conditions the momentum exposure |
| Momentum + earnings yield | 3 | Whether value conditions the momentum exposure |
| Residual reversal | 1 | Whether residualized reversal adds independent information |
| Signal-to-noise momentum | 1 | Whether volatility normalization improves ranking |
| Momentum ensemble | 1 | Whether fixed horizon blending improves robustness |
| Short-horizon equity momentum | 1 | Whether a 63/42-session definition generalizes |
| **Total** | **115** | Every row remains in the family-wide search burden |

Machine labels covered by this family are `eq_mom_252_21`, `eq_rev_21`,
`eq_operating_margin`, `eq_earnings_yield`, `eq_rev_resid_21`, `eq_mom_sn_252_21`,
`eq_mom_ens`, `eq_mom_63_42`, `forensic_alphamax_construction`,
`forensic_alphamax_weighting`, `alphamax_hyst_live`, `alphamax_turnover`, and
`alphamax_volscale`. Variant identifiers remain attached to
their exact hypothesis keys in the manifest rather than being treated as independent economic
families.

The machine-readable source of truth is
[`/glassbox/trial_packet_manifest.json`](/glassbox/trial_packet_manifest.json). Select identities
where `research_family_key` equals `alphamax_equity_momentum`; each row provides the exact
`hypothesis_key`, immutable first measurement, source ledger, candidate papers, and missing packet
sections.

## Results and decisions

### Selected short-window artifact

The persisted `k30_dn_63` deployed-path artifact covers 2023-07-06 through 2026-06-01 and reports
net Sharpe 0.9071, cumulative return 24.54%, annualized volatility 13.07%, maximum drawdown 8.68%,
and annual turnover 4.11. It is the historical survivor that motivated paper deployment. These are
backtest statistics from a selected configuration, not forward performance.

### Fresh-vendor clean-workspace replay

On 2026-08-24, I reacquired the available Polygon stock data under the owner's current licensed
access, reconstructed the exact 375-identifier strategy-window universe union, sealed a private
input inventory, and ran the historical command at pinned source commit
`fd3e930f41b0a62b222ecda4ab83bae21a4ce9f2` in a temporary workspace outside the repository. The
current entitlement begins on 2021-08-23. It excludes 58 requested sessions from 2021-06-01
through 2021-08-20, so the manifest does not claim a complete historical universe lookback. The
gap precedes the first leg's training and test periods but intersects the global feature warm-up.

The replay did not reproduce the historical result exactly. Timestamps and configuration matched,
but the equity frame and log returns differed. The largest absolute equity-path difference was
$574.69. Historical annualized Sharpe was 0.9071; the fresh-vendor replay produced 0.9213. The
historical final equity was $124,536.21; the replay produced $124,987.26. Historical maximum
drawdown was 8.68%; the replay reported 8.60%. The 27-trial validation context was retained rather
than recomputed from a smaller search: historical DSR was 0.3406 and replay DSR was 0.3479. Both
failed the 0.95 portfolio-maturity threshold.

This is a failed exact reproduction even though the headline metrics are close and the fresh
result is slightly more favourable. The surviving 2026-06-20 artifact remains the historical
record and is not regraded. The divergence is consistent with at least one unrecovered historical
input difference, including revised vendor rows, exact per-date membership, corporate-action
state, or the unavailable warm-up interval. The available evidence does not identify a unique
cause. A reviewer must therefore treat the short-window result as version-sensitive and not as a
portable strategy reproduction.

### Deep-history preregistered replication

The 2005-01-04 through 2026-06-01 preregistered momentum run reports net Sharpe -0.0493, cumulative
return -15.07%, annualized volatility 10.66%, a maximum drawdown exceeding one third, and DSR below
the 0.95 gate.
It was killed under its preregistered rule. This contradiction dominates any honest interpretation:
the short-window survivor does not establish durable historical replication.

### Construction attribution

The eight-arm construction study showed that universe and cadence decisions materially changed the
measured result. On its common 2022–2026 basis, arm Sharpes ranged from 0.172 to 1.613 and DSR values
from 0.025 to 0.529. None met the complete admission standard. This dispersion is evidence of
specification sensitivity, not a menu from which to select the largest number.

The later 4-by-4 weighting/breadth grid used the 2005–2026 research panel. Challenger net Sharpes
ranged from -0.293 to +0.066 against -0.062 for the incumbent cell. Although individual cells could
look better, the preregistered White Reality Check returned p=0.315. Zero cells were adopted.

That report also generated two complete 16-cell robustness surfaces that were initially omitted
from the ledger. The no-drift modelling convention produced net Sharpes from -0.564 to -0.077;
the volatility-eligibility guard produced -0.245 to +0.081. They were explicitly labelled
robustness views, but they still changed portfolio returns and therefore still consume selection
identities. All 32 are now charged. Their persisted summaries do not preserve exact daily curves or
higher moments, so this correction cannot manufacture current-union DSR values for them.

Two turnover studies account for another 14 identities. The selected-window K=30 hysteresis screen
reported net Sharpes from 1.282 to 1.630 over only 728 sessions and large turnover reductions for
several exit bands. The deep-history broad-universe study, however, reported net Sharpes from
-0.192 to -0.134 across all eight cadence/hold settings. These are parameter screens, not new
sleeves; identical ex-post results under some minimum-hold settings are still charged because the
settings were separately tried. No short-window improvement is presented as a deep-history or
forward Sharpe result.

The beta-neutral study rejected its own premise: estimated market beta was approximately -0.014 on
the research panel but +0.319 on the live-book sample, and the treatment had opposite effects across
the two contexts. Volatility-scaling and short-tail controls likewise failed their adoption gates.
No failed construction is silently promoted into the paper program.

## Uncertainty, selection, and forward burden

The family-level annualized Sharpe observations in the identity manifest range from approximately
-0.744 to +1.813. That range is not a confidence interval; it is a warning about configuration and
sample sensitivity. ALPHAC applies its Deflated Sharpe Ratio against the union of every return
hypothesis across all research profiles, not only the variants displayed in this paper. As of this
evidence date that union contains 228 identities, and no current legacy restatement clears DSR
0.95.

The governing program objective is an honest forward Sharpe of 1.5 with expected maximum drawdown
near 11%, pursued across a diversified book of up to 14 sleeves. AlphaMax has not established those
targets. The only acceptable path is a sufficiently long, continuous, broker-reconciled paper record
followed by external replication or scrutiny. Targets are design objectives, never guaranteed
outcomes and never reasons to weaken a gate.

## Execution, costs, and capacity boundary

The research path models one-way equity costs including commission, half-spread, latency, realized
turnover, and short borrow. The strategy is dollar-neutral and positions drift between rebalances.
The backtester replays point-in-time corporate actions and applies next-session execution semantics.

Capacity claims remain conditional. Breadth and liquidity screens can support a modelled estimate,
but borrow availability, market impact, locates, crowding, and crisis liquidity require security-level
forward evidence. The website must therefore distinguish modelled capacity from broker-observed
execution and must not describe either as live-money proof.

## Reproduction map

Primary implementation and evidence paths:

- `src/alphaforge/features/library/equity_price.py`: canonical feature implementation.
- `docs/design/EQUITIES_SLEEVE.md`: point-in-time equity data and feature contract.
- `docs/design/PRE_REGISTRATION.md`: deep-history gate and fixed momentum specification.
- `var/experiments.jsonl` and `var_sharadar/experiments.jsonl`: immutable charged identities.
- `artifacts/walkforward/k30_dn_63/`: selected short-window backtest artifact.
- `artifacts/publication/alphamax_upstream_replay_manifest.json`: public hash-only binding to the
  private fresh-input packet, source reconstruction, rights boundary, and disclosed entitlement
  gap.
- `artifacts/publication/alphamax_upstream_clean_workspace.json`: author-run clean-workspace replay
  receipt and failed exact comparison.
- `artifacts/walkforward/prereg_momentum/`: preregistered deep-history result.
- `artifacts/sweep/alphamax_construction/`: eight-arm attribution study.
- `artifacts/probe/alphamax_weighting/`: family-wise weighting/breadth grid.
- `scripts/probe_alphamax_betaneutral.py`, `scripts/probe_alphamax_shorttail.py`, and
  `scripts/probe_alphamax_volscale.py`: rejected construction probes.
- `artifacts/research/trial_packet_manifest.json`: exact family/identity join and packet debt.

Reproduction requires the pinned project environment and licensed/source datasets represented by
the artifacts. Public artifacts permit claim auditing; they do not imply that every underlying
licensed market-data row can be redistributed.

## Packet completeness and legacy limitations

This family paper materially improves lineage coverage but does not retroactively create evidence
that did not exist. At publication time, the manifest still marks every identity packet incomplete.
In particular, some legacy identities lack a contemporaneous preregistration, complete return
series, or independently rerunnable data bundle. Those absences must remain explicit. A later
validator may bind this paper to exact identities and credit only sections it can prove; it must not
convert “documented legacy absence” into “verified preregistration.”

## Decision

**Research decision:** retain AlphaMax as a paper-only forward experiment; do not claim the
historical edge is established; do not adopt any failed construction enhancement; continue
broker-reconciled observation under the frozen operational specification.

**Publication decision:** publish the positive survivor, failed deep-history replication, complete
family trial count, and unresolved evidence debt together. Any future promotion requires new
forward evidence under unchanged gates, not a more flattering retrospective window.
