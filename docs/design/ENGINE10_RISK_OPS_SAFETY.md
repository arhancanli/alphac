# ENGINE10 — Risk / Ops / Safety audit

Dimension: the kill switch, drawdown ladder, pre-trade checks, reconciliation,
crash recovery, the live-loop clock, monitoring/alerting, and the deferred
Phase-8 pre-arm real-money gates C3/C5/C7/C10. A 10/10 engine **fails safe** and
is **fully observable and recoverable**.

Audit posture: READ-ONLY. Verified against HEAD (dfdf515). The working tree had
two unrelated modified files (`cli/instruments_cmds.py`, `data/ingest/seed.py`)
mid-edit by another process — not touched.

Verdict score (this axis, today): **8.0 / 10**. The *mechanisms* that exist are
genuinely institutional (file-sentinel kill, hysteretic absorbing drawdown
ladder with bounded auto-rearm, single-clock loop with macOS-sleep handling,
persist-before-submit + deterministic client_order_id idempotency, online-backup
+ restore-drill). What keeps it off 10 is in the corners: **risk machinery that
is built but never wired** (VaR/CVaR, clock-sanity-in-loop, monthly universe
refresh), **monitoring promised by the spec but not built** (8h heartbeat, daily
tearsheet job, CRIT re-send-until-ack, the `risk_events` audit table, the
per-asset stop), and the **five pre-arm real-money gates that are still open**.

---

## 1. What a 10/10 engine has on this axis

- **Fail-safe by construction.** Every degenerate input (stale data, NaN equity,
  empty book, divergent reconcile, clock skew) routes to *hold or halt*, never to
  "lever up / guess / silently shrink". AlphaForge largely achieves this.
- **Defense in depth on the brake.** A dumb file kill (✓), an absorbing
  drawdown halt (✓), AND an automatic risk circuit that the strategy cannot
  out-vote (VaR limit, per-asset stop) — the last two are **missing/unwired**.
- **Liveness, not just safety.** A 10/10 tells you within minutes when the
  process *dies*. AlphaForge has only outbound event alerts; **no heartbeat / no
  dead-man's-switch**, so a crashed-and-not-restarted loop is silent.
- **A queryable risk/audit ledger.** Every reject, halt, stop, and breach lands
  in a durable table you can post-mortem. AlphaForge's spec defines `risk_events`;
  the code never creates it.
- **Reconciliation that is a genuine three-way check** (broker truth vs internal
  book vs a *shared* mark time) with a graded WARN→HALT ladder. AlphaForge's is a
  two-way check with a single hard bound and a known mark-time bug for real money.
- **Every safety control on the live path is also exercised on the live path.**
  Controls that only exist as one-shot CLI commands (clock sanity) do not protect
  the 24/7 loop.

---

## 2. Concrete gaps in OUR engine

### BLOCKER — pre-arm gates for real capital

These are unreachable in v1 (CCXTBroker is a NotArmed stub) but every one MUST
close before a single real order. They are documented in
`memory/project_alphaforge_phase8_prearm_gates.md`; I re-verified each against
HEAD.

**C3 — reconcile mark-time mismatch.**
`execution/reconcile.py:473` computes `equity_broker = self._broker.account().equity_quote`.
`PaperBroker.account()` (`execution/paper.py:517`) marks at `fills[-1].ts`, while
the book equity comes from the latest `equity_curve` row keyed at `floor_bar(now)`
(`reconcile.py:580-583`). On a live, moving order book those two instants differ,
so equity is compared at two different marks → spurious `ReconciliationError`
halts (or, worse, a real divergence masked by a favorable mark drift). The
`BrokerView` protocol (`reconcile.py:124-151`) exposes only `account()`, not
`account_at()`, even though `PaperBroker.account_at(ts)` already exists
(`paper.py:520`). Fix: add `account_at(as_of)` to `BrokerView`; reconcile broker
and book at one shared `as_of`.

**C5 — broker fill discovery on boot.**
`LiveLoop.recover_on_boot` rebuilds the book purely from *store-recorded* fills
(`loop.py:786-805`, `_replay_recorded_fills`). For PaperBroker the broker *is* the
serialized book, so this is sufficient. For a real venue, a fill that landed in
the window between submit and the store write (`fill_unpersisted`) is
**undiscoverable** — CCXTBroker has no `fills`/`fetch_order` wired
(`ccxt_broker.py` reads raise NotArmed). Fix: wire `fetch_order(client_order_id)`
into boot recovery for non-paper brokers so a venue-side fill we never persisted
is found and adopted before the first decision.

**C7 — boot reconcile is a tautology for the recovery case.**
`_sync_book_snapshot_after_recovery` (`loop.py:807-838`) writes the *broker's*
positions/equity into the book snapshot at `floor_bar(now)` and *then*
`reconcile()` compares book-to-broker — i.e. it compares the broker to a row we
just derived from the broker. For PaperBroker (book == broker) this is benign,
but it means boot reconcile cannot actually catch a divergence on the recovery
path, and the snapshot is keyed at `floor_bar(now)` rather than the failed
`cycle_ts`. Fix: reconcile against broker truth BEFORE adopting it into the book
row, and key the recovery snapshot at the interrupted `cycle_ts`.

**C10a — ack-before-fill ordering.**
`PaperBroker.submit` books the fill (`_book_fill`, `paper.py:480`) and only then
records the dedup ack (`acks[coid] = ack`, `paper.py:488`). A crash between those
two lines leaves a booked fill with no idempotency ack → on replay the same
client_order_id is treated as fresh and **double-fills**. (In-process this is one
synchronous call so the window is tiny, but the *ordering* is the unsafe one and
becomes load-bearing the moment fills are async/real.) Fix: record the ack
first/atomically with the position mutation.

**C10b — SQLite durability.**
`live/store.py:306` sets `PRAGMA synchronous=NORMAL`. Under NORMAL, a commit is
*not* guaranteed durable across an OS crash / power loss — the WAL frames may not
be fsync'd. The crash-recovery contract ("persist-before-submit") assumes the
intent row survives a hard crash; NORMAL weakens that to "survives a *process*
crash". Fix: `synchronous=FULL` on the trading store (or an explicit fsync between
`record_intent` and `submit`). The Parquet lake can stay NORMAL; the trading
store is the irreplaceable audit trail.

**C10c — single-bound reconcile tolerance, not the specced ladder.**
`ReconTolerance.equity_rel = 5e-3` (`reconcile.py:224`) is one hard bound, and the
docstring (`reconcile.py:217`) admits "v1 treats breach of this single bound as
halt-worthy". execDesign §8.4 specifies a graded **0.5% WARN → 2% HALT** ladder.
As built, a 0.6% transient equity wobble (a stale mark on one name) HALTS the
24/7 loop instead of warning. Fix: implement the two-tier ladder (WARN at 0.5%,
HALT at 2%), routed through the alerter at WARN.

### BLOCKER/HIGH — no liveness signal (the process can die silently)

execDesign §9 step 9 and §9.4 (line 716) specify **"heartbeat every 8h"** and a
**daily 00:05 UTC tearsheet job**. Neither is built:
- `Alerter.send_tearsheet` exists (`live/alerts.py:73, 149`) but has **zero
  callers** anywhere in the live path (grep: only backtest render uses
  `build_tearsheet`).
- There is no heartbeat command, no scheduled job, no dead-man's-switch.
- `cli/paper_cmds.py` wires no `launchd`/cron entry beyond the loop itself; the
  loop's "heartbeat tick" (`loop.py:644,667`) only keeps the *internal* tick
  alive while halted — it emits nothing outbound on a healthy idle.

Consequence: if `af paper run --forever` is OOM-killed or the box reboots and the
loop is not restarted, **nothing alerts the operator**. A safe system that has
gone dark is indistinguishable from a healthy idle one. This is the single
biggest fail-safe gap. Fix: an 8h heartbeat alert from the loop (or an external
watchdog that alerts if no heartbeat row was written in N hours), and the
00:05-UTC tearsheet job (`send_tearsheet` already exists — wire a cron/launchd
command that renders the live equity curve and pushes it).

### HIGH — VaR/CVaR is computed but wired to nothing

`risk/monitors.py:55 historical_var_cvar` and `VarReport` are fully implemented
and tested, but a grep shows they are **only re-exported** in
`risk/__init__.py:17,31` — no caller in `pretrade.py`, `loop.py`, `limits.py`, the
strategy, or any gate. `RiskCfg.var_confidence` / `var_window_days`
(`settings.py:268-269`) feed `RiskLimits` (`limits.py:62-63`) but `RiskLimits`
never uses them either. So the engine has VaR *numbers* but **no VaR limit** —
the design's tail-risk control is dead code. Fix: consume `historical_var_cvar`
over the live equity curve each cycle and gate gross (or alert) when CVaR exceeds
a configured fraction; at minimum surface VaR/CVaR in `af paper status` and the
tearsheet.

### HIGH — the per-asset stop is specced but absent

execDesign §7 (line 543): "if adverse move from `avg_entry_price` exceeds
`2.5 × σ_daily,i`, close next cycle (`reason="stop"`) and embargo re-entry for 24
bars. Persisted in `risk_events`." Grep finds **no implementation** — no stop
logic in `risk/`, `portfolio/strategy.py`, or the loop; no `stop`/`embargo`
config field in `settings.py`. The only hit for "per-asset" is a *cost* comment
in `strategy.py:106`. The portfolio-level drawdown ladder is the only stop that
exists; a single name blowing up is only caught indirectly via the position cap
and the aggregate ladder. Fix: implement the per-asset 2.5σ stop + 24-bar embargo
as designed, or formally retract it from the spec.

### HIGH — `risk_events` audit table does not exist

execDesign §9.1 (line 673) defines a `CREATE TABLE risk_events`; the pre-trade
checker is specced to write a `risk_event` row on every reject (line 502), and
stops/non-retryable broker errors likewise (lines 543, 601). In code:
`TradingStore` (`live/store.py`) creates `cycles/orders/fills/positions_snapshots/
equity_curve/paper_state/ladder_state` — **no `risk_events`**. Pre-trade
rejections are surfaced only as ephemeral WARN alerts
(`loop.py:1147-1151`) and structlog lines; there is no durable, queryable risk
ledger. For a top-shop post-mortem ("show me every limit breach in the last 30
days and why") this is a gap. Fix: add the `risk_events` table and write a row on
each pre-trade reject, ladder transition, reconcile breach, and clock-skew event.

### MEDIUM — clock sanity is not wired into the live loop

`ops/clock.py` implements `ClockSanity`/`CCXTExchangeTimeSource` and `loop.py`
accepts an optional `clock_sanity` seam (`loop.py:522`, consumed at
`loop.py:958 _check_clock_sanity`). But the production wiring in
`cli/paper_cmds.py _build_loop` (lines 588-606) **never passes `clock_sanity`** —
so the per-cycle clock check is `None` in the only place that matters, and the
loop's `clock_skew_alerts` counter is permanently 0 in production. The check
exists *only* as a manual one-shot `af ops clock` command (`cli/ops_cmds.py:231`).
The whole point of the design (two-layer defense: staleness breaker on the data
side + clock sanity on the time side, `ops/clock.py` docstring) is defeated for
the unattended soak. Fix: construct a `ClockSanity(CCXTExchangeTimeSource(...))`
in `_build_loop` and pass it to `LiveLoop`.

### MEDIUM — monthly universe refresh is not wired into the live loop

`LiveLoop` supports `universe_refresher` (`loop.py:528`, used at `loop.py:1014`
on a month boundary), but `_build_loop` (`cli/paper_cmds.py:588-606`) passes none.
So over a 30-day+ soak the live universe **never rebalances** — it is frozen at
whatever `membership_asof(cycle_ts)` returns from the last offline rebuild,
diverging from the backtested monthly-rebalanced universe. This is a
research/live consistency break with a risk flavor (you can hold a name that has
dropped out of the liquid universe). Fix: wire a `UniverseRefresher` adapter over
`UniverseBuilder.rebuild`.

### MEDIUM — CRIT alerts fire once; no re-send-until-ack

execDesign §9.4 (line 733): "CRIT (immediate, re-sent every 15 min until
`/ack`)." The alerter sends each CRITICAL exactly once
(`live/alerts.py:137-147`); there is no re-send loop and (by deliberate design,
correctly) no inbound `/ack` poller. A single dropped Telegram delivery on a halt
event means the operator may never learn the system halted. The `MultiAlerter`
always-log fallback mitigates (the JSONL has it) but nobody is watching JSONL on a
phone at 3am. Fix: a CRIT re-send timer keyed off a halt-acknowledged sentinel
file (mirroring the kill-switch's file-based ack, keeping the no-inbound-control
posture).

### MEDIUM — kill-switch not re-checked immediately before submission

`risk/killswitch.py` docstring (lines 6-8) promises the loop checks `engaged()`
"at cycle start AND again immediately before every order submission". In the loop
the kill is checked at cycle start (`loop.py:932`) and in the tick wait
(`loop.py:661,673`) but **not** re-checked just before `_om.place`
(`loop.py:1167`). A kill engaged during the decision computation is not honored
until the next bar. With 1h cadence and synchronous paper fills the window is
tiny and benign; for real money with a longer decide→submit path it is a real
(small) leak between the documented and actual guarantee. Fix: re-check
`self._kill.engaged()` immediately before `_om.place` and skip-with-halt if set.

### MEDIUM — does it scale to thousands of equity names?

The risk/ops layer was built for ~20 perps and several seams become O(N) hotspots
or hard caps at equity scale:
- `PaperBroker`'s tradable universe is **fixed at construction** from
  `instruments.all_known(as_of=now)` (`cli/paper_cmds.py:564-566`); with thousands
  of names this is a large fixed map and the broker cannot adopt a name that lists
  intra-run.
- `_decide_and_place` builds `adv`/`sigma` dicts by calling
  `cost_src.cost_inputs(iid, ...)` per instrument every cycle
  (`loop.py:1136-1137`) and `_closes_for` pulls a fresh book mid per instrument
  (`loop.py:1272-1273` via `_book_mid`, one `order_book` fetch each). At N=2000
  that is 2000 synchronous book fetches inside a single cycle — at 1h cadence it
  fits, but the staleness gate (`_ingest_and_wait`, `loop.py:1207-1213`) re-probes
  the *whole* universe each tick, and the watermark is the **min** freshest open
  across all ids (`cli/paper_cmds.py:107-123`) — one slow/illiquid name stalls or
  degrades the entire universe.
- The pre-trade book-gross check is O(N) per opening order (`pretrade.py:224`
  iterates the working book inside the per-order loop) → O(N²) per cycle in the
  worst case.
These are not blockers for the crypto sleeve but are unproven at equity scale;
the engine has no load test at N≫20. Fix: batch the cost-input/book fetches, make
the staleness watermark per-name (drop a stale name, don't stall the universe),
and precompute the running book-gross incrementally in the pre-trade loop.

### POLISH

- `af paper run --once` calls `loop.recover_on_boot()` explicitly
  (`cli/paper_cmds.py:306`) and `run_forever` also calls it (`loop.py:655`); the
  `--once` path is fine (it never calls `run_forever`), but the recovery is
  idempotent so this is harmless — worth a comment so a future refactor doesn't
  double-recover.
- `StalenessBreaker` treats a future-stamped bar (clock skew) as fresh
  (`monitors.py:348`); correct given the clock-sanity layer, but since
  clock-sanity isn't wired (above), a clock that runs *ahead* currently has **no**
  guard at all — the two-layer defense collapses to zero layers on the
  ahead-skew direction.
- `ReconTolerance.qty_abs_floor = 1e-8` is a single global floor; per-instrument
  `qty_step` would be more correct for mixed-precision equity lots.

---

## 3. Severity summary

| Severity | Gaps |
|---|---|
| blocker | C3 mark-time, C5 fill discovery, C7 reconcile-before-adopt, C10a ack ordering, C10b synchronous=NORMAL durability, C10c WARN→HALT ladder; no liveness/heartbeat |
| high | VaR/CVaR unwired; per-asset stop absent; `risk_events` table absent |
| medium | clock-sanity not wired into loop; universe refresh not wired; CRIT no re-send; kill not re-checked pre-submit; equity-scale unproven |
| polish | --once double-recover comment; ahead-skew unguarded w/o clock sanity; per-instrument qty floor |

## 4. The shortest path to 10/10 on this axis

1. Close all six pre-arm gates (C3/C5/C7/C10a/b/c) — these are the literal
   gate to real capital and most are small, surgical changes.
2. Add a liveness path: 8h heartbeat + an external dead-man's-switch that alerts
   on heartbeat absence, and wire the 00:05-UTC tearsheet job (`send_tearsheet`
   already exists).
3. Wire what is already built but dark: `clock_sanity` and `universe_refresher`
   into `_build_loop`; consume `historical_var_cvar` as a real gate.
4. Build the `risk_events` table and the per-asset 2.5σ stop the spec already
   promises.
5. Load-test the risk/ops layer at N≫20 and fix the O(N²) pre-trade gross check
   and the min-watermark universe stall before the equities sleeve goes live.
