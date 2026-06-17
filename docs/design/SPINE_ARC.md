# SPINE_ARC — per-sleeve anchor TF + TradingCalendar through the engine spine (P2) + corp-actions read path (P1)

**Role:** DIRECTOR / ARCHITECT build-ready plan. HEAD `549aecc`.
**Scope:** ENGINE10 punch-list **P2** (calendar-aware spine off a per-sleeve anchor TF) and
**P1** (corporate-actions read path + fail-closed adjusted panel), folded into one arc because
they are the *same root defect* (the spine is mono-sleeve and calendar-blind), surfacing in
5 of 7 audit dimensions.

**THE HARD CONSTRAINT — crypto is byte-for-byte identical.** Crypto IS
`asset_class ∈ {CRYPTO_PERP, CRYPTO_SPOT}` whose calendar is `Always24x7Calendar` with anchor
`Timeframe.H1`. That is *exactly* the current hard-coded behavior. This whole arc is an
**OFF == identity refactor**: introduce a per-sleeve anchor TF + `TradingCalendar`, with crypto
resolving to the existing 24/7 H1 grid so every crypto number is unchanged. The existing crypto
regression suite is the gate (§6). A regression in any crypto number is a FAIL.

---

## 0. The seam already exists; the spine bypasses it

`core/calendar.py` is complete and correct (read-only confirmed):

- `TradingCalendar` ABC: `is_session`, `expected_bar_opens(start, end, tf)`,
  `periods_per_year(tf)`, `floor_bar(ts, tf)`, `next_bar_open(ts, tf)`,
  `funding_events_in(...)`.
- `Always24x7Calendar`: every method **delegates to the `core.time` pure-integer kernel** —
  `expected_bar_opens` → `core_time.expected_bar_opens`, `periods_per_year` → `tf.bars_per_year`
  (8760 for H1), `floor_bar`/`next_bar_open` → `core_time.*`. This is the proof that routing
  crypto through the calendar is a pure identity: the calendar's 24/7 implementation IS the bare
  kernel the spine calls today.
- `XNYSCalendar`: D1-only (raises `NotImplementedError` otherwise), session-hopping
  `next_bar_open`/`floor_bar`/`expected_bar_opens`, `periods_per_year(D1)=252.0`.
- `calendar_for(asset_class)`: CRYPTO_* → shared `_ALWAYS_24X7`; EQUITY → shared `_XNYS`.

The **one** correct consumer today is `labeling/triple_barrier.py:534`
(`cal = calendar_for(inst.asset_class)` for funding-event counting). Every other spine site calls
the bare `core.time.expected_bar_opens` / `tf.bars_per_year` / `tf.ms` directly. The arc replaces
each bare call with the calendar, and the byte-identity is guaranteed by the `Always24x7Calendar`
delegation above.

---

## 1. The consumer contract — how each consumer resolves its calendar + anchor

### 1.1 The sleeve registry (config layer — the P2 root, audit G9 / P18 config corner)

A new module **`config/sleeve.py`** introduces the AssetClass-keyed sleeve descriptor. This is the
single source every spine entry point reads to get `(anchor_tf, asset_class)`; the calendar is
then `calendar_for(asset_class)` (NOT stored on the sleeve — the calendar is a stateless shared
singleton owned by `core/calendar.py`, keying off `asset_class` keeps one source of truth and
defers the MIC re-key, audit G11/P18, to a later arc).

```python
# config/sleeve.py
@dataclass(frozen=True, kw_only=True, slots=True)
class Sleeve:
    """One asset-class sleeve: its anchor timeframe + the calendar key.

    The anchor timeframe is the grid features/signals/sizing are valued on and the
    grid lookback_bars counts. CRYPTO sleeves anchor H1 (the current behavior);
    the EQUITY sleeve anchors D1. The calendar is calendar_for(asset_class)."""
    asset_class: AssetClass
    anchor_tf: Timeframe

    @property
    def calendar(self) -> TradingCalendar:
        return calendar_for(self.asset_class)

    def periods_per_year(self) -> float:
        return self.calendar.periods_per_year(self.anchor_tf)


CRYPTO_PERP_SLEEVE: Final = Sleeve(asset_class=AssetClass.CRYPTO_PERP, anchor_tf=Timeframe.H1)
CRYPTO_SPOT_SLEEVE: Final = Sleeve(asset_class=AssetClass.CRYPTO_SPOT, anchor_tf=Timeframe.H1)
EQUITY_SLEEVE:      Final = Sleeve(asset_class=AssetClass.EQUITY,      anchor_tf=Timeframe.D1)

_REGISTRY: Final[dict[AssetClass, Sleeve]] = {s.asset_class: s for s in
    (CRYPTO_PERP_SLEEVE, CRYPTO_SPOT_SLEEVE, EQUITY_SLEEVE)}

def sleeve_for(asset_class: AssetClass) -> Sleeve:
    try: return _REGISTRY[asset_class]
    except KeyError: raise ConfigError(f"no sleeve registered for {asset_class.value!r}") from None
```

`config/settings.py:74` `DataCfg` gains a `asset_class: AssetClass = AssetClass.CRYPTO_PERP` field
(default preserves crypto). `DataCfg.timeframe` stays (it is the *ingest/anchor* TF and the default
H1 is unchanged). The default sleeve is therefore `sleeve_for(cfg.data.asset_class)` =
`CRYPTO_PERP_SLEEVE` = H1 + 24/7 — identical to today.

> **Byte-identity rule for the whole arc:** every consumer's default path resolves
> `asset_class = CRYPTO_PERP`, `anchor_tf = H1`, `calendar = Always24x7Calendar`. Each consumer's
> calendar/anchor is supplied via a **keyword-only parameter with a crypto default**, so an
> un-migrated caller is byte-identical and migration is mechanical.

### 1.2 Per-consumer resolution table

| Consumer | File:line today | Resolves anchor/calendar from | Crypto identity |
|---|---|---|---|
| `FeatureEngine` | `features/engine.py:45,87,97,126` | ctor `anchor_tf`/`calendar` kw (default H1 / 24/7) | `expected_bar_opens` → calendar 24/7 → `core.time` kernel |
| `FeatureContext.panel` | `features/context.py:231` | `calendar` passed by engine; grid = `calendar.expected_bar_opens` | same kernel |
| `FeatureContext.corporate_actions` | (new) | `asset_class` passed by engine; reader CA read | crypto path never calls it |
| `PITDataReader.corporate_actions` | (new) | `as_of` (mirror `funding()`) | unused for crypto |
| `PITDataReader.gaps` | `reader.py:227` | `tf` + new `calendar` kw (default 24/7) | same kernel (P18 corner, fold in) |
| `BacktestEngine` | `backtest/engine.py:168,612,654,1002` | ctor `tf` + new `calendar` kw; grid hops via `calendar.next_bar_open` | grid from stored bars + 24/7 == today |
| `LakeCostInputs` | `backtest/engine.py:401-449` | gated 1h-only; equity gets a separate provider | unchanged (still H1) |
| `TripleBarrier` | `labeling/triple_barrier.py:285,329,379,476` | `cfg.timeframe` + `calendar_for(inst.asset_class)` | 24/7 `next_bar_open` == `+tf.ms` |
| `BlendStrategy` cov panel | `portfolio/strategy.py:527` | `StrategyContext` exposes `asset_class`; grid via calendar | same kernel |
| `BlendStrategy` annualizers | `portfolio/strategy.py:463,564` | `calendar.periods_per_year(tf)` | `Always24x7.periods_per_year(H1)` = `H1.bars_per_year` = 8760 |
| `GrinoldSizer` | `signals/sizing.py:87` | `periods_per_year` injected (was `timeframe.bars_per_year`) | 8760 unchanged |
| `SignalService` IC/blend/fwd | `signals/service.py:165,214,247,254,261` | sleeve anchor + calendar | H1 hops identical |
| `WalkForwardRunner` | `analytics/walkforward.py:720,743` | sleeve anchor + calendar; grid + embargo in sessions | 24/7 grid == today |

---

## 2. P1 — corporate-actions read path + fail-closed (file:line edits)

### 2.1 `PITDataReader.corporate_actions(...)` — mirror `funding()` EXACTLY

`data/store/reader.py` — add a method **byte-structurally identical to `funding()` (reader.py:144-177)**,
masking on the stored `available_at`, NEVER `ex_date`. `ex_date` is used ONLY as the within-range
window key; the PIT predicate is `available_at <= as_of`.

```python
def corporate_actions(
    self, instrument_ids: Sequence[str], *, start: Ms, end: Ms, as_of: Ms,
) -> pa.Table:
    """Corp-action rows with start <= ex_date < end AND available_at <= as_of.

    The PIT predicate uses the stored available_at (declaration/knowable date +
    publication lag) — NEVER ex_date (leakage finding 18). Mirrors funding()."""
    dataset = Dataset.CORPORATE_ACTIONS
    if end <= start or not instrument_ids:
        return empty_table(dataset)
    files = self._files(dataset, instrument_ids, start=start, end=end)
    if not files:
        return empty_table(dataset)
    sql = f"""
        SELECT instrument_id, action_type, ex_date, available_at, ratio,
               cash_amount, ingested_at
        FROM read_parquet({_sql_file_list(files)})
        WHERE list_contains(?::VARCHAR[], instrument_id)
          AND epoch_ms(ex_date) >= ?
          AND epoch_ms(ex_date) < ?
          AND epoch_ms(available_at) <= ?
        ORDER BY instrument_id, ex_date
    """
    params = [list(instrument_ids), start, end, as_of]
    result: pa.Table = self._con.execute(sql, params).to_arrow_table()
    return result.cast(schema_for(dataset))
```

- Columns/order match `CORPORATE_ACTIONS_SCHEMA` (`data/schemas.py:300-354`):
  `instrument_id, action_type, ex_date, available_at, ratio, cash_amount, ingested_at`.
- `_files` already supports any `Dataset` (reader.py:242). `Dataset.CORPORATE_ACTIONS`
  exists (`schemas.py:78`); `schema_for` includes it (`schemas.py:418`). No schema change.
- **Window-key subtlety:** `funding()` ranges on `ts_funding`; here the natural event key is
  `ex_date` (the schema natural sort/dedupe key, `schemas.py:363`). Range on `ex_date`, mask on
  `available_at`. This matches `_CA_COLUMNS` consumed downstream.

### 2.2 `FeatureContext.corporate_actions()` — serve the `_CA_COLUMNS` projection

`features/context.py` — add the column tuple + cache + method, mirroring `funding()`
(context.py:185-202):

```python
_CA_COLUMNS: tuple[str, ...] = (
    "instrument_id", "action_type", "ex_date", "available_at", "ratio", "cash_amount",
)
# add "ex_date", "available_at" to _TS_COLUMNS (context.py:79) so _to_pandas casts them to int64.

def corporate_actions(self) -> pd.DataFrame:
    """Corp-action rows in the window, pre-filtered to available_at <= end.

    Splits/dividends masked on the stored available_at (never ex_date). Served to
    the equity adjusted-close kernel; crypto never calls this."""
    if self._ca_cache is None:
        tbl = self._reader.corporate_actions(
            list(self._instrument_ids), start=self._start, end=self._end, as_of=self._end,
        )
        self._ca_cache = self._to_pandas(tbl, _CA_COLUMNS)
    return self._ca_cache.copy(deep=False)
```

Add `self._ca_cache: pd.DataFrame | None = None` to `__init__` (context.py:127-129) and
`"corporate_actions"` to `__all__`-adjacent surface (it is a method, no `__all__` change).

**Shape contract that the factor side already expects** (`equity_price.py:269-281`,
`adjusted_close`): a frame with `action_type` (`'split'`/`'dividend'`), `ex_date` (int64 ms),
`ratio`, `cash_amount`, indexed/grouped per `instrument_id`. The existing
`_adjusted_close_panel` does `ca_getter = getattr(ctx, "corporate_actions", None)` and
`actions = ca_getter()` then `adjusted_close(raw, actions, tf_ms=...)`. **Once the method exists,
no factor change is needed** — the feature-detect flips on. Confirm column names exactly match
what `adjusted_close` reads (verify against `equity_price.py:200-250`: `a_type`, `a_cash`, `ratio`,
`ex_date` arrays — projection names must align).

### 2.3 Replace the silent raw fallback with a FAIL-CLOSED raise (the P1 teeth)

`features/library/equity_price.py:253-281` `_adjusted_close_panel` — today returns `raw` when the
getter is absent (the documented "BUILD-ORDER GAP"). After 2.2, the getter exists. **Replace the
silent fallback with a fail-closed raise** for an EQUITY/D1 context with no CA surface:

```python
def _adjusted_close_panel(ctx: FeatureContext) -> pd.DataFrame:
    raw = ctx.panel("close")
    ca_getter = getattr(ctx, "corporate_actions", None)
    if ca_getter is None:
        raise ConfigError(  # FAIL-CLOSED: never silently feed raw prices to equity factors
            "equity price factors require a corporate-actions surface; FeatureContext "
            "exposes no corporate_actions() — refusing to run on raw unadjusted prices "
            "(a 2:1 split would print as a -50% return; leakage G1/G2)."
        )
    actions = ca_getter()
    if not isinstance(actions, pd.DataFrame):
        raise ConfigError("FeatureContext.corporate_actions() must return a DataFrame")
    if actions.empty:
        return raw  # legitimately no actions in the window: raw == adjusted
    ...  # adjusted_close as today
```

- Empty-frame-returns-raw is *correct* (no action ⇒ adjusted == raw) and is the only surviving
  pass-through. The dangerous case (getter absent) now raises.
- **Fold in P18 numerical corner** (`equity_price.py:282`): replace the inferred
  `tf_ms = grid[1]-grid[0]` (a Fri→Mon first gap gives a 2-session lookahead) with the explicit
  bar duration `Timeframe.D1.ms = 86_400_000`. The availability lag of a D1 bar is exactly D1.ms
  by construction, independent of session gaps.
- **Crypto safety:** crypto never instantiates equity factors, so this raise is unreachable on the
  crypto path. The guard in §4 additionally rejects EQUITY/D1 compute until the spine is verified.

### 2.4 Integration regression (the proof, P1)

`tests/integration/test_corp_actions_read_path.py` (new): plant a 2:1 split with
`available_at = declaration + lag` into a synthetic lake → `compute_history` on the equity id →
assert (a) **no -50% return at the ex bar** (split folded), (b) **split invisibility before
`available_at`** (a `compute_history` with `end < available_at` sees raw, post-`available_at` sees
adjusted), (c) the fail-closed raise fires when CA reader returns absent (monkeypatch the getter
off).

---

## 3. P2 — thread anchor TF + calendar through the spine (file:line edits)

### 3.1 `FeatureEngine` — replace the module constant (features/engine.py)

- **Delete** `ANCHOR_TIMEFRAME: Final[Timeframe] = Timeframe.H1` (engine.py:45) from `__all__`
  (engine.py:43) — OR keep it re-exported `= CRYPTO_PERP_SLEEVE.anchor_tf` for one release to not
  break `service.py:50` until that import is migrated (3.6). Director call: **keep the symbol,
  redefine it as the crypto default**, migrate importers in this arc, drop it at the end.
- `FeatureEngine.__init__` (engine.py:52) gains `*, anchor_tf: Timeframe = Timeframe.H1,
  calendar: TradingCalendar = _ALWAYS_24X7` kw-only with crypto defaults; store `self._anchor_tf`,
  `self._calendar`.
- `compute_history` (engine.py:87,97) and `compute_asof` (engine.py:126,128): `tf =
  self._anchor_tf`; `grid = self._calendar.expected_bar_opens(start, end, tf)` (was bare
  `expected_bar_opens`). The lookback window arithmetic `start - max_lookback*tf.ms` stays
  pure-ms (it is warm-up headroom that is *ceiled/floored by the read*; a slightly-too-wide window
  is harmless — confirm via parity).
- Thread `calendar`/`asset_class` into the `FeatureContext(...)` construction (engine.py:89-96,
  129-136): pass `calendar=self._calendar` and `asset_class=...` (from the sleeve) so the context's
  `panel` and `corporate_actions` resolve correctly.

> **as-of window subtlety (must verify in parity):** `compute_asof` computes the minimal window
> `[t_star - (L-1)*tf.ms, t_star+tf.ms)`. On a session calendar `(L-1)*tf.ms` calendar-ms may not
> reach back L sessions across weekends. The `t_star` itself must come from
> `calendar`-aware `bar_open_for_decision`. **For crypto this is identical** (24/7). For equity D1
> the window start should be derived by hopping L sessions back via `calendar` — but since this arc
> **fail-closed rejects EQUITY/D1 compute (§4)**, the equity as-of path is deferred; only the
> calendar-aware *grid* (batch) and the *guard* land now. Document this as the remaining equity
> as-of TODO.

### 3.2 `FeatureContext` — calendar-aware panel grid (features/context.py)

- `__init__` (context.py:106-129) gains `*, calendar: TradingCalendar = _ALWAYS_24X7,
  asset_class: AssetClass = AssetClass.CRYPTO_PERP` kw-only; store `self._calendar`,
  `self._asset_class`. Add `self._ca_cache` (§2.2).
- `panel()` (context.py:231): `grid = self._calendar.expected_bar_opens(self._start, self._end, tf)`
  replaces the bare call. Import `expected_bar_opens` stays only if still used elsewhere; otherwise
  drop the import to keep ruff clean.
- **Crypto identity:** `Always24x7Calendar.expected_bar_opens` delegates to the exact
  `core.time.expected_bar_opens(start, end, tf)` the line calls today → byte-identical panel.

### 3.3 `BacktestEngine` — session-aware grid + next-bar (backtest/engine.py)

The engine is **already data-driven**: the grid is `{ts_open + tf.ms for stored bars}`
(engine.py:612). The two 1h-only assumptions that break on session gaps:

1. **The grid step `ts_open + tf.ms`** (engine.py:612,618): on a 24/7 grid the close of bar `t` IS
   the open of bar `t+1`. The order created at close `t` (`decision_ts=t`, engine.py:1002) fills
   against `bars[iid].get(t)` (engine.py:775) — works because `t` (a close) == next bar's `ts_open`.
   On equity D1, Friday's close = Saturday-00:00, but Monday's bar `ts_open` = Monday-00:00 ≠
   Saturday. So the fill lookup `bars[iid].get(decision_ts)` misses → `dropped_missing_next_bar`
   (engine.py:776). **Fix:** the order's `decision_ts` and the fill target must be the **next
   session open** `calendar.next_bar_open(t_close, tf)`, not `t`. Concretely:
   - Build the **decision grid** = bar *closes* = `{calendar.next_bar_open(ts_open, tf) ... }` —
     i.e. iterate stored bar opens, the close of bar `o` is `calendar.next_bar_open(o, tf)` (for
     24/7 == `o + tf.ms`; for D1 a Friday's "close instant" maps to Monday's open as the fill bar).
   - **Director decision:** keep the loop variable `t` = decision instant = the *next bar's open*
     (the bar the order fills into), derived `t = calendar.next_bar_open(prev_open, tf)`. The
     mark/funding lookups `bars[iid].get(t - tf.ms)` (engine.py:654,663,940) become
     `bars[iid].get(calendar.floor_bar(t - 1, tf))` — the prior session's open. For 24/7,
     `floor_bar(t-1, tf) == t - tf.ms` exactly (the kernel), so **crypto is byte-identical**.
   - `last_close_of` (engine.py:618) `max(rows) + tf.ms` → `calendar.next_bar_open(max(rows), tf)`.
2. **`LakeCostInputs` (engine.py:356-463)** is `Timeframe.H1`-hardcoded (BARS_PER_DAY=24,
   sqrt(24), day-bucketing). The ctor already **gates** non-H1 to require an injected provider
   (engine.py:547-551). **Leave `LakeCostInputs` exactly as-is** (still H1, crypto-identical); the
   equity sleeve injects a future `EquityCostInputs` provider (audit G4 / out-of-scope here — note
   the gap). This arc does NOT touch the cost-input provider math.
- `BacktestEngine.__init__` (engine.py:523-560) gains `*, calendar: TradingCalendar = _ALWAYS_24X7`
  kw-only (the `tf` param already exists, default H1). Store `self._calendar`.
- `StrategyContext.__init__` (engine.py:164-179) gains `asset_class: AssetClass` (so the strategy
  can resolve its calendar); construction at engine.py:707 passes it. `StrategyContext` exposes a
  `calendar` property = `calendar_for(self._asset_class)`.
- The `start/end` `tf`-alignment check (engine.py:588-590) stays (alignment to the anchor TF is
  correct for both sleeves).

> **CRYPTO BYTE-IDENTITY PROOF for the engine:** every changed expression reduces to its current
> form under `Always24x7Calendar`: `next_bar_open(o, H1) == o + H1.ms`,
> `floor_bar(t-1, H1) == t - H1.ms`. The golden master (§6) asserts the equity curve and every
> fill **to the cent** on a CRYPTO_PERP HOUR grid — it is the gate.

### 3.4 `TripleBarrier` — session hops via the calendar (labeling/triple_barrier.py)

`_scan_one_instrument` (triple_barrier.py:285,304,329,379) walks `bar_ts = tau + (1+k)*delta` with
`delta = cfg.timeframe.ms` (positional `+k·Δ`). On D1 the weekend timestamps have no `pos_of` entry
→ `gapped=True` → NaN sentinel for ~every event. **Fix:** hop sessions via the calendar:

- Resolve `cal = calendar_for(inst.asset_class)` once per instrument (the seam ALREADY exists at
  triple_barrier.py:534 for funding — extend its use to the bar walk).
- `ent_ts = cal.next_bar_open(tau, tf)` (was `tau + delta`, line 304). The path walk
  (line 329): `bar_ts = cal.next_bar_open(prev_bar_ts, tf)` iterated k times (or precompute the
  next `horizon` session opens after `tau`). Vertical exit `vert_ts` (line 379): the horizon-th
  session open after `tau`.
- **Crypto identity:** `Always24x7.next_bar_open(t, H1) == t + H1.ms`, so the walk is
  `tau + (1+k)*delta` exactly. The existing `test_triple_barrier.py` crypto cases are the gate.
- `_scan_one_instrument` currently takes `cfg` (which has `timeframe`) but NOT `inst`/`calendar`.
  Thread `calendar: TradingCalendar` (or `asset_class`) into its signature; the caller at
  triple_barrier.py:510 already has `inst`. `_grid_sigma` (triple_barrier.py:504) takes `delta` —
  leave it (sigma is a positional EWMA on the *stored* grid, calendar-agnostic; verify parity).

### 3.5 `BlendStrategy` — cov grid + annualizers off the calendar (portfolio/strategy.py)

- **Cov panel grid** (strategy.py:527): `grid = ctx.calendar.expected_bar_opens(ctx.ts -
  window*ctx.tf.ms, ctx.ts, ctx.tf)` (was bare `expected_bar_opens`). Needs `ctx.calendar` from
  §3.3 `StrategyContext`. (The window *start* ms arithmetic is harmless warm-up width; the grid
  membership is what matters and the calendar filters it.)
- **Cov annualizer** (strategy.py:463): `cov_ann = annualize_cov(nearest_psd(cov_bar),
  ctx.calendar.periods_per_year(tf))` (was `tf.bars_per_year`). `annualize_cov` is *already*
  correctly parameterized (`portfolio/covariance.py:268`); only the caller's argument changes.
- **Realized-vol annualizer** `_realized_vol_ann` (strategy.py:544-564): the
  `np.sqrt(tf.bars_per_year)` (line 564) → `np.sqrt(ctx.calendar.periods_per_year(tf))`. Since
  `_realized_vol_ann(self, tf)` is a method without ctx, thread the calendar:
  `_realized_vol_ann(self, periods_per_year: float)` and pass
  `ctx.calendar.periods_per_year(tf)` from the caller (strategy.py:486).
- **`portfolio/overlay.py`** (G5 docstrings mention `sqrt(8760)`): **no code change** —
  `vol_target` takes `realized_vol_ann`/`sigma_realized` as a *caller-supplied* annualized scalar
  (confirmed overlay.py:50-56); the annualization happens in `_realized_vol_ann` (strategy.py:564),
  which is the single fix site above. The overlay docstrings should be updated to say "the
  calendar's `periods_per_year`" instead of the literal `sqrt(8760)` (doc-only, crypto value 8760).
- **Crypto identity:** `Always24x7.periods_per_year(H1) == H1.bars_per_year == 8760.0` →
  `annualize_cov(..., 8760.0)` and `sqrt(8760)` exactly as today. The `test_blend_strategy.py` and
  `test_mu_contract.py` (asserts `8760.0`, integration:236) are the gate.

### 3.6 `GrinoldSizer` + `SignalService` — periods_per_year from the calendar (signals/)

- `GrinoldSizer` (sizing.py:61-93): `annualization_factor` is `self.timeframe.bars_per_year /
  self.horizon_bars` (line 87). Replace the numerator with an injected `periods_per_year: float`
  field (default `Timeframe.H1.bars_per_year = 8760.0`). `from_cfg` (sizing.py:79) gains a
  `periods_per_year` arg. The μ contract `mu_ann = mu_h · (periods_per_year / h)` — for crypto
  H1 this is `8760/72`, **identical** (the mu_contract test asserts this).
- `SignalService` (service.py:50,165,214,247,254,261): replace `ANCHOR_TIMEFRAME` with the
  sleeve's `anchor_tf` resolved in `__init__` (`self._anchor_tf`, `self._calendar`,
  `self._periods_per_year = calendar.periods_per_year(anchor_tf)`), default crypto sleeve.
  - `GrinoldSizer.from_cfg(cfg, timeframe=self._anchor_tf, periods_per_year=self._periods_per_year)`
    (service.py:165).
  - `bar_open_for_decision(as_of, self._anchor_tf)` (service.py:214).
  - `forward_returns(bars, h, timeframe=self._anchor_tf)` (service.py:247) — `forward_returns`
    (`labeling/forward_returns.py:108`) hops `delta = timeframe.ms`. **For equity D1 this is a
    calendar-blind hop** and would need a calendar; but equity signal compute is fail-closed (§4),
    so this arc threads `anchor_tf` (crypto-identical) and leaves the session-hop of
    `forward_returns`/`estimate_blend_weights` as a documented equity TODO.
  - `delta = self._anchor_tf.ms` (service.py:254); `estimate_blend_weights(..., horizon_bars=h,
    timeframe=self._anchor_tf)` (service.py:261).
- **Crypto identity:** every site resolves `anchor_tf = H1`, `periods_per_year = 8760` → unchanged.

### 3.7 `WalkForwardRunner` — grid + embargo in sessions (analytics/walkforward.py)

- `tf = Timeframe.H1` (walkforward.py:720) → `tf = self._sleeve.anchor_tf` (sleeve resolved in
  the runner ctor from settings, default crypto). The alignment check (walkforward.py:723) stays.
- `grid = expected_bar_opens(start, end, tf)` (walkforward.py:743) →
  `self._calendar.expected_bar_opens(start, end, tf)`.
- **Embargo/purge in sessions** (the `PurgedWalkForward` geometry): the splitter measures
  train/test/embargo in *bar counts on the grid*. Since the grid is now session-filtered for
  equity (and 24/7 for crypto), a "168-bar embargo" is automatically 168 *grid rows* = 168
  sessions for equity, 168 hours for crypto — which is the correct sessions semantics **as long as
  the grid is the calendar grid**. No change to `splits.py` bar-count math is needed; the
  correctness comes from feeding it the calendar grid. Confirm with the equity-session parity test.
  (P11 — deriving embargo from active-lookback — is a *separate* punch-list item; not in this arc.)
- **Crypto identity:** 24/7 grid == today; `test_walkforward_equivalence.py` is the gate.

### 3.8 P18 fold-ins (cheap, same arc)

- `PITDataReader.gaps` (reader.py:227): add `calendar: TradingCalendar = _ALWAYS_24X7` kw (or
  `asset_class`); `expected = self._calendar.expected_bar_opens(start, end, tf)`. Crypto identical;
  equity stops reporting every weekend as a gap (audit G7/P18).

---

## 4. The GUARD — fail-closed on D1/EQUITY until the spine is verified

`FeatureEngine.compute_history` (and `compute_asof`) MUST **reject** D1/EQUITY specs rather than
silently use the 24/7 grid, until the equity path is proven in this arc. Add at the top of
`compute_history`/`compute_asof` (engine.py:84, 125), after `_checked`:

```python
if self._asset_class is AssetClass.EQUITY or self._anchor_tf is Timeframe.D1:
    raise NotImplementedError(  # fail-closed guard, removed once equity path is verified
        "FeatureEngine rejects EQUITY/D1 specs in this arc: the calendar-aware spine "
        "is wired but the equity as-of window + forward_returns/blend session hops are "
        "not yet verified; refusing to silently compute on a partially-migrated path."
    )
```

This is the single most important safety line: it makes the partial migration **loud**, not
silent. It is removed in a follow-up once `forward_returns`/`estimate_blend_weights`/the as-of
window are session-hopping and the equity E2E parity test is green. **Crypto (CRYPTO_PERP, H1)
never trips it.**

> The `_adjusted_close_panel` fail-closed raise (§2.3) and this guard are complementary: §2.3
> guards the *adjusted-price* surface; §4 guards the *whole equity compute path*. Until §4 is
> lifted, equity factors cannot run at all — so §2.3 is the safety net for when §4 is later lifted.

---

## 5. BYTE-IDENTITY plan — precisely how CRYPTO resolves to the current 24/7 H1 grid

| Spine expression today | After arc | Crypto reduction |
|---|---|---|
| `expected_bar_opens(s,e,H1)` | `Always24x7.expected_bar_opens(s,e,H1)` | delegates to **same** `core.time.expected_bar_opens` (calendar.py:117-119) |
| `tf.bars_per_year` (=8760) | `Always24x7.periods_per_year(H1)` | returns `tf.bars_per_year` (calendar.py:121-123) = 8760.0 |
| `ts_open + tf.ms` (grid step) | `Always24x7.next_bar_open(ts_open,H1)` | returns `core.time.next_bar_open` = `ts_open + H1.ms` (calendar.py:129-131) |
| `t - tf.ms` (prior open) | `Always24x7.floor_bar(t-1,H1)` | returns `core.time.floor_bar(t-1,H1)` = `t - H1.ms` |
| `tau + (1+k)*delta` (TB walk) | iterated `Always24x7.next_bar_open` | each hop `+H1.ms` ⇒ same arithmetic |
| `mu_h · 8760/h` | `mu_h · periods_per_year/h`, ppy=8760 | identical |

**Why it is byte-identical and not merely numerically close:** `Always24x7Calendar` is not a
re-implementation — each method *literally forwards* to the same `core.time` kernel / `tf` property
the spine calls today (verified, calendar.py:111-131). Floating-point: no new float ops are
introduced (the annualizers receive the *same* `8760.0` constant, just sourced via a method that
returns `tf.bars_per_year`). Integer grids: identical lists.

### Which existing crypto tests prove it (the GATE — must pass UNCHANGED)

1. **`tests/integration/test_golden_master.py`** (`test_golden_master_full`, :246): a full-pipeline
   CRYPTO_PERP backtest asserting fills, funding payments, and the equity curve **to the cent**
   (`round(final_equity,2) == 101_281.97`, :428; per-fill price/fee/realized to 1e-9, :356-369;
   funding payments to 1e-12, :394; counters incl. `dropped_missing_next_bar == 1`, :420). This is
   the primary byte-identity gate for §3.3 (engine grid/next-bar) and §3.5 (annualizers).
2. **`tests/integration/test_walkforward_equivalence.py`**: the slice-invariance equivalence the
   WF runner relies on — gate for §3.7.
3. **`tests/integration/test_mu_contract.py`**: asserts `annualize_cov(..., 8760.0)` (:236) and the
   `mu_ann = mu_h·8760/h` tripwire (:208,:260) on CRYPTO_PERP — gate for §3.5/§3.6.
4. **`tests/integration/test_phase4_deployed_path.py`**: the deployed-path parity/truncation harness
   — gate for §3.1/§3.2 (feature engine + context panel) and the as-of/batch parity.
5. **`tests/unit/test_triple_barrier.py`**: gate for §3.4 (TB session hops reduce to `+delta`).
6. **`tests/unit/test_backtest_engine.py`, `test_blend_strategy.py`, `test_sizing.py`,
   `test_feature_engine.py`, `test_pit_reader.py`, `test_calendar.py`**: per-component gates.
7. **`tests/unit/test_factors_equity_price.py`**: the equity factor bodies on the *fake* HOUR ==
   session grid (test admits this at :86-98). After §2.3 it must be updated to **inject a CA
   surface** (else it will hit the fail-closed raise) OR be re-pointed at the new equity-D1
   integration test. Director note: this test certifies *bodies*, not the deployed path — the new
   §2.4 integration test is the real equity proof.

**Run order (every step must keep crypto green):** after each file-group below, run the §5 gate
suite (`uv run pytest tests/integration/test_golden_master.py tests/integration/test_mu_contract.py
tests/integration/test_walkforward_equivalence.py tests/integration/test_phase4_deployed_path.py
tests/unit/test_triple_barrier.py tests/unit/test_backtest_engine.py -q`) before proceeding.

---

## 6. Parallel build partition — 3 independent file-groups

The work is partitioned so the three builder groups touch **disjoint files** and depend only on the
shared §1.1 sleeve module + §0 calendar (both already-existing or single-file additions). The
sleeve module (`config/sleeve.py`) + the `DataCfg.asset_class` field + the `StrategyContext`
`asset_class`/`calendar` surface are the **shared prelude** — one builder lands them FIRST (call it
Group 0, ~½ day), then Groups A/B/C proceed in parallel.

### Group 0 (PRELUDE — blocks A/B/C; ~½ day)
- `config/sleeve.py` (new) — `Sleeve` dataclass + registry + `sleeve_for` (§1.1).
- `config/settings.py:74` — `DataCfg.asset_class` field (crypto default).
- `backtest/engine.py:164-179,707` — `StrategyContext` gains `asset_class` + `calendar` property
  (§3.3) — the surface only; the loop migration is Group B.
- Unit test: `tests/unit/test_sleeve.py` — registry returns H1/24/7 for crypto, D1/XNYS for equity.

### Group A — DATA + FEATURES read path (P1 + feature spine)
**Files:** `data/store/reader.py`, `features/context.py`, `features/engine.py`,
`features/library/equity_price.py`.
- §2.1 `reader.corporate_actions` (+ §3.8 `reader.gaps` calendar kw).
- §2.2 `context.corporate_actions` + `_CA_COLUMNS` + `_TS_COLUMNS` + cache.
- §3.1 `FeatureEngine` anchor_tf/calendar threading + §4 fail-closed guard.
- §3.2 `FeatureContext.panel` calendar grid + asset_class/calendar ctor.
- §2.3 `_adjusted_close_panel` fail-closed raise + §2.4 tf_ms=D1.ms fix.
- **Tests:** `test_corp_actions_read_path.py` (new, §2.4), update `test_pit_reader.py`,
  `test_feature_engine.py`, `test_factors_equity_price.py` (inject CA surface).

### Group B — BACKTEST + LABELING execution path
**Files:** `backtest/engine.py` (the run-loop + `BacktestEngine.__init__`; NOT the
`StrategyContext` surface — Group 0 owns that), `labeling/triple_barrier.py`.
- §3.3 engine grid/next-bar/floor_bar via `self._calendar`; `BacktestEngine` `calendar` kw;
  `LakeCostInputs` left as-is (gated H1).
- §3.4 TripleBarrier session hops via `calendar_for(inst.asset_class)` (extend the existing :534
  seam); thread calendar into `_scan_one_instrument`.
- **Tests:** `test_backtest_engine.py`, `test_triple_barrier.py`, the golden master must stay green;
  add an equity-D1 session-grid backtest fixture (weekend-gap fill via Monday open).

### Group C — PORTFOLIO + SIGNALS + WALK-FORWARD annualization/grid path
**Files:** `portfolio/strategy.py`, `portfolio/overlay.py`, `signals/sizing.py`,
`signals/service.py`, `analytics/walkforward.py`.
- §3.5 cov grid + `annualize_cov`/`_realized_vol_ann` via `ctx.calendar.periods_per_year` +
  overlay.
- §3.6 `GrinoldSizer.periods_per_year` field + `SignalService` anchor/ppy threading.
- §3.7 WF grid via calendar + sessions-embargo (grid-fed).
- **Tests:** `test_blend_strategy.py`, `test_sizing.py`, `test_mu_contract.py`,
  `test_walkforward_equivalence.py` must stay green; add an equity-session annualization unit
  asserting `periods_per_year(D1)=252` flows into `annualize_cov`.

**Inter-group contract:** A/B/C all consume `Sleeve`/`sleeve_for` (Group 0) and `calendar_for`
(existing). The only shared file is `backtest/engine.py` (Group 0 = `StrategyContext` surface +
ctor kw; Group B = run-loop) — partition by **function**, merge Group 0 first. No other file is
touched by two groups.

---

## 7. Style + invariants

- Full type hints, `mypy --strict` clean, `ruff` clean. Match neighbour idioms: frozen `kw_only`
  `slots` dataclasses (the `Sleeve`), `Final` module constants, epoch-ms `Ms`, the
  one-of-everything-integrity-critical rule (the calendar is the ONE grid source; `periods_per_year`
  the ONE annualization source — no new bare `8760`/`365`/`252`/`tf.bars_per_year` in the spine).
- Every new kw-only parameter has a **crypto default** so the migration is mechanical and any
  un-migrated caller is byte-identical.
- **Crypto byte-identity over everything.** If a §6 gate test changes a single number, STOP — the
  refactor is not identity and must be corrected.

## 8. Out of scope (noted gaps, NOT this arc)

- Equity `CostInputProvider` (audit G4) — `LakeCostInputs` stays H1-gated; equity backtest cost
  inputs are a follow-up.
- Equity as-of window + `forward_returns`/`estimate_blend_weights` session hops (§3.1, §3.6 notes)
  — the fail-closed guard (§4) covers this until verified; lifting the guard is the next arc.
- `borrow_fee_bps`/locate (P14/G8), MIC-keyed `calendar_for` (G11/P18), lake breadth partitioning
  (P7/G10), embargo-from-lookback (P11) — separate punch-list items.
