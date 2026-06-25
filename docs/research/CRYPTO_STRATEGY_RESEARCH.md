# AlphaForge — Crypto Strategy Research Log (Fronts A / B / C)

Measurement experiments **outside** the equities A-grade campaign (that lives in
`docs/design/PRE_REGISTRATION.md`, N=9 Sharadar budget). These crypto fronts each write to
their **own** ledger under `artifacts/exp*/…` and do **not** spend the equity deploy budget.
Every number below is read from a real artifact on disk; nothing is hand-entered. Nulls are
published as a feature, never buried — that is the firm's soul.

The three fronts the owner chose (explicitly NOT managed-futures): **(A) crypto vol / VRP
(Deribit), (B) macro / cross-asset trend (ETF), (C) mine the existing markets harder.**

---

## Front A.1 — Crypto VRP (variance-risk-premium) timing — **PUBLISHED NULL**

**Script:** `scripts/exp2_crypto_vrp.py` · **Artifact:** `artifacts/exp2/20260625T094710Z/exp2_metrics.json`
**Data:** Deribit DVOL implied-vol index (BTC+ETH, 46,066 hourly rows each, 2021-03-24…2026-06,
backfilled by `scripts/dvol_backfill.py`) vs Yang-Zhang realized vol on the Binance perps.

**Pre-registered design (no knob search):** per currency, daily
`VRP = DVOL − RV_fcst(YZ, 7d, annualized)`; variance-swap proxy P&L
`g = DVOL²/365 − r²`; long-only short-vol size `s = max(0, VRP − 0.02)` (NEVER inverted);
10 bps cost on `|Δs|`; equal-weight BTC+ETH; expanding-window OOS after a 365-day warmup
(the signal has no fit parameters — the only PIT-fit object is the vol-normalizer);
deflated Sharpe vs the global trial budget (N=84). 1,492 OOS days.

**Result — fails decisively:**

| metric | value | reading |
|---|---:|---|
| net Sharpe (OOS, net of 10bps) | **−0.633** | timed short-vol *loses* money out-of-sample |
| deflated Sharpe | **0.0** | fails the deflation gate completely |
| PSR | 0.066 | — |
| **skew** | **−9.52** | catastrophic left tail — the short-vol crash signature |
| **kurtosis (raw)** | **132.7** | (normal = 3) — extreme fat tails |

**The boring-true-fact diagnostics (why it's null, not whether):**

| | mean VRP (vol pts) | % days VRP>0 | naive always-short Sharpe | naive always-short skew |
|---|---:|---:|---:|---:|
| BTC | +0.044 | 73% | **2.48** | **−5.49** |
| ETH | −0.001 | 65% | 0.53 | **−10.68** |

The premium is **real** (BTC implied exceeds realized by ~4.4 vol points, 73% of days).
Selling variance every day looks *seductive* — a 2.48 BTC Sharpe. **That number is a lie:**
its skew is −5.5 (BTC) / −10.7 (ETH). It picks up pennies in front of a steamroller. The
moment you time it with the VRP signal, pay a realistic 10 bps, and take it out-of-sample,
the net Sharpe goes **negative** and the skew stays catastrophic. Timing does not rescue it.

**Verdict:** PUBLISH THE NULL. No deploy slot spent. This is precisely the sleeve a naive
shop deploys and blows up on in the next crash; our DSR + skew gate rejected it on sight.
*Caveat already baked in:* this is the DVOL **proxy** (no historical options surface), which
if anything **understates** gap losses and **overstates** the premium (7d RV vs 30d implied) —
so the real, deployable version is *worse*, never better. `scripts/deribit_capture.py` is
accruing the true ATM surface forward (daily, since 2026-06-25) for an eventual surface-based
re-test once enough live sample exists.

---

## Front A.2 — Crypto MOMENTUM vs CARRY decorrelation — **RUNNING**

**Script:** `scripts/exp1_crypto_decorr.py` (committed f2f46d3) · **Artifact:** `artifacts/exp1/20260625T075446Z/`
Full purged walk-forward 2021-01-01…2026-06-01 (spans LUNA + FTX for honest stress
correlation), zero new data/factors. Decision rule pre-committed: spend a deploy slot ONLY
if carry/momentum corr < 0.3 calm AND not blowing out in stress AND momentum's standalone
DSR is non-trivially positive — else publish the null. Result pending (see exp1_metrics.json).

---

## Front B — ETF cross-asset / macro trend — **BLOCKED (data investment)**

Needs SHARADAR **SFP** price bars (Nasdaq Data Link bulk export); only the TICKERS metadata
(7,348 ETFs) is on disk. Also needs a custom TSMOM builder (the SignalService blend's
cross-sectional z-score destroys the absolute-trend sign a trend sleeve requires). Owner
action required: download SHARADAR/SFP.

---

## Front C — Maker / post-only execution recovery — **SCREENED → GREENLIT (conditional)**

**Screen:** `scripts/exp3_maker_exec_screen.py` · **Artifact:** `artifacts/exp3/20260625T095522Z/exp3_metrics.json`
**Non-invasive** — touches nothing in the engine, fill model, or golden master. Reads the live
carry sleeve's real WF (`L7_carry_cap_1M`: turnover_ann **33.2×**, vol_ann **11.9%**, Sharpe
**0.522**) and the **committed** fee schedule (maker 2 / taker 5 bps) + deployed half-spread
(2.5 bps). Edge **if a post-only order fills** = (5−2) fee delta + 2.5 spread avoided = **5.5
bps/side**. Models non-fill honestly: unfilled orders chase at taker + an adverse-selection
penalty `a`; `E[saving] = p·5.5 − (1−p)·a` per side, × 33.2 turnover ÷ 11.9% vol = Sharpe uplift.

| scenario | Sharpe uplift | carry Sharpe → |
|---|---:|---:|
| central (60% fill, 5bps adverse sel) | **+0.036** | 0.522 → 0.558 |
| good fills (80% fill, 4bps) | +0.10 | → 0.62 |
| optimistic ceiling (100% fill, 0 chase) | +0.153 | → 0.675 |

**Break-even fill rate:** 27% @2bps adverse sel · 42% @4bps · 52% @6bps · 59% @8bps.

**Verdict — worth building, conditionally.** EV is solidly positive across the realistic
fill range and the break-even is modest. Carry is a *patient* signal (rebalances aren't urgent
→ passive fills on liquid BTC/ETH perps should clear break-even comfortably). BUT the lever is
large (ceiling +0.15), so it MUST ship with **live maker-fill-rate logging** and conservative
non-fill modeling — never an assumed-fill advantage baked into a backtest (that manufactures
fake alpha).

### Engine built — `MakerFill` (opt-in; golden master byte-identical) — commit `63c3b56`

Per the owner's call (build it without re-blessing the golden master): `MakerFill` is a **new,
opt-in** fill model in `backtest/fills.py`. The engine still defaults to `NextOpenFill`, so the
deployed path and the crypto golden master are **provably unchanged** —
`tests/integration/test_golden_master.py` passes byte-identical (3/3). `WalkForwardRunner` gains
an opt-in `fill_model_factory` kwarg (`None` → taker, byte-identical); research injects MakerFill.

- **Passive fill** at the open (MAKER fee, no half-spread) using the **conservative
  close-direction rule** — BUY fills iff `close < open`, SELL iff `close > open` (~50% fill
  rate, a deliberate *lower bound*; NOT `low < open`, which is ~95% and would manufacture fake
  alpha). **Non-fill → chase** as TAKER at the full cost-model price + an explicit
  `adverse_selection_bps` penalty (default 5). Net per side reduces to the screen's formula
  `p·(fee+spread) − (1−p)·adverse_selection`, with `p` now empirical.
- 11 unit tests (passive fill both sides, taker chase + adverse selection, zero-adv == pure
  taker, lookahead guard, input validation); mypy --strict clean.

**`exp4_maker_exec_backtest.py`** (running) reports the engine-measured net-Sharpe uplift +
the **realized** maker fill rate (off the fills log) for the carry sleeve, taker vs MakerFill.
Next: ship the maker path **live iff** paper post-only fill logs beat break-even at the measured
adverse selection; the deployed-path flip remains a later, separate decision.
