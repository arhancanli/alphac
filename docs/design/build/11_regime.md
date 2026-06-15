# Build spec — Phase 11: HMM regime gate (`regime/hmm.py`)

Ground truth: `alphaDesign.md` §8 (HMM model), §9.2 (μ contract / where `G` plugs in),
`leakageCritique.md` finding 13 (HMM gate timing), finding 26 (data window).
Platform constraints (this build): **no `hmmlearn`** — the forward filter and
Baum–Welch EM are HAND-ROLLED here. Read `signals/service.py`, `labeling/forward_returns.py`,
`validation/dsr.py`, and `core/time.py` before writing code; match their docstring
density, full typing, and idioms (`from __future__ import annotations`, `Final`
module constants, `__all__`, frozen `@dataclass(slots=True, kw_only=True)`, pure
functions of injected arguments, no hidden mutable state).

---

## 0. What this module is and is NOT

It is a **gross-exposure gate**, not a signal. Its single job is to emit a scalar
multiplier `G ∈ [0.3, 1.0]` per **calendar day** that the alpha layer applies to
`mu_ann` (§9.2):

```
mu_ann_{i,t} = IC_target · σ̂_{i,t}·sqrt(h) · F̃_{i,t} · G_d
```

where `d` is the UTC calendar day containing hour-bar `t`. By **correctness rule 3**
the gate NEVER flips a sign — `G ≥ 0.3 > 0` always, and it multiplies the magnitude
only. By **correctness rule 5** it does not touch the μ contract: the gate is applied
INSIDE the alpha layer (multiplying the already-formed `mu_ann`), so the optimizer
still consumes a single verbatim `mu_ann` column. The HMM observes **daily** market
state; the gate is broadcast to all 24 hourly decision bars of a day.

The model is fitted **offline, monthly** (1st of month, after the daily close); live
inference is a cheap forward pass. It persists nothing; the caller (live loop /
walk-forward runner) owns the fitted-params object and the refit cadence.

---

## 1. Observation contract

Observation row per UTC day `d` (closes at `00:00` of day `d+1`):

```
x_d = [ m_d , v_d ]
m_d = daily log return of BTC/USDT             = ln(C_d / C_{d-1})
v_d = log of 14-day Yang–Zhang annualized vol  = ln( yang_zhang(BTC OHLC, window=14, annualize) )
```

- `m_d` uses the **daily** close panel (1d bars derived from 1h per `dataDesign.md`).
- `v_d` reuses the ONE sanctioned estimator `alphaforge.features.library.vol.yang_zhang`
  (do not re-implement vol). 14d window on **daily** bars; `annualize=True` is for human
  legibility only — any positive scaling is absorbed by the Gaussian means, but keep it
  for cross-refit comparability of logged state means. `ln(·)` for near-normality (§8).
- Each `x_d` is **available at `available_at(ts_open_d, Timeframe.D1)` = day-`d` close =
  `00:00` of day `d+1`**. This `available_at` stamp is the linchpin of the timing rule
  (§4); compute it with `core.time.available_at`, never by hand.
- Builder lives here as `build_observations(...)` (see §3.1); it drops the leading NaN
  rows (14d YZ warm-up + the one-bar gap return) and raises if fewer than `MIN_FIT_DAYS`
  finite rows remain. NaN inside the series (data gap) is NOT bridged — the day is
  dropped, matching `forward_returns` gap discipline.

---

## 2. The model: hand-rolled 2-state default, 3 supported

`K` is configurable in `{2, 3}` (default **3**, per §8). Full-covariance Gaussian
emissions in 2-D. Parameters:

- `start_prob` `π`: shape `(K,)`, sums to 1.
- `trans_mat` `A`: shape `(K, K)`, each row sums to 1 (`A[j,k] = P(s_t=k | s_{t-1}=j)`).
- `means` `μ`: shape `(K, 2)`.
- `covs` `Σ`: shape `(K, 2, 2)`, SPD (Cholesky-able). A diagonal floor `COV_FLOOR =
  1e-6` is added to the diagonal every M-step to keep emissions non-degenerate (the
  classic single-point-collapse failure of Gaussian EM).

All emission densities computed in **log space** (`scipy.stats.multivariate_normal.logpdf`
per state, then `scipy.special.logsumexp` for normalizers) — never raw products of
densities (underflow over ~2500 days). scipy is imported directly (it carries stubs in
this env; see `validation/dsr.py`, `validation/pbo.py`).

### 2.1 The forward FILTER (live inference, ~25 lines)

Scaled forward recursion producing **filtered** posteriors `P(s_t=k | x_{1:t})` — NEVER
smoothed (smoothed `P(s_t | x_{1:T})` uses future data; that is the §8/finding-13 leak):

```
log_b_t(k) = logpdf(x_t; μ_k, Σ_k)                       # emission log-likelihood
# t = 0:
log_α_0(k) = log π_k + log_b_0(k)
c_0        = logsumexp_k log_α_0(k);   filt_0(k) = exp(log_α_0(k) - c_0)
# t ≥ 1 (work in the normalized/filtered domain to stay bounded):
pred_t(k)  = Σ_j filt_{t-1}(j) · A[j,k]                  # one-step-ahead prior
log_α_t(k) = log pred_t(k) + log_b_t(k)
c_t        = logsumexp_k log_α_t(k);   filt_t(k) = exp(log_α_t(k) - c_t)
loglik     = Σ_t c_t                                     # data log-likelihood (for EM/seed pick)
```

`filt_t` is the filtered posterior row. This is the ONLY recursion used live and the
ONLY one whose output reaches `G`. No backward pass anywhere in the gate path.

### 2.2 Baum–Welch (EM), multi-seed (~120 lines incl. forward-backward)

Standard scaled forward–backward + EM, used for **fitting only** (offline). The backward
pass is permissible HERE because fitting happens on a closed historical window and its
output (the params) is then frozen and applied forward-only; the backward β's never
touch live `G`.

```
E-step (per seed, per iteration):
  forward  (scaled): log_α, scalers c_t  (as §2.1 but full series)
  backward (scaled): β_t(k) with the same c_t scalers
  γ_t(k)    = filt_t(k)·β_t(k) / Σ_k(...)          # smoothed posterior (FIT ONLY)
  ξ_t(j,k) ∝ filt_{t-1}(j)·A[j,k]·b_t(k)·β_t(k)    # joint, normalized per t
M-step:
  π_k      = γ_0(k)
  A[j,k]   = Σ_{t≥1} ξ_t(j,k) / Σ_{t≥1} γ_{t-1}(j)
  μ_k      = Σ_t γ_t(k)·x_t / Σ_t γ_t(k)
  Σ_k      = Σ_t γ_t(k)·(x_t-μ_k)(x_t-μ_k)ᵀ / Σ_t γ_t(k)  + COV_FLOOR·I
Converged when Δloglik < TOL (1e-4) or iter == MAX_ITER (300).
```

**Multi-seed restarts** (`hmmlearn` has no `n_init`; finding 13 demands a hand-rolled
loop): run `N_SEEDS = 10` independent fits from a seeded RNG (`np.random.default_rng(
RANDOM_STATE=42)` → per-seed child seeds, deterministic). Seed init: k-means++-style
pick of `K` observation rows as means, `π`/`A` uniform-ish (`A` diagonal-heavy, e.g.
`0.9` self-transition), `Σ` = global sample covariance. **Keep the params with the
highest final `loglik`.** Log every seed's final loglik at DEBUG and the chosen seed.

### 2.3 State identification by SORTED volatility (re-pinned every refit)

After the best fit, **relabel states by ascending `μ_k[1]` (the mean of `v_d = ln σ`)**:

- state 0 = lowest mean log-vol = "low" (quiet/bull),
- state 1 = "mid" (only when `K=3`),
- last state = highest mean log-vol = "high" (crisis).

Tie-break on equal vol means by **descending mean return** `μ_k[0]`. Apply the
permutation to `π`, `A` (both rows and columns), `means`, `covs` so the stored params
are already in canonical vol-ascending order. This re-pinning happens on EVERY monthly
refit, so state identity is defined by vol ordering, not by EM's arbitrary label — no
cross-refit Mahalanobis matching is needed for the GATE (gate weights attach to the
sorted index). [Optional continuity log: warn if the vol-sort disagrees with a nearest-
mean match to the previous fit; advisory only, does not change `G`.]

`gate_weights` map sorted-state → multiplier:

```
K=3:  g = (1.0, 0.7, 0.3)        # low, mid, high
K=2:  g = (1.0, 0.3)             # low, high
```

The per-day multiplier is the posterior-weighted blend (§8):

```
G_d = Σ_k filt_d(k) · g_k                     ∈ [min(g), max(g)] = [0.3, 1.0]
```

---

## 3. Public API — `regime/hmm.py`

### 3.0 Protocol seam (mirrors the ML-gate `Protocol` idiom)

```python
@runtime_checkable
class RegimeGate(Protocol):
    """The seam the alpha layer depends on: day -> gross multiplier in [0.3, 1.0].

    `regime/hmm.py` ships the HMM implementation; a constant-1.0 NullGate and any
    future model satisfy the same Protocol so the signal path never imports the HMM
    concretely (matches backtest/fills.py FillModel, execution/paper.py OrderBookSource).
    """
    def gross_multiplier_series(
        self, obs: pd.DataFrame, *, lag_days: int = 1
    ) -> pd.Series: ...
```

### 3.1 Observation builder

```python
MIN_FIT_DAYS: Final[int] = 730          # §8 expanding-window minimum (≈2y)
YZ_WINDOW_DAYS: Final[int] = 14
RANDOM_STATE: Final[int] = 42
N_SEEDS: Final[int] = 10
MAX_ITER: Final[int] = 300
TOL: Final[float] = 1e-4
COV_FLOOR: Final[float] = 1e-6
GATE_WEIGHTS: Final[dict[int, tuple[float, ...]]] = {2: (1.0, 0.3), 3: (1.0, 0.7, 0.3)}

def build_observations(daily_btc: pd.DataFrame) -> pd.DataFrame:
    """Daily HMM observation frame [m, v] from a BTC daily OHLC panel.

    `daily_btc` columns: open, high, low, close, indexed by ts_open (epoch-ms UTC
    int64, 1d-aligned). Returns a frame indexed by ts_open with float columns
    `m` (daily log return) and `v` (ln 14d annualized YZ vol) plus an int64
    `available_at` column = available_at(ts_open, Timeframe.D1) = day close.
    Leading warm-up NaNs dropped; gaps NOT bridged; raises if < MIN_FIT_DAYS rows.
    """
```

### 3.2 Fitted-params value object

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class HMMParams:
    """Frozen, vol-sorted HMM parameters (state index 0 = lowest log-vol).

    n_states K in {2,3}; start_prob (K,), trans_mat (K,K), means (K,2),
    covs (K,2,2) SPD; loglik = best-seed data log-likelihood; n_obs = fit length;
    seed = winning seed index. All arrays float64, C-contiguous, immutable view."""
    n_states: int
    start_prob: npt.NDArray[np.float64]
    trans_mat: npt.NDArray[np.float64]
    means: npt.NDArray[np.float64]
    covs: npt.NDArray[np.float64]
    loglik: float
    n_obs: int
    seed: int
```

### 3.3 The model

```python
class RegimeHMM:
    """Hand-rolled K-state Gaussian HMM on [BTC daily ret, ln 14d YZ vol]:
    multi-seed Baum–Welch fit, FILTERED (forward-only) live inference,
    vol-ascending state identity, gross-exposure gate. Satisfies RegimeGate.

    No hmmlearn (platform constraint). Persists nothing: fit() returns self with
    `params` set; callers freeze/store `params` for the monthly refit cadence.
    """

    def __init__(self, n_states: int = 3, *, random_state: int = RANDOM_STATE,
                 n_seeds: int = N_SEEDS, max_iter: int = MAX_ITER, tol: float = TOL,
                 gate_weights: tuple[float, ...] | None = None) -> None: ...
        # validates n_states in {2,3}; gate_weights defaults to GATE_WEIGHTS[n_states];
        # len(gate_weights) must == n_states; gate_weights must be DESCENDING (low-vol
        # state gets the largest multiplier) and within [0, 1] — asserted.

    @property
    def params(self) -> HMMParams: ...                 # raises if not yet fitted

    def fit(self, obs: pd.DataFrame) -> "RegimeHMM":
        """Multi-seed Baum–Welch on obs[['m','v']]; keep best-loglik seed; relabel
        states by ascending mean(v); store vol-sorted HMMParams. Raises ValueError
        if len(obs) < MIN_FIT_DAYS or obs has non-finite rows."""

    def filtered_probs(self, obs: pd.DataFrame) -> pd.DataFrame:
        """Forward-only P(s_d=k | x_{1:d}); columns state_0..state_{K-1} (vol-
        ascending), indexed by obs.index (ts_open). Uses self.params; pure forward
        pass — NO backward/smoothing. Row d uses observations 0..d ONLY."""

    def gross_multiplier(self, probs: pd.DataFrame) -> pd.Series:
        """G_d = Σ_k probs[state_k]·g_k, indexed by probs.index; in [min g, max g]."""

    def gross_multiplier_series(self, obs: pd.DataFrame, *, lag_days: int = 1) -> pd.Series:
        """END-TO-END GATE WITH THE TIMING LAG (§4). Returns a Series indexed by the
        DAY-d ts_open the gate APPLIES TO, whose value is the filtered multiplier
        computed from observations available strictly BEFORE day d (i.e. through day
        d-`lag_days` close). lag_days=1 is the only no-leak default; 0 is rejected."""
```

---

## 4. CRITICAL TIMING — zero same-day leak (correctness rule 4 / finding 13)

The HMM observes **daily** state; the gate is consumed at **hourly** decision bars. The
join must guarantee: **`G` for ALL 24 hours of day `d` is the filtered posterior computed
through day `d-1`'s close, and uses NO observation from day `d` itself.**

Mechanics (implemented in `gross_multiplier_series`, enforced again at the join in
Phase 12):

1. Compute `filt_d` over the observation series. `filt_d` is, by §2.1, a function of
   `x_{1:d}` — observation `x_d` (day `d`'s own return and vol) IS baked into `filt_d`.
   Therefore `filt_d` MUST NOT gate day `d`.
2. `x_d` becomes available at `available_at(ts_open_d, Timeframe.D1)` = `00:00` of day
   `d+1`. So `filt_d` is the FIRST posterior a decision on day `d+1` may use.
3. The gate value applied on day `D` is therefore `G_D = blend(filt_{D-lag_days})`,
   with `lag_days = 1`. Equivalently: **shift the filtered-multiplier series forward by
   `lag_days` days**, so the value indexed at day `D` originated from day `D-1`'s
   observation/posterior. Day `D=0..lag_days-1` (cold start) → `G = 1.0` (no gate yet,
   documented).
4. Phase-12 hourly join: `pd.merge_asof(hourly_decisions, gate_daily, left_on="ts_open",
   right_on="available_at", direction="backward")` — match each hour-bar `t` to the
   LATEST daily gate row whose `available_at <= t`. Because `available_at = day-close =
   00:00 next day`, the gate that the FIRST hour of day `D` (00:00..01:00) sees is the
   one stamped at `00:00 of day D`, which is `filt_{D-1}`. This single `merge_asof` is
   the live/research-identical join (the §9.2 seam already broadcasts other daily
   quantities the same way).

So there are **two independent guards**, and both are tested (§5):
- the `shift(lag_days)` inside `gross_multiplier_series` (the producer never emits a
  same-day value), and
- the `merge_asof` on `available_at <= t` at the hourly join (the consumer never reads a
  future-stamped row). `lag_days = 0` is explicitly rejected by `gross_multiplier_series`.

`G` is **constant across the 24 hours of a day** (daily granularity). It changes only at
`00:00` UTC boundaries, always to a value derived from data fully closed before that
boundary.

---

## 5. Tests

### 5.1 Unit — `tests/unit/test_regime_hmm.py`

- **Synthetic regime-switch recovery (the headline test).** Build a 2-state generator
  with well-separated emissions: low-vol state `μ=(+0.001, ln 0.4)`, high-vol state
  `μ=(−0.002, ln 1.2)`, sticky `A=[[0.97,0.03],[0.05,0.95]]`, `Σ` small-diagonal; draw
  ~1500 days from a seeded RNG, recording the hidden state path. Build observations, fit
  `RegimeHMM(n_states=2)`. Assert: (a) **state identity** — `params.means[0,1] <
  params.means[1,1]` (vol-sorted); (b) **hidden-state recovery** — Viterbi/argmax-filtered
  decode agrees with the true hidden path on **≥ 90%** of days (allow label via the vol
  sort, not EM's raw labels); (c) recovered transition self-probs within `0.05` of truth;
  (d) recovered state-vol means within a tolerance band of the generator's. Mark with a
  seeded RNG so it is deterministic; mirror the 3-state version with a mid state and a
  looser `≥ 80%` accuracy bar.
- **Multi-seed determinism & monotonic loglik.** Two fits with the same `random_state`
  give bit-identical `HMMParams`; within a single fit the per-iteration loglik is
  non-decreasing (EM monotonicity) up to `1e-9` slack; the winning seed's loglik is the
  max over seeds.
- **Vol-sort re-pinning.** Permute the generator's two states (swap labels) and confirm
  the fitted `params` come back in the SAME vol-ascending order (state 0 still the
  low-vol one) — identity is pinned by vol, not by data labeling.
- **Filtered ≠ smoothed.** Assert the forward-only `filtered_probs` row `d` is unchanged
  when later observations `d+1:` are deleted (truncation-invariance: `filtered_probs(obs)
  .iloc[d] == filtered_probs(obs.iloc[:d+1]).iloc[d]` to `1e-12`) — proving no backward
  information. A smoothed posterior would FAIL this; this is the leak regression guard.
- **Gate range & sign-preservation (rule 3).** `gross_multiplier` output is within
  `[0.3, 1.0]` everywhere and strictly positive for any valid posterior; a degenerate
  all-high-vol posterior → `G ≈ 0.3`, all-low → `G ≈ 1.0`. Assert `G` never `≤ 0`.
- **Validation/guards.** `fit` raises on `< MIN_FIT_DAYS` rows and on non-finite rows;
  `n_states ∉ {2,3}` raises; `gate_weights` length/ordering mismatch raises; `params`
  before `fit` raises; `gross_multiplier_series(lag_days=0)` raises.
- **Cov-floor stability.** Feed a near-collapsed cluster (many identical rows) and assert
  `fit` completes with SPD `covs` (Cholesky succeeds) rather than diverging.

### 5.2 Property / timing — `tests/property/test_regime_timing.py`

The load-bearing leakage proof (correctness rule 4). Two complementary properties:

- **Producer lag (synthetic, no fit needed — inject a known `filt` series).**
  `gross_multiplier_series` with `lag_days=1`: the value indexed at day `D` must EQUAL
  the un-lagged multiplier of day `D-1`, for all `D ≥ 1`; day 0 = `1.0`. Hypothesis over
  random daily observation lengths and `K∈{2,3}`.
- **Consumer cannot see day-`d` data (the real proof).** Take a fitted gate and a daily
  observation series. For a random day `d`, **mutate `x_d` (and all `x_{>d}`) to NaN/±∞**,
  recompute the gate series, and assert the gate value applied to EVERY hour-bar of day
  `d` (via the Phase-12 `merge_asof(... right_on="available_at", direction="backward")`)
  is **bit-identical** to the unmutated run. If any hour of day `d` consumed `x_d`, the
  poisoned value would change `G` for that day → test fails. Also assert the FIRST gated
  hour-bar with a non-`1.0` (non-cold-start) gate has `ts_open ≥ available_at(first_obs,
  D1) + Δ_1h`, i.e. the gate is never live before its source day has fully closed.
- **`available_at` monotonicity.** `merge_asof` direction="backward" on
  `available_at <= t` never selects a daily row whose `available_at > t` — checked over
  random hourly grids straddling `00:00` boundaries (the off-by-one zone from finding 13).

### 5.3 CI

`uv run ruff check`, `uv run mypy --strict src/alphaforge/regime`, `uv run pytest
tests/unit/test_regime_hmm.py tests/property/test_regime_timing.py`. All clean before the
phase is considered shippable. Wire `RegimeHMM`/`HMMParams`/`build_observations`/
`RegimeGate` into `regime/__init__.py` `__all__`.

---

## 6. Phase-12 handoff (where `G` enters the signal path — built later, noted here)

- Monthly refit: on the 1st (after daily close) rebuild observations over the expanding
  window (min `MIN_FIT_DAYS`), `RegimeHMM.fit`, freeze `HMMParams` for the month. In
  CPCV/walk-forward the HMM is refit **inside each training window only**, never on test
  data (§8). The refit job joins the unified scheduler (finding 25).
- Live/research apply: `G_d` series → `merge_asof` onto the hourly `(ts_open,
  instrument_id)` grid (§4 step 4) → multiply the existing `mu_ann` column produced by
  `SignalService._emit`. The μ contract (rule 5) is preserved: still ONE `mu_ann` column
  to the optimizer. The multiply happens in the alpha layer, after `_emit`, gated by a
  `RegimeGate` injected behind the Protocol (default `NullGate → 1.0` so the gate is
  opt-in and the parity tests stay green until Phase 12 turns it on).
```
