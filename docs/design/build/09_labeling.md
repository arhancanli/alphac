# Build Spec 09 — Cost-Honest Triple-Barrier Meta-Labeling

Implements alphaDesign.md §5.2–§5.4 with the leakageCritique fixes baked in
(findings **11** cost-honest + gap-aware stops, **24** vertical exit at next
open, **6/18** funding-event/`available_at` discipline, **12** label-space is a
diagnostic only). This spec covers Phase 9 only — `meta.py`'s bet sizing feeds
Phase 12, and the model that consumes these labels lives in `alphaforge.ml`.

**Doctrine carried forward from `forward_returns.py`:**
- Decision at the close of bar τ (availability `τ + Δ`); entry at `O(τ + Δ)`;
  exit at a *next-open* or an intrabar barrier of a bar strictly after entry.
  `C_t` as entry is the banned classic lookahead bug.
- Bar lookup by exact `ts_open` arithmetic (`+ k·Δ`), **never** positional
  `shift`. Missing entry/exit/path bar ⇒ that event's label is NaN; gaps are
  **never** bridged.
- The label looks into the future by construction. It is a **TARGET ONLY** and
  must never re-enter the feature path (enforced by the `labeling/__init__.py`
  curated surface + the `is_target_only` registry guard in `ml`).
- Inputs are never mutated.

---

## 0. Files

| File | Contents |
|---|---|
| `src/alphaforge/labeling/triple_barrier.py` | `TripleBarrierConfig`, `apply_triple_barrier`, `_cost_honest_exit_return` (private), `_label_one_instrument` (private numpy kernel + numba `njit` fast path behind a flag, pure-numpy fallback) |
| `src/alphaforge/labeling/weights.py` | `concurrency`, `average_uniqueness`, `attribution_weights`, `sample_weights` (composer) |
| `src/alphaforge/labeling/meta.py` | `make_meta_labels`, `bet_size_from_prob` |
| `src/alphaforge/labeling/__init__.py` | extend `__all__` with the public functions + `TripleBarrierConfig` |
| `tests/unit/test_triple_barrier.py` | golden + property + leakage-guard tests |
| `tests/unit/test_weights.py` | concurrency / uniqueness / attribution / decay tests |
| `tests/unit/test_meta.py` | meta-label and bet-size tests |

Match `forward_returns.py` / `costs/model.py` docstring density and typing.
Third-party imports without stubs (numba) follow the existing pattern — grep
`features/library/vol.py` for the `# type: ignore[...]` + pure-numpy fallback
idiom before importing numba; numba is **optional** and gated by a config flag,
default numpy path must be bit-identical to the JIT path (atol 0).

---

## 1. `triple_barrier.py`

### 1.1 Config

```python
@dataclass(frozen=True, slots=True)
class TripleBarrierConfig:
    horizon_bars: int = 72            # vertical barrier H (3 days @ 1h)
    pt_mult: float = 1.0              # profit-take barrier multiple of w
    sl_mult: float = 1.0              # stop-loss barrier multiple of w
    vol_span: int = 168              # ewma_vol span for σ̂ (== EWMA_VOL_SPAN)
    vertical_zero_band: float = 0.0   # |ret_net| < band·w at vertical → label 0
    timeframe: Timeframe = Timeframe.H1
    cost_honest: bool = True          # net out fees+½-spread+E[funding]; gross kept as diagnostic
    use_numba: bool = False           # JIT first-touch loop; numpy path is the contract
```

`__post_init__` validates `horizon_bars > 0`, `pt_mult > 0`, `sl_mult > 0`,
`vol_span >= 1`, `vertical_zero_band >= 0`, raising `ValueError` (programming
error, mirror `FeeSchedule.__post_init__`).

### 1.2 Signature

```python
def apply_triple_barrier(
    bars: pd.DataFrame,
    events: pd.DataFrame,
    cfg: TripleBarrierConfig,
    *,
    cost_model: TransactionCostModel,
    instruments: Mapping[str, Instrument],
    funding: pd.DataFrame | None = None,
    vol: pd.Series | None = None,
) -> pd.DataFrame:
    """First-touch triple-barrier labels, COST-HONEST and gap-aware."""
```

**`bars`** — long panel: `instrument_id`, `ts_open` (int64 epoch-ms UTC),
`open`, `high`, `low`, `close`. Validated like `forward_returns`: required
columns present, `ts_open` integer dtype, no duplicate `(instrument_id,
ts_open)`, all finite OHLC strictly positive. Never mutated.

**`events`** — one row per labeling decision: `ts` (int64 epoch-ms = the
decision bar τ's `ts_open`), `instrument_id`, `side` (int8 ∈ {−1, +1}; the
side-less primary run passes all +1). Dead-zone filtering (`|A| < 0.25`) is the
caller's job in `meta.py`/the signal layer — this function labels exactly the
events handed to it. Duplicate `(ts, instrument_id)` raises.

**`cost_model`** — the single shared `TransactionCostModel`. Reimplementing a
basis point here is banned (buildabilityCritique §3.7 / leakage finding 11
fix: "one import").

**`instruments`** — `instrument_id → Instrument`, for `funding_interval_hours`
(and `MarketType` routing inside the cost model). A perp event whose
instrument is absent raises `KeyError` (metadata is mandatory; mirrors
`carry._annualizer`).

**`funding`** — funding-events frame in the `FeatureContext.funding()` shape:
`ts_funding`, `instrument_id`, `rate`, `available_at` (all int64 ms except
`rate`). May be `None` only when `cfg.cost_honest is False` *or* the universe
is spot-only; a perp with `cost_honest` and no funding row contributes
`E[funding] = 0` over the hold (last-known rate is NaN → treated as 0, logged).

**`vol`** — optional externally-supplied per-bar σ̂ on the `(ts_open,
instrument_id)` MultiIndex; if omitted it is computed via the shared
`_sigma_at_decision(close)` helper reused verbatim from `forward_returns.py`
(span = `cfg.vol_span`). σ̂ is read **at the decision bar τ** (PIT-correct —
bar τ's close is known at `τ + Δ`).

### 1.3 Output frame (alphaDesign §4.3 label schema, MultiIndex form)

Indexed by sorted `(ts, instrument_id)` MultiIndex (named `ts_open`,
`instrument_id` to join 1:1 against the feature panel; `ts` == decision τ).
Columns, dtype:

| column | dtype | definition |
|---|---|---|
| `entry_ts` | int64 | `τ + Δ` |
| `entry_price` | float64 | `O(τ + Δ)` = `p0` |
| `t1` | int64 | event end `ts_open`: barrier-touch bar, or vertical bar `τ + (1+H)·Δ` — **REQUIRED by CV purging/embargo** |
| `exit_price` | float64 | barrier level or next-open (see §1.5) |
| `ret_gross` | float64 | `s · ln(exit_price / entry_price)` — DIAGNOSTIC ONLY |
| `ret` | float64 | cost-honest net return (§1.6); the label's economic truth |
| `label_tb` | int8 | −1 / 0 / +1 first-touch sign (on the gap-aware exit) |
| `touch` | int8 | +1=PT, −1=SL, 0=vertical |
| `side` | int8 | passthrough of `events.side` |
| `meta_label` | int8 | `1 if ret > 0 else 0` — computed on the **net** `ret` |
| `vol_at_entry` | float64 | σ̂ per-bar at τ |
| `n_funding` | int8 | settlements expected in `[entry_ts, t1)` (diagnostic + property test) |

NaN/`-1`-sentinel rows: when entry bar, the vol estimate, or the whole path
window is unavailable the row is emitted with NaN prices/returns and
`label_tb = touch = 0`, `meta_label = 0` is NOT written (set to a masked
sentinel — use a separate boolean is not needed; emit NaN-prices row and let
the consumer drop on `entry_price.isna()`). Document this explicitly.

`make_meta_labels` / `attribution_weights` consume this frame; `forward_returns`
columns (`fwd_ret_24/72/168`) are joined by the dataset builder downstream, not
here.

### 1.4 Barrier geometry (per event)

```
p0 = O(τ + Δ)                                   # entry, next open
w  = σ̂(τ) · sqrt(H)                             # H-bar vol forecast, log-return units
up = p0 · exp(+ pt_mult·w)  if s=+1 else p0 · exp(+ sl_mult·w)
dn = p0 · exp(− sl_mult·w)  if s=+1 else p0 · exp(− pt_mult·w)
```

PT is always *in the direction of `side`*. For `s = −1` the profit-take
barrier `dn` is BELOW entry and the stop `up` is ABOVE. `up`/`dn` are price
levels, compared against the **high/low of bars `τ + 2Δ … τ + (1+H)Δ`**
(the path bars k = 1 … H, strictly after the entry bar — never the entry bar
itself, which we filled at its open).

### 1.5 First-touch scan + gap-aware exits (the leakage-critical core)

For k = 1 … H, let bar `b_k` have open `O_k = O(τ + (1+k)Δ)`, high `H_k`,
low `L_k`. If `b_k` is **missing from the panel** the scan stops and the event
is NaN (gap = could-not-have-traded; never bridge).

```
hit_up = H_k >= up
hit_dn = L_k <= dn
```

- **Both touched in one bar (path unknown):** CONSERVATIVE STOP-FIRST
  (non-configurable in production). `touch = −1`, `label_tb = −s`,
  `t1 = ts(b_k)`. Adverse-barrier level for `side`:
  `exit_lvl = dn if s=+1 else up`.
- **Stop only (`hit_dn` for s=+1 / `hit_up` for s=−1):** `touch = −1`,
  `label_tb = −s`, adverse-barrier level as above.
- **PT only:** `touch = +1`, `label_tb = +s`, `exit_lvl = up if s=+1 else dn`.

**Gap-aware fill (leakage finding 11(a)/(b)):** a stop or PT does NOT fill at
the barrier price when the bar *gapped through* it — a live resting order fills
at the open if the bar opened beyond the level:

```
# stop (adverse) exit:
exit_price = min(barrier_lvl, O_k)   if the position is LONG-equivalent (s=+1 stop is dn → worse = lower)
           = max(barrier_lvl, O_k)   if SHORT-equivalent
# expressed sign-agnostically: the fill is the WORSE of {barrier, open} for the trader on a stop,
#   and the barrier level (resting limit) on a PT — PT fills at the limit, never better.
```

Concretely, with `r_to_exit = s · ln(exit_price/p0)` measuring trader PnL:
- **Stop:** `exit_price` = the price that makes `r_to_exit` the *smaller* (more
  adverse) of `s·ln(barrier/p0)` and `s·ln(O_k/p0)`. (Gap through stop ⇒ worse.)
- **PT:** `exit_price = barrier_lvl` (resting limit at the barrier; the
  optimistic `high==barrier` fill is accepted as the limit, the conservative
  bias lives in the stop rule and the cost net-out).

- **No touch (vertical, finding 24):** `t1 = ts(τ + (1+H)Δ)`,
  `exit_price = O(τ + (1+H)Δ)` — the **next open at the vertical**, NOT
  `C_{t+H}` (an unobtainable close). `ret_gross = s · ln(exit/p0)`;
  `label_tb = sign(ret)` on the **net** return, with a zero-band:
  `label_tb = 0` if `|ret| < cfg.vertical_zero_band · w`. `touch = 0`.

The scan loop is the numba `njit` hotspot; the numpy fallback must produce
bit-identical `t1`/`exit_price`/`label_tb` (atol 0) and is the default.

### 1.6 Cost-honest net return (finding 11 — the whole point)

`ret_gross` is the trader-PnL log return `s · ln(exit_price/p0)` (diagnostic).
The label's economic truth nets out the **round-trip frictions over the actual
hold**:

```
ret = ret_gross − roundtrip_cost_frac − funding_cost_frac
```

**Round-trip cost** — from the single cost model, *notional-independent* part
only (we do not know order size at label time; impact is a sizing concern and
is excluded here — document this as a deliberate, conservative-leaning choice):

```
roundtrip_cost_frac = 2 · ( cost_model.fee_frac(inst, TAKER)
                          + cost_model.half_spread_frac(inst) )
```

(2× = entry + exit; TAKER is the conservative liquidity assumption for a
barrier exit / stop; latency is NOT added — it lives in `fill_price`, not in
the economic penalty, exactly as `oneway_cost_frac` documents.) The impact term
is omitted with a one-line rationale referencing `oneway_cost_frac`.

**Expected funding over the hold (PIT-correct, finding 6/18):** funding is a
forward cashflow paid each settlement the position is open. Using the *realized*
future rates would be lookahead. Use the **last-known rate as of the decision**
`τ + Δ` as the expectation, times the **count of scheduled settlements** in
`[entry_ts, t1)`:

```
f_hat       = last funding rate with available_at <= τ + Δ        # backward as-of merge, NEVER on ts_funding
n_funding   = len(calendar.funding_events_in(entry_ts, t1, interval_hours))   # interval from instruments[iid]
# longs PAY shorts when f>0 (carry sign convention, carry.py): a position of side s pays s·f per settlement
funding_cost_frac = s · f_hat · n_funding          # subtracted from ret_gross as a cost
```

So `ret = ret_gross − roundtrip_cost_frac − s·f_hat·n_funding`. When
`f_hat` is NaN (no published settlement yet) treat as 0 and log a counter. Spot
instruments: `funding_cost_frac = 0`, `n_funding = 0`. The as-of merge reuses
the *exact* mechanics of `FeatureContext.funding_asof_join` (decision_ts =
`ts_open + tf.ms`, sort by `available_at`, `direction="backward"`,
`allow_exact_matches=True`); do NOT re-implement — factor a small helper or
call the join, matching `carry.py`.

`meta_label = 1{ ret > 0 }` is computed on **net** `ret` (finding 11: the
classifier must learn P(net win), not P(gross win)).

### 1.7 PIT / leakage guards (assert + test)

1. Every price/high/low used for event (τ, i) has `ts_open >= τ + Δ` (strictly
   after the decision bar). No record with `ts_open <= τ` enters the label.
2. σ̂ read at τ only (decision-time vol); supplied `vol` reindexed to τ rows.
3. Funding expectation uses `f_hat` available at `τ + Δ` only; the
   *count* `n_funding` uses the deterministic schedule calendar (a clock is
   allowed for **counting scheduled events**, never for **rates** — finding 6).
4. Vertical exit is next-open, never a close (finding 24).
5. No positional `shift`; all bar fetches are `+k·Δ` exact lookups; missing bar
   ⇒ NaN, no bridge.

---

## 2. `weights.py` (alphaDesign §5.4)

Concurrency and uniqueness are **within-symbol** (cross-symbol commonality is
handled by CV purging, not weights). All operate on the §1.3 label frame
(needs `entry_ts`, `t1`, and the per-bar return series).

```python
def concurrency(events: pd.DataFrame, *, timeframe: Timeframe = Timeframe.H1) -> pd.Series:
    """c_t = Σ_i 1{ t ∈ [entry_ts_i, t1_i] } per (ts_open, instrument_id) bar."""

def average_uniqueness(events: pd.DataFrame, conc: pd.Series, *,
                       timeframe: Timeframe = Timeframe.H1) -> pd.Series:
    """ū_i = (1/n_i) Σ_{t=entry_ts_i}^{t1_i} 1/c_t,  n_i = bar count of the span."""

def attribution_weights(events: pd.DataFrame, returns: pd.Series, conc: pd.Series, *,
                        time_decay: float = 0.75, timeframe: Timeframe = Timeframe.H1) -> pd.Series:
    """w̃_i = |Σ_t r_t / c_t| over the span; w_i = w̃_i · N/Σ w̃_j (mean 1);
    then optional time decay d + (1−d)·x_i on the cumulative-uniqueness clock."""

def sample_weights(events: pd.DataFrame, bars: pd.DataFrame, *,
                   time_decay: float = 0.75, timeframe: Timeframe = Timeframe.H1) -> pd.Series:
    """Composer: per-bar returns from bars (open→open, gap-safe) → concurrency
    → attribution × decay → normalized mean-1 `sample_weight` Series for §4.3."""
```

- `c_t` built by sweeping each event's `[entry_ts, t1]` over the exact bar grid
  (`expected_bar_opens` / `+k·Δ` arithmetic) per instrument; a missing bar in
  the span does not increment (it was never tradable).
- `returns` for attribution are per-bar log returns of the path
  (open-to-open to match the execution contract), NOT the event return.
- Time decay: `x_i ∈ [0,1]` is the cumulative-uniqueness clock oldest→newest;
  `d = 0.75` floor; newest = 1.0. Applied AFTER mean-1 normalization, then the
  result is the persisted `sample_weight` (do not re-normalize after decay so
  the documented "newest 1.0 / oldest 0.75" relationship holds).
- Output: float64 Series on the `(ts_open, instrument_id)` MultiIndex, name
  `sample_weight`, NaN-free for non-NaN events, ≥ 0.

---

## 3. `meta.py` (alphaDesign §5.3)

```python
def make_meta_labels(labels: pd.DataFrame) -> pd.Series:
    """meta_label = 1 if net `ret` > 0 else 0 (int8), on the §1.3 frame.
    Pass-through accessor so the column has one definition. NaN ret → masked."""

def bet_size_from_prob(p: pd.Series, side: pd.Series, *,
                       p_min: float = 0.5, step: float = 0.05) -> pd.Series:
    """LdP bet size (AFML ch.10):
        z    = (p − 0.5) / sqrt(p·(1−p))
        size = side · (2·Φ(z) − 1)          ∈ [−1, 1]
    size = 0 where p < p_min (never trade against the classifier); discretized to `step`.
    """
```

**Sign invariant (NON-NEGOTIABLE, rule 3):** `bet_size_from_prob` returns
`side · magnitude` with `magnitude ∈ [0, 1]`. It scales/gates; it NEVER flips
`side`. `p == 0.5 → size 0`; `p == 1 → size = side`. Validate `p ∈ [0,1]`,
`side ∈ {−1,+1}`, `0 < p_min <= 1`, `0 < step <= 1`. Φ = `scipy.stats.norm.cdf`
or a `0.5·(1+erf(z/√2))` numpy expression (match the repo's existing choice —
grep for `erf`/`norm.cdf` first). This is the seam Phase 12 multiplies by the
HMM gate `G` and the alpha magnitude `|Ã|` to form `F = size·|Ã|`.

---

## 4. Unit tests

**`test_triple_barrier.py`**
- *Golden synthetic path* where touches are known by construction: a rising
  ramp touches PT at a hand-computed bar k; a falling ramp touches SL; assert
  `t1`, `touch`, `label_tb`, `exit_price`.
- *Both-touch bar* (a single bar with `high≥up` and `low≤dn`) ⇒ stop-first:
  `touch=−1`, `label_tb=−s`, exit at adverse level.
- *Gap-through-stop*: bar opens beyond the stop ⇒ `exit_price = open` (worse),
  `ret_gross` strictly more negative than the barrier-fill counterfactual.
- *PT fills at the limit* even when `high > up` (no better-than-limit fill).
- *Vertical exit at next open* (finding 24): no touch over H ⇒
  `exit_price == O(τ+(1+H)Δ)`, `t1 == τ+(1+H)Δ`, `touch==0`; assert it is NOT
  the close `C_{t+H}`.
- *Cost-honest net* (finding 11): with a fixed `TransactionCostModel`,
  `ret == ret_gross − 2·(fee+½spread) − s·f_hat·n_funding`; a small gross-positive
  vertical flips `meta_label` to 0 once costs + funding are netted.
- *Funding PIT* (finding 6/18): `f_hat` is the rate with
  `available_at ≤ τ+Δ`, NEVER a later settlement; `n_funding` equals
  `len(funding_events_in(entry_ts, t1, interval))`; 4h vs 8h instruments get the
  right count (property: count scales with interval). A future rate change after
  `τ+Δ` does not move the label.
- *Side = −1 symmetry*: relabel a mirrored path, PT below / stop above resolve
  correctly; `bet_size` later preserves the sign.
- *Gap = NaN* (no bridge): drop the entry bar, an interior path bar, the
  vertical bar — each yields a NaN row, neighbours unaffected; no positional
  shift bridges it.
- *PIT guard*: assert no `ts_open ≤ τ` price contributes (truncate the panel at
  `τ` and confirm identical labels to the full panel for already-resolved
  events; later bars must not change a touched label).
- *Numba/numpy parity* (when numba present): atol 0 on `t1`/`exit_price`/`ret`.
- *Validations*: missing column, dup `(ts,instrument_id)`, non-positive price,
  non-int `ts_open`, missing perp instrument (`KeyError`), bad config raise.
- *Immutability*: `bars`, `events`, `funding` unchanged after the call.

**`test_weights.py`**
- *Concurrency hand-count* on a 3-event overlap; isolated event ⇒ `c_t≡1` ⇒
  `ū=1`.
- *Average uniqueness* = `1/2` for two fully-overlapping equal-span events.
- *Attribution* mean-1 normalization (`Σ w_i == N`); a flat (zero-return) span
  ⇒ `w̃=0`.
- *Time decay*: newest event weight 1.0, oldest 0.75, monotone in the
  uniqueness clock; `time_decay=1.0` disables it.
- *Gap in span* does not inflate concurrency.

**`test_meta.py`**
- *make_meta_labels* equals `1{ret>0}` on net `ret`; NaN masked.
- *bet_size*: `p=0.5→0`; `p<p_min→0`; `p=1→side`; sign always == `side`
  (Hypothesis over `p∈[0,1]`, `side∈{−1,+1}`) — **never flips**; discretization
  lands on the `step` grid; out-of-range inputs raise.

---

## 5. `__init__.py` surface

```python
from alphaforge.labeling.forward_returns import forward_returns
from alphaforge.labeling.triple_barrier import TripleBarrierConfig, apply_triple_barrier
from alphaforge.labeling.weights import (
    attribution_weights, average_uniqueness, concurrency, sample_weights,
)
from alphaforge.labeling.meta import bet_size_from_prob, make_meta_labels

__all__ = [...]  # add all of the above; keep the "targets only, never features" note
```

CI: `ruff` clean, `mypy --strict` clean (numba behind the same ignore/fallback
idiom as `features/library/vol.py`), `pytest` green.
