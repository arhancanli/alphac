# ENGINE10 — Validation-Rigor Audit

Dimension: **Validation-Rigor** — DSR/PSR/PBO/CPCV correctness, honest full-funnel
trial counting, the must-beat-baseline gate, embargo/purge sufficiency for slow
features, capacity analysis. The bar: *a 10/10 engine cannot fool itself.*

HEAD audited: `dfdf515`. Read-only; no source edited. Verdict: **8.5 / 10.**

---

## 1. What a 10/10 has on this axis

1. **Mathematically exact anti-overfit instruments** — PSR/DSR (Bailey–López de
   Prado, Mertens non-normal SE), PBO via CSCV (BBLZ 2017), CPCV producing a
   *distribution* of OOS paths. Per-period vs annualized periodicity handled
   without a single mismatched (SR, n) pair.
2. **The deflation actually reflects the whole search.** `N` (trials) and `V[SR]`
   capture *every* configuration the researcher tried — factor screening, horizon
   choice, universe construction, hyper-parameter sweeps, feature engineering —
   not merely the last-mile backtest grid. The number you deflate against is the
   true funnel width, not a curated subset of it.
3. **`V[SR]` is the right statistic.** The cross-trial Sharpe dispersion fed to the
   expected-max-Sharpe benchmark is the dispersion the selection actually happened
   over (CPCV-path Sharpes per BLP, or the genuine config-trial distribution),
   computed — not stubbed.
4. **Leakage-tight CV for the features in use.** Purge ≥ label horizon AND embargo ≥
   the *dominant feature lookback* on every path where train can follow test, so a
   2025-bar carry feature cannot bleed test-period information into a neighbouring
   train block.
5. **Capacity analysis that models impact at scale**, not just bigger starting cash
   through the same per-order cap — and reports the impact-killed Sharpe honestly,
   with the participation ceiling surfaced rather than silently truncating fills.
6. **No dead instruments.** Every validation tool that ships is wired into the gate
   it claims to feed; nothing is computed-but-ignored.

AlphaForge nails #1, #5 (largely), and the *machinery* of #2/#4 — but misses #6 and
the *semantics* of #2/#3, and #4 on the headline DSR path. Details below.

---

## 2. Strengths verified against the code (so the gaps are calibrated)

- **DSR/PSR maths is correct and honest** (`validation/dsr.py`). Non-excess
  kurtosis (`fisher=False`), Mertens denominator, per-period convention enforced by
  `dsr_from_returns` deriving moments from the daily series internally
  (`dsr.py:228-267`) so callers can never hand a mismatched (annualized-SR,
  per-period-n) pair. Degenerate-denominator and zero-variance guards present.
- **PBO/CSCV is textbook** (`validation/pbo.py`): contiguous equal blocks, `C(S,S/2)`
  IS/OOS splits, seeded uniform sub-sampling above `max_combinations`, ascending OOS
  rank with average ties, logit, `PBO = mean(λ ≤ 0)`. `std==0 → −inf` so a constant
  column can never win IS (`pbo.py:96-111`). Deterministic.
- **Purge/embargo arithmetic is shared, not copy-pasted** between `PurgedWalkForward`
  and `CombinatorialPurgedCV` via `_purge_embargo_mask` (`cpcv.py:81-103`), and the
  splitters *refuse to construct* with `purge_bars < horizon_bars`
  (`splits.py:115-121`, `cpcv.py:153-159`). This is genuinely good defensive design.
- **The honest-deflation run-order fix is real and well-reasoned.** `grand_matrix.py`
  re-deflates *every* config against the SHARED final `(N, V[SR])`
  (`_redeflated_dsr`, `cross_config_dsr` at `grand_matrix.py:213-253`) instead of the
  run-order-dependent per-config `validation.dsr` (preserved only as audit
  `runtime_dsr`). This closes a subtle self-fooling vector most shops miss.
- **The idempotent ledger** (`experiments.py`) makes N count *distinct* configs;
  re-runs cannot inflate the deflation (`record` skips on hash hit, `experiments.py:231-249`).
- **Capacity uses a real square-root impact law** (`costs/model.py:148-174`,
  `impact_frac = Y·σ_daily·√(Q/ADV)`) and *hard-fails* above 5% ADV rather than
  extrapolating a law it knows underestimates cost — and the grand harness treats
  that failure as a finding (`grand_backtest.py:516-537`), recording the config as
  capacity-exceeded and continuing.
- **Must-beat-baseline is strict and on identical legs** (`compare_to_baseline`,
  `walkforward.py:502-526`; mirrored re-deflated in `grand_matrix.py:414-432`):
  `dsr≥0.95 AND dsr>baseline.dsr AND sr_ann>baseline.sr_ann`, all strict, non-finite
  → False. The blend baseline is re-run on the *same purged legs* (`walkforward.py:874-885`).
- ~2500 tests; validation module alone has 26 (DSR) + 25 (PBO) + 19 (CPCV) + 24
  (experiments) + 13 (splits) + 19 (metrics) + 30 (grand_matrix) + an integration
  test pinning honest trial-count idempotency.

This is an 8.5, not a 7. The gaps are in the corners — but on this axis the corners
are the whole game.

---

## 3. Gaps (file:line, mechanism, severity, fix)

### G1 — `V[SR]` is NOT the CPCV-path Sharpe variance the design mandates *(HIGH)*

**What the spec says.** `alphaDesign.md:657` (verbatim): "`V[SR]` = sample variance
of their **CPCV-path Sharpe estimates**." `cpcv.py:12` repeats it: CPCV "feeds the
path Sharpe variance `V[SR]` consumed by the Deflated Sharpe Ratio (§7.4)."

**What the code does.** `V[SR]` is `ExperimentLog.trial_sharpe_variance()`
(`experiments.py:260-278`) — the sample variance of the *per-config* OOS daily
Sharpes on the ledger (8 distinct configs in the grand matrix). It is consumed at
`walkforward.py:479`, `grand_matrix.py:224`, `research_cmds.py:272`. **`CPCV.n_backtest_paths`
and the per-path Sharpe distribution are never computed for any verdict** — confirmed
by grep: the only consumers of `CombinatorialPurgedCV` are `validation/__init__.py`,
its own module, and `tests/unit/test_cpcv.py`.

**Why it matters.** These are different statistics. The BLP construction deflates
against the dispersion of Sharpe estimates *across the resampled OOS paths of the
selected family* — a within-strategy sampling variance. The shipped quantity is the
*between-config* dispersion of 8 hand-chosen variants. With a tight cluster of 8
similar configs `V[SR]` is small, `SR*` is small, and the DSR is *more permissive*
than the design intends — the deflation under-penalizes. The engine is using a
plausible-but-different number and calling it the spec's number.

**Fix.** Either (a) compute `V[SR]` from CPCV path Sharpes for the selected family
and feed that to `expected_max_sharpe` (wire `CPCV.n_backtest_paths` paths through
the engine, collect per-path Sharpe, take ddof=1 variance), matching the spec; or
(b) if the config-trial variance is the deliberate, defensible choice, **amend
`alphaDesign.md:657` and the `cpcv.py:12` docstring** and demote CPCV to an explicit
research-only diagnostic. Today the doc and the code disagree, and a reviewer trusting
the docstring believes a deflation that is not happening.

---

### G2 — Honest trial count `N` excludes the entire upstream research funnel *(HIGH)*

**Mechanism.** Only two sites ever call `log.record(...)`: the walk-forward runner
(`walkforward.py:468`) and ML retrain promotion (`retrain.py:545`). The grand matrix
logs exactly **8 distinct trials** (Block A: 4 gate variants; Block C: 4 one-knob
robustness; Block B capacity shares a hash by design). Verified: `grep '\.record('`
returns those two sites only.

The choices that *actually* constitute the search are invisible to `N`:
- The **25-factor library** (`features/library/`) and which subset becomes "alphas."
- **IC screening / blend-weight estimation** (`signals/blending.py`,
  `signals/service.py` reference IC but never `record` a trial) — this selects the
  signal, the highest-leverage overfitting surface, and logs nothing.
- The **horizon** (`horizon_bars=72`), the **universe** (top-N), the **rebalance/band**
  defaults — each was a decision; none is a counted trial except the few Block-C
  perturbations.

So a researcher who tried 10 horizons, 30 factor subsets, and 5 universes, then ran
the 8-config matrix, deflates against `N≈8`. The expected-max-Sharpe benchmark is a
monotone increasing function of `N`; under-counting `N` is precisely the way DSR is
fooled. The design's own framing — "N is *measured*, not guessed" (`alphaDesign.md:657`)
— is satisfied *mechanically* (the matrix's own trials are logged) but *not in spirit*
(the funnel that preceded the matrix is unmeasured).

**Fix.** Add `record` calls (with the appropriate `nan` Sharpe placeholder, which
`trial_sharpe_variance` already excludes) at the upstream decision points that
constitute search: the IC-screening pass (one trial per factor-subset evaluated),
the horizon/universe sweep harness, and any blend-weight grid. At minimum, document
a manual "research budget" knob that seeds `N` with an honest lower bound for the
human search depth so the DSR is not deflated against `N=8` when the true funnel is
hundreds. The ledger schema already supports this; the calls are missing.

---

### G3 — The headline DSR path uses embargo=168, below the 720-bar slow-feature lookback *(MEDIUM)*

**The contradiction is in the codebase's own words.** `retrain.py:93-96` sets
`DEFAULT_EMBARGO_BARS = 720` with the comment: "the embargo must be >= the dominant
slow-feature lookback that enters the model, ~720 bars, **not the splitter's 168
default**." Yet the walk-forward analytics that produce the DSR/PBO verdict default to
`embargo_bars: int = 168` (`walkforward.py:678`), and the grand backtest hardcodes
`_EMBARGO_BARS = 168` (`grand_backtest.py:106`).

**Severity is MEDIUM, not HIGH, because of a real mitigant:** the deployment-faithful
`PurgedWalkForward` is *forward-chaining* — train always precedes test — so its
embargo (the train-after-test term) is provably vacuous (`splits.py:30-34, 195-196`).
The embargo only bites in `CombinatorialPurgedCV`, where train blocks can follow test
blocks. **But** the engine's factors genuinely span far beyond 168 bars:
`carry_fund_*` derives `lookback_bars = _carry_lookback_bars(252) = 2025`
(`carry_dynamics.py:255`), beta uses `722` (`market_state.py:106`), `cov_window_bars`
and `cov_halflife_bars` default to `720` (`walkforward.py:683-684`). A feature
computed at a train bar within ~2025 bars *after* a CPCV test block still embeds that
test block's data.

So: the *forward-chaining DSR path* is safe by construction, but (a) if CPCV were
ever wired into `V[SR]` (see G1) it would leak under embargo=168, and (b) the
embargo default is inconsistent with the retrain path's own correctness argument,
which is a latent foot-gun for anyone reusing `PurgedWalkForward` in a non-forward
context.

**Fix.** Set the walk-forward / grand-backtest embargo default to derive from the
maximum lookback of the *active* factor set (≥720, up to ~2025 when carry is in the
blend), exactly as `retrain.py` does, rather than the bare 168. Even though it is a
no-op on the forward-chaining path today, it removes the inconsistency and makes the
embargo correct the moment train-after-test ever appears (CPCV V[SR], cross-validated
blend weights). Pin a test asserting `embargo_bars ≥ max_active_lookback`.

---

### G4 — CPCV is shipped, tested, and correct — but dead with respect to every gate *(MEDIUM)*

**Mechanism.** `CombinatorialPurgedCV` (`cpcv.py`) is a fully-correct, 19-test
implementation that produces `n_backtest_paths` OOS paths. Nothing in the production
verdict consumes it — not `walkforward.py`, not `grand_matrix.py`, not
`research_cmds.py`. The PBO gate instead runs CSCV over an *8-column variant-returns
matrix* (`oos_returns_matrix`, `grand_matrix.py:266-313`), which is a different
construction (cross-config, not cross-path).

**Why it matters.** A 10/10 has no validation instrument that is computed-but-ignored.
CPCV is the spec's source of `V[SR]` (G1) and the natural source of an OOS-path Sharpe
*distribution* for a single selected family; shipping it unwired means the deflation
the design describes is not the deflation that runs, and a reader auditing "do we do
CPCV?" gets a misleading yes.

**Fix.** Wire CPCV into the selected-family evaluation (it resolves G1 simultaneously):
run the winning config through `CPCV.split`, backtest each of the `φ` paths, and feed
the path-Sharpe variance to the DSR. Then PBO can also run over the CPCV paths of the
single family (its intended use) in addition to the cross-config CSCV. If CPCV is
deliberately benched, say so in `validation/__init__` and the design doc.

---

### G5 — Small-N regime: expected-max-Sharpe asymptotics + 8-config PBO are statistically thin *(MEDIUM)*

**Mechanism.** `expected_max_sharpe` is the BLP *asymptotic* closed form for the
expected max of `N` i.i.d. normal Sharpes (`dsr.py:108-137`). The grand matrix feeds
it `N_used = max(2, 8) = 8`. The (1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(Ne)) approximation is
known to be loose for small `N`; at `N=8` the benchmark `SR*` carries non-trivial
approximation error that is neither bounded nor surfaced. Separately, `matrix_pbo`
runs CSCV over **8 config columns** (`grand_matrix.py:704` — Blocks A+C). CSCV's rank
statistic over 8 columns has a coarse `ω = rank/(N+1)` lattice (denominator 9), so
the PBO estimate is granular and high-variance.

**Why it matters.** The gates (`DSR≥0.95`, `PBO<0.20`) are applied as bright lines to
statistics whose small-N sampling error is comparable to the margin. A `PBO=0.18`
over 8 columns is not meaningfully distinguishable from `0.22`. The engine reports a
point estimate and a hard pass/fail with no confidence band.

**Fix.** (a) For `SR*`, either compute the expected-max via Monte-Carlo at the true
`N` (exact, cheap) or surface a documented small-N caveat in the verdict. (b) For PBO,
widen the config-variant matrix (more genuine alternatives) or report a bootstrap CI
on the PBO estimate next to the point value, so the operator sees the gate is being
applied to a noisy statistic. (c) Cross-reference G2: a larger honest `N` would also
relieve the small-N asymptotic stress on `SR*`.

---

### G6 — Capacity sweep varies starting cash but not the per-order ADV cap; the curve can be truncated rather than impact-decayed *(MEDIUM)*

**Mechanism.** Block B varies only `initial_cash` ∈ {100k, 1M, 10M, 100M}
(`grand_matrix.py:177-191`) through the *same* engine, whose pre-trade checks reject
at 1% ADV and whose cost model hard-fails at 5% ADV (`costs/model.py:51-57, 168-173`).
At 100M on a ~20-name top-perp universe, target notionals routinely exceed those caps,
so the run does not produce an *impact-decayed* Sharpe — it either silently has its
orders **clipped to the cap** (the position never reaches target, so the curve
reflects a smaller-than-intended book, not the cost of trading the intended one) or it
raises `CostModelMisuse` and the whole config is dropped (`grand_backtest.py:516-537`).
The verdict prose promises "where market impact kills the thin edge"
(`grand_matrix.py:807, 820-826`), but a clipped or dropped run measures *capacity
exhaustion as a missing data point*, not the smooth impact-erosion curve the
narrative implies.

**Why it matters.** A true capacity analysis answers "what Sharpe survives at $X AUM
*after* paying realistic impact to actually establish the book?" The current sweep
conflates three regimes (impact-decayed / order-clipped / config-dropped) into one
`sr_ann` column without distinguishing them, so a reader cannot tell whether `100M`'s
Sharpe fell because impact ate it or because the engine couldn't fill the book.

**Fix.** Record, per capacity point, the fraction of target notional actually filled
and the fraction of bars where the ADV cap bound; emit those alongside `sr_ann` in the
capacity row so a clipped point is visibly distinct from an impact-decayed one. Better:
add a participation-aware sizing mode (scale target down to the ADV cap and charge the
multi-bar liquidation cost) so the curve is continuous through the capacity ceiling
instead of terminating at it.

---

### G7 — Cross-ledger N/V[SR] consistency is fragile across the two `record` sites *(POLISH)*

**Mechanism.** Retrain logs trials with `sharpe_per_period=nan` (`retrain.py:555-556`).
`n_trials()` counts distinct hashes regardless of finiteness (`experiments.py:251-258`),
but `trial_sharpe_variance()` excludes non-finite Sharpes (`experiments.py:270-272`).
If the retrain path and a DSR-consuming path ever share the default ledger
(`var/experiments.jsonl` — both default to it: `walkforward.py:1072`,
`retrain.py:544`, `research_cmds.py:270`), retrain trials inflate `N` (good, honest)
but contribute nothing to `V[SR]`, mixing model-promotion trials with backtest-config
trials in the same `N` while `V[SR]` reflects only the latter. The grand backtest
dodges this with a dedicated per-run ledger (`grand_backtest.py:329`), but the default
CLI wiring does not.

**Why it matters.** It is a quiet way for `N` and `V[SR]` to describe different
populations. Not a blocker — the magnitude is small and the default path is rarely the
one used for the real verdict — but a 10/10 keeps `N` and `V[SR]` over the *same* set.

**Fix.** Either segregate ledgers by trial *kind* (backtest-config vs
model-promotion), or have `n_trials()`/`trial_sharpe_variance()` operate on the same
finite-Sharpe-filtered subset so the two quantities always describe one population, or
require an explicit ledger path on every DSR-consuming CLI entry (drop the
`var/experiments.jsonl` default).

---

## 4. Scaling note (crypto-20 → equities-thousands)

Validation-rigor specific scaling concern, flagged for the funnel-width axis: the
`N`/`V[SR]` and PBO machinery is `O(configs)` and indifferent to instrument count, so
it scales fine numerically. **But** the honest-N gap (G2) gets *worse* with breadth:
a thousands-name equity sleeve multiplies the upstream search surface (per-sector
factors, many universes, cross-sectional vs time-series variants) while the trial
ledger still only sees the final backtest grid. The deflation will be even more
permissive relative to the true funnel on equities than on crypto. G2's fix
(instrument upstream search logging) is a prerequisite for trusting any equities DSR.

## 5. Cross-cutting (out of dimension, noted only)

The Phase-8 pre-arm gates C3/C5/C7/C10 are execution/reconciliation issues
(mark-time, fill discovery, reconcile-before-adopt, ack durability) — they belong to
the live-execution audit, not Validation-Rigor, and do not affect the statistics
above. Flagged here only so they are not assumed covered by this doc.

---

## 6. Scorecard

| Sub-axis | State |
| --- | --- |
| DSR/PSR maths | Correct, honest periodicity — 10/10 |
| PBO/CSCV maths | Textbook BBLZ — 10/10 |
| CPCV maths | Correct — but **unwired** (G4) |
| Purge sufficiency (label horizon) | Enforced at construction — 10/10 |
| Embargo sufficiency (slow features) | 720 on retrain; **168 on DSR path** (G3) |
| `V[SR]` correctness | **Config-variance, not spec's CPCV-path variance** (G1) |
| Honest full-funnel `N` | **Final-grid only; upstream search uncounted** (G2) |
| Must-beat-baseline gate | Strict, same-legs, re-deflated — 10/10 |
| Run-order-invariant deflation | Implemented well (`grand_matrix`) — 10/10 |
| Small-N statistical honesty | Asymptotic SR*, 8-col PBO, no CI (G5) |
| Capacity analysis | Real √-impact law; **clip/drop conflation** (G6) |

**Verdict: 8.5 / 10.** The instruments are correct and the run-order honesty is
genuinely top-shelf. The gap to 10 is two semantic holes that let the deflation be
gentler than designed — `V[SR]` is the wrong (smaller) dispersion (G1) and `N` omits
the upstream funnel (G2) — plus an unwired CPCV (G4), an embargo default that
contradicts the engine's own slow-feature reasoning (G3), and a capacity curve that
can measure exhaustion as a hole rather than a slope (G6). None is a maths error; all
are "the deflation does not see the whole search," which on this axis is exactly the
corner where a 9 hides from a 10.
