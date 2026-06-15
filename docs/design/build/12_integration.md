# Phase 12 — Integration: ML gate + regime gate into the signal path & walk-forward

Scope: wire the Phase-9 ML meta-model and the Phase-11 HMM regime gate into the
ONE alpha→portfolio seam (`signals/`) and the ONE walk-forward orchestrator
(`analytics/walkforward.py`), **behind flags that default OFF** so every shipped
artifact is byte-for-byte unchanged until a flag is set. This doc gives exact
edit anchors (function + nearby line markers as of HEAD), the contracts each new
seam honours, and the integration tests to add.

Ground rules carried verbatim from `alphaDesign.md` §5.3/§8/§9.2 and
`leakageCritique.md` findings 2/11/12/13:

- **R3 (gate, never flip):** the ML gate produces `F = Ã · |size|` re-z-scored;
  since `sign(size) = sign(Ã)` by construction (§5.3), it only **scales**. The
  blend's sign is sacred.
- **R4 (no same-day regime leak):** `G` for ALL hours of day `d` uses the
  filtered posterior through day `d−1` close. Joined by an explicit
  `available_at = day_close + lag`, never the in-progress day.
- **R5 (mu contract):** the layer still emits exactly one column, `mu_ann`
  (`signals/sizing.py::MU_ANN_COLUMN`). The gates multiply factors **inside** the
  Grinold formula; the column name, units, and the optimizer's `|mu_ann| < 3.0`
  tripwire are untouched. `G ∈ (0, 1]` and `|size| ∈ [0, 1]` both shrink, so the
  tripwire can only get safer.
- **OFF == identity:** with both flags off, `F̃ = Ã` and `G = 1`, so
  `SignalService.compute_research` / `.on_bar_close` and the walk-forward emit
  numbers identical to today (pinned by an equivalence test).

---

## 0. New seams introduced (Protocols, so Phase 9/11 internals stay swappable)

Two clean Protocol seams live next to the consumers. They are the ONLY surface
`signals/` depends on; Phase 9 (`ml/`) and Phase 11 (`regime/`) implement them.
This keeps the platform constraint (sklearn `HistGradientBoostingClassifier`
now, lightgbm later; hand-rolled HMM, no `hmmlearn`) entirely behind the seam.

```python
# signals/gating.py  (NEW module — the gate adapters + Protocols + identity defaults)

class MetaModel(Protocol):
    """Phase-9 meta-model seam (alphaDesign.md §5.3). Pure, PIT-respecting."""
    feature_names: tuple[str, ...]          # engine columns it consumes
    model_id: str                           # stamped on predictions (§4.4)
    def bet_size(self, x: pd.DataFrame, side: pd.Series) -> pd.Series:
        """|size| ∈ [0,1] per (ts_open, instrument_id): LdP bet size from
        calibrated P(win) (§5.3), floored at 0 below p_min, side-signed so
        sign(size) == side. The CALLER passes side = sign(Ã); this never reads
        Ã's magnitude and never returns a sign opposite to `side`."""

class RegimeGate(Protocol):
    """Phase-11 HMM regime seam (alphaDesign.md §8; leakage finding 13)."""
    def gross_multiplier(self, day_index: pd.DatetimeIndex) -> pd.Series:
        """G_d ∈ (0,1] per UTC day, from the FILTERED posterior through day d−1
        close — `available_at = day_close + lag`. Forward-only; never smoothed."""
```

`signals/gating.py` also holds two **identity** defaults used when a flag is off
or no artifact is supplied — so the consumer body has a single code path:

```python
class IdentityMeta:    # |size| ≡ 1  ⇒  F = Ã·1 = Ã
class IdentityRegime:  # G ≡ 1
def apply_meta_gate(a_tilde, x, meta, mask, min_members) -> pd.Series:  # returns F̃
def apply_regime_gate(mu_ann, regime, *, timeframe) -> pd.Series:       # broadcasts G_d to hourly mu
```

`apply_regime_gate` does the day→hour join: it maps each `mu_ann` row's
`ts_open` to its UTC day, looks up `G_d` from the gate (which was built with the
`d−1` rule), and multiplies. The day-floor + `available_at` lag live INSIDE
`RegimeGate.gross_multiplier`, so the consumer cannot reintroduce the leak.

---

## (a) SignalService applies the trained meta-model to scale |Ã|

**File:** `src/alphaforge/signals/service.py`.

**Anchor 1 — constructor (`SignalService.__init__`, ~L132–165).** Add two
keyword-only params after `min_members`, both defaulting to the identity gate:

```python
    meta_model: MetaModel | None = None,     # None ⇒ IdentityMeta (OFF, default)
    regime_gate: RegimeGate | None = None,   # None ⇒ IdentityRegime (OFF, default)
```

Store `self._meta = meta_model or IdentityMeta()` and
`self._regime = regime_gate or IdentityRegime()`. When a real `meta_model` is
given, extend the spec list resolution: the meta-model's `feature_names` are
appended to the engine spec set (resolved via `registry.get`) so its X matrix is
computed on the SAME PIT window the alphas saw (no second engine pass, no skew).
Validate the names exist and don't collide with `SIGMA_COLUMN`/`_OPEN_COLUMN`
(mirror the existing collision guard at ~L155).

**Anchor 2 — `_emit` (~L263–273), THE single body both windows share.** This is
the one place the gates apply, so research and live get them identically (the
anti-skew invariant). Current body:

```python
        a_tilde = blend(zs, weights, mask, min_members=self._min_members)
        mu = self._sizer.mu_ann(a_tilde, frame[SIGMA_COLUMN])
        return pd.DataFrame({ALPHA_BLEND_COLUMN: a_tilde, MU_ANN_COLUMN: mu}, index=frame.index)
```

New body (gates between `blend` and the sizer; identity by default):

```python
        a_tilde = blend(zs, weights, mask, min_members=self._min_members)
        # (a) ML gate: F = Ã·|size| re-standardized to F̃; size's sign == sign(Ã),
        #     so this SCALES, never flips (alphaDesign §5.3, R3). IdentityMeta ⇒ F̃ = Ã.
        x = frame[list(self._meta.feature_names)] if self._meta.feature_names else None
        f_tilde = apply_meta_gate(a_tilde, x, self._meta, mask, self._min_members)
        mu = self._sizer.mu_ann(f_tilde, frame[SIGMA_COLUMN])
        # (b) regime gate: G_d (filtered through d−1 close, R4) multiplies mu_ann.
        mu = apply_regime_gate(mu, self._regime, timeframe=ANCHOR_TIMEFRAME)
        return pd.DataFrame({ALPHA_BLEND_COLUMN: a_tilde, MU_ANN_COLUMN: mu}, index=frame.index)
```

Notes locked to the codebase:
- `apply_meta_gate` computes `side = sign(a_tilde)`, gets `|size|` from
  `meta.bet_size(x, side)`, forms `F = a_tilde·|size|`, then re-z-scores via the
  same `cs_zscore(..., min_members=...)` under `mask` that `blend` uses (so a
  partially-informed name stays NaN and drops out — matching `blend`'s strict
  NaN discipline). `ALPHA_BLEND_COLUMN` still carries the **ungated** `Ã` (the
  raw blend is the audit/IC quantity; the gate's effect is in `mu_ann`).
- The gates apply AFTER `blend` and BEFORE/AROUND the sizer, never inside
  `blending.py` or `sizing.py` — those modules' docstrings already reserve this
  spot ("Future hooks … `F = Ã·|size|` … and a gross multiplier `G_t`", `sizing.py`
  ~L31–37). No edit to `sizing.py`'s formula: `F̃` and the post-multiply both
  flow through the existing `GrinoldSizer.mu_ann`.

**Anchor 3 — `on_bar_close` (~L218).** The live spec list `[*self._alpha_specs,
_SIGMA_SPEC]` must also include the meta-model's feature specs (same extension as
research's `_panel` at ~L233) so `frame[self._meta.feature_names]` exists at the
single decision instant. Parity (the deployed contract, module docstring) is
preserved because `_emit` is shared and the gates are pure functions of the
frame + as-of artifacts.

**Why `compute_research` stays leak-free with a real meta-model:** the model is a
FROZEN artifact passed in (trained on a prior window via Phase-9
`WalkForwardTrainer` with purged CV). `bet_size` reads only `x` at row `t`
(features through `t`) and `side` at `t`. No fit happens in `SignalService`. The
walk-forward (section d) is what supplies the correctly-trained-per-leg model.

---

## (b) Regime G multiplier applied to mu_ann

Covered by Anchor 2's `apply_regime_gate`. The contract (R4, finding 13):

- `RegimeGate.gross_multiplier(day_index)` returns `G_d` keyed by UTC day, where
  `G_d = Σ_k P(s_d=k | x_{1:d−1})·g_k`, `g=(1.0,0.7,0.3)` — the filtered
  posterior **through day d−1's close**. The `d−1` shift and
  `available_at = day_close + lag` (the Phase-11 default `lag = SignalsCfg`-level
  grace, e.g. one bar) live in the gate, asserted by its own unit test.
- `apply_regime_gate` floors each `mu_ann` row's `ts_open` (epoch-ms) to its UTC
  day, `merge_asof`-joins `G_d` (backward, on `available_at`), and multiplies.
  Rows whose day has no available `G` (cold start) get `G=1` (documented neutral,
  never NaN — a missing regime read must not zero the book).
- `G ∈ (0,1]` only shrinks gross, so the `|mu_ann| < 3.0` tripwire is unaffected
  and R5 holds.

The HMM is refit **inside each walk-forward training window only** (§8, never on
test data) — see section (d). In live, the gate is a frozen monthly-refit artifact
the loop holds, exactly like `BlendWeights`.

---

## (c) Walkforward gains --ml and --regime knobs

**File:** `src/alphaforge/cli/walkforward_cmds.py`.

**Anchor — option block in `walkforward(...)` (~L124, after `--alphas`).** Add:

```python
    ml: Annotated[bool, typer.Option("--ml/--no-ml",
        help="Gate the blend by the per-leg-trained meta-model (|size| scales Ã; "
             "never flips). Default OFF — identical to the shipped blend-only run.")] = False,
    regime: Annotated[bool, typer.Option("--regime/--no-regime",
        help="Multiply mu_ann by the per-leg-refit HMM gross multiplier G "
             "(filtered through day d−1; no same-day leak). Default OFF.")] = False,
```

**Anchor — `runner.run(...)` call (~L203–219).** Pass `ml=ml, regime=regime`
through. The CLI does NOT construct models/HMMs itself (it has no per-leg
window); it flips the runner's switches and the runner trains per leg (section d).
The trial config hash MUST include these flags so `--ml`/`--regime` runs are
counted as **distinct trials** for honest N (section e). The existing
`config_echo` and the rendered summary gain `ml`/`regime` lines.

`SignalService` in the CLI is still built blend-only (no `meta_model`/
`regime_gate` kwargs) — the runner injects the per-leg artifacts; the CLI's
service is the warm-up/identity reference.

---

## (d) Full-pipeline walk-forward as ONE artifact

**File:** `src/alphaforge/analytics/walkforward.py`. This is the deployment gate
(finding 12: "the only deployment gate must be the C-engine walk-forward of the
full pipeline"). Today the runner computes the signal frame ONCE and slices per
leg (`compute_research` at ~L546, slice at ~L564). With gates ON, the frame
becomes **leg-dependent** because each leg trains its own model/HMM on its own
train slice — so the single-global-compute optimization is replaced by a per-leg
gated recompute when (and only when) a gate is on.

**Anchor 1 — `SignalSource` Protocol (~L126).** It currently exposes only
`compute_research(start, end)`. Add the per-leg gated method the runner calls when
a flag is set (the blend-only path keeps using `compute_research`, so the OFF path
and its global-compute perf optimization are untouched):

```python
    def compute_research_gated(
        self, start: Ms, end: Ms, *, train_start: Ms, test_start: Ms,
        ml: bool, regime: bool,
    ) -> pd.DataFrame:
        """Blend → (ml gate) → mu_ann → (regime gate), where the meta-model is
        TRAINED and the HMM REFIT on [train_start, test_start) only (purged),
        then frozen and applied over [train_start, end). OFF flags ⇒ identical to
        compute_research over the same span."""
```

`SignalService.compute_research_gated` (new method in `service.py`, sibling of
`compute_research`):
1. If both flags off → delegate to `compute_research(start, end)` (byte-identical).
2. Build the meta-model: pull the Phase-9 `MLDataset` over `[train_start,
   test_start)` (features + cost-honest triple-barrier meta-labels, finding 11 —
   labels NET of fees+half-spread+expected funding via the shared
   `TransactionCostModel`), fit `HistGradientBoostingClassifier` behind the
   `MetaModel` Protocol with the Phase-10 `PurgedWalkForward`/embargo for early
   stopping. Freeze it.
3. Build the regime gate: fit the hand-rolled HMM on the BTC daily obs over
   `[train_start, test_start)`, expose `gross_multiplier` with the `d−1` filtered
   rule. Freeze it.
4. Re-run the blend over `[train_start, end)` with `_emit` now seeing the frozen
   `meta`/`regime` (i.e. construct a transient `SignalService` carrying them, or
   pass them into a shared `_emit`). Return the frame; the runner slices it to the
   leg's `[train_start, test_end)` exactly as today.

**Anchor 2 — `WalkForwardRunner.run` signature (~L442–463).** Add
`ml: bool = False, regime: bool = False`. **Anchor 3 — the leg loop (~L552–602).**
Replace the single pre-loop `full_frame = self._signals.compute_research(start,
end)` (~L546) with a branch:

- **OFF (default):** unchanged — one global `compute_research`, slice per leg.
  The shipped equivalence test (`test_walkforward_equivalence.py`) still holds.
- **ON:** inside the leg loop, before building/`load_leg`-ing the strategy, call
  `signal_frame = self._signals.compute_research_gated(train_start, test_end,
  train_start=train_start, test_start=test_start, ml=ml, regime=regime)`. The
  per-leg model/HMM is trained on `[train_start, test_start)` (the leg's train
  span = OOS-honest: test bars never touch the fit), applied over the leg, then
  discarded. This realizes §10.4's "models swap inside one continuous run"
  (the runner docstring at ~L59 already promises this arrives "with the ML layer").

The rest of the leg loop is unchanged: ONE `BlendStrategy` reused across legs
(risk state continuous, F-A), positions flat-restart, equity compounds. The
pipeline per leg is therefore exactly: **factors → blend → ml gate → regime gate
→ optimizer (`BlendStrategy` MVO/rank) → next-open fills (`EventDrivenBacktester`)**,
stitched into ONE `WalkForwardResult` (one `equity.parquet`, one
`walkforward.json`, one tearsheet — `WalkForwardResult.save` ~L248 unchanged).

**Anchor 4 — `config` dict (~L612–632) and `trial_config` (~L643–653).** Add
`"ml": ml, "regime": regime` to BOTH. The `config` echo is for the artifact; the
`trial_config` is the hashed trial identity (section e).

---

## (e) Validation block extends to the gated result + experiments.log

**File:** `src/alphaforge/analytics/walkforward.py`, `compute_validation`
(~L322) and the `run` tail (~L634–654). The existing block already records the
trial on `ExperimentLog` and attaches `psr`/`dsr` to `walkforward.json`'s
`validation` key (`ValidationReport.to_json_obj`, ~L189). Two changes:

1. **Honest trial count (finding 10).** Because `"ml"` and `"regime"` are now in
   `trial_config`, the blend-only run, `--ml`, `--regime`, and `--ml --regime`
   hash to four DISTINCT configs → four ledger lines → DSR's `N` counts each as a
   real trial. This is exactly the selection pressure the gates add: searching
   "does the ML/regime variant help?" is a trial and must deflate the survivor.
   No code change beyond adding the flags to `trial_config` (the ledger and
   `n_trials()`/`trial_sharpe_variance()` are already idempotent-by-hash, ~L251).

2. **Report the gated result alongside the ungated.** `ValidationReport` gains an
   optional companion so the artifact carries BOTH curves' verdicts when a gate is
   on. Cleanest wiring that doesn't perturb the OFF path: in `run`, when `ml or
   regime`, ALSO compute the blend-only OOS curve once (it is already the
   `compute_research` global frame the runner can reuse for a cheap baseline leg
   set) and call `compute_validation` for it too, recording its own trial. Attach
   it as `ValidationReport.baseline: ValidationReport | None`:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationReport:
    ...
    variant: str = "blend"      # "blend" | "ml" | "regime" | "ml+regime"
    baseline: "ValidationReport | None" = None   # ungated companion when gated
```

`to_json_obj` emits `"variant"` and a nested `"baseline"` block, so
`walkforward.json`'s `validation` shows e.g. `dsr=0.71 (variant "ml+regime")`
vs `baseline.dsr=0.55` — the operator sees the gate's marginal lift AND that both
were logged as trials. The CLI summary (`walkforward_cmds.py` ~L233–240) gains one
line printing `variant` and, when present, the baseline DSR. The DSR gate verdict
(`clears_dsr_gate`, ~L402) is computed per variant unchanged.

`_DSR_GATE`, `_MIN_DSR_TRIALS`, `compute_validation`'s leak-free contract (UTC
daily returns, caller-supplied `now_ms`, idempotent record) are all unchanged.

---

## Integration tests to add (under `tests/integration/`)

1. **`test_gates_default_off_identity.py`** — the headline guarantee.
   `SignalService.compute_research` with no gate kwargs == with `IdentityMeta`/
   `IdentityRegime` == today's output, exact (assert frame `equals`); and
   `WalkForwardRunner.run(..., ml=False, regime=False)` produces an `equity` and
   `validation` byte-identical to the current run (reuse the tmp-lake fixture from
   `test_mu_contract.py` / `test_walkforward_equivalence.py`).

2. **`test_meta_gate_scales_never_flips.py`** (extends the seam tests) — feed a
   stub `MetaModel` returning known `|size|`; assert `sign(F̃) == sign(Ã)`
   everywhere (R3), that `size ≡ 1` reproduces the ungated `mu_ann`, and that the
   gated `mu_ann` still clears `check_mu_ann_contract` (R5).

3. **`test_regime_gate_no_same_day_leak.py`** (R4, finding 13) — a stub
   `RegimeGate` whose `G_d` would differ if it used day `d` vs `d−1`; build a frame
   spanning a regime flip and assert every hour of day `d` uses the `d−1`
   multiplier (and that `apply_regime_gate` never reads the in-progress day).
   Cold-start days get `G=1`. Assert `0 < G ≤ 1` ⇒ `|mu_ann|` only shrinks.

4. **`test_walkforward_full_pipeline.py`** — end-to-end on the tmp lake with
   `--ml --regime`: assert (i) per-leg model is trained on `[train_start,
   test_start)` only (inject spies asserting no test-span row enters `fit`);
   (ii) ONE stitched artifact set is written; (iii) the OOS pipeline order is
   factors→blend→ml→regime→optimizer→next-open fills (fill `ts` == decision
   `ts+Δ`, reusing the next-open assertion from `test_mu_contract.py`).

5. **`test_experiments_honest_trial_count.py`** (finding 10, section e) — run
   blend-only, `--ml`, `--regime`, `--ml --regime` against one `ExperimentLog`;
   assert four distinct hashes (`n_trials()==4`), re-running any one is idempotent
   (still 4), and the gated `ValidationReport` carries a `baseline` whose DSR is
   the blend-only trial's. Assert `walkforward.json`'s `validation.variant` and
   nested `baseline` round-trip.

All tests: offline, `tmp_path` lake, deterministic (`seed=42`), no network — the
shipped integration-test idiom.

---

## Edit checklist (anchors, by file)

- `signals/gating.py` — NEW: `MetaModel`/`RegimeGate` Protocols, `IdentityMeta`/
  `IdentityRegime`, `apply_meta_gate`, `apply_regime_gate`.
- `signals/service.py` — `__init__` (~L132) +2 kwargs & spec extension;
  `_emit` (~L263) gate calls; `on_bar_close` (~L218) spec extension; new
  `compute_research_gated`.
- `analytics/walkforward.py` — `SignalSource` (~L126) +`compute_research_gated`;
  `run` (~L442) +`ml`/`regime`; leg loop (~L546/L564) OFF/ON branch;
  `config`/`trial_config` (~L612/L643) +flags; `ValidationReport` (~L154)
  +`variant`/`baseline` & `to_json_obj`.
- `cli/walkforward_cmds.py` — options (~L124) +`--ml`/`--regime`; `runner.run`
  (~L203) passthrough; summary print (~L233) +variant/baseline line.
- Phase 9/11 deliverables implement `MetaModel`/`RegimeGate`; this phase only
  consumes the Protocols.
