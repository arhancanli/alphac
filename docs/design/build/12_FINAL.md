# Phase 12 — FINAL: wire the ML meta-gate + HMM regime gate into the full-pipeline walk-forward

> **This sheet SUPERSEDES `12_integration.md`.** It folds in the load-bearing
> decisions D1–D7 (reconciled against `CRITIQUE_leakage.md` and
> `CRITIQUE_overfit.md`) and pins exact, on-disk signatures. Where it disagrees
> with `12_integration.md`, this sheet wins. The original spec's three known bugs
> are NOT to be reproduced: (a) re-z-scoring after the meta-gate (leakage #1),
> (b) the `DatetimeIndex` regime seam + double-lag join (leakage #4/#5), and
> (c) a flag-not-a-gate report with no must-beat-baseline predicate (overfit #1).

The Phase-9 (`alphaforge.ml`) and Phase-11 (`alphaforge.regime`) modules are
SHIPPED (commit `7039a1a`) and their seams are FROZEN. Phase 12 only *consumes*
those seams; it never edits `ml/` or `regime/`. The seams as they exist on disk
(do not redefine — quoted verbatim from the modules):

- `ml.model.MetaModel` (= `ModelProtocol`): `feature_names: tuple[str,...]`,
  `model_id: str`, `predict_proba(X)->ndarray`,
  `bet_size(x: pd.DataFrame, side: pd.Series) -> pd.Series` (returns
  `side*magnitude`, magnitude ∈ [0,1], sign == sign(side), **never flips**).
  `IdentityMeta(feature_names=())` is the OFF gate (`|size| ≡ 1`).
  `HistGBMMetaModel.fit(X, y, w, t1, windows, *, label_is_net=True)`.
  `FitWindows(train_start, es_start, iso_start, fit_end)`. `bet_size_from_prob`.
- `ml.retrain`: `build_fit_windows`, `weekly_retrain`, `judge_promotion`,
  `PromotionVerdict`, `dataset_content_sha`, `MLDataset` Protocol
  (`matrices(start,end)->(X,y,w,t1,side)`, `ret_signed(start,end)`,
  `label_is_net`). `ml.registry`: `ModelRegistry`, `ModelCard`.
- `labeling`: `apply_triple_barrier` / `TripleBarrierConfig`, `sample_weights`,
  `make_meta_label_dataset` / `MetaLabelDataset` / `make_meta_labels`.
- `regime.hmm.RegimeGate` Protocol:
  `gross_multiplier_series(obs: pd.DataFrame, *, lag_days: int = 1) -> pd.Series`
  keyed by the day-`D` `ts_open` it APPLIES TO, **already lagged exactly once**
  (value at day `D` = filtered posterior through day `D-1` close; cold start →
  `1.0`). `RegimeHMM(n_states=3).fit(obs)->self`. `build_observations(daily_btc)`
  → frame `[m, v, available_at]` indexed by int64 `ts_open`. `IdentityRegime`.
  `MIN_FIT_DAYS = 730`.
- `signals.service.SignalService.compute_research(start, end)` →
  `DataFrame[alpha_blend, mu_ann]` on the `(ts_open, instrument_id)` MultiIndex;
  `_emit` builds `a_tilde = blend(zs, weights, mask, ...)` then
  `mu = GrinoldSizer.mu_ann(a_tilde, frame[SIGMA_COLUMN])`.
- `signals.sizing.GrinoldSizer.mu_ann` is **LINEAR** in `alpha_tilde`
  (`mu_ann = ic_target·sigma·sqrt(h)·F̃·(8760/h)`).
- `analytics.walkforward.WalkForwardRunner.run(...)`: computes
  `full_frame = compute_research(start,end)` ONCE, slices per leg via an
  `in_leg` boolean mask on `full_ts`, builds/`load_leg`s ONE `BlendStrategy`,
  runs `EventDrivenBacktester` per leg compounding cash, stitches equity, then
  `compute_validation(equity, trial_config, log, now_ms, dsr_fn) -> ValidationReport`
  (`_DSR_GATE = 0.95`; `trial_config` hashed for honest `N` via `ExperimentLog`).

All epoch-ms timestamps are `alphaforge.core.time.Ms` (int64). **Never** a
`pd.DatetimeIndex` or `pd.Timestamp` in any new seam (leakage #5). Style: frozen
`@dataclass(slots=True, kw_only=True)`, `Final` constants, full type hints,
`mypy --strict` + `ruff` clean. Tests use synthetic fixtures; never touch the
live data lake (`ingest.lock`).

---

## The seven load-bearing decisions (authoritative)

### D1 — Gating is MULTIPLICATIVE on `mu_ann`; NEVER re-z-score (kills leakage #1)

Because `mu_ann` is **linear** in `F̃` (verified: `GrinoldSizer.mu_ann`), the gate
applies as a magnitude-only multiply. The reported blend column and the gated
`mu_ann` are:

```
F̃_{i,t}        = alpha_blend_{i,t} · |size_meta|_{i,t}          # the gated signal magnitude
mu_ann_gated   = mu_ann_blend_{i,t} · |size_meta|_{i,t} · G_d   # equivalent, by linearity
```

- `|size_meta| = abs(meta.bet_size(x, side=sign(alpha_blend)))` ∈ [0,1] (the
  bet-size map floors below `P_MIN` to 0 and never flips sign).
- `G_d` ∈ (0,1] from the regime gate.
- `sign(mu_ann_gated) == sign(alpha_blend)` **by construction** (both factors are
  ≥ 0). There is **no** call to `cs_zscore` / no re-standardization anywhere after
  gating. The `ALPHA_BLEND_COLUMN` in the emitted frame keeps the **ungated** `Ã`
  (the audit/IC quantity); the gate's entire effect lives in `mu_ann`.
- Equivalence used in code: rather than recompute `mu_ann` from `F̃`, multiply the
  already-computed blend `mu_ann` by `|size|` then by `G_d` (one vector multiply
  each), which is identical to `GrinoldSizer.mu_ann(a_tilde·|size|, sigma)·G` by
  linearity and avoids a second `mu_ann` call. The OFF path multiplies by 1.0 → no
  numeric perturbation (D7).
- μ-contract (rule 5) holds trivially: `|size| ∈ [0,1]`, `G ∈ (0,1]` only shrink,
  so `|mu_ann_gated| ≤ |mu_ann_blend|` and the optimizer's `|mu_ann| < 3.0`
  tripwire can only get safer.

### D2 — Regime broadcast is a SINGLE backward `merge_asof` on `ts_open` (kills leakage #4)

The daily `G` series from `gross_multiplier_series(obs, lag_days=1)` is **already
lagged once** and is keyed by the day-`D` `ts_open` it applies to. Broadcast to
hourly `mu_ann` rows with **one** join:

```python
pandas.merge_asof(
    left=hourly_rows_sorted_by_ts_open,         # the (ts_open, instrument_id) panel, ts_open key
    right=g_series.rename("regime_gate").reset_index(),   # columns: [ts_open, regime_gate]
    left_on="ts_open", right_on="ts_open",
    direction="backward", allow_exact_matches=True,
)
```

Key on the day-`D` `ts_open` (the gate's own index), **NOT** on `available_at`. Do
**not** `shift` again. Rows before the first available gate day (cold start) get
`G = 1.0` (the gate already fills cold-start with its max weight 1.0; any residual
left-NaN from the asof is `fillna(1.0)` — a missing regime read must never zero the
book). Floor the hourly `ts_open` to its UTC day only if the gate key is daily-
aligned; since both the gate and the hourly panel are epoch-ms on the same venue
grid, the backward asof selects the most-recent day-`D` `ts_open ≤ hour_ts`, which
is exactly the gate for the day containing the hour.

### D3 — HMM walk-forward window is EXPANDING `[global_start, test_start)` (kills leakage #14)

Per leg, fit the HMM on daily BTC observations with `ts_open < test_start` only —
an **expanding** window anchored at the global run start, **never** leg-local. If
fewer than `MIN_FIT_DAYS` (730) finite daily obs are available
(`build_observations` raises `ValueError`), fall back to `IdentityRegime` for that
leg (documented cold start) rather than crashing. The real no-leak invariant the
test asserts is: **no `ts_open >= test_start` daily obs enters any HMM fit.** Refit
per leg (cheap: a few seconds on ≤ ~3 000 daily rows); a monthly-cadence cache is a
permitted optimization but the per-leg refit is the reference.

### D4 — Meta-model trained PER LEG on the purged train window; ONE shared feature assembly (train/serve parity, kills leakage #15)

Per leg, train on the purged train window via
`build_fit_windows(asof=test_start, horizon_bars=...)` →
`HistGBMMetaModel.fit(X, y, w, t1, windows, label_is_net=True)` where the dataset
is assembled over `[train_start, test_start)`. `FitWindows` already carves
train/40d-ES/20d-iso and the fit purges train rows whose label `t1` overlaps the ES
block; **no `ts_open >= test_start` decision bar enters the fit** because
`fit_end = test_start − horizon_bars·Δ`.

**TRAIN/SERVE PARITY is the load-bearing invariant (leakage #15).** The model's X
matrix is the engine's **processed** decision-time surface: `direction!=0` alphas
arrive POST-CSPipeline (winsorize→zscore, PIT-masked, direction-signed) — i.e. the
`zs` panel — and `direction==0` risk/regime context arrives RAW from the engine
`frame`. Both training (the `MLDataset` builder) and serve (`SignalService._emit`)
MUST build X through **one shared helper** so the processed surface is byte-
identical. The original `12_integration.md` `x = frame[feature_names]` is WRONG: it
hands raw factor values for the directional alphas, skewing train vs serve.

**The shared helper:** `signals/gating.py::assemble_meta_features`. See §3.

### D5 — Must-beat-baseline gate (kills overfit #1)

A gated variant is **live-eligible** only if, measured on the **identical** purged
legs net of fees + half-spread + funding:

```
clears_baseline_gate  ==  (dsr >= _DSR_GATE)                 # 0.95
                          AND (dsr > baseline.dsr)
                          AND (sr_ann > baseline.sr_ann)
```

Implemented as a hard predicate `clears_baseline_gate` (a field on
`ValidationReport`, computed in the `run` tail) plus a compare-to-baseline helper.
A gated variant that **ties or loses** to the blend-only baseline on either DSR or
annualized Sharpe is reported **NOT live-eligible** — even if its own DSR ≥ 0.95.
`cli/research_cmds.py::evaluate`'s `eligible` is extended to require it.

### D6 — Honest trial count (kills overfit #2)

When `ml` or `regime` is on, `trial_config` must hash the **actual gate
parameters**, not two booleans:

- `ml`: `True`/`False`; when `True`, also `ml_feature_set_sha` (sha256 of the
  resolved sorted `feature_names`, 16 hex) and `ml_window_days`.
- `regime`: `True`/`False`; when `True`, also `regime_n_states`,
  `regime_gate_weights` (the tuple), `regime_lag_days`.

So blend-only / `--ml` / `--regime` / `--ml --regime`, and any **tuned** gated
variant (different feature set, different `n_states`, different gate weights), each
hash to a DISTINCT config → a distinct DSR trial → `N` rises → `SR*` rises → the
gate gets harder, which is the point. Idempotent re-runs of the same config still
count once.

### D7 — OFF == identity, byte-for-byte

With `ml=False` and `regime=False` the runner output (`equity`, `validation`, the
full `WalkForwardResult`) is **identical to today's HEAD**:

- The runner's OFF path stays the single global `compute_research(start,end)` +
  slice — untouched, so `test_walkforward_equivalence.py` still holds.
- The gated path is taken ONLY when `ml or regime`. `SignalService` keeps its
  existing `__init__`/`_emit`/`on_bar_close` and parity tests **untouched**; the
  one new `SignalService` method (`compute_research_gated`) is **purely additive**
  and, with both flags off, delegates to `compute_research` (byte-identical).
- `trial_config` gains keys ONLY when a gate is on. With both off, `trial_config`
  is byte-identical to today → the same `config_hash` → `N` unchanged.

---

## Files to CREATE / EDIT (exact)

### 1. NEW: `src/alphaforge/signals/gating.py`

The gate adapters, the shared feature assembly helper, and the pure gating math.
This is the ONLY new file in `signals/`. It depends on `ml`/`regime` only through
their frozen Protocols (`MetaModel`, `RegimeGate`).

```python
# module constants
ML_GATE_LAG_OK: Final  # (none needed; documented)

def assemble_meta_features(
    frame: pd.DataFrame,                    # engine output (raw columns), MultiIndex
    zs: Mapping[str, pd.Series],            # processed directional z panel (post-CSPipeline, signed)
    feature_names: tuple[str, ...],         # the model's pinned column order
) -> pd.DataFrame:
    """THE single train/serve feature surface (D4 / leakage #15).

    For each name in feature_names: if it is a directional-alpha name present in
    `zs`, take the PROCESSED, direction-signed z column from `zs`; otherwise take
    the RAW engine column from `frame[name]` (the direction==0 risk/regime
    context). Returns a (ts_open, instrument_id) MultiIndex float frame with
    columns in EXACTLY feature_names order. A name absent from BOTH zs and frame
    is a KeyError (no silent positional drift). Used IDENTICALLY by the Phase-9
    dataset builder (training) and by `_emit` (serve), so the X at decision bar t
    is byte-identical on both paths — the parity invariant the test pins."""

def apply_meta_gate(
    a_tilde: pd.Series,                     # the ungated blend Ã (sign source)
    x: pd.DataFrame | None,                 # assembled features; None ⇒ identity
    meta: MetaModel,
    mask: pd.Series,                        # PIT membership (NaN non-members stay NaN)
) -> pd.Series:
    """F̃ = Ã · |size|, magnitude-only (D1). side = sign(a_tilde); |size| from
    meta.bet_size(x, side). NO cs_zscore — never re-standardize (leakage #1).
    With IdentityMeta, |size| ≡ 1 ⇒ F̃ == Ã (NaN-preserving under mask). Returns
    a float Series aligned to a_tilde.index."""

def apply_regime_gate(
    mu_ann: pd.Series,                      # the (post-meta) mu_ann on the hourly panel
    g_series: pd.Series,                    # daily G keyed by day-D ts_open, ALREADY lagged
) -> pd.Series:
    """Broadcast G_d to hourly mu_ann rows via ONE backward merge_asof on ts_open
    (D2), allow_exact_matches=True. Rows with no available G ⇒ G=1.0 (cold start;
    never NaN). Multiply mu_ann by G. With an all-1.0 g_series (IdentityRegime) the
    result equals mu_ann exactly (D7). Returns a float Series aligned to mu_ann.index."""
```

`assemble_meta_features` is the resolution of leakage #15: the directional-alpha
names resolve to `zs` (processed, signed) and the `direction==0` context names
resolve to `frame` (raw) — matching `09_ml.md §3` ("cross_sectional=True ones
arrive POST-CSPipeline … direction-signed" / "risk/regime context … fed raw"). The
membership of each set is decided by *presence in `zs`* (the service's
`_directional_zs` already produces exactly one `zs` entry per directional alpha),
not by a hardcoded list.

### 2. EDIT: `src/alphaforge/signals/service.py` (purely additive — D7)

Do **not** touch `__init__`, `_emit`, `on_bar_close`, `_panel`, `_directional_zs`,
`_weights_from_panel`, or any existing method body — the deployed-path parity tests
(`test_phase4_deployed_path.py`, `test_mu_contract.py`) must stay green. Add ONE
new method, sibling of `compute_research`:

```python
def compute_research_gated(
    self,
    start: Ms,
    end: Ms,
    *,
    train_start: Ms,
    test_start: Ms,
    meta: MetaModel,                 # frozen, trained on [train_start, test_start)
    regime: RegimeGate,              # frozen, fit on expanding [global_start, test_start)
    daily_obs: pd.DataFrame,         # build_observations(...) frame for the regime broadcast
) -> pd.DataFrame:
    """Blend → meta-gate (D1) → mu_ann → regime-gate (D2) over [start, end).

    Identical chain and PIT discipline to compute_research; the gates are PURE
    functions of the per-leg frozen artifacts. Returns the SAME schema
    [alpha_blend (ungated Ã), mu_ann (gated)] on the (ts_open, instrument_id) index.
    With IdentityMeta + IdentityRegime this returns a frame EQUAL to
    compute_research(start, end) (asserted by test 1)."""
    frame, mask, zs = self._panel(start, end)
    weights = self._weights_from_panel(frame, mask, zs)
    a_tilde = blend(zs, weights, mask, min_members=self._min_members)
    x = assemble_meta_features(frame, zs, meta.feature_names) if meta.feature_names else None
    f_tilde = apply_meta_gate(a_tilde, x, meta, mask)
    mu = self._sizer.mu_ann(f_tilde, frame[SIGMA_COLUMN])
    g = regime.gross_multiplier_series(daily_obs, lag_days=1)
    mu = apply_regime_gate(mu, g)
    return pd.DataFrame({ALPHA_BLEND_COLUMN: a_tilde, MU_ANN_COLUMN: mu}, index=frame.index)
```

Note this re-uses the EXISTING `_panel` / `_weights_from_panel` / `blend` / `_sizer`
so the OFF-equivalent path (`IdentityMeta`/`IdentityRegime`) is mechanically the
same numbers as `compute_research`. The trained-meta path threads the model's
feature specs into `_panel` only if the model needs engine columns that the alpha
specs don't already produce; v1 model features are a subset of the alpha + sigma +
context columns the engine already computes for the blend, so `_panel`'s existing
spec set suffices. If a model lists a `direction==0` context column not already in
the alpha set, the per-leg builder (runner, §4) constructs a transient
`SignalService` whose `alpha_names`/specs include those context specs — additive,
no edit to the shared body. Document this in the method docstring.

### 3. EDIT: `src/alphaforge/analytics/walkforward.py`

**3a. `SignalSource` Protocol (~L126)** — add the gated method (the OFF path keeps
using `compute_research`, so its global-compute optimization is untouched):

```python
def compute_research_gated(
    self, start: Ms, end: Ms, *, train_start: Ms, test_start: Ms,
    meta: MetaModel, regime: RegimeGate, daily_obs: pd.DataFrame,
) -> pd.DataFrame: ...
```

**3b. `ValidationReport` (~L154)** — add baseline + Occam fields; extend
`to_json_obj`:

```python
variant: str = "blend"                         # "blend" | "ml" | "regime" | "ml+regime"
gate_inactive_frac: float = 0.0                # leakage #19 observability (cold-start fraction)
baseline: "ValidationReport | None" = None     # ungated companion when gated
clears_baseline_gate: bool = False             # D5 / overfit #1
```

`to_json_obj` emits `variant`, `gate_inactive_frac`, `clears_baseline_gate`, and a
nested `baseline` block (recursively `to_json_obj()` or `None`). The existing
`clears_dsr_gate` and all current fields are unchanged.

**3c. `WalkForwardRunner.__init__`** — add optional gated-build collaborators
(kept None on the OFF path so nothing changes):

```python
cost_model is already held; add:
    registry: ModelRegistry | None = None,            # per-leg model register/lookup (optional)
    daily_btc_reader: <callable/Reader> | None = None,# source of the daily BTC OHLC for build_observations
```

The daily BTC source is read once over `[global_start, end)` at run start (a single
`reader.read_window(..., tf=Timeframe.D1)` for the BTC instrument) and sliced per
leg to `ts_open < test_start`; if the slice has `< MIN_FIT_DAYS` rows after
`build_observations`, that leg uses `IdentityRegime` and increments the
`gate_inactive` counter.

**3d. `compute_baseline_gate` helper (module-level, NEW)** — D5:

```python
def compare_to_baseline(variant: ValidationReport, baseline: ValidationReport) -> bool:
    """D5 / overfit #1: the must-beat-baseline predicate. True iff
        variant.clears_dsr_gate
        AND variant.dsr > baseline.dsr
        AND variant.sr_ann > baseline.sr_ann.
    Strict inequalities: a tie loses (a tying gated variant is NOT live-eligible)."""
    return bool(
        variant.clears_dsr_gate
        and variant.dsr > baseline.dsr
        and variant.sr_ann > baseline.sr_ann
    )
```

**3e. `WalkForwardRunner.run` signature (~L442)** — add `ml: bool = False,
regime: bool = False` (keyword-only, after `dsr_fn`).

**3f. The leg loop (~L546–602)** — branch on `ml or regime`:

- **OFF (default):** unchanged. `full_frame = self._signals.compute_research(start,
  end)` once, `in_leg` slice per leg. Byte-identical to today (D7).
- **ON:** inside the leg loop, BEFORE building/`load_leg`-ing the strategy:
  1. `meta`: if `ml`, build the per-leg `MLDataset` over `[train_start,
     test_start)` (via `make_meta_label_dataset` over the leg's bars+events+the
     engine's processed features assembled by `assemble_meta_features`),
     `build_fit_windows(asof=test_start, horizon_bars=settings.signals.horizon_bars)`,
     `HistGBMMetaModel(...).fit(X, y, w, t1, windows, label_is_net=True)`; else
     `IdentityMeta()`.
  2. `regime`: if `regime`, `obs = build_observations(daily_btc[ts_open <
     test_start])`; if `len(obs) >= MIN_FIT_DAYS` →
     `RegimeHMM(n_states=...).fit(obs)`, else `IdentityRegime()` (+1 to
     `gate_inactive`); else `IdentityRegime()`.
  3. `signal_frame = self._signals.compute_research_gated(train_start, test_end,
     train_start=train_start, test_start=test_start, meta=meta, regime=regime_gate,
     daily_obs=<obs over [train_start, test_end) for the broadcast>)`. The frame is
     then used exactly as the OFF slice (build/`load_leg` the ONE `BlendStrategy`,
     flat-restart positions, compound cash). Pipeline per leg is therefore: factors
     → blend → ml gate → regime gate → optimizer (`BlendStrategy`) → next-open fills
     (`EventDrivenBacktester`).

  The frozen `meta`/`regime` are discarded after the leg (or registered on the
  optional `registry`). The HMM and model are trained on `< test_start` data only.

**3g. ON-path baseline + variants** — after the gated stitch, ALSO compute the
blend-only OOS curve once (reuse `compute_research` global frame, which is cheap and
already the baseline-leg signal source) and run `compute_validation` for it,
recording its own trial; build the variant `ValidationReport`, set its
`baseline=<blend ValidationReport>`, `variant=` one of `ml`/`regime`/`ml+regime`,
`gate_inactive_frac = gate_inactive / n_legs`, and
`clears_baseline_gate = compare_to_baseline(variant_report, baseline_report)`.

**3h. `config` dict (~L612) and `trial_config` (~L643)** — D6. Add `"ml": ml`,
`"regime": regime` to BOTH. Additionally, ONLY when the respective gate is on, add
to `trial_config`: `ml_feature_set_sha`, `ml_window_days` (ml on);
`regime_n_states`, `regime_gate_weights`, `regime_lag_days` (regime on). With both
off these keys are absent → `config_hash` byte-identical to today (D7).

**3i. `compute_validation`** — unchanged signature and body; the baseline/variant
distinction and `clears_baseline_gate` are computed in the `run` tail (each variant
is its own `compute_validation` call with its own `trial_config`, so each is a
distinct ledger trial — D6). `_DSR_GATE`, `_MIN_DSR_TRIALS`, the leak-free contract
all unchanged.

### 4. EDIT: `src/alphaforge/cli/walkforward_cmds.py`

**4a. options (~L132, after `--alphas`)** — add:

```python
ml: Annotated[bool, typer.Option("--ml/--no-ml",
    help="Gate the blend by a per-leg-trained meta-model (|size| scales Ã; never "
         "flips). Default OFF — byte-identical to the shipped blend-only run.")] = False,
regime: Annotated[bool, typer.Option("--regime/--no-regime",
    help="Multiply mu_ann by the per-leg-refit HMM gross multiplier G (filtered "
         "through day d-1; no same-day leak). Default OFF.")] = False,
```

**4b. `runner.run(...)` call (~L203)** — pass `ml=ml, regime=regime`. The CLI keeps
building the blend-only `SignalService` (the warm-up/identity reference); the runner
injects per-leg artifacts. Construct `WalkForwardRunner` with the optional
`registry` + `daily_btc_reader` collaborators only when `ml or regime`.

**4c. summary print (~L233)** — add a line printing `variant` and, when
`validation.baseline is not None`, the baseline DSR + `clears_baseline_gate` +
`gate_inactive_frac`, e.g.:
`variant ml+regime  DSR 0.71 vs baseline 0.55  beats-baseline: True  gate-inactive 12%`.

### 5. EDIT: `src/alphaforge/cli/research_cmds.py` (`evaluate`, ~L280)

Extend `eligible` to require the baseline gate when the run is a gated variant. Read
the variant/baseline from `walkforward.json`'s `validation` block (the `evaluate`
command already loads the run dir):

```python
# load validation.variant / validation.baseline / validation.clears_baseline_gate
# from walkforward.json (if present alongside equity.parquet)
baseline_ok = (validation is None) or validation.get("baseline") is None or \
              bool(validation.get("clears_baseline_gate"))
eligible = (dsr_ok if config_matrix is None else (dsr_ok and pbo_ok)) and baseline_ok
```

Print a `must-beat-baseline gate` line and, for a gated variant that ties/loses,
print `NOT live-eligible (does not beat blend baseline)`.

### 6. Phase 9/11 — NOT edited

`ml/` and `regime/` are frozen. `judge_promotion` (overfit #5) already flags
`label_space_only=True`; the binding economic gate is this phase's
`clears_baseline_gate` on the gated WF. No change.

---

## Integration tests to add (under `tests/integration/`)

All: offline, `tmp_path` lake, deterministic (`seed=42`), no network — reuse the
synthetic-lake fixture idiom from `test_mu_contract.py` /
`test_walkforward_equivalence.py`.

1. **`test_gates_default_off_identity.py`** — the headline D7 guarantee.
   - Assert `SignalService.compute_research(start, end).equals(
     SignalService.compute_research_gated(start, end, train_start=..., test_start=...,
     meta=IdentityMeta(), regime=IdentityRegime(), daily_obs=<obs>))` (exact frame
     equality — both `alpha_blend` and `mu_ann`).
   - Assert `WalkForwardRunner.run(..., ml=False, regime=False)` produces an
     `equity` Series and a `ValidationReport` byte-identical to the current run on
     the same fixture (`equity.equals(...)`; same `config_hash` on the ledger; same
     `to_json_obj()`).

2. **`test_meta_gate_scales_never_flips.py`** — D1 / leakage #1, the bug that hid
   behind the identity case. Feed a stub `MetaModel` returning **mixed, non-constant**
   `|size|` over a cross-section with **mixed `Ã` signs**. Assert: (i)
   `sign(f_tilde) == sign(a_tilde)` for **every finite row** (the sign-flip case the
   old re-z-score body failed); (ii) `|size| ≡ 1` reproduces the ungated `mu_ann`
   exactly; (iii) the gated `mu_ann` still clears `check_mu_ann_contract` /
   `|mu_ann| < 3.0` (rule 5); (iv) `assemble_meta_features` returns processed `zs`
   columns for directional names and raw `frame` columns for context names (the
   train/serve parity surface — a directional name's served column equals its `zs`
   value, NOT `frame[name]`).

3. **`test_regime_gate_no_same_day_leak.py`** — D2 / leakage #4 / #13. Build a stub
   `RegimeGate` whose daily `G` would differ if it used day `d` vs `d-1`; span a
   regime flip. Assert: every hour of day `D` receives the gate keyed at day `D`'s
   `ts_open` (= the producer's already-lagged `filt_{D-1}` value), via the single
   backward `merge_asof` (no second shift); the `t == day-open` boundary matches
   `allow_exact_matches=True`; cold-start rows get `G = 1.0` (never NaN); and
   `0 < G ≤ 1 ⇒ |mu_ann_gated| ≤ |mu_ann|` everywhere.

4. **`test_walkforward_full_pipeline.py`** — end-to-end on the tmp lake with
   `ml=True, regime=True`. Inject spies on `HistGBMMetaModel.fit` and `RegimeHMM.fit`.
   Assert: (i) **no `ts_open >= test_start`** row enters EITHER fit, for every leg
   (the D3/D4 OOS-honest invariant — assert on the spied `X.index`/`obs.index` max
   ts); (ii) a leg whose expanding daily window has `< MIN_FIT_DAYS` obs uses
   `IdentityRegime` (G≡1) and bumps `gate_inactive_frac`, rather than raising; (iii)
   ONE stitched artifact set is written (`equity.parquet`, `walkforward.json`, one
   tearsheet); (iv) the OOS pipeline order is factors→blend→ml→regime→optimizer→
   next-open fills (fill `ts` == decision `ts + Δ`, reusing the next-open assertion
   from `test_mu_contract.py`).

5. **`test_experiments_honest_trial_count.py`** — D5 + D6 / overfit #1, #2. Run
   blend-only, `--ml`, `--regime`, `--ml --regime` against ONE `ExperimentLog`.
   Assert: (i) four DISTINCT hashes (`n_trials() == 4`) and re-running any one is
   idempotent (still 4); (ii) changing a gate parameter (e.g. `regime_n_states`
   2→3, or the ml feature set) makes a FIFTH distinct hash (D6 — the gate params are
   in `trial_config`, not just the booleans); (iii) the gated `ValidationReport`
   carries a `baseline` whose DSR is the blend-only trial's; (iv)
   `clears_baseline_gate` is `False` for a gated variant whose `dsr <= baseline.dsr`
   OR `sr_ann <= baseline.sr_ann` (construct a stub model that ties), and such a
   variant is reported NOT live-eligible; (v) `walkforward.json`'s
   `validation.variant`, `validation.clears_baseline_gate`, and nested
   `validation.baseline` round-trip through `to_json_obj`.

---

## Edit checklist (anchors, by file)

- `signals/gating.py` — **NEW**: `assemble_meta_features` (D4 parity helper),
  `apply_meta_gate` (D1, no cs_zscore), `apply_regime_gate` (D2, one merge_asof).
  Imports `MetaModel`/`RegimeGate` Protocols only.
- `signals/service.py` — **ADD** `compute_research_gated` (purely additive, D7);
  do NOT touch `__init__`/`_emit`/`on_bar_close`/`_panel`/`_directional_zs`.
- `analytics/walkforward.py` — `SignalSource` +`compute_research_gated`;
  `ValidationReport` +`variant`/`gate_inactive_frac`/`baseline`/`clears_baseline_gate`
  & `to_json_obj`; `compare_to_baseline` (NEW); `WalkForwardRunner.__init__`
  +`registry`/`daily_btc_reader`; `run` +`ml`/`regime`; leg loop OFF/ON branch
  (per-leg meta fit on `[train_start, test_start)`, HMM expanding fit on
  `ts_open < test_start`); baseline+variant validation in the tail; `config` &
  `trial_config` +gate keys (D6).
- `cli/walkforward_cmds.py` — options +`--ml`/`--regime`; `runner.run` passthrough;
  summary +variant/baseline/beats-baseline/gate-inactive line.
- `cli/research_cmds.py` — `evaluate`'s `eligible` requires `clears_baseline_gate`
  for a gated run (D5); print the must-beat-baseline verdict.
- `tests/integration/` — the five tests above.
- Phase 9/11 (`ml/`, `regime/`) — consumed only; NOT edited.
