# CRITIQUE — Leakage / Point-in-Time Audit of Build Specs 09/11/12

Adversarial review of `09_labeling.md`, `09_ml.md`, `11_regime.md`,
`12_integration.md` against the four correctness rules, `leakageCritique.md`, and
the ACTUAL shipped code (`signals/`, `features/`, `validation/`, `costs/`,
`core/`, `labeling/forward_returns.py`). Builders MUST clear every **MUST-FIX**
before writing the module it names. Findings are ordered by severity. Each cites
file + function + the exact mechanism, and the fix.

Legend: **[BLOCK]** = correctness-rule violation or silent leak that ships a
wrong number; **[MAJOR]** = real leak/skew under plausible inputs; **[MINOR]** =
tighten-before-merge.

---

## [BLOCK] 1. Re-z-scoring `F = Ã·|size|` can FLIP THE SIGN — direct R3 violation

**Where:** `12_integration.md` §(a) Anchor-2 + §0 `apply_meta_gate`:
"forms `F = a_tilde·|size|`, then **re-z-scores via the same `cs_zscore(...)`**".
Also `09_ml.md` §0.3 and `sizing.py` docstring both say "`F = Ã·|size|`
re-standardized to `F̃`".

**Why wrong (verified against `features/cross_section.py::cs_zscore` L113-121):**
`cs_zscore` subtracts the **cross-sectional mean** and divides by std:
`z_i = (x_i − mean(x))/std(x)`. `F_i = Ã_i·|size_i|` with per-instrument
`|size_i| ∈ [0,1]` is NOT a uniform positive rescale of the `Ã` cross-section, so
`mean(F) ≠ 0` in general and is not proportional to `mean(Ã)`. After subtracting
`mean(F)`, an instrument with `Ã_i > 0` but small `|size_i|` can land BELOW
`mean(F)` and emerge with `F̃_i < 0`. That is the meta-model flipping the sign of
the blend — exactly what correctness rule 3 forbids ("It SCALES/GATES the blend
… it NEVER flips the sign"). The spec's own test `test_meta_gate_scales_never_flips`
(integration test 2) asserts `sign(F̃)==sign(Ã)` and **will fail** against the
specified `apply_meta_gate` body. The bug is silent in any test where every
`|size_i|` happens to be equal (e.g. the `size ≡ 1` identity case), so it sneaks
past the identity test and only bites with a real model.

**MUST-FIX:** Do NOT re-z-score after gating. The gate multiplies an already
cross-sectionally standardized quantity by a per-name factor in `[0,1]`; the
correct gated signal that preserves sign is simply `F̃_i = Ã_i · |size_i|`
(magnitude-only shrink, sign preserved by construction since `|size_i| ≥ 0`).
If a re-standardization is desired for optimizer scaling, it must be a **single
positive scalar** applied to the whole vector (e.g. divide by
`cross-sectional std of F`, NO mean subtraction) — never `cs_zscore`. Update
`sizing.py` and `09_ml.md` §0.3 docstrings to drop "re-standardized to F̃".
Add the sign-flip case to the test: a cross-section with mixed `Ã` signs and
non-constant `|size|`, assert `sign(F̃)==sign(Ã)` for every finite row.

---

## [BLOCK] 2. Meta-label / `meta_label` column has TWO contradictory definitions across specs — gross-vs-net and side-vs-no-side

**Where:** `09_labeling.md` §1.3 (column `meta_label`) and §3 `make_meta_labels`:
"`meta_label = 1 if net ret > 0 else 0`". But `09_ml.md` §0.2 and alphaDesign
§5.3 define `y_meta = 1{ s·ret_net > 0 }` (side-signed). `09_labeling.md` §1.6
last line also says "`meta_label = 1{ ret > 0 }`".

**Why wrong:** The label's `ret`/`ret_gross` are ALREADY trader-PnL of side `s`
(`ret_gross = s·ln(exit/p0)`, §1.6) — so `1{ret>0}` already equals `1{s·(raw
move)>0}` and the two are consistent ONLY if `ret` is the side-signed return.
But the spec's §1.4 geometry then sets PT "in the direction of side", and
`label_tb = ±s`. If a builder reads `09_ml.md`'s `1{s·ret_net>0}` literally while
`ret` is already side-signed, they apply the side TWICE (`s·(s·move) = move`),
inverting the label for every short. The two docs disagree on whether `ret` is
raw or side-applied. This is a label-inversion landmine for `s=−1` events.

**MUST-FIX:** Pin ONE definition in `09_labeling.md` and reference it from
`09_ml.md`: `ret` and `ret_gross` are the SIDE-SIGNED net/gross trader return
(`ret_gross = s·ln(exit/p0)`); therefore `meta_label = 1{ ret > 0 }` (no extra
`s`). `09_ml.md` must cite the labeling doc's definition verbatim, not restate
`1{s·ret_net>0}` as if `ret_net` were raw. Add a `s=−1` golden test asserting a
known short win → `meta_label=1`, `label_tb=+1` (= `+s`·… resolves to a winning
short), and that flipping `s` flips `meta_label` correctly.

---

## [BLOCK] 3. Funding-cost sign in the label is under-specified vs the load-bearing `carry.py` convention

**Where:** `09_labeling.md` §1.6: `funding_cost_frac = s · f_hat · n_funding`,
then `ret = ret_gross − roundtrip_cost_frac − s·f_hat·n_funding`.

**Why wrong (checked against `features/library/carry.py` L3-8, L86-97):** the
sanctioned convention is `CARRY = − f̄ · (8760/interval)` because on Binance
USDT-M perps `f > 0 ⇒ longs PAY shorts`. So a LONG (`s=+1`) holding through a
settlement with `f>0` PAYS `f` per settlement (a cost, positive number to
subtract), and a SHORT (`s=−1`) RECEIVES it (a negative cost). The spec's
`s·f_hat·n_funding` gives `+f` for a long (subtracted → reduces return ✓) and
`−f` for a short (subtracting a negative → increases return ✓). The ARITHMETIC
is correct, but the spec never states the convention or cross-references
`carry.py`, so a builder can easily invert it (the single most common funding
bug — `leakageCritique` finding 18 / alphaDesign §10.3 risk 3 calls this out
explicitly as a regression-test target). It also doesn't define `f_hat`'s sign
relative to the stored `rate` column.

**MUST-FIX:** State the convention inline and reuse `carry.py`'s sign exactly:
`per-settlement funding PnL for side s = − s · f` (long pays when `f>0`), hence
the COST subtracted from `ret_gross` is `+ s · f_hat · n_funding`. Cross-
reference `carry.py` module docstring. Add the alphaDesign §10.3 historical-
episode regression test: a known negative-funding window (shorts pay) must
INCREASE a long's labeled `ret` vs the zero-funding counterfactual. Confirm
`f_hat` is the raw stored `rate` (not negated) so the single negation lives in
one place.

---

## [BLOCK] 4. Regime gate `merge_asof` join key mismatch — off-by-one-DAY same-day leak (R4)

**Where:** `11_regime.md` §4 step 4 and `12_integration.md` §0/§(b)
`apply_regime_gate`: live/research join is
`merge_asof(hourly, gate_daily, left_on="ts_open", right_on="available_at",
direction="backward")` with `available_at = day_close = 00:00 next day`.

**Why wrong:** the two specs disagree on what the gate Series is indexed by, and
the join math only works for ONE of them. `11_regime.md` §3.3 says
`gross_multiplier_series` returns a Series "indexed by the DAY-d ts_open the gate
APPLIES TO" after a `shift(lag_days)`. But §4 step 4 then joins on
`right_on="available_at"`. If the producer ALREADY shifted by `lag_days` (so the
value at day-D ts_open is `filt_{D-1}`) AND the consumer ALSO joins
`available_at <= t` (which selects `filt_{D-1}` for hour-bars of day D because
`available_at` of `filt_{D-1}` = 00:00 of day D), the lag is applied TWICE → the
gate for day D becomes `filt_{D-2}`, a one-day-stale gate (over-conservative, not
a leak, but a research/live number that is simply wrong and untested). Conversely
if the producer does NOT shift and only the `available_at` join is relied upon,
the merge_asof at exactly `t = 00:00` with `allow_exact_matches` (the default
that `funding_asof_join` uses, L285) will match `filt_{D-1}` whose `available_at
== 00:00 of day D` — correct — but `gross_multiplier_series`'s `lag_days=1`
default then double-counts. The single-vs-double-application is unresolved.

**MUST-FIX:** Define ONE mechanism, not two. Recommended: the producer emits a
daily Series carrying its OWN `available_at` column (`= available_at(ts_open_d,
D1) = day-d close`) and value `filt_d` (NO shift); the consumer does the single
`merge_asof(... left_on=hour_ts, right_on="available_at",
direction="backward", allow_exact_matches=True)`. Because `filt_d` is stamped at
day-(d+1) 00:00, the first hour of day d+1 correctly receives `filt_d`, i.e. the
posterior through day-d close — exactly R4. Drop the `shift(lag_days)` from
`gross_multiplier_series` OR make `gross_multiplier_series` the ONLY mechanism
and have it emit `available_at` already lagged with NO second join shift. Pick
one; assert in a test that the day-D gate equals `filt_{D-1}` (NOT `filt_{D-2}`,
NOT `filt_D`). Match `funding_asof_join`'s `allow_exact_matches=True` semantics
verbatim and TEST the `t == 00:00` boundary (the exact off-by-one zone).

---

## [BLOCK] 5. `RegimeGate` Protocol has THREE incompatible signatures across the specs

**Where:** `11_regime.md` §3.0 `RegimeGate.gross_multiplier_series(obs, *,
lag_days)`; `12_integration.md` §0 `RegimeGate.gross_multiplier(day_index:
pd.DatetimeIndex)`; `11_regime.md` §3.3 also has `gross_multiplier(probs)` AND
`gross_multiplier_series(obs, lag_days)` as concrete methods.

**Why wrong:** Phase 12 (`apply_regime_gate`) calls `regime.gross_multiplier(
day_index)` taking a **`pd.DatetimeIndex`**, while the whole codebase uses int64
epoch-ms `ts_open` (`core/time.Ms`), and the HMM's actual method
`gross_multiplier(probs)` takes a posterior frame, not a day index. A
`DatetimeIndex` argument is an alien type for this repo (everything is epoch-ms;
see `service.py`, `context.py`, `splits.py`) and silently invites tz/naive
datetime bugs that `core/time.require_utc` exists to prevent. The seam the
consumer depends on does not match the seam the producer implements → the
integration won't type-check, or a builder will paper over it with an adapter
that re-introduces a timestamp-unit mismatch (leakageCritique finding 17).

**MUST-FIX:** ONE Protocol, epoch-ms only. The seam method the consumer calls
must take and return epoch-ms-keyed structures. Recommended seam:
`gross_multiplier_series(obs: pd.DataFrame, *, lag_days: int = 1) -> pd.Series`
returning a daily Series whose index is `ts_open` (int64 ms) and which ALSO
carries the `available_at` join key (per fix #4). `apply_regime_gate` consumes
THAT, never a `DatetimeIndex`. Delete the `DatetimeIndex` signature from
`12_integration.md`. Make `IdentityRegime` satisfy the identical signature
(returns all-1.0 over the requested days). Add a Protocol-conformance test
(`isinstance(RegimeHMM(...), RegimeGate)` and `isinstance(IdentityRegime(),
RegimeGate)`).

---

## [BLOCK] 6. `MetaModel` seam signature mismatch — `bet_size(x, side)` vs `bet_size_from_prob(p, side)`

**Where:** `12_integration.md` §0 `MetaModel.bet_size(self, x: pd.DataFrame,
side: pd.Series)` vs `09_ml.md` §1.1 which delivers `HistGBMMetaModel.
predict_proba(X)` + a free function `bet_size_from_prob(p, side)`. There is NO
`bet_size(x, side)` method on `HistGBMMetaModel` in `09_ml.md`.

**Why wrong:** the consumer (`apply_meta_gate`) calls `meta.bet_size(x, side)`,
but the Phase-9 deliverable exposes `predict_proba` + a separate
`bet_size_from_prob`. The composition (predict_proba → calibrated p → bet size)
is exactly where the p_min floor and the sign-preservation invariant live; if
each phase builds its own glue the floor/sign logic can diverge between research
(`SignalService`) and the model's own tests. Also `IdentityMeta` is specified as
"`|size| ≡ 1`" but must satisfy whatever `bet_size` signature is chosen.

**MUST-FIX:** Add `bet_size(self, x: pd.DataFrame, side: pd.Series) -> pd.Series`
to the `ModelProtocol`/`HistGBMMetaModel` in `09_ml.md` as the SINGLE composition
`bet_size_from_prob(predict_proba(x), side, p_min=P_MIN, step=SIZE_STEP)`, so the
seam Phase 12 calls and the model's own code are the same line. `feature_names`
and `model_id` (read in `apply_meta_gate`/§4.4) must be attributes on the
Protocol. `IdentityMeta.bet_size` returns `|size|≡1` with `sign==side`. Assert
`isinstance(HistGBMMetaModel, MetaModel)` and `isinstance(IdentityMeta, MetaModel)`.

---

## [BLOCK] 7. ML `fit` early-stopping uses sklearn `early_stopping` but the spec forbids `validation_fraction` — the only sklearn ES path IS a random/tail split, which leaks across `t1`

**Where:** `09_ml.md` §1.1 `DEFAULT_PARAMS`: `"early_stopping": True,
"n_iter_no_change": 50`, with the NOTE "`validation_fraction` is NOT used — we
pass an explicit purged tail via `validation_data`". Step 3: "early stopping on
the purged 40d ES block".

**Why wrong (sklearn API fact):** `HistGradientBoostingClassifier` has NO
`validation_data` parameter. With `early_stopping=True` it can ONLY hold out via
`validation_fraction` (a RANDOM stratified split of the training rows it was
given) or score on the train set. There is no public hook to feed an explicit
held-out purged block. So as written, either (a) `validation_fraction` silently
applies a random split of the 365d train window — pulling future, label-
overlapping rows into the ES set, the precise `t1`-leak finding 9 exists to kill;
or (b) the code passes a kwarg sklearn ignores/rejects. The "purged 40d ES block"
cannot be honored through sklearn's `early_stopping` flag.

**MUST-FIX:** Disable sklearn's internal early stopping
(`early_stopping=False`) and implement the iteration-count selection EXTERNALLY:
fit with `warm_start=True` incrementally (or fit a path of `max_iter` and use
`staged_predict_proba`/`staged_decision_function`) and choose `n_iter` by binary
log-loss on the explicitly-carved, purged 40d ES block — the ES block rows are
NEVER in the trees' `fit` set, and train rows whose `[t,t1]` overlaps the ES
block are purged using `PurgedWalkForward`'s arithmetic (finding 16). Document
that `validation_fraction` is unused because sklearn cannot purge. Test
`test_no_lookahead_es_block_purged` must assert the ES rows are absent from the
fitted estimator's training data AND that purged train rows are absent — neither
is achievable via `early_stopping=True`.

---

## [MAJOR] 8. Triple-barrier vol `σ̂(τ)` uses `_sigma_at_decision` which spans data gaps — and the spec reads it at τ but the helper computes over close, decoupled from the entry bar

**Where:** `09_labeling.md` §1.2 (`vol` param) and §1.4: `w = σ̂(τ)·sqrt(H)`,
"σ̂ read at the decision bar τ", reusing `_sigma_at_decision(close)` "verbatim
from `forward_returns.py`".

**Why wrong:** `forward_returns.py::_sigma_at_decision` (L39-48) is computed on a
per-instrument **stored-close** Series, NOT on the complete expected-bar grid.
Its own docstring admits "Where the panel has a gap the first post-gap return
spans the gap". For the LABEL's barrier width this matters more than for the
forward-return scale: a gap-spanning return inflates `σ̂(τ)`, widening barriers,
so a touched-barrier event near a gap gets a label computed from an artificially
wide `w`. Worse, `09_labeling.md` says σ̂ is read "at the decision bar τ" but
`_sigma_at_decision` returns a value per stored close — if τ itself is a grid
slot with no stored bar (the event's decision bar is missing), the σ̂ lookup is
silently NaN or misaligned. The spec doesn't say to compute σ̂ on the
`expected_bar_opens` grid (the way `FeatureContext.panel` mandates, L206-239, to
make window math gap-exact).

**MUST-FIX:** Compute σ̂ on the COMPLETE expected-bar grid per instrument
(reindex closes to `expected_bar_opens(...)` before `ewma_vol`), matching
`FeatureContext.panel` discipline, so `σ̂(τ)` is an exact time operation and gap
returns don't leak into barrier width. When the externally-supplied `vol` is
used, assert it is on the full `(ts_open, instrument_id)` grid and reindex to the
event's τ rows; an event whose τ has NaN σ̂ → NaN label (already the policy, make
it explicit). Add a test: an event adjacent to a data gap has identical σ̂ whether
or not later bars exist (truncation-invariance of the barrier width).

---

## [MAJOR] 9. `concurrency` / `average_uniqueness` "within-symbol" leaves cross-symbol redundancy uncorrected — inflates effective N in BOTH the ML fit and the promotion gate

**Where:** `09_labeling.md` §2: "Concurrency and uniqueness are **within-symbol**
(cross-symbol commonality is handled by CV purging, not weights)."

**Why wrong (leakageCritique finding 23, unaddressed):** purging removes
train/test OVERLAP across the time axis; it does nothing about ~40 simultaneous,
regime-correlated barrier events per bar (every symbol fires an event every bar).
Within-symbol uniqueness treats those 40 cross-sectional events at time t as 40
independent samples. The GBM's `sample_weight`, the log-loss early-stopping
criterion, and the promotion `rank_ic`/`logloss` comparisons (`judge_promotion`,
`09_ml.md` §1.4) all then over-count effective sample size → optimistically tight
ES, optimistic promotion metrics, a slow selection ratchet (finding 9's concern
amplified). The spec explicitly defers this to "CV purging" which provably does
not cover it.

**MUST-FIX:** Either (a) multiply `sample_weight` by a cross-sectional
de-correlation factor `1/√(n_t)` where `n_t` = number of concurrent events at
timestamp t across ALL symbols (cheap, in `weights.py::sample_weights`), or (b)
report the promotion-gate metrics with timestamp-clustered (block-bootstrap by
`ts_open`) error bars and require the lift to clear the cluster-bootstrapped CI,
not a point estimate. Document the choice in `09_labeling.md` §2 and
`09_ml.md` §2. At minimum, STOP claiming "CV purging handles it" — it does not.

---

## [MAJOR] 10. Promotion-gate `rank_ic` contract mismatch — `predict_proba` is not direction-signed, but `rank_ic` assumes a direction-adjusted factor

**Where:** `09_ml.md` §1.4 `judge_promotion`: "rank_ic via
`validation.metrics.rank_ic` on the meta-prob vs the §5.1 forward return".

**Why wrong (checked `validation/metrics.py::rank_ic` L89-90):** `rank_ic`'s
docstring states "The factor is assumed direction-adjusted upstream
(× FeatureSpec.direction); this function never re-signs." The meta-prob `p =
P(win)` is a CONFIDENCE in `[0,1]`, NOT a directional alpha — it has no sign
relative to the forward return. Correlating raw `p` against the side-less §5.1
forward return is meaningless (a high-`p` short and a high-`p` long both have
large `p` but opposite expected `fwd_ret`). The promotion gate would compute a
near-zero / noise `rank_ic` and the `rank_ic_new >= 0.8·rank_ic_champ` clause
becomes a coin-flip, defeating the gate.

**MUST-FIX:** Define the promotion IC on a DIRECTION-CONSISTENT quantity:
correlate the bet size `size = side·(2Φ(z)−1)` (which IS signed like the trade)
against the side-signed realized net return `ret`, OR correlate `p` against the
realized `meta_label` outcome (a probability-calibration IC). State explicitly
which forward return (the §5.1 fixed-horizon `fwd_ret_h`, or the label's `ret`)
and on what grid. The cleanest: gate on `rank_ic(size, ret_signed)` on the
non-overlapping h-grid (`non_overlapping`, the same machinery `service.py` L255
uses). Add a test that a model with genuine edge produces positive promotion IC
and a sign-blind `p` does not.

---

## [MAJOR] 11. `cluster_features` Spearman-correlation distance is computed over the FULL training matrix without purging — leaks test-block structure into the feature-clustering used by MDA

**Where:** `09_ml.md` §1.2 `cluster_features(X, corr_threshold)` and
`mda_importance` which clusters once then permutes per fold.

**Why wrong:** if `cluster_features` is called on the whole X (all folds) before
the per-fold MDA loop, the cluster definitions are fit using test-fold rows.
That is a mild contamination, but more importantly the MDA importance is then
reported on clusters whose membership depended on the very test data the
importance is supposed to be OOS over. With slow features (90d momentum, 1y
vol-percentile — `09_ml.md` §3 lists `mom_xs_*`, `reg_rvp_720`, etc.) the
correlation structure is strongly time-varying, so a global clustering is not the
clustering that held in any single fold.

**MUST-FIX:** Either compute `cluster_features` on the TRAIN slice of each fold
(re-cluster per fold, accept that cluster ids differ per fold and aggregate by
member-set), or document that clustering is a fixed pre-registered grouping
derived ONLY from a held-out design window that never enters any reported
fold. The deterministic-cluster-id requirement (`'cluster_00'...`) must survive
whichever choice. Add a note that MDA numbers are conditional on the clustering's
provenance.

---

## [MAJOR] 12. CPCV / WF embargo (168 bars) << longest feature lookback (8760 bars) — slow-feature train/test dependence (leakageCritique finding 14, NOT fixed)

**Where:** `09_ml.md` §0.1 leans on `validation/splits.py` +
`validation/cpcv.py`, both `embargo_bars=168` default (verified L101 splits.py,
L139 cpcv.py). `09_ml.md` §3 enumerates features with lookbacks up to
`reg_rvp_720` (720 bars) and `vol_*_720`, `adv_quote_30d`, and the regime layer's
14d-YZ-on-daily / `RVP 8760`-class context.

**Why wrong:** finding 14 from the prior review is restated nowhere in these
specs and the inherited splitter default (168) is far below the dominant feature
decorrelation length. A train sample 7 days after a test block computes its slow
features mostly from test-block prices; purging by `t1` (label horizon 72) does
not touch the FEATURE lookback. CPCV Sharpe/IC distributions — the input to PBO
and to MDA — are inflated. The ML specs adopt the splitter as-is and add no
embargo-sensitivity study.

**MUST-FIX:** In `09_ml.md` and `12_integration.md`, set the ML/CPCV embargo to
≈ the dominant feature decorrelation length (the spec must pick a number ≥ the
largest feature lookback that actually enters the model's `feature_names`, e.g.
720+), OR restrict CPCV inference to a fast-feature subset and rely on the
strictly forward-chaining walk-forward (where train always precedes test, so this
cannot occur) for any model containing slow features. Add the embargo-sensitivity
report (E ∈ {168, 720, …}) called for in finding 14. At minimum, pass an explicit
`embargo_bars` derived from `max(feature_lookback)`, never the 168 default.

---

## [MAJOR] 13. HMM observation `available_at` for the DAILY bar is `00:00 next day`, but the daily bar is BUILT from 1h bars whose own availability is `+Δ_1h` — the daily close is not knowable until the last 1h bar closes, and the spec never proves the daily bar itself is PIT

**Where:** `11_regime.md` §1: "Each `x_d` is available at
`available_at(ts_open_d, Timeframe.D1) = 00:00 of day d+1`"; §1 also says daily
bars are "derived from 1h per dataDesign.md".

**Why wrong:** `available_at(ts_open_d, D1) = ts_open_d + 86_400_000` = exactly
00:00 of day d+1 — which is correct ONLY if the day-d 1d bar's close equals the
day-d 23:00 1h bar's close AND that 1h bar is itself available at 00:00 of d+1
(`available_at(23:00, H1) = 00:00 d+1` ✓). So the arithmetic is consistent.
BUT: the spec computes `m_d = ln(C_d/C_{d-1})` and the 14d YZ vol from a DAILY
panel; it does not state that the daily panel is constructed with the SAME PIT
discipline (no partial-day bar, day-d bar only emitted once all 24 hourly bars
are present). If the daily resample emits a day-d bar from a partial day (e.g.
during a gap), `C_d` could reflect <24h and `available_at` would be wrong. The
gate then reads a posterior built on a malformed observation.

**MUST-FIX:** `build_observations` must construct the daily OHLC by the
sanctioned calendar grid and DROP any day not backed by a complete set of 1h bars
(gap discipline: a partial day is a gap, not bridged — matching
`forward_returns` and §1's stated "gaps NOT bridged"). Assert the day-d
observation's `available_at == available_at(ts_open_d, D1)` and that no partial
day enters. Cross-reference dataDesign's daily-from-hourly construction so the
1d-bar PIT guarantee is explicit, not assumed.

---

## [MAJOR] 14. Walk-forward gated path: HMM and meta-model refit on `[train_start, test_start)` but the HMM needs ≥730 days (`MIN_FIT_DAYS`) — early legs will RAISE or silently fall back

**Where:** `12_integration.md` §(d) Anchor-1/leg-loop: per leg, "the HMM REFIT on
`[train_start, test_start)` only"; `11_regime.md` §3.1 `MIN_FIT_DAYS=730`, `fit`
"Raises ValueError if `len(obs) < MIN_FIT_DAYS`".

**Why wrong:** a walk-forward leg's train span `[train_start, test_start)` is
typically far shorter than 730 daily observations (WF train windows are sized in
the hundreds of days, and the FIRST legs are shortest). `RegimeHMM.fit` will
RAISE on those legs. The integration spec gives no policy for "train span <
MIN_FIT_DAYS": the run either crashes or a builder inserts a silent fallback
(expanding to before `train_start`, which would pull pre-leg data — fine for an
expanding HMM, but then the per-leg "fit on `[train_start, test_start)` only"
claim and the test in integration-test 4 ("no test-span row enters fit") is
violated for the HMM if the window is expanded past `test_start`). The
HMM's expanding-window design (alphaDesign §8 "expanding, min 730 days") actually
CONFLICTS with the leg-local `[train_start, test_start)` framing.

**MUST-FIX:** Specify the HMM walk-forward window explicitly: it is an EXPANDING
window `[global_start, test_start)` (NOT leg-local), capped only below by
`MIN_FIT_DAYS`, and it must end strictly at `test_start` (never include test
days) — that is the real no-leak invariant, not "leg-local". Reconcile this with
the meta-model (which uses a 365d rolling window). State that legs whose
`[global_start, test_start)` has < `MIN_FIT_DAYS` daily obs run with the
IdentityRegime gate (G≡1, documented cold-start) rather than crashing. Update
integration-test 4 to assert "no `ts_open >= test_start` row enters either fit"
(the correct invariant) rather than a leg-local span.

---

## [MAJOR] 15. `SignalService` spec-list extension for the meta-model can pull RAW (un-pipelined) feature columns into the model, but the model was specified to consume POST-CSPipeline `direction!=0` alphas

**Where:** `12_integration.md` §(a) Anchor-1/Anchor-2: "the meta-model's
`feature_names` are appended to the engine spec set … so its X matrix is computed
on the SAME PIT window", and `x = frame[list(self._meta.feature_names)]`.
`09_ml.md` §3: "`cross_sectional=True` ones arrive POST-CSPipeline
(winsorize→zscore, PIT-masked), `direction`-signed."

**Why wrong:** `_emit` reads `frame[...]` which is the RAW engine output, BEFORE
`_directional_zs`/CSPipeline (the processed z's live in the `zs` mapping, not in
`frame`; see `service.py::_emit` L271 takes `zs` separately, and
`_directional_zs` L275-288 produces the processed values). So
`frame[self._meta.feature_names]` hands the model RAW factor values, not the
winsorized/z-scored/direction-signed matrix `09_ml.md` §3 says the model trains
on. Train (Phase 9 dataset builder) and serve (`_emit`) would then feed DIFFERENT
preprocessing of the same features → train/serve skew, the exact anti-skew
invariant `SignalService` exists to protect. Also the directional alphas appear
BOTH as raw `frame` columns and as processed `zs` — which one is in
`feature_names`?

**MUST-FIX:** Pin the model's X to the SAME processed surface the dataset builder
used. Either (a) the model consumes the processed `zs` panel + the raw
`direction==0` risk/regime context, assembled by a shared helper that BOTH the
Phase-9 `MLDataset` and `_emit` call (one preprocessing path, no skew), or (b)
the model's `feature_names` are explicitly raw engine columns and the Phase-9
dataset builder is required to use the IDENTICAL raw columns (no CSPipeline on
model inputs) — and `09_ml.md` §3's "POST-CSPipeline" claim is corrected. Add a
parity test: the X matrix at decision bar t in `compute_research_gated` equals
the X the `MLDataset` produced for the same t (the deployed-path parity the
module docstring promises).

---

## [MAJOR] 16. `bet_size_from_prob` z-statistic divides by `√(p(1−p))` → blows up at p→0/1; spec says "p∈{0,1}→0" but the formula path can produce ±inf before the floor

**Where:** `09_labeling.md` §3 and `09_ml.md` §1.1 `bet_size_from_prob`:
`z = (p−0.5)/√(p(1−p))`, `size = side·(2Φ(z)−1)`, "`p=1 → size=side`",
degenerate `p∈{0,1}`/NaN → 0.

**Why wrong:** at `p=1`, `√(p(1−p))=0` → `z=+inf` → `Φ(inf)=1` → `size=side·1`,
which the spec WANTS (`p=1→side`). But `09_ml.md` §1.1 ALSO says "`p in {0,1}` and
NaN → size 0 (no div-by-zero)" — directly contradicting `09_labeling.md`'s
"`p=1→side`". One says p=1 gives full size, the other says p=1 gives ZERO. And
the intermediate `0/0` at exactly p=0.5… is fine (z=0), but the `(p−0.5)/0` at
p=1 is `0.5/0=+inf` (not 0/0), numerically a RuntimeWarning then `inf`. The two
specs disagree on the p=1 edge and neither pins the numpy errstate handling.

**MUST-FIX:** Reconcile to ONE rule. AFML/alphaDesign intent: `p→1 ⇒ |size|→1`
(full confidence = full size). So `p=1 → size=side` is correct; `09_ml.md`'s
"p∈{0,1}→0" is wrong and must be changed to "p∈{0,1} → size=±side via the limit
(handled by clipping z to a finite bound or computing Φ on the clipped p)". Pin
the implementation: clip `p` to `[eps, 1−eps]` BEFORE the z computation (so the
limit is approached, not inf), keep the `p<p_min→0` floor, then discretize. Only
NaN `p` → 0. Fix the contradictory test specs (`test_degenerate_p_zero` in
`09_ml.md` vs `09_labeling.md`'s `p=1→side` test).

---

## [MINOR] 17. `n_funding` counts settlements in `[entry_ts, t1)` but the position is entered at `entry_ts = τ+Δ` (next OPEN) and the funding count window must match the actual hold, including the entry/exit boundary convention

**Where:** `09_labeling.md` §1.6: `n_funding = len(funding_events_in(entry_ts,
t1, interval_hours))`, half-open `[entry_ts, t1)`.

**Why wrong (minor, but directional):** a position entered at the open of bar
`τ+Δ` and exited at `t1` (a bar open) pays funding at every settlement instant it
is OPEN ACROSS. The half-open `[entry_ts, t1)` correctly excludes a settlement
exactly at exit (you've closed) and includes one exactly at entry (you opened
into it). On Binance the settlement at the entry instant is paid by whoever holds
THROUGH it; entering exactly at a settlement boundary is a coin-flip the
conservative label should resolve as "paid if long-pays". The spec doesn't state
the boundary convention and `funding_events_in` (calendar.py L71-96) is
half-open `[start, end)` — so a settlement at `entry_ts` IS counted and one at
`t1` is NOT, which is a defensible convention but must be DECLARED and tested.

**MUST-FIX:** Declare the boundary convention explicitly (`[entry_ts, t1)`
half-open, settlement at entry counted, at exit not) and add a property test:
total funding counted == settlements the position actually spans; a 4h-interval
instrument gets exactly 2× the count of an 8h one over the same hold (the spec
already wants this test — make the boundary part of it).

---

## [MINOR] 18. `ModelCard.data_sha256` "of the training label/feature parquet" — but the dataset is assembled in-memory per leg in the WF gated path; there is no parquet to hash

**Where:** `09_ml.md` §1.3 `ModelCard.data_sha256` "of the training label/feature
parquet (reproducibility)"; `12_integration.md` §(d) builds `MLDataset` in-memory
per leg.

**Why wrong:** in the walk-forward gated path the per-leg dataset is never
written to parquet — it's `dataset.matrices(start, end)`. Hashing "the parquet"
is undefined there, so `data_sha256` is either empty or hashes something
inconsistent between the live (parquet-backed) and WF (in-memory) paths, breaking
the reproducibility claim it exists for.

**MUST-FIX:** Define `data_sha256` as a hash of the MATERIALIZED `(X, y, w, t1)`
arrays (content hash of the sorted matrices + `feature_names` + window bounds),
computed identically in both paths, not of a file. State it in `09_ml.md` §1.3.

---

## [MINOR] 19. Cold-start regime gate `G=1.0` for `D < lag_days` and "insufficient-oos" promotion both default to permissive — make sure neither silently disables the gate in production

**Where:** `11_regime.md` §4 step 3 (cold-start `G=1.0`); `12_integration.md`
§(b) ("cold start gets `G=1`, never NaN"); `09_ml.md` §1.4
(`insufficient-oos → keep champion`).

**Why wrong:** these are individually correct (a missing gate must not zero the
book), but combined with finding #14 (early WF legs fall back to Identity), a
LARGE fraction of a backtest could run with G≡1 and/or the champion never
promoting, while the operator believes the gates are active. Silent
no-op-ness is a research/live divergence risk.

**MUST-FIX:** Emit a per-leg / per-window counter of "gate inactive (cold-start /
insufficient-data)" fraction into `walkforward.json` and the model card / verdict
`reason`, so a run that was 60% Identity-gated is visible, not silent. No logic
change; observability only.

---

## Cross-cutting checks the builders must run (regression-test the prior critique stays fixed)

- **μ contract (rule 5):** the gated `mu_ann` must still pass the existing
  `check_mu_ann_contract` / `|mu_ann| < 3.0` tripwire. Since `G∈(0,1]` and
  `|size|∈[0,1]` only shrink, the tripwire can only get safer — assert it
  (integration test 2/3 already do; keep them).
- **Identity == today (OFF path):** `frame.equals` byte-identity with gates off.
  This is the single most important regression guard; it catches #1, #5, #6 the
  moment a real artifact is plugged in only if the test ALSO exercises a non-
  trivial stub (see #1 — the identity test alone is insufficient).
- **Timestamp units:** every new seam is epoch-ms `Ms`, never `datetime`/
  `DatetimeIndex` (#5). Grep the new modules for `DatetimeIndex`/`Timestamp`.
- **One splitter:** ML CV imports `PurgedWalkForward`/`CombinatorialPurgedCV`;
  no hand-rolled fold loop (finding 16). Spy-assert in `test_mda_uses_purged_folds`.
- **Funding from events table, never a clock for RATES:** `f_hat` via the
  `funding_asof_join` mechanics (backward, on `available_at`, exact matches);
  `n_funding` via `funding_events_in` (the clock is for COUNTS only). Both are
  already-sanctioned helpers — reuse, don't reimplement (#3, finding 6/18).
