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

## Front C — Maker / post-only execution recovery — **PLANNED**

The single highest-EV *free* lever for the live crypto carry sleeve (est. +0.02–0.05 Sharpe):
model passive maker fills instead of taker. Requires `MakerFill` in `backtest/fills.py` + a
`fill_model_factory` param on `WalkForwardRunner` + execution-config gating, AND a **conscious,
logged golden-master re-bless** — the crypto golden master (`tests/integration/test_golden_master.py`)
must never break silently; any cost-model change is a deliberate, recorded re-baseline with
conservative non-fill modeling. Higher-risk engine surgery; sequenced after Front A.
