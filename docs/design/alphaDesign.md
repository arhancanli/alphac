# AlphaForge — Alpha Factors & Machine Learning: Detailed Design

Scope: everything from point-in-time feature computation through labeled datasets, LightGBM modeling, validation statistics, regime detection, and the final per-asset expected-return vector handed to portfolio construction. Crypto-first (Binance spot + USDT-M perps via ccxt), asset-class-agnostic interfaces. Primary bars: 1h UTC; 4h/1d aggregates derived from 1h.

Conventions used throughout:
- All timestamps are UTC, `datetime64[ns, UTC]`. A bar stamped `ts` covers `[ts, ts+1h)`; its OHLCV is **known only at `ts+1h`** (bar close). All factors at decision time `t` use data through the close of the bar that ENDS at `t`.
- Signals computed at bar close `t`; entry price for labels/execution is the **open of the next bar**, `O_{t+1bar}`.
- Returns are log returns unless stated: `r_t = ln(C_t / C_{t-1})`.
- "Bars" = 1h bars. Calendar conversions: 1d = 24 bars, 7d = 168, 30d = 720, 90d = 2160, 365d = 8760 (crypto trades 24/7 — no trading-calendar logic needed in v1, but window lengths are expressed in bars so equities can later supply their own bars-per-day constant via the Instrument abstraction).

---

## 1. Package layout

```
alphaforge/
├── features/
│   ├── __init__.py
│   ├── base.py              # Factor protocol, FactorMeta dataclass, decorator
│   ├── registry.py          # FactorRegistry: name → (fn, meta), versioned
│   ├── cross_section.py     # winsorize_mad, cs_zscore, cs_rank, neutralize, CSPipeline
│   ├── vol.py               # yang_zhang, parkinson, ewma_vol, realized_vol
│   ├── momentum.py          # xs_momentum, ts_momentum
│   ├── mean_reversion.py    # residual_reversal (beta-residual z-scored)
│   ├── carry.py             # funding_carry (annualized), funding loading utils
│   ├── liquidity.py         # amihud_illiq, volume_zscore, corwin_schultz_spread
│   ├── regime_features.py   # rv_percentile, btc_correlation, market_breadth
│   └── pipeline.py          # FeaturePipeline: raw panel → processed factor panel + parquet
├── labeling/
│   ├── __init__.py
│   ├── forward_returns.py   # execution-aware forward returns, vol-scaled
│   ├── triple_barrier.py    # get_events / apply_barriers (numba-accelerated loop)
│   ├── meta.py              # meta-labels from primary side, bet sizing from P(win)
│   └── weights.py           # concurrency, average uniqueness, time-decay weights
├── ml/
│   ├── __init__.py
│   ├── datasets.py          # MLDataset: align X, y, w, t1, side; train matrices
│   ├── model.py             # AlphaLGBM wrapper, DEFAULT_PARAMS, calibration
│   ├── train.py             # WalkForwardTrainer (purged), early stopping protocol
│   ├── importance.py        # MDA (cluster-permutation), SHAP report
│   ├── registry.py          # ModelRegistry (SQLite + artifact dir), ModelCard
│   └── retrain.py           # weekly retrain job, champion/challenger promotion
├── validation/
│   ├── __init__.py
│   ├── splits.py            # PurgedWalkForward, CombinatorialPurgedCV (CPCV)
│   ├── metrics.py           # ic, rank_ic, ic_ir, hit_rate, newey_west_tstat
│   ├── pbo.py               # CSCV → Probability of Backtest Overfitting
│   └── dsr.py               # probabilistic & deflated Sharpe ratio
├── regime/
│   ├── __init__.py
│   └── hmm.py               # RegimeHMM: fit, FILTERED probs, state relabeling, gating
└── signals/
    ├── __init__.py
    ├── blending.py          # ICWeightedBlender (EWMA Rank-IC weights)
    ├── sizing.py            # bet_size_from_prob, grinold_mu
    └── service.py           # SignalService: on bar close → mu vector for portfolio
```

(Dependencies assumed from other areas: `alphaforge.data` provides the OHLCV + funding panels with the schema in §4.1; `alphaforge.core` provides `Instrument`, bar-period constants, and config.)

---

## 2. Factor library

### 2.1 Factor abstraction and registry (`features/base.py`, `features/registry.py`)

```python
@dataclass(frozen=True)
class FactorMeta:
    """Immutable metadata describing a factor's identity and data requirements."""
    name: str                  # canonical id, e.g. "mom_xs_504_48"
    family: str                # "momentum" | "reversal" | "carry" | "vol" | "liquidity" | "regime"
    direction: int             # +1: higher value => higher expected return; 0: risk/regime feature
    lookback_bars: int         # max bars of history consumed (drives warm-up & PIT tests)
    inputs: tuple[str, ...]    # subset of {"open","high","low","close","volume","quote_volume","funding"}
    cross_sectional: bool      # True if value only meaningful relative to universe
    version: str = "1.0.0"

class Factor(Protocol):
    def __call__(self, panel: pd.DataFrame) -> pd.Series:
        """Compute factor from a point-in-time panel; returns Series indexed by (ts, symbol).

        `panel` is the long-format OHLCV(+funding) frame of §4.1, containing ONLY bars
        with close time <= decision time. Must be a pure function: no I/O, no state.
        """

class FactorRegistry:
    def register(self, meta: FactorMeta) -> Callable[[Factor], Factor]:
        """Decorator: registers fn under meta.name; raises on duplicate name."""
    def get(self, name: str) -> tuple[Factor, FactorMeta]: ...
    def compute_all(self, panel: pd.DataFrame, names: list[str] | None = None) -> pd.DataFrame:
        """Compute factors into a wide frame indexed by (ts, symbol); columns = factor names."""
```

Every factor below is registered via `@registry.register(FactorMeta(...))`. The `lookback_bars` field is load-bearing: the automated point-in-time test (§7, safeguard 1) truncates the panel and asserts factor values are unchanged, and the live `SignalService` uses `max(lookback_bars)` to size its rolling buffer.

### 2.2 Volatility estimators (`features/vol.py`) — built first; labeling depends on them

**EWMA volatility (the workhorse σ̂ used by labels, TS-momentum, sizing).** Per-bar log returns `r_t`; span `S = 168` bars (7d — long enough to be stable, short enough to track crypto vol regime shifts):

```
λ = 2/(S+1)
σ̂²_t = λ · r_t² + (1−λ) · σ̂²_{t−1}        (zero-mean assumption, standard for hourly)
σ̂_t = sqrt(σ̂²_t)                          # per-bar (1h) vol
```

```python
def ewma_vol(close: pd.Series, span: int = 168) -> pd.Series:
    """Per-bar EWMA volatility of log returns; zero-mean; min_periods = span."""
```

**Parkinson (1980).** Window `n = 168` bars. Per-bar variance:

```
σ²_P = (1 / (4·n·ln 2)) · Σ_{t=1..n} [ln(H_t / L_t)]²
```

Annualized vol = `sqrt(σ²_P · 8760)`. ~5x more efficient than close-close under GBM; biased low when there are gaps (rare in 24/7 crypto, relevant later for equities — which is why Yang-Zhang is also included).

**Yang-Zhang (2000).** Window `n = 168` bars (also registered at n = 720). Define for each bar:

```
o_t = ln(O_t / C_{t−1})        # gap return
c_t = ln(C_t / O_t)            # open-to-close
u_t = ln(H_t / O_t),  d_t = ln(L_t / O_t)

σ²_o  = (1/(n−1)) Σ (o_t − ō)²
σ²_c  = (1/(n−1)) Σ (c_t − c̄)²
σ²_RS = (1/n) Σ [ u_t·(u_t − c_t) + d_t·(d_t − c_t) ]      # Rogers–Satchell
k     = 0.34 / (1.34 + (n+1)/(n−1))
σ²_YZ = σ²_o + k·σ²_c + (1−k)·σ²_RS
```

`σ_YZ` per-bar = sqrt(σ²_YZ); annualized = × sqrt(8760). Drift-independent and gap-robust — the default for any factor needing OHLC vol.

```python
def yang_zhang(ohlc: pd.DataFrame, window: int = 168, annualize: bool = False) -> pd.Series: ...
def parkinson(high: pd.Series, low: pd.Series, window: int = 168, annualize: bool = False) -> pd.Series: ...
```

Registered factors: `vol_yz_168`, `vol_yz_720`, `vol_pk_168` (direction 0 — features, not alphas), plus `vol_ratio_168_720 = σ_YZ(168)/σ_YZ(720)` (vol-of-vol regime proxy).

### 2.3 Momentum (`features/momentum.py`)

**Cross-sectional momentum with skip period.** For lookback `L` bars and skip `S` bars:

```
MOM_{L,S}(i,t) = ln( C_{i, t−S} / C_{i, t−L} )
```

The skip removes the short-horizon reversal that contaminates raw momentum. Registered variants (defaults chosen to span the canonical 1-week / 1-month / 3-month horizons documented in crypto momentum literature; the 21d-skip-2d is the spec's anchor):

| name | L (bars) | S (bars) | calendar |
|---|---|---|---|
| `mom_xs_168_24` | 168 | 24 | 7d skip 1d |
| `mom_xs_504_48` | 504 | 48 | 21d skip 2d |
| `mom_xs_2160_168`| 2160 | 168 | 90d skip 7d |

These are tagged `cross_sectional=True`; raw values pass through the CS pipeline (§3) before use.

**Time-series momentum (vol-normalized).** For lookback `L`:

```
TSMOM_L(i,t) = ln( C_{i,t} / C_{i,t−L} ) / ( σ̂_{i,t} · sqrt(L) )
```

with `σ̂` = `ewma_vol(span=168)`. The denominator is the L-bar vol forecast, so the statistic is approximately a t-stat of the trend; values are comparable across assets and time. Registered: `mom_ts_168`, `mom_ts_504`, `mom_ts_2160` (same L set, no skip — TS momentum conventionally uses the full window).

```python
def xs_momentum(close: pd.Series, lookback: int, skip: int) -> pd.Series:
    """ln(C[t-skip]/C[t-lookback]) per symbol; NaN until lookback bars exist."""
def ts_momentum(close: pd.Series, lookback: int, vol: pd.Series) -> pd.Series:
    """Vol-normalized L-bar log return: trend t-statistic."""
```

### 2.4 Short-term mean reversion (`features/mean_reversion.py`)

Reversal on **beta-residual** returns so we don't fade the market itself.

1. Market return: `m_t = (1/N_t) Σ_{i ∈ U_t} r_{i,t}` (equal-weight over the point-in-time universe `U_t`; equal-weight because free data gives no clean float-cap, and EW is the standard crypto "market" proxy after BTC).
2. Rolling beta, window `W_β = 720` bars (30d):
   `β_{i,t} = Cov_{720}(r_i, m) / Var_{720}(m)`
3. Residual return: `ε_{i,t} = r_{i,t} − β_{i,t} · m_t` (use β from `t−1` info — computed on returns through `t`, which is fine since `r_t` itself is known at `t`; to be strictly conservative β uses window ending `t−1`).
4. Reversal factor over horizon `W`:

```
MR_W(i,t) = − Σ_{k=0}^{W−1} ε_{i,t−k} / ( σ_{ε,i,t} · sqrt(W) )
```

where `σ_{ε,i,t}` = EWMA vol (span 168) of `ε_i`. Negative sign so **higher factor ⇒ recent residual loser ⇒ expected to outperform**. Registered: `mr_res_24` (1d) and `mr_res_72` (3d) — both inside the well-documented short-horizon reversal zone; 24 is primary.

```python
def residual_reversal(returns: pd.DataFrame, mkt: pd.Series, window: int = 24,
                      beta_window: int = 720, vol_span: int = 168) -> pd.DataFrame:
    """−(cum residual return)/(residual vol·√W): z-scored reversal vs EW market."""
```

### 2.5 Carry (`features/carry.py`)

**Sign convention (explicit).** Binance USDT-M funding settles every 8h (00:00/08:00/16:00 UTC). When funding rate `f > 0`, **longs pay shorts**. Therefore the carry earned by a LONG perp position per settlement is `−f`. The factor is defined so that **positive value = positive expected carry for a long position**:

```
CARRY(i,t) = − f̄_{i,t} · 3 · 365
f̄_{i,t}   = (1/K) Σ_{j=1..K} f_{i, τ_j}     over the last K = 21 settlements (7 days)
```

`× 3 × 365` annualizes (3 settlements/day). Funding ≈ the annualized perp–spot basis (perp premium ⇒ positive funding ⇒ negative carry for longs ⇒ shorts get paid), so this is the crypto analogue of FX/futures carry. Registered: `carry_fund_21` (7d mean, primary) and `carry_fund_90` (30d mean, slow).

**Point-in-time rule:** funding rate `f_{τ_j}` enters the factor only for `τ_j ≤ t` (settlement already occurred). Join is a backward as-of merge on settlement timestamp (§7 safeguard 3). Spot symbols get NaN for carry; the CS pipeline mean-imputes 0 *after* z-scoring (i.e., neutral exposure).

```python
def funding_carry(funding: pd.DataFrame, n_settlements: int = 21) -> pd.DataFrame:
    """Annualized long-carry from trailing funding: −mean(f)·3·365, as-of joined to 1h grid."""
```

### 2.6 Liquidity & microstructure proxies (`features/liquidity.py`)

**Amihud illiquidity (2002).** Window `n = 720` bars, using quote (USDT) volume `QV`:

```
ILLIQ(i,t) = (1/n) Σ_{k=0}^{n−1} |r_{i,t−k}| / QV_{i,t−k}        (bars with QV=0 skipped)
factor value = ln( ILLIQ + 1e−12 )                                 (log for scale stability)
```

Direction as an alpha is + (illiquidity premium), but in v1 it is registered `direction=0` and used as a **risk feature and universe filter** (the premium is unreliable at hours-to-days horizons and conflicts with tradability).

**Volume z-score (abnormal volume).** Window `n = 720`:

```
VZ(i,t) = ( ln(1+QV_{i,t}) − μ_{i,t} ) / s_{i,t}
```

with `μ, s` = rolling mean/std of `ln(1+QV)` over the window. Log first — raw crypto volume is wildly heavy-tailed. Registered: `liq_volz_720`; also `liq_volz_24h_sum` using rolling 24-bar volume sums to suppress intraday seasonality.

**Corwin–Schultz spread estimator (2012).** From two consecutive bars (we apply it to 1h bars as a proxy; CS derived it for daily bars — fine for ranking, do not interpret as an absolute spread):

```
β_t = [ln(H_{t−1}/L_{t−1})]² + [ln(H_t/L_t)]²
γ_t = [ln( max(H_{t−1},H_t) / min(L_{t−1},L_t) )]²
α_t = (√(2β_t) − √β_t) / (3 − 2√2)  −  √( γ_t / (3 − 2√2) )      # 3−2√2 ≈ 0.171573
S_t = 2(e^{α_t} − 1) / (1 + e^{α_t})
S_t ← max(S_t, 0)                                                  # standard negative-spread floor
CS_SPREAD(i,t) = (1/168) Σ_{k=0}^{167} S_{t−k}                     # 7d mean
```

Registered: `liq_cs_spread_168`, `direction=0` (transaction-cost/risk feature; also exported to the execution-cost model).

```python
def amihud_illiq(returns: pd.Series, quote_volume: pd.Series, window: int = 720) -> pd.Series: ...
def volume_zscore(quote_volume: pd.Series, window: int = 720) -> pd.Series: ...
def corwin_schultz_spread(high: pd.Series, low: pd.Series, smooth: int = 168) -> pd.Series: ...
```

### 2.7 Regime features (`features/regime_features.py`)

These are time-series features broadcast to all symbols (constant across the cross-section at each `t`) plus one per-symbol feature. They feed the ML feature matrix AND the HMM observation builder.

**Realized vol percentile.** Market = BTC/USDT spot. With `σ_t` = annualized `yang_zhang(window=720)` of BTC:

```
RVP_t = (1/N) Σ_{k=0}^{N−1} 1{ σ_{t−k} ≤ σ_t },   N = 8760  (1y trailing)
```

**BTC correlation (per symbol).** Rolling Pearson correlation of hourly log returns vs BTC, window 720 bars: `CORR_BTC(i,t) = corr_{720}(r_i, r_BTC)`. BTC itself gets 1.0.

**Market breadth.** Over point-in-time universe `U_t`:

```
BREADTH_SMA_t  = (1/|U_t|) Σ_{i∈U_t} 1{ C_{i,t} > SMA_{720}(C_i)_t }
BREADTH_MOM_t  = (1/|U_t|) Σ_{i∈U_t} 1{ ln(C_{i,t}/C_{i,t−168}) > 0 }
```

Registered: `reg_rvp_720`, `reg_corr_btc_720`, `reg_breadth_sma720`, `reg_breadth_mom168` — all `direction=0`, `cross_sectional=False` (excluded from CS z-scoring; fed raw to ML and as interaction context).

---

## 3. Cross-sectional processing (`features/cross_section.py`)

Applied per timestamp `t`, only over the point-in-time universe mask `U_t` (membership comes from the data module's universe snapshots — never today's listing set applied historically). Crypto v1 universe ≈ 30–80 names, so quantile winsorization is noisy; MAD clipping is the default.

**Winsorize (MAD clip).** Per timestamp:

```
med = median_i(x_i);   MAD = median_i(|x_i − med|)
x̃_i = clip( x_i,  med − c·1.4826·MAD,  med + c·1.4826·MAD ),   c = 3.0
```

(1.4826 makes MAD a consistent σ estimator under normality; c=3 ≈ 3σ clip.) Fallback to quantile clip at (1%, 99%) when MAD = 0 (degenerate cross-sections).

**Z-score.** `z_i = (x̃_i − mean_i(x̃)) / std_i(x̃)` (ddof=1); if `std == 0` or `|U_t| < 5`, emit NaN for the whole timestamp (too few names for a meaningful cross-section).

**Rank transform.** `u_i = (rank_i − 0.5)/N` (average ranks for ties), mapped to `[−1, 1]` via `2u_i − 1`; optional Gaussianization `Φ⁻¹(u_i)`. Default for ML features: rank-to-[−1,1] (bounded, outlier-proof — preferred for tree models’ split stability across regimes).

**Neutralization.** OLS residualization against exposure matrix `X_t` (columns: intercept, market beta `β_{i,t}` from §2.4; later: sector/size dummies):

```
f_neut = f − X_t (X_tᵀ X_t)⁻¹ X_tᵀ f
```

Default ON for momentum and reversal families (removes the "everything is a BTC beta bet" degeneracy), OFF for carry and vol (their beta loading is part of the signal).

```python
def winsorize_mad(x: pd.Series, c: float = 3.0) -> pd.Series: ...
def cs_zscore(x: pd.Series, min_names: int = 5) -> pd.Series: ...
def cs_rank(x: pd.Series, gaussianize: bool = False) -> pd.Series: ...
def neutralize(f: pd.Series, exposures: pd.DataFrame) -> pd.Series: ...

@dataclass
class CSPipeline:
    """Per-timestamp chain: winsorize → (neutralize) → zscore or rank; universe-masked."""
    steps: tuple[str, ...] = ("winsorize", "neutralize", "zscore")
    def apply(self, factor: pd.Series, universe: pd.Series, exposures: pd.DataFrame | None) -> pd.Series: ...
```

`FeaturePipeline` (in `features/pipeline.py`) runs: load panel → compute raw factors via registry → apply each factor's configured CSPipeline → write the processed wide panel to parquet (schema §4.2). Both raw and processed values are persisted (raw needed for PIT audits).

---

## 4. Data schemas (persisted as Parquet via pyarrow, snappy compression, partitioned by month)

### 4.1 Input panel (owned by data module; stated here as the contract)

Long format, sorted by (`symbol`, `ts`):

| column | dtype | notes |
|---|---|---|
| ts | datetime64[ns, UTC] | bar START; data known at ts+1h |
| symbol | string (dict-encoded) | e.g. `BINANCE:BTC/USDT`, `BINANCE:BTC/USDT:USDT` (perp, ccxt style) |
| open, high, low, close | float64 | quote currency (USDT) |
| volume | float64 | base volume |
| quote_volume | float64 | USDT volume |
| in_universe | bool | point-in-time membership flag |

Funding table: `ts` (settlement time, UTC), `symbol`, `funding_rate` float64 (raw per-8h rate, e.g. 0.0001 = 1bp).

### 4.2 Feature panel `features/факт…` → `data/features/*.parquet`

| column | dtype |
|---|---|
| ts | datetime64[ns, UTC] |
| symbol | string |
| `<factor_name>_raw` | float64 |
| `<factor_name>` | float64 (post-CS-pipeline; what ML consumes) |

Plus a sidecar `feature_manifest.json`: factor names, FactorMeta fields, pipeline steps, code version hash — written every run for reproducibility.

### 4.3 Labels `data/labels/*.parquet`

| column | dtype | notes |
|---|---|---|
| ts | datetime64[ns, UTC] | decision bar close |
| symbol | string | |
| entry_ts | datetime64[ns, UTC] | = ts + 1 bar |
| entry_price | float64 | O at entry_ts |
| t1 | datetime64[ns, UTC] | event end (barrier touch or vertical) — REQUIRED by purging |
| exit_price | float64 | |
| ret | float64 | ln(exit/entry) |
| label_tb | int8 | −1 / 0 / +1 first-touch label |
| touch | int8 | 1=PT, −1=SL, 0=vertical |
| side | int8 | primary signal side (meta-labeling) |
| meta_label | int8 | 1 if side·ret > 0 else 0 |
| vol_at_entry | float64 | σ̂ per-bar at ts |
| sample_weight | float64 | uniqueness × time-decay, normalized |
| fwd_ret_24, fwd_ret_72, fwd_ret_168 | float64 | execution-aware forward log returns |
| fwd_ret_72_vs | float64 | vol-scaled (regression target) |

### 4.4 Predictions `data/predictions/*.parquet`

`ts`, `symbol`, `model_id` (string), `p_meta` float64, `side` int8, `alpha_blend` float64, `signal` float64, `mu` float64 (expected return over horizon), `gross_mult` float64 (HMM gate), `created_at` datetime64 — append-only; the live loop and backtester both write here, enabling live-vs-backtest reconciliation.

### 4.5 Model registry (SQLite `models/registry.db` + artifact dir `models/artifacts/<model_id>/`)

Table `models`: `model_id` (str, e.g. `lgbm_meta_2026-06-07_a1b2c3`), `trained_at`, `train_start`, `train_end`, `n_samples`, `params_json`, `feature_list_json`, `val_logloss`, `val_auc`, `val_rank_ic`, `code_git_sha`, `data_hash` (sha256 of training parquet), `status` (`candidate`/`champion`/`retired`). Artifacts: `model.txt` (LightGBM native), `calibrator.pkl`, `shap_summary.parquet`.

---

## 5. Labeling (`alphaforge/labeling/`)

### 5.1 Execution-aware forward returns (`forward_returns.py`)

For horizon `h` bars (h ∈ {24, 72, 168}):

```
y_{i,t,h} = ln( O_{i, t+1+h} / O_{i, t+1} )
```

Entry and exit at next-bar opens — exactly matches the "compute at close, execute next bar" execution contract; using `C_t` as entry is the classic lookahead bug and is banned. Vol-scaled regression target:

```
ỹ_{i,t,h} = y_{i,t,h} / ( σ̂_{i,t} · sqrt(h) )
```

```python
def forward_returns(panel: pd.DataFrame, horizons: tuple[int, ...] = (24, 72, 168)) -> pd.DataFrame:
    """Execution-aware forward log returns: open(t+1) → open(t+1+h)."""
```

### 5.2 Triple-barrier method (`triple_barrier.py`) — exact algorithm

Parameters (defaults): vertical barrier `H = 72` bars (3 days — center of the hours-to-days mandate); barrier multiples `m_pt = 1.0`, `m_sl = 1.0` (symmetric; with barriers set at 1× the H-horizon vol, roughly half of events touch a horizontal barrier under a diffusive null — informative labels without degenerating into all-vertical or all-touch); vol = `ewma_vol(span=168)`.

For each event (i, t) with side `s ∈ {−1,+1}` (s=+1 for the side-less primary model run):

```
p0 = O_{i, t+1}
w  = σ̂_{i,t} · sqrt(H)                       # H-bar vol forecast (log-return units)
up = p0 · exp( + m_pt · w )   if s=+1, else p0 · exp( + m_sl · w )
dn = p0 · exp( − m_sl · w )   if s=+1, else p0 · exp( − m_pt · w )
   # i.e. profit-take is in the direction of `side`; for s=−1 the PT barrier is BELOW entry

for k = 1 .. H:                               # bars t+1 .. t+H, inclusive
    hit_up = H_{i,t+k} ≥ up
    hit_dn = L_{i,t+k} ≤ dn
    if hit_up and hit_dn:                     # both inside one bar — path unknown
        → CONSERVATIVE RULE: treat as STOP first (the adverse barrier for `side`)
          label_tb = −s; exit_price = (dn if s=+1 else up); t1 = ts(t+k); break
    elif hit_up: label_tb = +1·sign_at_up; exit_price = up; t1 = ts(t+k); break
    elif hit_dn: label_tb = −1·...;        exit_price = dn; t1 = ts(t+k); break
if no touch:
    t1 = ts(t+H); exit_price = C_{i,t+H}
    ret = ln(exit_price / p0)
    label_tb = sign(ret)                      # LdP option: sign at vertical (default)
                                              # config: zero_band — label 0 if |ret| < 0.25·w
ret = ln(exit_price / p0)
```

Exit prices at the barrier level itself (not the bar close) — assumes a resting limit/stop fill at the barrier; the backtester applies slippage on top. The conservative both-touched rule biases AGAINST the strategy, never for it.

```python
@dataclass(frozen=True)
class TripleBarrierConfig:
    horizon_bars: int = 72
    pt_mult: float = 1.0
    sl_mult: float = 1.0
    vol_span: int = 168
    vertical_zero_band: float = 0.0   # in units of w; 0 disables 0-labels at vertical

def apply_triple_barrier(panel: pd.DataFrame, events: pd.DataFrame,
                         cfg: TripleBarrierConfig) -> pd.DataFrame:
    """events: (ts, symbol, side). Returns label frame of §4.3. Inner loop in numba njit."""
```

### 5.3 Meta-labeling and bet sizing (`meta.py`)

Primary model: the **blended raw-alpha signal** (§9.1) provides the side: `s_{i,t} = sign(A_{i,t})`, with a dead zone — no event generated when `|A_{i,t}| < 0.25` (z-score units; avoids labeling noise trades). Triple barrier is applied with that side. Meta-label:

```
y_meta = 1{ s · ret > 0 }     ∈ {0, 1}
```

The ML classifier estimates `p = P(y_meta = 1 | X)`. Bet size (López de Prado, AFML ch.10):

```
z = (p − 0.5) / sqrt( p·(1 − p) )
size = s · ( 2·Φ(z) − 1 )            ∈ [−1, 1]
```

with `size = 0` enforced when `p < p_min = 0.50` (never trade against the classifier). Discretize to step 0.05 to suppress churn.

```python
def make_meta_labels(labels: pd.DataFrame) -> pd.Series:
    """1 if side·ret > 0 else 0."""
def bet_size_from_prob(p: pd.Series, side: pd.Series, p_min: float = 0.5, step: float = 0.05) -> pd.Series:
    """LdP bet size: side·(2Φ((p−.5)/√(p(1−p)))−1), floored at p_min, discretized."""
```

### 5.4 Sample weights by uniqueness (`weights.py`) — exact formulas

Events overlap (a new event every bar, each spanning up to 72 bars), so observations are heavily redundant. Per symbol (concurrency is computed within symbol; cross-symbol commonality is handled by CV purging, not weights):

1. **Concurrency** at bar t: `c_t = Σ_i 1{ t ∈ [entry_ts_i, t1_i] }`
2. **Average uniqueness** of event i spanning `n_i` bars:

```
ū_i = (1/n_i) · Σ_{t = entry_ts_i}^{t1_i} 1 / c_t
```

3. **Return-attribution weight** (default ON — weights events by the absolute return uniquely attributable to them):

```
w̃_i = | Σ_{t = entry_ts_i}^{t1_i} r_t / c_t |
w_i  = w̃_i · N / Σ_j w̃_j                      # normalize to mean 1
```

4. **Time decay** (optional, default ON): with cumulative-uniqueness clock `x_i ∈ [0,1]` (oldest→newest) and decay floor `d = 0.75`: `w_i ← w_i · (d + (1−d)·x_i)` — newest events weighted 1.0, oldest 0.75. Mild, because crypto regimes drift.

Final `sample_weight = w_i` is persisted in §4.3 and passed to LightGBM. Mean uniqueness `ū` also sets `bagging_fraction` sanity (if ū ≈ 0.1, don't bag at 0.9).

```python
def concurrency(events: pd.DataFrame, bar_index: pd.DatetimeIndex) -> pd.Series: ...
def average_uniqueness(events: pd.DataFrame, conc: pd.Series) -> pd.Series: ...
def attribution_weights(events: pd.DataFrame, returns: pd.Series, conc: pd.Series,
                        time_decay: float = 0.75) -> pd.Series: ...
```

---

## 6. Model (`alphaforge/ml/`)

### 6.1 Primary formulation: **binary classification on the meta-label** — recommendation and rationale

Recommended primary: **LightGBM binary classifier on `y_meta`** (P(primary-side trade wins)). Rationale:
- Hourly-frequency forward returns have signal-to-noise so low that regression targets are dominated by tail noise; a bounded {0,1} target with a proper scoring rule (log loss) is far more robust, and barrier outcomes embed a realistic trade lifecycle (stop/target) instead of a fixed-horizon snapshot.
- Meta-labeling factorizes the problem: the **side** comes from interpretable, individually-validated raw alphas; ML only learns **when those alphas work** — strictly easier, less prone to inventing spurious directional structure, and yields a calibrated probability that maps directly to position size (§5.3).
- Calibration is checkable (reliability curves); a regression's μ is not.

Secondary (diagnostic, also implemented): LightGBM **regression with Huber loss (α=1.35) on `ỹ_{72}`** (vol-scaled forward return). Used for IC analysis, blending research, and as a challenger; not for live sizing in v1.

### 6.2 Hyperparameter defaults (`model.py`) — tuned for noisy financial panels

```python
DEFAULT_PARAMS: dict = {
    "objective": "binary",
    "boosting": "gbdt",
    "num_leaves": 15,             # shallow: ≈ depth-4 trees; financial S/N can't support more
    "max_depth": 4,               # hard cap, belt-and-braces with num_leaves
    "learning_rate": 0.03,        # slow; rely on early stopping
    "n_estimators": 2000,         # ceiling; early stopping picks the real number
    "min_child_samples": 200,     # large leaves: each leaf must be a statistical statement
    "feature_fraction": 0.6,      # decorrelate trees across correlated factors
    "bagging_fraction": 0.7,
    "bagging_freq": 1,
    "lambda_l1": 1.0,
    "lambda_l2": 5.0,             # heavy L2: shrink leaf values toward 0
    "min_split_gain": 0.01,
    "max_bin": 127,               # coarse bins resist micro-noise splits
    "extra_trees": False,
    "deterministic": True,
    "force_col_wise": True,       # deterministic + faster on M-series
    "seed": 42,
    "verbose": -1,
}
EARLY_STOPPING_ROUNDS = 100       # on purged-validation binary_logloss
```

Justifications: depth-4/15-leaf trees express up to 4-way interactions — already generous for alphas; `min_child_samples=200` ensures every split is estimated on ≥200 weighted events; LR 0.03 + early stopping on an **embargoed** validation tail (last 60d of the train window, purged from training per §8.1) controls the effective capacity adaptively per refit.

```python
class AlphaLGBM:
    """Thin LightGBM wrapper: fixed params, sample-weight aware, isotonic calibration."""
    def fit(self, X: pd.DataFrame, y: pd.Series, w: pd.Series, t1: pd.Series,
            val_frac: float = 0.15) -> "AlphaLGBM":
        """Fits with purged+embargoed tail validation for early stopping; then isotonic calibrator on val."""
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray: ...
    def save(self, path: Path) -> None: ...
    @classmethod
    def load(cls, path: Path) -> "AlphaLGBM": ...
```

Calibration: isotonic regression fit on the validation tail (sklearn `IsotonicRegression`, out-of-bounds clip). Bet sizing consumes calibrated p.

### 6.3 Feature importance (`importance.py`)

1. **Cluster features first**: hierarchical clustering (average linkage) on distance `d = 1 − |ρ_Spearman|`, cut at `d = 0.3` (|ρ| ≥ 0.7 ⇒ same cluster) — kills the substitution effect that makes per-feature permutation lie about correlated factors.
2. **MDA / cluster permutation importance**: for each purged CV fold, for each cluster `G`: shuffle all columns in `G` jointly within the validation fold (same permutation per column), importance = mean over folds of `(logloss_permuted − logloss_base)`; report mean ± std across folds; a cluster whose CI includes 0 is a removal candidate.
3. **SHAP** via `shap.TreeExplainer` (exact tree SHAP) on the validation set — direction and interaction diagnostics; summary persisted per model (§4.5).

```python
def cluster_features(X: pd.DataFrame, corr_threshold: float = 0.7) -> dict[str, list[str]]: ...
def mda_importance(model_factory: Callable[[], AlphaLGBM], X, y, w, t1,
                   splitter: "PurgedWalkForward", clusters: dict[str, list[str]],
                   n_repeats: int = 5, seed: int = 42) -> pd.DataFrame: ...
def shap_report(model: AlphaLGBM, X_val: pd.DataFrame) -> pd.DataFrame: ...
```

### 6.4 Live retraining cadence (`retrain.py`)

- **Weekly refit**, Sundays 00:30 UTC (after the 00:00 bar closes): train window = trailing **365 days** rolling; early-stopping validation = final 60d of the window, purged/embargoed; features and labels recomputed from canonical parquet.
- **Champion/challenger**: new model is promoted only if, on the shared validation tail, `logloss_new ≤ logloss_champion + 0.002` AND `rank_ic_new ≥ 0.8 × rank_ic_champion`. Otherwise the champion stays and an alert is logged. Prevents a bad data week from silently degrading live signals.
- Between refits the model is frozen; only features update bar-by-bar. Model ID is stamped on every prediction row (§4.4).

```python
def weekly_retrain(asof: pd.Timestamp, window_days: int = 365) -> ModelCard:
    """Build dataset → fit candidate → evaluate vs champion → promote or hold; returns card."""
```

---

## 7. Validation (`alphaforge/validation/`)

### 7.1 Purging and embargo — exact algorithm (`splits.py`)

Each sample i has an information interval `[t_i, t1_i]` (decision time to event end; both stored in §4.3). Given a test set spanning `[T_a, T_b]` (by decision time, but tests overlap into `[T_a, max t1 of test]`):

- **Purge**: drop train sample i if `[t_i, t1_i] ∩ [T_a, T1_b] ≠ ∅`, where `T1_b = max{t1_j : j ∈ test}` — i.e., any train event whose lifetime touches any test event's lifetime.
- **Embargo**: additionally drop train samples with `t_i ∈ (T1_b, T1_b + E]` for train data occurring *after* the test block (relevant in CPCV; in forward-chaining WF train precedes test so only purging binds). Default `E = 168` bars (7d) — > 2× the 72-bar max label horizon, with headroom for serial correlation in features.

```python
class PurgedWalkForward:
    """Forward-chaining splits with purging+embargo. n_splits=8, test_size=90d,
    expanding train with min 365d warm-up."""
    def __init__(self, n_splits: int = 8, test_bars: int = 2160,
                 min_train_bars: int = 8760, embargo_bars: int = 168): ...
    def split(self, t: pd.Series, t1: pd.Series) -> Iterator[tuple[np.ndarray, np.ndarray]]: ...

class CombinatorialPurgedCV:
    """CPCV: N=10 contiguous groups, k=2 test groups per split → C(10,2)=45 splits,
    yielding φ = k·C(N,k)/N = 9 full backtest paths."""
    def __init__(self, n_groups: int = 10, n_test_groups: int = 2, embargo_bars: int = 168): ...
    def split(self, t: pd.Series, t1: pd.Series) -> Iterator[tuple[np.ndarray, np.ndarray]]: ...
    def paths(self) -> list[list[tuple[int, int]]]:
        """Assignment of (split, group) pairs into 9 contiguous backtest paths."""
```

Research protocol: CPCV for model/feature selection statistics (gives 9 OOS paths → distribution of Sharpe/IC); purged walk-forward as the final, deployment-faithful evaluation.

### 7.2 IC metrics (`metrics.py`)

At each timestamp t, over universe `U_t`, against execution-aware forward return `y_{·,t,h}` (h = 72 default):

```
IC_t      = PearsonCorr_i( ŝ_{i,t}, y_{i,t,h} )
RankIC_t  = SpearmanCorr_i( ŝ_{i,t}, y_{i,t,h} )      # = Pearson on cross-sectional ranks
IC̄       = mean_t(IC_t);   IC-IR = IC̄ / std_t(IC_t)
Annualized ICIR = IC-IR · sqrt(8760 / h)               # sampled on a non-overlapping h-bar grid
```

Because h-bar labels overlap on a 1h grid, IC time series are computed on a **non-overlapping grid** (every h-th bar) for inference; the t-stat uses Newey–West HAC with lag = h when computed on the dense grid. RankIC is primary (robust to crypto tails).

```python
def ic_series(pred: pd.DataFrame, fwd: pd.DataFrame, method: Literal["pearson","spearman"] = "spearman",
              stride: int | None = None) -> pd.Series: ...
def newey_west_tstat(x: pd.Series, lags: int) -> float: ...
```

### 7.3 Probability of Backtest Overfitting — CSCV (`pbo.py`)

Input: matrix `M ∈ R^{T×N}` of period returns for N strategy variants (e.g., hyperparameter/feature configurations) on a common grid. Algorithm (Bailey–Borwein–LdP–Zhu):

1. Partition rows into `S = 16` contiguous equal blocks.
2. For each of the `C(16, 8) = 12870` combinations c (cap at 5000 random combinations if needed): IS = chosen 8 blocks (concatenated), OOS = complement.
3. `n* = argmax_n SR_IS(n)`; compute OOS rank of n*: `ω_c = rank_OOS(n*) / (N + 1)` (rank ascending, 1 = worst).
4. Logit: `λ_c = ln( ω_c / (1 − ω_c) )`.
5. **PBO = (1/C) Σ_c 1{ λ_c ≤ 0 }** — the probability that the IS-best variant is below-median OOS. Gate: PBO must be < 0.2 before a configuration family is eligible for live.

```python
def pbo_cscv(returns_matrix: pd.DataFrame, n_blocks: int = 16,
             max_combinations: int = 5000, seed: int = 42) -> PBOResult:
    """Returns PBO, λ distribution, IS-vs-OOS SR pairs for the degradation plot."""
```

### 7.4 Deflated Sharpe Ratio (`dsr.py`) — all terms defined

Probabilistic Sharpe Ratio of observed per-period Sharpe `SR` against benchmark `SR*` over `T` return observations with sample skewness `γ₃` and sample kurtosis `γ₄` (non-excess; =3 for a Gaussian):

```
PSR(SR*) = Φ( ( (SR − SR*) · sqrt(T − 1) ) / sqrt( 1 − γ₃·SR + ((γ₄ − 1)/4)·SR² ) )
```

**Deflated** SR sets `SR*` to the expected maximum Sharpe among `N` effectively-independent trials with cross-trial SR variance `V[SR]`:

```
SR* = sqrt(V[SR]) · ( (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) )
γ = 0.5772156649 (Euler–Mascheroni),  e = exp(1)
```

`N` = number of strategy configurations actually tried (logged automatically by the experiment tracker — every CPCV run appends its config hash to `experiments.log`, so N is *measured*, not guessed); `V[SR]` = sample variance of their CPCV-path Sharpe estimates. **DSR = PSR(SR\*)**; deployment gate: DSR ≥ 0.95. All SR quantities per-period (the `sqrt(T−1)` handles horizon); report annualized separately for humans.

```python
def deflated_sharpe(returns: pd.Series, n_trials: int, var_sr_trials: float) -> DSRResult:
    """PSR vs expected-max SR* of n_trials; returns DSR, SR*, PSR(0), moments used."""
```

---

## 8. Regime model — HMM (`regime/hmm.py`)

**Specification.** Gaussian HMM, `K = 3` states, **daily** observations (1d bars of the market), observation vector:

```
x_t = [ m_t,  ln σ_t ]
m_t  = daily log return of BTC/USDT
σ_t  = 14d Yang-Zhang annualized vol of BTC (ln for near-normality)
```

Two dimensions only — with ~2500 daily observations (2019→), a 3-state full-covariance HMM on 2-D inputs has 3·(2+3) + 6 + 2 = 23 free parameters: comfortably identified; adding breadth/funding inputs is a v2 experiment. Fit: Baum–Welch (`hmmlearn.hmm.GaussianHMM`, `covariance_type="full"`, `n_iter=300`, `tol=1e-4`, `n_init=10` restarts keeping best log-likelihood, `random_state=42`). Training window: expanding, min 730 days; refit monthly (1st of month, after the daily close).

**Label switching / state identification.** After every fit, relabel states by **ascending state mean of ln σ**: state 0 = low-vol ("quiet/bull"), 1 = mid, 2 = high-vol ("crisis"); tie-break by descending mean return. For continuity across refits, match new states to old by minimal total Mahalanobis distance between state means (3×3 → exhaustive over 6 permutations); log a warning if the matching disagrees with the vol-sort.

**Live inference — filtered, never smoothed.** `hmmlearn.predict_proba` returns *smoothed* posteriors `P(s_t | x_{1:T})`, which use future data — a silent lookahead. We implement the forward recursion ourselves and use **filtered** probabilities:

```
α̃_0(k) = π_k · N(x_0; μ_k, Σ_k);    normalize
α̃_t(k) = [ Σ_j α̃_{t−1}(j) · A_{jk} ] · N(x_t; μ_k, Σ_k);   normalize each t
P(s_t = k | x_{1:t}) = α̃_t(k)
```

**Usage: exposure gating (v1 recommendation).** Gross exposure multiplier:

```
G_t = Σ_k P(s_t = k | x_{1:t}) · g_k,    g = (1.0, 0.7, 0.3)
```

`G_t` multiplies the final μ vector (equivalently the portfolio gross target). Gating chosen over per-regime blending weights for v1: regime-conditional IC estimation needs far more data per state than four years of dailies provide; gating needs only the (well-established) fact that mid-frequency alpha Sharpe degrades and tails fatten in high-vol states. Per-regime blend weights `w_{k,regime}` are a v2 experiment behind a config flag. In CPCV/walk-forward backtests, the HMM is refit inside each training window only (never on test data).

```python
class RegimeHMM:
    """3-state Gaussian HMM on [BTC daily ret, ln 14d YZ vol]; filtered probs; vol-sorted states."""
    def fit(self, obs: pd.DataFrame) -> "RegimeHMM": ...
    def filtered_probs(self, obs: pd.DataFrame) -> pd.DataFrame:
        """Forward-only P(s_t=k | x_{1:t}); columns state_0..2 (vol-ascending)."""
    def gross_multiplier(self, probs: pd.DataFrame, g: tuple[float, ...] = (1.0, 0.7, 0.3)) -> pd.Series: ...
```

---

## 9. Signal blending (`alphaforge/signals/`)

### 9.1 Raw-alpha blend — EWMA Rank-IC weighting (recommended) (`blending.py`)

Inputs: processed factor z-scores `z_{k,i,t}` for the K directional alphas (momentum ×3, TS-mom ×3, reversal ×2, carry ×2 — each pre-multiplied by `FactorMeta.direction`). Weighting:

```
For each alpha k, on the non-overlapping h-bar grid (h = 72):
    RIC_{k,t} = SpearmanCorr_i( z_{k,i,t}, y_{i,t,h} )
    ÎC_{k,t}  = EWMA( RIC_{k,·} ; halflife = 20 grid-points ≈ 60 days ),  LAGGED:
                uses only RIC observations with t' + h ≤ t   (label fully realized)
    w_{k,t}   = max(ÎC_{k,t}, 0) + κ,    κ = 0.2 · mean_k max(ÎC_{k,t},0)   # shrink toward EW
    w_{k,t}   ← w_{k,t} / Σ_j w_{j,t}

A_{i,t} = Σ_k w_{k,t} · z_{k,i,t}
Ã_{i,t} = cs_zscore(A_{·,t})          # re-standardize the blend
```

Why IC-weighting over ridge stacking: with a 72-bar horizon there are only ~120 independent cross-sections per year — a ridge regression of overlapping noisy returns on 10 correlated alphas is unstable and sign-flips weights; IC weights are positive, interpretable, and degrade gracefully (an alpha that stops working decays toward κ, not negative). Ridge stacking `w = (ZᵀZ + λI)⁻¹ Zᵀ y` is implemented behind a flag as a research comparison only.

### 9.2 Final signal and expected-return vector (`sizing.py`)

```
F_{i,t} = Ã_{i,t} · |size_{i,t}| · sign-consistency guard
```
where `size_{i,t}` is the meta-model bet size (§5.3; computed with `s_{i,t} = sign(Ã_{i,t})`). Since `sign(size) = s` by construction, equivalently `F = size · |Ã|`. The ML output **gates and scales** the blend; it never flips it.

Expected return for the portfolio optimizer via the Grinold rule, gated by regime:

```
μ_{i,t} = IC_target · σ̂_{i,t}·sqrt(h) · F̃_{i,t} · G_t
```

with `F̃` = the cross-sectionally re-z-scored `F`, `IC_target = 0.02` (a deliberately conservative realized-RankIC assumption for mid-freq crypto; recalibrated quarterly to trailing realized IC), `h = 72`, `G_t` the HMM gross multiplier. Output: §4.4 prediction rows, one per (ts, symbol).

```python
class SignalService:
    """Live: on each 1h bar close, compute factors → blend → meta-prob → μ vector."""
    def on_bar_close(self, ts: pd.Timestamp) -> pd.DataFrame:
        """Returns frame (symbol, alpha_blend, p_meta, signal, mu, gross_mult); persists to predictions."""
```

---

## 10. Library choices (with Apple Silicon notes)

| Need | Choice | Rationale / gotchas |
|---|---|---|
| Dataframes | **pandas ≥2.2 + numpy ≥1.26** | Lingua franca of the LdP toolchain; team-of-one auditability beats polars speed at this data scale (≤100 symbols × 1h). pyarrow-backed parquet I/O. |
| Storage | **pyarrow ≥15** (Parquet, snappy) | Universal arm64 wheels; columnar, partition-by-month. |
| GBM | **lightgbm ≥4.3** | arm64 wheels exist; **gotcha: requires `brew install libomp`** (wheel dylinks OpenMP). Set `deterministic=True, force_col_wise=True` for reproducibility across thread counts. |
| HMM | **hmmlearn ≥0.3.2** | Standard Baum–Welch; arm64 fine. **Gotcha: its `predict_proba` is smoothed — use our own forward-pass filter for anything live (§8).** |
| SHAP | **shap ≥0.45** | TreeExplainer is exact and fast for LightGBM; arm64 wheels OK; pin numba ≥0.59 for py3.12 arm compatibility. |
| CV/metrics/calibration | **scikit-learn ≥1.4** | Isotonic calibration, clustering; **do NOT use its TimeSeriesSplit (no purging)** — custom splitters only. |
| Stats | **scipy ≥1.12**, statsmodels (Newey–West) | rankdata, Φ/Φ⁻¹. |
| Speed hotspots | **numba ≥0.59** | Triple-barrier first-touch loop and concurrency counters; arm64 JIT is solid. Keep a pure-numpy fallback path behind a flag for debuggability. |
| Tooling | uv, ruff, pytest, hypothesis | hypothesis for property tests on estimators (e.g., YZ ≥ 0, CS spread ∈ [0,1)). |

Implement all factor math in-house (no pandas-ta/talib): every formula above is ~10 lines and must be unit-tested against hand-computed fixtures — auditability is the point.

---

## 11. Build order (within this area)

1. **`features/vol.py`** — EWMA/YZ/Parkinson + fixture tests (everything downstream needs σ̂).
2. **`features/base.py` + `registry.py` + `cross_section.py`** — abstractions and CS ops, with the point-in-time truncation test harness.
3. **Factor implementations** (`momentum`, `mean_reversion`, `carry`, `liquidity`, `regime_features`) + `pipeline.py` writing §4.2 parquet.
4. **`labeling/`** — forward returns → triple barrier (numba) → weights → meta. Golden-file tests on a tiny synthetic OHLC path where barrier touches are known by construction.
5. **`validation/splits.py` + `metrics.py`** — must exist BEFORE any model is fit; includes the no-overlap assertion test.
6. **`ml/datasets.py` + `model.py` + `train.py` + `registry.py`** — first end-to-end walk-forward fit.
7. **`validation/pbo.py` + `dsr.py` + `ml/importance.py`** — research gates.
8. **`regime/hmm.py`** — independent of 6–7, can parallelize.
9. **`signals/blending.py` + `sizing.py` + `service.py`** — integration layer to portfolio/execution.
10. **`ml/retrain.py`** — weekly job, wired to the live scheduler last.

---

## 12. Top 5 silent-failure modes and safeguards

1. **Feature lookahead (using bar-t information that's only known later, e.g., entry at `C_t`).** Safeguard: (a) labels enter at `O_{t+1}` by construction; (b) automated **PIT truncation test** in CI: for every registered factor, compute on full panel vs panel truncated at random t, assert values at ≤ t identical to 1e-12 — any factor reading the future fails instantly (this is why `FactorMeta.lookback_bars` and pure-function discipline exist).
2. **Label-overlap leakage into CV → inflated IC/Sharpe.** Safeguard: `t1` persisted on every sample; splitters purge by interval intersection + 168-bar embargo; a CI test asserts for each emitted split that `max(train t1 before test) < test start` and no train interval intersects `[T_a, T1_b + E]`.
3. **Funding-rate misalignment or sign flip (8h settlements as-of-joined wrong, or carry sign inverted).** Safeguard: backward as-of join with explicit `tolerance=8h`; a **historical-episode regression test**: May 2021 alt-perp negative-funding period must produce `CARRY > 0` (longs paid) for known symbols, and factor at ts strictly precedes the next settlement.
4. **Survivorship/universe drift — CS z-scores computed over today's universe historically.** Safeguard: every CS op takes the point-in-time `in_universe` mask; a test builds a panel with a synthetically "delisted" symbol and asserts its absence from cross-sections after delist and presence before.
5. **Optimistic intrabar resolution when both barriers are touched in one bar (and at vertical).** Safeguard: conservative stop-first rule is the default and non-configurable in production; a diagnostics report quantifies the label delta between optimistic and conservative resolution per run and alerts if mean |Δlabel| > 2% (signal that barriers are too tight for the bar size — widen `m` or H).

(Honorable mentions handled in-design: HMM smoothed-posterior leak → filtered-only inference §8; sklearn TimeSeriesSplit misuse → custom splitters only §10; IC overlap inflation → non-overlapping grid + Newey–West §7.2.)

---

### Critical Files for Implementation
- /Users/arhancanli/alphaforge/alphaforge/features/base.py (Factor protocol, FactorMeta, registry — everything keys off this)
- /Users/arhancanli/alphaforge/alphaforge/labeling/triple_barrier.py (event engine: barriers, t1, conservative touch rule)
- /Users/arhancanli/alphaforge/alphaforge/validation/splits.py (purged walk-forward + CPCV — the integrity backbone)
- /Users/arhancanli/alphaforge/alphaforge/ml/model.py (AlphaLGBM wrapper + DEFAULT_PARAMS + calibration)
- /Users/arhancanli/alphaforge/alphaforge/signals/service.py (live bar-close → μ vector; the contract with portfolio/execution)
