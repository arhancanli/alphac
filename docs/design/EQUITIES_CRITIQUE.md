# EQUITIES SLEEVE — CORRECTNESS CRITIQUE

Role: correctness critic. Verdict: **BLOCK**.

Scope reviewed: `docs/design/EQUITIES_SLEEVE.md` against the live engine contracts in
`features/{engine,context,parity}.py`, `data/store/reader.py`,
`data/universe/builder.py`, `core/{calendar,time,types,symbols,instruments}.py`,
`data/sources/base.py`, `data/schemas.py`, and the crypto factor library.

## 0. State of the world (material to the verdict)

NO equity scaffold code exists yet. The only artifact is the spec
(`EQUITIES_SLEEVE.md`). Verified absent: `data/sources/polygon_source.py`,
`features/library/equity_price.py`, all four equity test files, `MarketType.CASH`,
the `XNYSCalendar` branch in `calendar_for` (still `raise NotImplementedError`),
`Dataset.CORPORATE_ACTIONS`. So this critique adversarially verifies the *spec* —
because it will be implemented verbatim, a latent PIT/parity/survivorship error in
the spec is a leak that ships. The findings below are spec-level defects that will
become code-level lookahead/parity/identity bugs unless corrected before the build.

The crypto contracts themselves are sound and unchanged; every BLOCK below is a place
where the equities spec **mis-states what the existing seam actually does**, so a
faithful implementer would either (a) introduce lookahead/parity breakage, or (b)
discover mid-build that "surgical, additive, no crypto behavior change" is false and
improvise. Both are unacceptable for a PIT engine.

---

## BLOCKING FINDINGS

### B1 — The engine is hardwired to a 1h grid; equity D1 factors get a 253-HOUR warm-up, not 253 sessions. (lookahead-adjacent + guaranteed-wrong values)

`features/engine.py` is the deepest defect. `ANCHOR_TIMEFRAME = Timeframe.H1` is used
at EVERY layer of both `compute_history` and `compute_asof`:

```
tf = ANCHOR_TIMEFRAME                                  # = H1, hardcoded
ctx window start = start - max_lookback * tf.ms        # max_lookback * 3_600_000
grid = expected_bar_opens(start, end, tf)              # 24/7 H1 grid
t_star = bar_open_for_decision(as_of, tf)              # floors to the H1 boundary
```

The spec (§4.0, §6) claims the ONLY engine/context edits are: inject a `calendar`
into `FeatureContext` and have `panel` call `self._calendar.expected_bar_opens`. That
is false and dangerously incomplete:

- `lookback_bars` for `eq_mom_252_21` is **253** (sessions). The engine multiplies it
  by `H1.ms` → a warm-up window of **253 hours ≈ 10.5 days**, not 253 trading
  sessions ≈ 1 year. Every equity momentum/beta/vol factor would be computed off a
  window two orders of magnitude too short → all NaN or garbage. The factor is not
  "wrong by a constant"; it is structurally unable to see its own lookback.
- `compute_asof` uses `bar_open_for_decision(as_of, H1)` to find the decision bar.
  For a daily equity decision this floors to an hour boundary, not the session open —
  the live path would request the wrong `t*` and the minimal window would be 253
  hours wide. **Batch/asof parity (the §4.5 gate) cannot hold** because the two paths
  disagree on what a "bar" even is.
- `expected_bar_opens(start, end, H1)` builds a 24/7 hourly grid; the spec's whole
  §4.0 argument ("row position == session") collapses because the target grid the
  engine reindexes onto is hourly and 24/7.

The spec's §3.2 even concedes "`bars_per_year` is the 24/7 number and MUST NOT be used
for equities" — but the engine's window arithmetic uses `tf.ms` of a hardcoded H1,
which is the same class of leak one layer down. **The engine must become
timeframe/calendar-aware** (an `anchor_tf` + `calendar` per compute, threaded through
the window math, the grid, and `bar_open_for_decision`), and the parity harness
(`features/parity.py`, which also hardcodes `ANCHOR_TIMEFRAME` and
`bar_open_for_decision(t, 1h)` at lines 122/125/138) must be parameterized too.

This is NOT "surgical additive" and NOT "no crypto behavior change risk": it edits the
hottest path in the system. **Fix:** thread `anchor_tf: Timeframe` and
`calendar: TradingCalendar` through `FeatureEngine.__init__` (or per-call), replace
every `ANCHOR_TIMEFRAME`/`tf.ms`/`expected_bar_opens`/`bar_open_for_decision` use with
the calendar-aware equivalent (`calendar.next_bar_open`/`floor_bar`/
`expected_bar_opens`), prove crypto parity is byte-identical (the
`Always24x7Calendar` path must reduce to today's arithmetic exactly), and re-run the
FULL existing parity suite. Until the engine and parity harness are calendar-aware,
NO equity factor can be parity-verified, so §4.5 (the discipline gate) is unsatisfiable
as specced.

### B2 — `bar_open_for_decision` / `next_bar_open` for equities must hop sessions; the reader's PIT `ts_open + tf.ms <= as_of` is correct but the GRID and DECISION-BAR math are not. (parity + correctness)

The spec §3.1 correctly says equity bar arithmetic must hop sessions
(`next_bar_open` skips weekends/holidays), and §1.5/§3.2 say `available_at = ts_open +
86_400_000` is fine for the reader's PIT predicate. These two statements are BOTH true
but the spec does not reconcile that they live in different places:

- The reader's `epoch_ms(ts_open) + tf.ms <= as_of` (reader.py:137) is a pure
  availability predicate and is correct unchanged for D1 — a daily bar for session D is
  available at D+1d. Good.
- BUT the engine's `bar_open_for_decision(as_of, D1)` = `floor_bar(as_of - D1.ms, D1)`
  = a pure-integer floor to a calendar-day boundary. On a Monday `as_of`, `as_of -
  86_400_000` lands on Sunday (a NON-session) and floors to Sunday 00:00 UTC — which is
  NOT a session open. The decision bar would be a phantom Sunday slot that has no bar,
  so the live row is NaN while the batch row (session-gridded) is real → parity fails.

The spec asserts (§3.1) "anything doing `ts + tf.ms` for equities is a bug; it must
call the calendar" but then (§1.5/§3.2) blesses `ts_open + 86_400_000` for
`available_at`. The resolution the build needs, stated nowhere: **availability math
(`+tf.ms`) stays integer; decision-bar and grid math (`bar_open_for_decision`,
`next_bar_open`, `expected_bar_opens`) must go through the calendar.** This boundary
must be pinned explicitly in the spec or B1's implementer will get it wrong in both
directions. **Fix:** state the rule precisely (availability = integer close; bar
selection = calendar session hop) and add a parity test where `as_of` falls on a
Monday after a holiday weekend — the decision bar must be the prior Friday session,
not a phantom weekend slot.

### B3 — `Dataset.OHLCV_1D` is hardcoded as RESAMPLER-DERIVED everywhere; equities ingest it NATIVELY, and the reader/universe builder assume H1 provenance. (correctness + a silent data-integrity trap)

`data/schemas.py:66-83`: "the latter two hold bars *derived* from stored 1h bars by
the resampler — never fetched." `OHLCV_DATASETS` membership gates the writer's
partial-bar guard, and the resampler (`data/store/resample.py:230`) is the only
producer. The spec §2 claims `OHLCV_1D` "becomes a natively-ingested dataset" and "the
lake does not care about provenance." Two concrete breakages the spec glosses:

1. **UniverseBuilder reads H1, not D1.** `builder.py:287` hardcodes `tf=Timeframe.H1`
   in `_median_daily_quote_volume`, and the module docstring (lines 25-31) is written
   around 1h bars summed per UTC day. For an equity universe there ARE no H1 bars —
   the native bar is D1. The spec §5 calls this a "≤10-line change" (parameterize
   `tf`), but it is more: the per-UTC-day summing loop (builder.py:296-301) assumes
   multiple intraday bars per day; with D1 it must be a pass-through, AND the
   `as_of=t` PIT read for D1 hits the `ohlcv_1d` dataset which today is empty unless
   the resampler ran. If an implementer parameterizes `tf` but a D1 equity bar's
   `ts_open + D1.ms` straddles the rebalance instant `t` (00:00 on the 1st), the bar
   for session = the 1st is NOT yet available at `t` (closes at the 2nd) — correct,
   but the spec's claim "the per-UTC-day summing becomes a no-op" hides that the
   ranking now sees one fewer day than the crypto path at the boundary. Needs an
   explicit equity universe test (the spec lists one but does not pin this boundary).

2. **Resampler completeness flag collision.** `schemas.py:143` reserves a quality-flag
   bit for "the resampler's" use on derived 1d bars. A natively-fetched equity 1d bar
   must NOT carry resampler-derived flag semantics, and the reader's
   `_flag_mask_sql(D1, as_of)` lags bits by `(1+L)*D1.ms`. The spec does not state
   what `quality_flags` an equity native D1 bar carries (it says `quality_flags=0` in
   §1.3 for the fetch — good) nor that the resampler must be FORBIDDEN from running on
   equity instruments (otherwise it would overwrite native bars with derived ones, or
   refuse because there are no H1 source bars). **Fix:** the spec must (a) state that
   the resampler is never invoked for `AssetClass.EQUITY` (no H1 source exists), (b)
   confirm the writer's partial-bar guard for `OHLCV_1D` keys on the bar's own
   `ts_open + D1.ms` not on H1 provenance (verify `writer.py:130`), and (c) add the
   universe boundary test above.

### B4 — The `<TICKER>USD` identity round-trip is NOT safe: `split_exchange_symbol` uses longest-suffix matching against `KNOWN_QUOTES`, which silently mis-splits real tickers. (identity corruption → wrong instrument, wrong universe, wrong PIT joins)

The spec §1.1 "Chosen approach" stores the canonical exchange-symbol as `<TICKER>USD`
so `__post_init__`'s `f"{base}{quote}" == id_symbol` invariant holds "with zero new
code." But `KNOWN_QUOTES` (symbols.py:32-45) contains `"BTC"`, `"ETH"`, `"DAI"`,
`"EUR"`, `"TRY"`, `"BNB"`, `"USDC"`, `"USDT"`, ... and `split_exchange_symbol` returns
the FIRST matching suffix in tuple order (longest-first), which is matched against the
WHOLE `<TICKER>USD` string. Concrete corruptions:

- A real ticker whose name ends in a quote token, e.g. an ADR/ETF ticker ending
  `...ETH`, `...BTC`, `...EUR`, or a class ticker normalized to end that way, would
  have `Instrument.__post_init__` reconstruct `base+quote` from the id symbol
  `<TICKER>USD` via `split_exchange_symbol`, which strips `USD` correctly here
  (USD is last in the tuple but suffix match is on the literal string end) — so
  `XYZUSD` → base `XYZ`. OK for the common case.
- The break is the OTHER direction: any path that round-trips an equity through
  `to_ccxt`/`from_ccxt` (or any consumer that calls `split_exchange_symbol` expecting
  a crypto pair) will treat `AAPLUSD` as base `AAPL` quote `USD` and could emit a
  ccxt symbol `AAPL/USD` — a crypto venue call for an equity. The spec routes equities
  to a separate source, but `split_exchange_symbol` is a SHARED stateless helper with
  no asset-class guard, and the equity id deliberately reuses it. A ticker that is
  ITSELF a known quote (`BTC`, `ETH` exist as real tickers — Grayscale, etc.) yields
  `BTCUSD` → `split_exchange_symbol` longest-suffix could match... `BTC`? No — suffix
  is `USD` (string ends in USD). But ticker `USDC` (a real ticker? no) aside, ticker
  `EUR`-like names create base=`""` after stripping if ticker==quote. The
  empty-base guard raises `SchemaError` — a HARD failure at instrument construction for
  any legitimately-named ticker colliding with a quote token.

The spec's "zero new code" claim is the trap: it assumes the crypto symbol grammar
generalizes to equities, but the equity namespace is far larger and collides with the
crypto-quote vocabulary. **Fix:** do NOT overload `<TICKER>USD` through the shared
crypto `split_exchange_symbol`. Either (a) add the dedicated
`equity_instrument_id`/`parse_equity_id` helpers the spec lists as the rejected
alternative (they are the correct, collision-free choice), with a regression test for a
quote-colliding ticker (`BTC`, `ETH`, `EUR`), or (b) gate `split_exchange_symbol` on
`MarketType.CASH` to bypass quote-suffix matching entirely. The spec must also add a
round-trip test for dotted/class tickers (`BRK.B` → `BRKB`) and the `vendor_ticker`
recovery, since `BRKB` canonicalization is asserted but untested.

### B5 — `funding_asof_join` is a CRYPTO-ONLY concept and the spec's corporate-actions analogue has a PIT hole at the split-folding boundary. (lookahead in the adjusted-close helper)

The spec §4.3 defines `adjusted_close(ctx)` whose cumulative split factor folds split
`ratio` for actions with `available_at <= ts_open + tf.ms` AND `ex_date > ts_open`.
The `available_at` gate is correct (mirrors finding 18). But the **`ex_date > ts_open`
condition is a future-relative test evaluated per historical row**, and the spec does
not pin WHICH `as_of` defines "future." Two readable interpretations:

- Per-decision: for the decision at row `t`, fold splits whose `ex_date` is after the
  HISTORICAL bar being adjusted — correct (a split between an old price and `t` must be
  applied to express the old price in current share terms).
- Per-window-end: fold all splits with `available_at <= end` — WRONG, leaks a split
  known only near the window end back onto a decision early in the window.

`funding_asof_join` solves this with a per-row `decision_ts = ts_open + tf.ms` backward
as-of merge (context.py:272-285). The spec says `adjusted_close` is "per-row PIT exactly
like `funding_asof_join`" but the formula in §4.3 mixes a per-row `available_at` gate
with a per-bar `ex_date` gate WITHOUT specifying that the adjustment factor for
decision row `t` must be recomputed using only `available_at <= (ts_open_of_t + tf.ms)`
— i.e. the cumulative factor is a FUNCTION OF THE DECISION ROW, not a single
window-wide vector. A naive implementer will compute ONE cumulative split-factor series
per instrument (using all actions in the window) and apply it to all rows — which
back-applies a split announced late in the window to early-window momentum values =
lookahead. **This is the exact funding finding-18 bug in equity clothing.**

Compounding risk: the spec keeps `fetch_funding` on the equity source raising
`NotImplementedError` (good), but `FeatureContext.funding_asof_join` and `.funding()`
remain callable on an equity context. If any blended/shared factor body (e.g. a carry
factor accidentally included in an equity run) calls `funding_asof_join`, it reads an
empty funding table and returns all-NaN silently rather than failing — a crypto concept
leaking into the equity path undetected. **Fix:** (a) specify `adjusted_close` as a
per-decision-row PIT reconstruction (the cumulative factor at row `t` uses only actions
with `available_at <= ts_open_t + tf.ms`), with a test that a split with
`available_at` between two decision rows is invisible to the earlier row and visible to
the later one — the §4.5 "split invisible before its available_at" test must assert
this ACROSS rows, not just at one timestamp; and (b) add an assertion/guard that equity
factor specs never invoke the funding leg (e.g. the equity factor registry block is
disjoint from any funding-consuming spec, enforced by a test that the equity factor set
contains no `ewma_family`/funding params and that `funding_asof_join` is never reached
on an equity context).

### B6 — BAB reuses `rolling_beta`, but `BETA_WINDOW = 720` is a hardcoded module constant baked into the crypto specs; the spec's `eq_beta_252`/`eq_bab_252` need 252 and the spec never states how the override is plumbed without editing crypto. (correctness)

`mean_reversion.py:77`: `BETA_WINDOW: int = 720`. `rolling_beta(returns, market, *,
window=BETA_WINDOW)` takes `window` as a kwarg, so passing `window=252` is fine — BUT
the spec §4.2 step 4 says "reuse `mean_reversion.rolling_beta` + `market_return`
machinery" and the registered crypto consumers (`mr_res_*`, market_state) pass
`beta_window=BETA_WINDOW`. The spec must state that `eq_beta_252` passes `window=252`
explicitly (it does imply this via the table), AND that `_member_mask` (a
module-private in `mean_reversion.py`, line 192) is reused. The spec §4.2 step 2 says
"lift it to a shared location or import; it is calendar-agnostic." This is an
UNDERSPECIFIED edit to `mean_reversion.py` (exporting a private symbol) that the §6
manifest lists `mean_reversion.py` as... it does NOT list it as edited. §6 EDITED files
omits `mean_reversion.py` and `market.py` entirely, yet §4.2 requires importing/lifting
`_member_mask`, `market_return`, `rolling_beta`, `log_returns` from there. Either the
import is from the existing public surface (verify: `__init__.py` re-exports
`market_return`, `rolling_beta`, but `_member_mask` is PRIVATE and not exported) or the
file must be edited. `_member_mask` is NOT in `library/__init__.py`'s exports — so the
equity module either reaches into a private symbol (lint/`mypy`-fragile, breaks the
encapsulation the crypto module documents) or `mean_reversion.py` must be edited to
promote it. **Fix:** add `mean_reversion.py` (or a new shared `_market.py`) to the §6
EDITED manifest, specify `_member_mask` is promoted to a shared public helper with its
own test, and confirm `eq_beta_252` passes `window=252` (not the 720 default).

---

## NON-BLOCKING (fix-soon; correctness-adjacent, not leaks)

### N1 — `available_at = ts_open + 86_400_000` is conservative by up to a full session, not "< a session."
§1.3/§3.2 call the daily-bar availability lag "conservative by < a session." For a
session that closes ~6.5h after 00:00 UTC open is irrelevant (UTC midnight labeling),
but the bar for session D (labeled 00:00 UTC of D) becomes "available" at 00:00 UTC of
D+1 — roughly a full calendar day after the session OPEN and ~17.5h after the session
CLOSE (NYSE closes 21:00 UTC). That is a ~17.5h conservative lag, not "< a session."
Harmless for daily-frequency decisions (you decide at the next session open anyway) but
the spec's quantification is wrong and should say so honestly, since intraday (post-v1)
will care.

### N2 — `XNYSCalendar` static-schedule caching assumes a bounded backtest horizon; `exchange_calendars` future sessions are estimates.
§3.1 caches the session `DatetimeIndex` lazily, "keyed nowhere ... the calendar is
effectively static." `exchange_calendars` future holiday schedules (e.g. ad-hoc
closures, presidential funerals) are not knowable PIT. For a backtest this is fine
(history is settled); for the LIVE loop a cached forward schedule could miss a
late-announced closure. Document that the live path must refresh the calendar, not
trust a cached forward window — the same spirit as the universe finding-21 ordering
contract.

### N3 — `eq_lowvol_252` and `eq_vol_252` registering "the same number" twice (direction -1 vs 0) doubles compute and risks drift.
§4.1 registers the identical realized-vol body twice. If they ever diverge (one edited,
the other not) the "context == alpha input" invariant silently breaks. Prefer one
computed series consumed by both, or a test asserting `eq_vol_252` and
`|eq_lowvol_252 pre-CS|` are bit-identical.

### N4 — `periods_per_year(D1) = 252.0` must be wired into Sharpe/vol/covariance via `calendar_for(asset_class)`, but the spec does not list the consumers.
§3.1 asserts "no hard-coded 8760 or 365 leaks into the equity path," but `analytics/`,
`portfolio/covariance.py`, and `validation/` annualization sites are not in the §6
manifest. Grep for hardcoded `365`/`8760`/`252` annualization in those modules and pin
that each reads `calendar_for(asset_class).periods_per_year(tf)`. Otherwise an equity
Sharpe is computed with the crypto 365 basis — a silent 1.6x annualization error
(sqrt(365/252)).

### N5 — Survivorship regression: the spec names LEHMQ/FTT-analogue but does not pin the SCD2 seed path for delisted equities.
§1.4 is correct in shape (delisted ticker → closed interval at `delisted_ts`). But the
crypto FTT test seeds via Binance Vision archive; the equity path seeds from Polygon's
`active=false` page. The spec must assert the ingest pipeline actually PERSISTS the
delisted instruments into the SCD2 store (the universe builder reads
`instruments.all_known(as_of=now)`, builder.py:157) — `list_instruments` returning them
is necessary but not sufficient; the seed/upsert must run. Add that link to §7 step 5/6
and the test must build the universe from the STORE, not from the source list directly.

---

## What is correct in the spec (credit where due)

- Raw-in-lake + PIT-reconstruct-adjusted-at-read is the RIGHT call (§1.3 rationale) and
  matches the crypto "raw bars as stored, derived data regenerable" discipline exactly.
  Storing Polygon `adjusted=true` would silently rewrite history on each new split.
- `CORPORATE_ACTIONS_SCHEMA` with a mandatory `available_at` and "ALL joins use this"
  is the correct funding-finding-18 analogue at the schema level.
- Keeping `OHLCV_SCHEMA`/`UNIVERSE_SCHEMA` unchanged and adding ONE new dataset is the
  right blast-radius instinct.
- The factor SELECTION (12-1 momentum, 1m reversal, low-vol, BAB, Amihud) is the
  correct replication-first, price-only set; deferring value/quality to fundamentals is
  honest.
- The survivorship REGRESSION-TEST discipline (§1.4 mirroring FTT/LUNA) is exactly the
  right gate, conceptually.

The selection and storage philosophy are sound. The defects are all in the
**mechanical wiring** — and in a PIT engine, the wiring IS the correctness. B1, B2, B5
are genuine lookahead/parity leaks waiting to be coded; B3, B4, B6 are correctness/
identity breaks the "zero new code / surgical additive" framing actively hides.

## Required before build proceeds
1. Re-spec the engine + parity harness as calendar/anchor-tf aware (B1, B2), with a
   proof that crypto parity is byte-identical.
2. Pin the per-decision-row PIT semantics of `adjusted_close` with a cross-row test
   (B5).
3. Replace the `<TICKER>USD` identity overload with collision-free equity-id helpers
   + a quote-colliding-ticker regression test (B4).
4. Correct the §6 EDITED manifest to include `mean_reversion.py` (or a shared market
   helper) and the annualization consumers (B6, N4); state the resampler is never run
   for equities (B3).
