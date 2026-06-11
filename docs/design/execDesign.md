Greenfield confirmed: no `~/alphaforge` exists, machine is arm64 (Apple Silicon), system Python is 3.9 (project will pin its own 3.12+ via uv). Below is the complete design for my area.

---

# AlphaForge — Backtesting, Portfolio Construction, Risk & Execution

**Scope of this document:** the simulation engines, transaction cost model, portfolio optimizer, risk engine, broker/execution layer, 24/7 live paper-trading loop, persistence, and analytics. Data pipeline / feature engineering / ML are owned by other areas; their contract surfaces (bar schema, alpha vector) are stated where consumed.

**Global conventions (binding for all modules below):**
- All timestamps are **integer epoch seconds, UTC**, and always refer to **bar close time** unless suffixed `_open_ts`. No naive datetimes anywhere.
- All money is float64 USDT (quote currency). All weights are signed fractions of current equity.
- Variable-name unit suffixes are mandatory: `mu_ann`, `sigma_ann`, `cov_bar`, `cost_frac` (fraction, e.g. 0.0005), `*_bps` (basis points, 1e-4).
- Crypto trades 24/7: **bars per year = 8760** for 1h, 2190 for 4h, 365 for 1d. This constant lives on the calendar object, never hard-coded, so equities (≈ 252 days) plug in later.

---

## 1. Package layout

```
alphaforge/
├── core/                          # shared kernel (owned jointly; my area defines these)
│   ├── __init__.py
│   ├── types.py                   # Instrument, OrderRequest, Fill, Position, AccountState, enums
│   ├── calendar.py                # BarCalendar: bar boundaries, periods_per_year, funding times
│   └── config.py                  # pydantic Settings models (cost, portfolio, risk, live)
├── costs/
│   ├── __init__.py
│   ├── fees.py                    # FeeSchedule presets (BINANCE_VIP0_SPOT, BINANCE_VIP0_PERP)
│   └── model.py                   # TransactionCostModel — THE single cost model, imported everywhere
├── backtest/
│   ├── __init__.py
│   ├── ledger.py                  # Ledger: positions, cash, funding, margin, equity
│   ├── fills.py                   # FillModel ABC, NextOpenFill, VWAPParticipationFill
│   ├── engine.py                  # EventDrivenBacktester (truth engine)
│   ├── vectorized.py              # run_vectorized (fast research pre-screen)
│   └── result.py                  # BacktestResult container + parquet writers
├── portfolio/
│   ├── __init__.py
│   ├── covariance.py              # ewma_cov, ledoit_wolf_cc, nearest_psd, annualize_cov
│   ├── optimizer.py               # MeanVarianceOptimizer (cvxpy), RankEqualVolFallback
│   ├── overlay.py                 # vol_target_scale, kelly_fraction_note helpers
│   └── discretize.py              # weights_to_orders: lot/min-notional rounding, no-trade band
├── risk/
│   ├── __init__.py
│   ├── limits.py                  # RiskLimits dataclass (every numeric limit in one place)
│   ├── pretrade.py                # PreTradeChecker
│   ├── monitors.py                # historical_var_cvar, DrawdownLadder, PerAssetStop, StalenessMonitor
│   └── killswitch.py              # KillSwitch (DB-backed + file sentinel)
├── execution/
│   ├── __init__.py
│   ├── broker.py                  # Broker ABC, OrderAck, OrderState, state machine enums
│   ├── paper.py                   # PaperBroker (uses TransactionCostModel + Ledger + StateStore)
│   ├── ccxt_broker.py             # CCXTBroker (live, stub in v1: implements interface, raises NotArmed)
│   ├── order_manager.py           # OrderManager: idempotency, retry/backoff, partial fills
│   └── reconcile.py               # Reconciler: broker vs internal book
├── live/
│   ├── __init__.py
│   ├── store.py                   # StateStore: SQLite (WAL) DDL + typed accessors
│   ├── loop.py                    # LiveLoop: the hourly cycle
│   ├── recovery.py                # startup crash recovery
│   └── alerts.py                  # TelegramAlerter + inbound command poller
├── analytics/
│   ├── __init__.py
│   ├── metrics.py                 # sharpe, sortino, calmar, max_drawdown, turnover, exposure
│   ├── attribution.py             # per-asset & per-sleeve PnL attribution
│   ├── tearsheet.py               # daily/backtest tearsheet PNG + metrics.json
│   └── walkforward.py             # WalkForwardRunner: stitched OOS equity curve
└── tests/                         # mirrors package; golden-master fixtures in tests/fixtures/
```

---

## 2. Core types (`alphaforge/core/types.py`)

```python
class InstrumentType(StrEnum):
    SPOT = "spot"
    PERP = "perp"          # USDT-M linear perpetual

@dataclass(frozen=True, slots=True)
class Instrument:
    """Static contract metadata; the asset-class abstraction. Equities later = new factory, same fields."""
    symbol: str            # canonical, e.g. "BTC/USDT" or "BTC/USDT:USDT" (ccxt unified)
    base: str
    quote: str             # always "USDT" in v1
    itype: InstrumentType
    price_step: float      # PRICE_FILTER tickSize
    qty_step: float        # LOT_SIZE stepSize
    min_qty: float
    min_notional: float    # MIN_NOTIONAL, quote units
    can_short: bool        # False for spot, True for perp
    contract_mult: float = 1.0

class Side(StrEnum):  BUY = "buy"; SELL = "sell"
class Liquidity(StrEnum): MAKER = "maker"; TAKER = "taker"
class OrderType(StrEnum): MARKET = "market"; LIMIT = "limit"

@dataclass(slots=True)
class OrderRequest:
    client_order_id: str   # idempotency key, see §8.3
    symbol: str
    side: Side
    qty: float             # always positive; side carries sign
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    reduce_only: bool = False
    decision_price: float = 0.0   # close used for sizing — for price-collar check & slippage attribution
    cycle_ts: int = 0
    reason: str = ""              # "rebalance" | "stop" | "flatten" | "recon"

@dataclass(slots=True)
class Fill:
    fill_id: str
    client_order_id: str
    symbol: str
    ts_ms: int
    qty: float             # signed: + = bought, - = sold
    price: float
    fee: float             # quote units, always >= 0
    liquidity: Liquidity

@dataclass(slots=True)
class Position:
    symbol: str
    qty: float             # signed
    avg_entry_price: float # VWAP of opening fills (resets on flat / flip)
    entry_ts: int

@dataclass(slots=True)
class AccountState:
    equity: float
    cash: float
    margin_used: float
    ts_ms: int
```

`core/calendar.py`:

```python
class BarCalendar:
    """Bar arithmetic for 24/7 crypto. Equity calendar implements the same interface later."""
    def __init__(self, bar_seconds: int = 3600) -> None: ...
    @property
    def periods_per_year(self) -> float:
        """8760.0 for 1h, 2190.0 for 4h, 365.0 for 1d (24/7 markets, leap days ignored — <0.3% effect, documented)."""
    def floor(self, ts: int) -> int: ...
    def next_close(self, ts: int) -> int: ...
    def funding_ts_in(self, bar_close_ts: int) -> int | None:
        """Return bar_close_ts if it is 00:00/08:00/16:00 UTC (Binance funding), else None."""
```

---

## 3. Transaction cost model (`alphaforge/costs/`) — single source of truth

Imported by: vectorized backtester, event-driven backtester, PaperBroker, optimizer (turnover penalty), pre-trade checks. **Never reimplemented.**

### 3.1 Fee schedule (`fees.py`)

```python
@dataclass(frozen=True)
class FeeSchedule:
    maker_bps: float
    taker_bps: float

BINANCE_VIP0_SPOT = FeeSchedule(maker_bps=10.0, taker_bps=10.0)   # 0.10% both at VIP0, no BNB discount
BINANCE_VIP0_PERP = FeeSchedule(maker_bps=2.0,  taker_bps=5.0)    # 0.02% / 0.05%
```

Fee on a fill: `fee = |qty| * price * fee_bps * 1e-4`.

### 3.2 Cost components (`model.py`)

For an order of quote notional `Q` in instrument `i`:

1. **Half-spread**: `hs_i` (fraction). Default `2.5 bps` (2.5e-4) for all instruments; per-instrument override table populated from observed spreads (BTC/ETH perps run ≈0.5–1 bps; a flat 2.5 bps is deliberately conservative for a mixed top-30 universe).
2. **Market impact, square-root law**:

```
impact_frac = Y * sigma_daily * sqrt(Q / ADV)
```

- `Y = 1.0` default (empirical estimates across asset classes cluster in 0.5–1.5; Tóth et al. 2011, Almgren 2005 — 1.0 is the standard conservative midpoint).
- `sigma_daily` = EWMA daily return vol of instrument i: `sigma_daily = sigma_1h * sqrt(24)`, `sigma_1h` from EWMA with halflife 240 bars (10 days).
- `ADV` = **30-day rolling median of daily quote volume** (median, not mean, to resist single-day wash/news spikes). Supplied by the data layer per instrument per bar.
- **When to cap instead of model:** the sqrt law is only trustworthy for `Q/ADV ≲ 1%`. Above that the model both underestimates cost and signals you shouldn't do the trade at all. Policy: pre-trade check rejects orders with `Q > 0.01 * ADV` (§7.1); the impact term is therefore always evaluated in its valid regime. Do **not** extrapolate the formula to large Q.

3. **Total one-way cost** (fraction of notional):

```
cost_frac(Q) = fee_bps*1e-4 + hs_i + Y * sigma_daily * sqrt(Q / ADV)
```

```python
class TransactionCostModel:
    """All trading frictions. One instance shared by both backtesters and PaperBroker."""
    def __init__(self, spot_fees: FeeSchedule = BINANCE_VIP0_SPOT,
                 perp_fees: FeeSchedule = BINANCE_VIP0_PERP,
                 impact_coef: float = 1.0,
                 default_half_spread_bps: float = 2.5,
                 half_spread_overrides: Mapping[str, float] | None = None) -> None: ...

    def fee_frac(self, inst: Instrument, liquidity: Liquidity) -> float:
        """Fee as fraction of notional."""
    def half_spread_frac(self, inst: Instrument) -> float: ...
    def impact_frac(self, notional: float, adv_quote: float, sigma_daily: float) -> float:
        """impact_coef * sigma_daily * sqrt(notional / adv). Raises if notional > 0.05*adv (model misuse guard)."""
    def oneway_cost_frac(self, inst: Instrument, notional: float, adv_quote: float,
                         sigma_daily: float, liquidity: Liquidity = Liquidity.TAKER) -> float:
        """fee + half_spread + impact. Used by optimizer penalty & vectorized engine."""
    def fill_price(self, inst: Instrument, side: Side, ref_price: float, notional: float,
                   adv_quote: float, sigma_daily: float) -> float:
        """ref_price * (1 + s*(half_spread + impact)), s=+1 buy / -1 sell. Fee charged separately."""
```

---

## 4. Event-driven backtester (`alphaforge/backtest/`) — the truth engine

### 4.1 Event-loop semantics (the no-lookahead contract)

Bar-based loop over close timestamps `t_1 < t_2 < … < t_T`:

```
for each bar close t_k:
    1. apply funding if t_k ∈ {00,08,16}:00 UTC (perp positions, §4.3)
    2. mark book at close[t_k]; record equity point E(t_k)
    3. risk monitors update (DD ladder, stops) — may inject forced orders for t_{k+1}
    4. strategy.on_bar(history ≤ t_k) → target weights w(t_k)
    5. discretize w(t_k) → OrderRequests (decision_price = close[t_k])
    6. pre-trade checks; surviving orders queued for bar t_{k+1}
    7. advance: fill queued orders using bar t_{k+1} data via FillModel
```

**Hard rule enforced in code:** the `FillModel` receives *only* bar `t_{k+1}` (and instrument ADV/vol as of `t_k`); the engine asserts `order.cycle_ts < fill_bar.close_ts` on every fill and raises `LookaheadError` otherwise. Strategy callbacks receive a view of history truncated at `t_k` (the engine slices, the strategy cannot ask for more).

### 4.2 Fill models (`fills.py`)

```python
class FillModel(ABC):
    @abstractmethod
    def fill(self, order: OrderRequest, next_bar: Bar, inst: Instrument,
             adv_quote: float, sigma_daily: float, cost: TransactionCostModel) -> list[Fill]: ...
```

**`NextOpenFill` (default, matches live execution timing):**
- Fill price: `P = open_{t+1} * (1 + s*(hs + impact))`, `s = +1` buy / `-1` sell; `impact` from §3.2 with `Q = qty * open_{t+1}`.
- Fee: taker.
- Volume guard: if `Q > 0.10 * quote_volume_{t+1}` the order is **partially filled** down to that cap and the remainder is dropped with a `VolumeCapped` log record (mid-frequency on top-30 names should never hit this; if it does you want to know, not to pretend).

**`VWAPParticipationFill` (for size-sensitivity studies):**
- Per child bar: `q_filled = min(remaining, participation * quote_volume_bar / P_typ)`, `participation = 0.05` default (5% — keeps realized impact within the sqrt-law regime).
- Price: `P_typ * (1 + s*(hs + impact_of_child))` with `P_typ = (H + L + C)/3` of the child bar (standard typical-price VWAP proxy when you have no intrabar data).
- Remainder rolls forward up to `max_child_bars = 8`, then cancels (logged).

### 4.3 Ledger: positions, cash, funding, fees, margin (`ledger.py`)

```python
class Ledger:
    """Double-entry-ish book. Cash + positions; equity is derived, never stored independently."""
    def __init__(self, initial_cash: float, instruments: Mapping[str, Instrument]) -> None: ...
    def apply_fill(self, fill: Fill) -> None:
        """Spot: cash -= qty*price + fee; position += qty.
        Perp: cash -= fee; realized PnL booked on reducing fills; avg_entry updated on increasing fills."""
    def apply_funding(self, symbol: str, funding_rate: float, mark_price: float, ts: int) -> float:
        """payment = -qty * mark_price * funding_rate; cash += payment; returns payment. Long pays when rate>0."""
    def mark(self, closes: Mapping[str, float]) -> None: ...
    @property
    def equity(self) -> float:
        """cash + Σ_spot qty*mark + Σ_perp qty*(mark - avg_entry)."""
    def gross_exposure(self) -> float:   # Σ_i |qty_i * mark_i| / equity
    def net_exposure(self) -> float:     # Σ_i  qty_i * mark_i  / equity
    def margin_used(self, leverage: float = 5.0) -> float:
        """Σ_perp |qty*mark| / leverage  (initial margin, cross)."""
    def maintenance_margin(self, mmr: float = 0.01) -> float:
        """Σ_perp |qty*mark| * mmr. Flat conservative 1% (Binance tier-1 BTC/ETH is 0.4–0.5%)."""
```

**Funding (USDT-M perps), exactly:** Binance settles every 8h at 00:00, 08:00, 16:00 UTC. At each bar whose close hits a funding timestamp:

```
payment_i = - qty_i * close_i(t) * f_i(t)        # close as mark-price proxy (documented approximation)
cash     += payment_i
```

Sign check built into a property test: `qty > 0, f > 0 ⇒ payment < 0` (longs pay shorts). Historical `f_i(t)` comes from the data layer (Binance `fundingRate` history, free). Funding is a first-class PnL line item — in crypto it routinely dominates fees.

**Perp PnL:** position marked-to-market each bar: `unreal_i = qty_i * (close_i − avg_entry_i)`. On a reducing fill of signed qty `q` at price `p`: `realized = -q * (avg_entry − p)` booked to cash (linear contract). Position flips reset `avg_entry` to the flip fill price.

**Liquidation guard (should be unreachable):** after each mark, if `equity < maintenance_margin()` raise `LiquidationError` and halt the run with a loud report. With gross ≤ 1.6 and mmr 1% this requires a −62% instantaneous move; the check exists so the assumption is verified, not assumed.

### 4.4 Engine API

```python
class Strategy(Protocol):
    def on_bar(self, ts: int, history: BarView, ledger_view: LedgerView) -> dict[str, float]:
        """Return target weights {symbol: w}. history is hard-truncated at ts."""

class EventDrivenBacktester:
    def __init__(self, bars: BarSource, funding: FundingSource, instruments: Mapping[str, Instrument],
                 strategy: Strategy, cost_model: TransactionCostModel,
                 fill_model: FillModel | None = None,            # default NextOpenFill
                 risk: RiskEngine | None = None,
                 initial_cash: float = 100_000.0) -> None: ...
    def run(self, start_ts: int, end_ts: int) -> BacktestResult: ...
```

### 4.5 Persisted backtest artifacts (parquet, `~/alphaforge/artifacts/backtests/{run_id}/`)

`equity.parquet`:

| column | dtype | meaning |
|---|---|---|
| ts | int64 | bar close epoch s UTC |
| equity | float64 | end-of-bar equity |
| ret | float64 | `equity_t/equity_{t-1} - 1` |
| gross | float64 | gross exposure |
| net | float64 | net exposure |
| turnover | float64 | Σ\|traded notional\|/equity this bar (one-way) |
| fees | float64 | fees paid this bar |
| slippage | float64 | half-spread+impact cost this bar |
| funding | float64 | net funding received this bar (signed) |
| n_pos | int32 | open positions |

`trades.parquet`: `ts:int64, symbol:str, side:str, qty:float64, price:float64, notional:float64, fee:float64, slippage_cost:float64, reason:str`.
`positions.parquet`: `ts:int64, symbol:str, qty:float64, mark:float64, weight:float64, unreal_pnl:float64`.
`run_meta.json`: config dump + hash, git SHA, data range, cost params, fill model — full reproducibility.

---

## 5. Vectorized pre-screen backtester (`vectorized.py`)

For fast factor research sweeps (thousands of variants). **Shares `TransactionCostModel`.**

Inputs: weights matrix `W` (T×N, weight decided at close of row's ts), close-to-close returns `R` (T×N), funding rates `F` (sparse), per-instrument `adv`, `sigma_daily`, typical trade notional.

```
r_p(t) = Σ_i W[t-1,i] * R[t,i]  -  TC(t)  -  Σ_{i∈perp, funding bar} W[t-1,i] * f_i(t)
TC(t)  = Σ_i |W[t,i] - W[t-1,i]| * oneway_cost_frac_i      # evaluated at E[t]*|Δw| notional
E(t)   = E(t-1) * (1 + r_p(t))
```

```python
def run_vectorized(weights: pd.DataFrame, closes: pd.DataFrame,
                   funding: pd.DataFrame | None, instruments: Mapping[str, Instrument],
                   cost_model: TransactionCostModel, adv: pd.DataFrame, sigma_daily: pd.DataFrame,
                   initial_cash: float = 100_000.0) -> VectorizedResult:
    """Fast approximate backtest. Documented biases: fills at close t (not open t+1);
    weight drift between rebalances ignored (second-order at mid-freq sizes)."""
```

**Parity contract (acceptance test, `tests/test_engine_parity.py`):** run the same momentum strategy through both engines on 2 years of real BTC/ETH/SOL data; require per-bar return correlation > 0.99, |annualized return difference| < 2 pts, total cost difference < 5%. This test is what makes the fast engine trustworthy as a screen; it runs in CI.

---

## 6. Portfolio construction (`alphaforge/portfolio/`)

Pipeline each rebalance: **blended alpha → μ → Σ → cvxpy MVO → vol-target overlay → discretize**.

### 6.1 Covariance (`covariance.py`)

**EWMA on hourly returns, zero-mean** (hourly means are noise; assuming 0 reduces estimator variance):

```
λ = 0.5^(1/H),  H = 720 bars (30 days)            # decay per bar
S_t = (1-λ) r_t r_tᵀ + λ S_{t-1},  S_0 = sample cov of first 240 bars
```

Halflife justification: effective sample size ≈ 2H/ln2 ≈ 2078 obs ≫ 10×N for N≈30 (estimation stability), while still adapting to crypto vol-regime shifts within ~2 weeks. `min_periods = 240` (10 days) before the matrix is usable.

**Ledoit–Wolf shrinkage to the constant-correlation target** (Ledoit & Wolf 2004, "Honey, I Shrunk the Sample Covariance Matrix"), computed on the trailing `T = 720` hourly returns (unweighted window for the asymptotic estimates — documented approximation alongside EWMA `S`):

```
r̄    = (2 / (N(N-1))) Σ_{i<j} s_ij / sqrt(s_ii s_jj)            # mean pairwise correlation
F    : f_ii = s_ii ;  f_ij = r̄ sqrt(s_ii s_jj)                  # shrinkage target
π_ij = (1/T) Σ_t (x_ti x_tj - s_ij)² ;            π̂ = Σ_ij π_ij
θ_kk,ij = (1/T) Σ_t (x_tk² - s_kk)(x_ti x_tj - s_ij)
ρ̂    = Σ_i π_ii + Σ_{i≠j} (r̄/2) [ sqrt(s_jj/s_ii) θ_ii,ij + sqrt(s_ii/s_jj) θ_jj,ij ]
γ̂    = Σ_ij (f_ij - s_ij)²
δ*   = clip( (π̂ - ρ̂) / (γ̂ T), 0, 1 )
Σ_shrunk = δ* F + (1-δ*) S
```

**PSD repair:** eigendecompose, clip eigenvalues at `ε = 1e-10 · tr(Σ)/N`, reconstruct (`nearest_psd`).
**Annualize:** `Σ_ann = Σ_1h × 8760` (factor from `BarCalendar.periods_per_year`).

```python
def ewma_cov(returns_1h: pd.DataFrame, halflife_bars: int = 720, min_periods: int = 240) -> np.ndarray: ...
def ledoit_wolf_cc(returns_1h: np.ndarray, S: np.ndarray) -> tuple[np.ndarray, float]:
    """Constant-correlation LW shrink. Returns (Sigma_shrunk, delta_star)."""
def annualize_cov(cov_bar: np.ndarray, periods_per_year: float) -> np.ndarray: ...
def nearest_psd(S: np.ndarray, eps_rel: float = 1e-10) -> np.ndarray: ...
```

### 6.2 Mean–variance optimizer (`optimizer.py`) — the exact problem

Contract with the ML/alpha layer: it delivers per-bar expected returns `r̂_bar,i`; we annualize `μ_ann = r̂_bar × 8760`. `Σ_ann` from §6.1. `w̃` = current drifted weights (from ledger marks). Per-asset one-way cost `c_i = oneway_cost_frac` evaluated at the typical trade size (`0.5 × w_max × equity`).

```
maximize_w    μ_annᵀ w  −  (λ/2) wᵀ Σ_ann w  −  A · Σ_i c_i |w_i − w̃_i|

subject to    Σ_i |w_i|        ≤ G_max          # gross,   default 1.0
              |Σ_i w_i|        ≤ N_max          # net,     default 0.5
              −w_max·shortable_i ≤ w_i ≤ w_max  # per-asset, default w_max = 0.15
              Σ_i |w_i − w̃_i|  ≤ τ_max         # per-rebalance one-way turnover cap, default 0.10
```

- **λ (risk aversion) = 7.0.** Derivation: unconstrained MVO gives `w* = (1/λ)Σ⁻¹μ` with ex-ante vol `σ_p = SR_implied/λ`; targeting σ ≈ 0.15 at a believed gross alpha Sharpe ≈ 1.0 gives `λ = 1.0/0.15 ≈ 6.7 → 7`. Note μ and Σ are scaled by the same annualization factor, so λ is invariant to the per-bar vs annual unit choice — but both must be annualized *together* (see failure mode #4).
- **A (cost amortization) = 8760 / h_hold, h_hold = 48 bars (2 days)** ⇒ A ≈ 182.5. Rationale: a one-shot cost `c_i` is paid against alpha that accrues over the expected holding period h, so on the annualized footing of the objective the cost must be multiplied by trades-per-year at that horizon. h_hold = 48h sits in the middle of the mandated "hours to days" band; recalibrate to *realized* median holding period after the first month and document the change.
- **Shorting:** `shortable_i = 1` for perps, `0` for spot (lower bound 0). Gross/net caps keep total perp leverage modest; margin feasibility is independently verified pre-trade (§7.1).
- **Solver:** cvxpy with **Clarabel** (default), OSQP fallback. The `|·|` terms are handled by cvxpy's automatic epigraph reformulation — write the objective with `cp.norm1`/`cp.abs` directly.

```python
@dataclass(frozen=True)
class PortfolioConstraints:
    gross_max: float = 1.0
    net_max: float = 0.5
    w_max: float = 0.15
    turnover_max: float = 0.10

@dataclass
class OptResult:
    weights: dict[str, float]
    status: str                  # "optimal" | "fallback_used"
    ex_ante_vol_ann: float
    objective: float

class MeanVarianceOptimizer:
    def __init__(self, risk_aversion: float = 7.0, holding_bars: int = 48,
                 constraints: PortfolioConstraints = PortfolioConstraints(),
                 solver: str = "CLARABEL") -> None: ...
    def solve(self, mu_ann: np.ndarray, cov_ann: np.ndarray, w_prev: np.ndarray,
              cost_frac_oneway: np.ndarray, shortable: np.ndarray) -> OptResult:
        """Solve the MVO above. On solver failure/infeasible/NaN: log, alert, delegate to fallback."""
```

**Fallback — `RankEqualVolFallback`** (used when the solver fails, returns non-finite weights, or ex-ante vol is implausible):
1. Rank assets by `μ_ann`. Long top `K`, short bottom `K` (perps only), `K = min(10, ⌊N/4⌋)`.
2. `w_i ∝ sign_i / σ_ann,i` (inverse-vol), normalized so `Σ|w_i| = 0.5 · G_max` (half gross — deliberately conservative because we're in a degraded mode).
3. Clip at `w_max`, drop non-shortable shorts, renormalize. Alert fires whenever fallback engages.

### 6.3 Volatility targeting overlay (`overlay.py`)

```
σ̂_p   = max( sqrt(w_optᵀ Σ_ann w_opt),  σ_realized )      # conservatism: take the larger
σ_real = EWMA std of realized portfolio 1h returns, halflife 240 bars, × sqrt(8760)
s      = min( σ_target / σ̂_p , s_max )                    # σ_target = 0.15, s_max = 1.5
w_final = s · w_opt   (then re-clip so Σ|w| ≤ G_max)
```

- `σ_target = 0.15` (bottom of the 15–20% mandate band: crypto return distributions are fat-tailed, so a Gaussian-calibrated 15% realizes hotter; start low, raise deliberately).
- `s_max = 1.5` prevents levering up when a quiet regime makes ex-ante vol deceptively small — exactly when vol targeting blows accounts up.

**Fractional Kelly note (documented in module docstring, not a separate mechanism):** unconstrained MVO `w* = (1/λ)Σ⁻¹μ` *is* `(1/λ) × full-Kelly` (Kelly-optimal under log utility ≈ `Σ⁻¹μ`). λ = 7 ⇒ ≈ 1/7-Kelly before constraints and vol targeting bind further — comfortably under the half-Kelly ceiling practitioners use to survive μ-estimation error. Do not add a second Kelly knob; it's already in λ.

### 6.4 Discrete order generation (`discretize.py`)

```python
def weights_to_orders(targets: Mapping[str, float], ledger: Ledger,
                      closes: Mapping[str, float], instruments: Mapping[str, Instrument],
                      no_trade_band: float = 0.0010, cycle_ts: int = 0) -> list[OrderRequest]:
    """Target weights → integer-constrained OrderRequests. Skips churn; splits position flips."""
```

Per asset:
1. `Δ_notional = w_target · E − qty_current · close` .
2. **No-trade band:** skip if `|Δ_notional| < 0.0010 · E` (10 bps of equity — below this, cost_frac ≈ 15–20 bps round trip eats any rebalancing benefit; cuts churn dramatically at hourly cadence).
3. **Exchange filters:** `qty = sign(Δ) · floor(|Δ|/close / qty_step) · qty_step`; skip if `|qty| < min_qty` or `|qty|·close < 1.05 · min_notional` (5% buffer so a price tick between sizing and submission can't reject the order).
4. **Position flips** (sign(target qty) ≠ sign(current qty), perps): emit **two** orders — a `reduce_only` close to flat, then an open — so live margin/position-mode accounting on Binance never sees an ambiguous netting order.
5. `decision_price = close`, `reason = "rebalance"`.

---

## 7. Risk engine (`alphaforge/risk/`)

All limits live in one frozen dataclass (`limits.py`) so the entire risk posture is reviewable in one screen:

```python
@dataclass(frozen=True)
class RiskLimits:
    w_max_hard: float = 0.20          # > optimizer's 0.15: drift buffer
    gross_max_hard: float = 1.6
    net_max_hard: float = 0.75
    max_adv_participation: float = 0.01     # order notional ≤ 1% of 30d-median ADV
    price_collar_frac: float = 0.02         # live price within ±2% of decision_price
    margin_utilization_max: float = 0.50    # initial margin ≤ 50% of equity
    var_1d_limit_frac: float = 0.05         # 99% 1d VaR ≤ 5% of equity
    dd_tier1: float = 0.10; dd_tier1_release: float = 0.075
    dd_tier2: float = 0.15
    stop_sigma_mult: float = 2.5            # per-asset stop, daily sigmas
    stop_embargo_bars: int = 24
    staleness_bars: float = 2.0             # bar age > 2× interval ⇒ quarantine
    staleness_universe_frac: float = 0.25   # >25% stale ⇒ global halt
```

### 7.1 Pre-trade checks (`pretrade.py`)

```python
class PreTradeChecker:
    def check(self, order: OrderRequest, ledger: Ledger, last_price: float,
              adv_quote: float, limits: RiskLimits, kill: KillSwitch) -> CheckResult:
        """Every order passes through here in backtest AND live (same code). Fail ⇒ reject + risk_event row."""
```

Checks, in order (first failure rejects; every rejection persisted + alerted):
1. kill-switch not engaged; staleness gate passed.
2. post-trade `|notional_i| ≤ w_max_hard · E`.
3. post-trade gross ≤ `gross_max_hard · E`; |net| ≤ `net_max_hard · E`.
4. order notional ≤ `max_adv_participation · ADV` (this is also the sqrt-impact validity guard, §3.2).
5. **price collar:** `|last_price/decision_price − 1| ≤ 0.02`, else the market moved since signal — reject (stale signal protection for market orders).
6. post-trade `margin_used ≤ 0.5 · equity` (perps).
7. `reduce_only` orders bypass 2–4 (you must always be able to de-risk).

### 7.2 Portfolio monitors (`monitors.py`)

**Historical VaR/CVaR** — empirical, no distributional assumption:

```
window: last 2160 hourly portfolio returns (90 days); confidence c = 0.99, p = 0.01
sort returns ascending: r_(1) ≤ … ≤ r_(n);  k = max(1, floor(p·n))      # k = 21 at n = 2160
VaR_1h,99  = − r_(k)
CVaR_1h,99 = − (1/k) Σ_{j=1..k} r_(j)
VaR_1d,99  = VaR_1h,99 · sqrt(24)          # iid scaling; caveat documented (understates under vol clustering — hence CVaR also monitored)
```

Action: if `VaR_1d,99 > 0.05 · E`, multiply the vol-target scale by `0.05·E / VaR_1d,99` next cycle until compliant (proportional de-gross, not a cliff).

**Drawdown ladder** — equity marked hourly:

```
HWM_t = max(HWM_{t-1}, E_t);   DD_t = 1 − E_t / HWM_t
DD ≥ 0.10  → TIER1: gross & vol targets × 0.5; WARN alert.   Releases when DD < 0.075 (hysteresis, no flapping).
DD ≥ 0.15  → TIER2: flatten everything (reduce_only market orders), engage kill-switch, CRIT alert.
             Manual re-arm only (§7.3); on re-arm HWM resets to current equity (else it instantly re-trips).
```

**Per-asset stop (backstop, not the exit signal):** if adverse move from `avg_entry_price` exceeds `2.5 × σ_daily,i`, close next cycle (`reason="stop"`) and embargo re-entry for 24 bars. Persisted in `risk_events`.

**Data-staleness circuit breaker:** instrument's latest bar older than `2 × bar_interval` ⇒ quarantined (no new orders; existing position held, flagged). If > 25% of universe is stale, or account/ticker fetch fails twice consecutively ⇒ **global no-trade** for the cycle. *Critical interaction:* stale prices read as zero volatility — without this breaker, vol targeting would lever up into a data outage.

### 7.3 Kill-switch (`killswitch.py`)

State = row in `kill_switch` table **and** sentinel file `~/alphaforge/KILL` (file wins if they disagree — survives DB corruption; `touch ~/alphaforge/KILL` from any SSH session kills the system). Checked at cycle start **and** inside `OrderManager.execute_batch` immediately before every submission.

Engages on: DD tier-2; reconciliation divergence > 2% of equity; ≥ 5 consecutive order errors; Telegram `/kill`; manual file touch.
Disengages **only** via CLI `alphaforge arm --confirm <reason>` (typed confirmation, audit row with operator + reason). Telegram cannot re-arm — deliberate friction.

---

## 8. Execution layer (`alphaforge/execution/`)

### 8.1 Broker ABC (`broker.py`) — real interface from day one

```python
class OrderStatus(StrEnum):
    PENDING_NEW = "pending_new"; NEW = "new"; PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"; CANCELED = "canceled"; REJECTED = "rejected"; UNKNOWN = "unknown"

class Broker(ABC):
    @abstractmethod
    async def submit(self, req: OrderRequest) -> OrderAck: ...
    @abstractmethod
    async def cancel(self, client_order_id: str, symbol: str) -> bool: ...
    @abstractmethod
    async def fetch_order(self, client_order_id: str, symbol: str) -> OrderState | None:
        """MUST be queryable by client_order_id — the idempotency backbone."""
    @abstractmethod
    async def open_orders(self) -> list[OrderState]: ...
    @abstractmethod
    async def positions(self) -> list[Position]: ...
    @abstractmethod
    async def account(self) -> AccountState: ...
    @abstractmethod
    async def fills_since(self, ts_ms: int) -> list[Fill]: ...
```

### 8.2 PaperBroker (`paper.py`)

- Holds its own `Ledger` + persists every order/fill/position to the **same SQLite schema** as live (§9.1) — paper *is* the production path with simulated fills.
- Market-order fill: fetch live ticker price at submission (data layer), then `price = cost_model.fill_price(...)`, fee = taker — **identical `TransactionCostModel` instance** as the backtester. Applies funding at boundaries from the live funding-rate feed.
- Fills fully in v1 (sizes ≪ 1% ADV by pre-trade construction); the `OrderState` machinery still flows through `OrderManager` so partial-fill code paths get exercised by tests.

### 8.3 OrderManager (`order_manager.py`)

```python
class OrderManager:
    def __init__(self, broker: Broker, store: StateStore, kill: KillSwitch,
                 max_retries: int = 3, backoff_base_s: float = 1.0) -> None: ...
    async def execute_batch(self, orders: list[OrderRequest], cycle_ts: int,
                            fill_timeout_s: float = 60.0) -> list[OrderState]:
        """Submit, poll to terminal state, persist every transition. Crash-safe via idempotency keys."""
```

- **Idempotency:** `client_order_id = "af-{strategy_id}-{cycle_ts}-{symbol_slug}-{sha1(side,qty,type)[:8]}"` — deterministic for a given cycle's intent. Before any submit: `fetch_order(client_order_id)`; if it exists, **adopt** it instead of resubmitting. A crash between submit and persist therefore cannot double-order.
- **Retry:** exponential backoff 1s/2s/4s, max 3. On *timeout/connection* errors, always `fetch_order` first — the order may have landed. Non-retryable errors (insufficient balance, filter violation) fail fast → risk_event.
- **Partial fills:** accumulate `filled_qty` from `fills_since`; if not terminal after `fill_timeout_s`, cancel; residual intent is *not* chased — it re-enters as a fresh delta at the next cycle's optimization (mid-frequency: the hour-later rebalance is the natural cleanup).
- ≥ 5 consecutive submission errors ⇒ kill-switch.

### 8.4 Reconciler (`reconcile.py`)

Runs at every cycle start and every 15 min between cycles:

```python
class Reconciler:
    async def reconcile(self, broker: Broker, ledger: Ledger, store: StateStore) -> ReconReport:
        """Compare broker positions/equity to internal book. Broker is truth; divergences adopted + audited."""
```

- Per-symbol qty divergence > `max(1 qty_step, 0.1% of |position|)` ⇒ WARN alert + adopt broker qty (audit row `recon_events`).
- Equity divergence > 0.5% ⇒ WARN; > 2% ⇒ kill-switch (something is deeply wrong: missed fills, fee model drift, or an unrecorded manual trade).

### 8.5 CCXTBroker (`ccxt_broker.py`)

Implements the full ABC against `ccxt.async_support.binance` / `binanceusdm` with unified `params={"newClientOrderId": ...}` for idempotency. In v1 it is complete enough to compile and pass interface tests but `submit` raises `BrokerNotArmedError` unless config `live.real_money=true` **and** an environment variable `ALPHAFORGE_ARMED=1` are both set — flipping to real money is a config change, not a code change, as mandated.

---

## 9. Live loop & persistence (`alphaforge/live/`)

### 9.1 SQLite schema (`store.py`) — one file `~/alphaforge/state/alphaforge.db`, WAL mode

```sql
PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;

CREATE TABLE orders (
  client_order_id TEXT PRIMARY KEY, broker_order_id TEXT,
  cycle_ts INTEGER NOT NULL, symbol TEXT NOT NULL, itype TEXT NOT NULL,
  side TEXT NOT NULL, order_type TEXT NOT NULL,
  qty REAL NOT NULL, limit_price REAL, reduce_only INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL, filled_qty REAL NOT NULL DEFAULT 0, avg_fill_price REAL,
  decision_price REAL NOT NULL, reason TEXT NOT NULL,
  created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL);
CREATE INDEX ix_orders_cycle ON orders(cycle_ts);

CREATE TABLE fills (
  fill_id TEXT PRIMARY KEY, client_order_id TEXT NOT NULL REFERENCES orders,
  symbol TEXT NOT NULL, ts_ms INTEGER NOT NULL,
  qty REAL NOT NULL,            -- signed
  price REAL NOT NULL, fee REAL NOT NULL, fee_ccy TEXT NOT NULL, liquidity TEXT NOT NULL);

CREATE TABLE positions_snapshots (
  cycle_ts INTEGER NOT NULL, symbol TEXT NOT NULL,
  qty REAL NOT NULL, avg_entry_price REAL NOT NULL, mark_price REAL NOT NULL,
  unreal_pnl REAL NOT NULL, notional REAL NOT NULL,
  PRIMARY KEY (cycle_ts, symbol));

CREATE TABLE equity_curve (
  cycle_ts INTEGER PRIMARY KEY, equity REAL NOT NULL, cash REAL NOT NULL,
  gross REAL NOT NULL, net REAL NOT NULL, n_pos INTEGER NOT NULL,
  drawdown REAL NOT NULL, var_1d_99 REAL, hwm REAL NOT NULL);

CREATE TABLE cycles (
  cycle_ts INTEGER PRIMARY KEY,
  status TEXT NOT NULL,          -- STARTED|SIGNALS_DONE|ORDERS_SUBMITTED|FILLS_DONE|COMPLETE|FAILED
  started_ms INTEGER NOT NULL, finished_ms INTEGER, error TEXT);

CREATE TABLE target_weights (
  cycle_ts INTEGER NOT NULL, symbol TEXT NOT NULL,
  mu_ann REAL NOT NULL, weight_opt REAL NOT NULL, weight_final REAL NOT NULL,
  PRIMARY KEY (cycle_ts, symbol));

CREATE TABLE funding_events (
  ts INTEGER NOT NULL, symbol TEXT NOT NULL, funding_rate REAL NOT NULL,
  position_qty REAL NOT NULL, mark_price REAL NOT NULL, payment REAL NOT NULL,
  PRIMARY KEY (ts, symbol));

CREATE TABLE risk_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL,
  kind TEXT NOT NULL, severity TEXT NOT NULL, detail TEXT NOT NULL, action TEXT NOT NULL);

CREATE TABLE recon_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL, symbol TEXT,
  internal_qty REAL, broker_qty REAL, diff REAL, action TEXT NOT NULL);

CREATE TABLE kill_switch (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL,
  engaged INTEGER NOT NULL, source TEXT NOT NULL, reason TEXT NOT NULL, operator TEXT);
```

Access: stdlib `sqlite3` run via `asyncio.to_thread` (single writer; WAL gives concurrent readers for the tearsheet job). No ORM — typed accessor functions in `StateStore`.

### 9.2 The hourly cycle (`loop.py`)

Plain asyncio, no APScheduler (one fewer moving part; drift control is explicit):

```python
def next_cycle_ts(now_s: int, bar_s: int = 3600, grace_s: int = 20) -> int:
    """Next bar close + grace. grace_s=20: Binance finalizes the kline within seconds; 20s is safe margin."""

class LiveLoop:
    def __init__(self, cfg: LiveConfig, pipeline: SignalPipeline,  # data+features+model (other areas)
                 optimizer: MeanVarianceOptimizer, risk: RiskEngine,
                 om: OrderManager, broker: Broker, store: StateStore, alerts: TelegramAlerter) -> None: ...
    async def run_forever(self) -> None: ...
    async def run_cycle(self, cycle_ts: int) -> None: ...
```

`run_cycle(cycle_ts)` — every stage writes its `cycles.status` transition *before* proceeding (the crash-recovery ladder), each stage has its own timeout and try/except → FAILED + alert:

```
0. kill-switch & staleness gate; Reconciler.reconcile()
1. ingest: confirm bar cycle_ts present for universe (data layer)        → SIGNALS_DONE after 3
2. funding: if cycle_ts is a funding boundary, ledger.apply_funding per perp position
3. features → model.predict → blended alpha → mu_ann (other areas' frozen artifacts)
4. covariance update; optimizer.solve; vol-target overlay; weights_to_orders
5. PreTradeChecker on each order                                          
6. om.execute_batch(orders, cycle_ts)                                    → ORDERS_SUBMITTED → FILLS_DONE
7. persist: positions snapshot, equity point, target_weights             
8. monitors: DD ladder, VaR, per-asset stops (may queue forced orders for next cycle)
9. alerts: trade summary if traded; heartbeat every 8h; daily tearsheet job at 00:05 UTC → COMPLETE
```

### 9.3 Crash recovery (`recovery.py`) — exact startup algorithm

1. Open DB; read kill-switch (file sentinel overrides DB).
2. `Reconciler.reconcile()` — adopt broker truth for positions/cash; audit rows.
3. Find orders with status ∈ {PENDING_NEW, NEW, PARTIALLY_FILLED, UNKNOWN}: `fetch_order` by `client_order_id`; update terminal states; ingest missed fills via `fills_since(last_fill_ts)`.
4. Rebuild in-memory `Ledger` = last `positions_snapshots` row-set + all subsequent fills + funding events (replay).
5. Read last `cycles` row. If status ≠ COMPLETE **and** `now < cycle_ts + bar_s`: resume `run_cycle` at the stage after the recorded status (idempotency keys make stage 6 re-entry safe). Otherwise mark FAILED, alert, sleep until next boundary.

Because cycles are keyed by `cycle_ts` (PRIMARY KEY) and order ids are deterministic per cycle, restarting mid-bar can never double-process a bar or double-submit an order.

### 9.4 Alerting (`alerts.py`)

Raw Telegram Bot API over `httpx` (no python-telegram-bot dependency): `POST https://api.telegram.org/bot{TOKEN}/sendMessage`. Config via env `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

- Severities: INFO (batched into heartbeat), WARN (immediate), CRIT (immediate, re-sent every 15 min until `/ack`).
- Inbound (long-poll `getUpdates` every 60 s, chat-id allowlisted): `/status` (equity, DD, gross, positions), `/halt` (pause new orders), `/flatten`, `/kill`, `/ack`. **No `/arm`** (CLI only).
- Daily 00:05 UTC: tearsheet PNG + metrics sent as Telegram photo + caption — mobile-first owner reads the day's P&L in bed.

---

## 10. Analytics (`alphaforge/analytics/`)

### 10.1 Metrics (`metrics.py`) — exact definitions, `A = periods_per_year` (8760 for 1h crypto)

Per-bar simple returns `r_t = E_t/E_{t−1} − 1`, T bars, risk-free = 0 (idle USDT earns nothing in v1; documented):

```
CAGR     = (E_T / E_0)^(A/T) − 1
Sharpe   = mean(r) / std(r, ddof=1) · sqrt(A)
Sortino  = mean(r) / sigma_down · sqrt(A),   sigma_down = sqrt( (1/T) Σ_t min(r_t, 0)² )   # full-T denominator, target 0
MaxDD    = max_t ( 1 − E_t / max_{s≤t} E_s )
Calmar   = CAGR / MaxDD
Turnover = (1/T) Σ_t τ_t · A,   τ_t = Σ_i |traded notional_{i,t}| / E_t      # one-way, annualized
```

Documented caveat in the docstring: hourly Sharpe assumes iid bars; positive autocorrelation inflates it (Lo 2002). v1 reports the standard estimator and additionally the same Sharpe computed on daily-aggregated returns — if the two disagree wildly, distrust the hourly one.

```python
def sharpe(returns: np.ndarray, periods_per_year: float, rf: float = 0.0) -> float: ...
def sortino(returns: np.ndarray, periods_per_year: float) -> float: ...
def max_drawdown(equity: np.ndarray) -> tuple[float, int, int]:
    """(max_dd, peak_idx, trough_idx)."""
def calmar(equity: np.ndarray, periods_per_year: float) -> float: ...
```

### 10.2 Attribution (`attribution.py`)

- Per-asset: `pnl_contrib_{i,t} = w_{i,t−1} · r_{i,t}` (weights from `positions.parquet` / `positions_snapshots`).
- Per-sleeve (factor): the alpha layer persists pre-blend sleeve weights `w^k` and blend shares `a_k` at each rebalance; sleeve PnL `= a_k Σ_i w^k_{i,t−1} r_{i,t}`. Costs and funding attributed pro-rata to |traded notional| and |perp weight| respectively. Sleeve sum reconciles to total within rounding — asserted.

### 10.3 Tearsheet (`tearsheet.py`)

`make_tearsheet(result, out_dir) -> Path`: one matplotlib figure (PNG, 6 panels: equity (log) + HWM, drawdown, rolling 30d Sharpe, gross/net exposure, turnover, monthly return heatmap) + `metrics.json` with every number from §10.1. Same function serves backtests and the live daily job.

### 10.4 Walk-forward orchestrator (`walkforward.py`)

```python
class WalkForwardRunner:
    def __init__(self, train_days: int = 365, test_days: int = 30,
                 purge_days: int = 5, embargo_days: int = 1) -> None: ...
    def run(self, fit_fn: Callable[[TrainSlice], Model], data: BarSource,
            backtester_factory: Callable[..., EventDrivenBacktester]) -> WalkForwardResult:
        """Rolling folds; one CONTINUOUS event-driven backtest where the model swaps at fold
        boundaries (positions persist across boundaries — realistic). Returns stitched OOS
        equity curve + per-fold metrics table."""
```

- Fold k: train `[t0 + 30k·d, t0 + 30k·d + 365d)`; **purge gap = 5d** between train end and test start — must be ≥ the triple-barrier max horizon (constant shared with the ML layer via config, asserted equal, not duplicated). Embargo 1d on top as feature-window hygiene. Test = next 30d; roll by 30d.
- Output: one out-of-sample equity curve spanning all test windows (this is the number that matters), plus per-fold Sharpe/DD table to spot regime fragility.

---

## 11. Library choices & Apple Silicon notes

| Library | Use | Rationale / arm64 gotchas |
|---|---|---|
| numpy ≥ 2.0, pandas ≥ 2.2 | numerics, frames at module boundaries | arm64 wheels use Apple Accelerate — fast, no compile. |
| **cvxpy ≥ 1.5 + Clarabel** (OSQP fallback) | MVO | Clarabel is pure Rust, ships native arm64 wheels, modern cvxpy default, handles the QP+L1 problem natively. **Avoid CVXOPT/GLPK** (source builds, BLAS pain on Apple Silicon). |
| ccxt ≥ 4.x (`async_support`) | CCXTBroker, exchange metadata | Unified `clientOrderId` support; pure Python. |
| stdlib `sqlite3` (WAL) via `asyncio.to_thread` | state | Zero deps, single-writer fits. Python wheel bundles its own libsqlite (macOS system one is ancient — irrelevant). **Gotcha: keep the DB outside iCloud/Dropbox-synced folders** — file-sync vs SQLite locking corrupts databases; `~/alphaforge/state/` must be excluded from iCloud Drive sync. |
| httpx | Telegram | Async, tiny; skip python-telegram-bot's weight. |
| pydantic v2 | configs | Rust-core validation, arm64 wheels. |
| matplotlib | tearsheets | Use `Agg` backend explicitly (headless 24/7 process; never let it try Cocoa). |
| pytest + hypothesis | tests | Property tests for Ledger/funding invariants. |
| (ML area, noted) LightGBM | — | needs `brew install libomp` on Apple Silicon; not my area but it shares the venv. |

Not used, deliberately: APScheduler (hand-rolled boundary sleep is simpler and drift-explicit), tenacity (15-line deterministic backoff is more testable), quantstats (unmaintained; we need exact, owned formulas), any ORM.

Also: run the live process under `launchd` (KeepAlive) or a `tmux` + restart-wrapper script; macOS App Nap must be avoided — `caffeinate -i` wrapper or launchd `ProcessType: Background`.

## 12. Build order (dependency-driven)

1. `core/types.py`, `core/calendar.py`, `core/config.py` — everything imports these.
2. `costs/` — pure functions; exhaustive unit tests with hand-computed expected values (these numbers gate everything downstream).
3. `backtest/ledger.py` — property tests (equity invariance under fill+reverse-fill, funding sign, flip accounting).
4. `analytics/metrics.py` — needed to evaluate anything; golden tests vs hand-computed toy series.
5. `backtest/fills.py` + `backtest/engine.py` + `result.py` — golden-master test: 3-asset synthetic dataset, scripted strategy, every fill/fee/funding/equity value asserted to the cent.
6. `backtest/vectorized.py` + parity test vs engine (§5).
7. `portfolio/` — covariance (test vs brute-force LW on small matrices), optimizer (test KKT-style sanity: zero cost + no constraints ⇒ `w ≈ (1/λ)Σ⁻¹μ`), overlay, discretize.
8. `risk/` — unit tests per check; DD-ladder state-machine test.
9. `execution/broker.py` + `paper.py` + `order_manager.py` — OrderManager tested against a `FlakyBroker` test double (timeouts, duplicate acks, partial fills).
10. `live/store.py` + `recovery.py` — kill-the-process-mid-cycle integration test (subprocess, SIGKILL at each stage, assert clean recovery).
11. `live/loop.py` + `alerts.py` + `execution/reconcile.py` — then soak: 2 weeks paper on 5 symbols before widening the universe.
12. `analytics/walkforward.py` + `tearsheet.py` (needs 5 + 7; can proceed in parallel with 9–11).

## 13. Top 5 ways this area silently produces wrong results — and the safeguard

1. **Same-bar lookahead in fills** (filling at bar *t* prices an order decided at bar *t* close — inflates every backtest, the classic career-ender). *Safeguard:* the FillModel structurally receives only bar `t+1`; engine asserts `order.cycle_ts < fill_bar.close_ts` on every fill (`LookaheadError`); regression test asserts a signal on the final bar produces zero fills.
2. **Funding sign or timing error on perps** (a flipped sign turns a real cost into fake alpha; funding often exceeds fee PnL in crypto). *Safeguard:* hypothesis property test `qty>0, f>0 ⇒ payment<0` and `long+short of equal size ⇒ net funding ≈ 0`; golden test reproducing hand-computed funding for a real historical BTC perp position against Binance's published rates.
3. **Cost-model drift between vectorized research, event-driven backtest, and PaperBroker** (research trades a strategy whose costs production doesn't match — slow bleed that looks like "bad luck"). *Safeguard:* one `TransactionCostModel` class imported by all three (no constants live anywhere else), plus the CI parity test (§5) and a weekly live report comparing realized fill slippage vs modeled slippage per trade.
4. **Annualization/unit mismatch in μ vs Σ** (e.g. per-bar μ with annualized Σ mis-scales every position by ~8760× inside the optimizer — output can still look superficially plausible). *Safeguard:* mandatory `_ann`/`_bar` suffix convention; optimizer asserts `0.01 ≤ ex_ante_vol_ann ≤ 2.0` and `assert cov_ann.trace()/N > 0.001` before returning weights; violation refuses to trade and alerts.
5. **Stale data masquerading as low volatility** (feed silently dies → flat prices → EWMA vol collapses → vol targeting and the optimizer lever up into an outage; then real prices return with a gap). *Safeguard:* staleness circuit breaker runs *before* any signal computation (quarantine at 2× bar age, global halt at 25% universe), `s_max = 1.5` hard-caps the vol-target scale regardless, and the reconciliation/equity cross-check catches any book divergence the outage caused.

### Critical Files for Implementation
- /Users/arhancanli/alphaforge/alphaforge/core/types.py
- /Users/arhancanli/alphaforge/alphaforge/costs/model.py
- /Users/arhancanli/alphaforge/alphaforge/backtest/engine.py
- /Users/arhancanli/alphaforge/alphaforge/portfolio/optimizer.py
- /Users/arhancanli/alphaforge/alphaforge/live/loop.py
