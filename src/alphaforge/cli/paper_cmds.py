"""``af paper`` -- run, inspect, and (refuse to) arm the live PAPER trading loop.

Three commands (execDesign.md section 9; buildabilityCritique.md section 1):

* ``af paper run`` -- start the single-timer 24/7 loop (``--once`` runs exactly
  one cycle for the current bar then exits; that mode drives the soak/cron and
  the crash test). PAPER money only.
* ``af paper status`` -- the operator dashboard: last cycle, N/M expected-vs-run
  cycle accounting (buildabilityCritique.md section 4 -- missed cycles are never
  silent), the current paper book + equity, the drawdown-ladder state, and any
  open intents left in flight.
* ``af paper arm`` -- PRINTS the real-money arming contract and REFUSES in v1.
  Real trading (CCXTBroker) stays NotArmed; arming is a deliberate later flip
  (config ``live.paper=False`` AND env ``ALPHAFORGE_ARMED=1`` AND a Phase-8+ code
  path), never reachable from here.

Wiring mirrors ``af backtest`` / ``af data``: the lake lives at
``settings.paths.lake_dir``; the SCD2 instrument record + ingest checkpoints live
in ``settings.paths.var_dir / "ops.sqlite"``; the trading source-of-truth SQLite
lives at ``settings.paths.var_dir / "trading.sqlite"``; the KILL sentinel at
``settings.paths.var_dir / "KILL"``. Telegram credentials come from the
environment (``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``); absent, alerts fall
back to the structured log. All printed timestamps are UTC.

Heavy imports (pyarrow, duckdb, pandas, the feature/signal stack) are deferred
into command bodies so ``af --help`` stays fast.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Annotated, Final

import typer

from alphaforge.core.time import Ms, from_ms, now_ms

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from alphaforge.backtest.engine import StrategyContext
    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import Instrument, InstrumentStore
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.live.loop import CostInputSource, LiveLoop
    from alphaforge.live.store import TradingStore

__all__ = ["paper_app"]

paper_app = typer.Typer(
    name="paper",
    help="24/7 PAPER trading loop: run the hourly cycle, inspect status, arm (refused in v1).",
    no_args_is_help=True,
)

_OPS_DB: Final[str] = "ops.sqlite"
_TRADING_DB_STEM: Final[str] = "trading"  # per-sleeve -> trading_{asset_class}.sqlite
_KILL_FILE: Final[str] = "KILL"
_VISION_DELAY_S: Final[float] = 0.2
_TELEGRAM_TOKEN_ENV: Final[str] = "TELEGRAM_BOT_TOKEN"
_TELEGRAM_CHAT_ENV: Final[str] = "TELEGRAM_CHAT_ID"

_ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", help="Config profile overlay (configs/<profile>.yaml)."),
]


def _load_settings(profile: str | None) -> Settings:
    from alphaforge.config.settings import load_settings

    return load_settings(profile)


def _trading_db_path(settings: Settings) -> Path:
    """Per-sleeve trading DB. Each live algorithm owns its own NAV/positions/orders
    SQLite so two loops never write the same book (AlphaForge=crypto_perp,
    AlphaMax=equity); the cross-asset ALPHAC curve is combined downstream from both."""
    return settings.paths.var_dir / f"{_TRADING_DB_STEM}_{settings.data.asset_class.value}.sqlite"


def _fmt_ts(ms: Ms | None) -> str:
    """Epoch ms UTC -> compact ISO string (``-`` for None)."""
    if ms is None:
        return "-"
    return from_ms(ms).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- adapters


class _UpdaterAdapter:
    """Drives :meth:`BackfillJob.update` for the loop (the single ingest clock),
    scoped to the CURRENT trading universe (resolved per cycle) so each cycle ingests
    only the handful of names it will actually trade - fast and robust, never a slow
    full-universe sweep that one hung fetch could stall. The wider candidate set is
    kept fresh for the monthly rebuild by the daily broad ``af data update``."""

    __slots__ = ("_job", "_members")

    def __init__(self, job: object, members: Callable[[Ms], list[str]]) -> None:
        self._job = job
        self._members = members

    def update(self, *, as_of: Ms) -> object:
        """Ingest only the current universe members up to ``as_of`` (report ignored)."""
        ids = self._members(as_of)
        return self._job.update(as_of=as_of, instrument_ids=ids or None)  # type: ignore[attr-defined]


class _WatermarkAdapter:
    """Reports lake freshness via the reader's freshest fully-available bar open."""

    __slots__ = ("_reader", "_tf")

    def __init__(self, reader: PITDataReader, tf: object) -> None:
        self._reader = reader
        self._tf = tf

    def latest_bar_open(self, instrument_ids: Sequence[str], *, as_of: Ms) -> Ms | None:
        """Min over the universe of each id's freshest bar open (the staleness floor).

        The universe is fresh enough to trade only when EVERY member has the
        just-closed bar; the minimum freshest-open across ids is therefore the
        gate. An id with no data at all makes the universe stale (returns None).
        """
        from alphaforge.core.time import Timeframe

        tf = self._tf if isinstance(self._tf, Timeframe) else Timeframe.H1
        floor: Ms | None = None
        for iid in instrument_ids:
            latest = self._reader.latest_bar_open(iid, as_of=as_of, tf=tf)
            if latest is None:
                return None
            floor = latest if floor is None else min(floor, latest)
        return floor


class _InstrumentsAdapter:
    """Resolves the tradable ``{id: Instrument}`` at a cycle: PIT universe x record,
    scoped to this profile's asset class. The shared universe store + SCD2 record hold
    every class (crypto perps + the equities universe); a single-asset live loop must
    only ever trade its own, or it would size/freshness-check over another class's names
    that this loop's data source never ingests."""

    __slots__ = ("_asset_class", "_instruments", "_universe")

    def __init__(
        self, universe: object, instruments: InstrumentStore, asset_class: object
    ) -> None:
        self._universe = universe
        self._instruments = instruments
        self._asset_class = asset_class

    def __call__(self, cycle_ts: Ms) -> Mapping[str, Instrument]:
        """PIT members at ``cycle_ts`` with a valid record AND in this asset class."""
        members = self._universe.membership_asof(cycle_ts)  # type: ignore[attr-defined]
        out: dict[str, Instrument] = {}
        for iid in sorted(members):
            inst = self._instruments.get(iid, cycle_ts)
            if inst is not None and inst.asset_class == self._asset_class:
                out[iid] = inst
        return out


#: Blend-weight cache TTL. The Rank-IC blend weights are EWMA-smoothed (halflife
#: ~60d), so they move negligibly hour-to-hour; recomputing the multi-minute
#: estimate_weights every hourly cycle is pure waste. Cache them on disk and
#: refresh at most once per this interval -> the per-cycle cost collapses to the
#: ~1-2s on_bar_close. 25h means a daily refresh that tolerates a missed cycle.
_WEIGHTS_CACHE_TTL_S: Final[float] = 25 * 3600.0


class _MuProviderAdapter:
    """``(decision_ts) -> {id: mu_ann}`` over ``SignalService.on_bar_close``.

    The blend weights (slow-moving, EWMA-smoothed Rank-IC) are estimated at most
    once per ``_WEIGHTS_CACHE_TTL_S`` and persisted to ``cache_path`` (pickle, an
    atomic tmp+replace). A fresh cycle loads the cached weights instantly and does
    only the cheap per-bar ``on_bar_close``; a stale/absent cache triggers one
    (multi-minute) re-estimate that the next 24h of cycles then reuse. The cached
    weights' grid ends a few hours back, but ``asof`` returns its last row -- a
    <2% drift at a 60d halflife, far inside the live/research EWMA tolerance. An
    empty/failed signal yields ``{}`` (HOLD).
    """

    __slots__ = ("_cache_path", "_service", "_weights", "_window_start")

    def __init__(self, service: object, window_start_ms: Ms, cache_path: Path) -> None:
        self._service = service
        self._window_start = window_start_ms
        self._weights: object | None = None
        self._cache_path = cache_path

    def _load_or_estimate(self, decision_ts: Ms) -> object:
        import pickle
        import time

        p = self._cache_path
        try:
            if p.is_file() and (time.time() - p.stat().st_mtime) < _WEIGHTS_CACHE_TTL_S:
                with p.open("rb") as fh:
                    return pickle.load(fh)
        except Exception:
            pass
        weights = self._service.estimate_weights(  # type: ignore[attr-defined]
            self._window_start, decision_ts
        )
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            with tmp.open("wb") as fh:
                pickle.dump(weights, fh)
            tmp.replace(p)  # atomic publish
        except Exception:
            pass
        return weights

    def __call__(self, decision_ts: Ms) -> Mapping[str, float]:
        from alphaforge.signals.sizing import MU_ANN_COLUMN

        if self._weights is None:
            self._weights = self._load_or_estimate(decision_ts)
        try:
            frame = self._service.on_bar_close(  # type: ignore[attr-defined]
                decision_ts, weights=self._weights
            )
        except ValueError:
            return {}
        col = frame[MU_ANN_COLUMN]
        return {str(iid): float(v) for iid, v in col.items() if _is_finite(v)}


class _CostInputsFactory:
    """Builds a per-cycle :class:`LakeCostInputs` over the trailing window."""

    __slots__ = ("_reader", "_warmup_ms")

    def __init__(self, reader: PITDataReader, warmup_ms: Ms) -> None:
        self._reader = reader
        self._warmup_ms = warmup_ms

    def __call__(self, cycle_ts: Ms, instrument_ids: Sequence[str]) -> CostInputSource:
        from alphaforge.backtest.engine import LakeCostInputs

        return LakeCostInputs(
            self._reader,
            list(instrument_ids),
            start=cycle_ts - self._warmup_ms,
            end=cycle_ts,
        )


class _ContextFactory:
    """Builds the :class:`StrategyContext` the live BlendStrategy decides on."""

    __slots__ = ("_reader", "_tf")

    def __init__(self, reader: PITDataReader, tf: object) -> None:
        self._reader = reader
        self._tf = tf

    def __call__(
        self,
        *,
        cycle_ts: Ms,
        equity: float,
        positions: Mapping[str, float],
        instruments: Mapping[str, Instrument],
    ) -> StrategyContext:
        from alphaforge.backtest.engine import StrategyContext
        from alphaforge.core.time import Timeframe

        tf = self._tf if isinstance(self._tf, Timeframe) else Timeframe.H1
        return StrategyContext(
            reader=self._reader,
            tf=tf,
            ts=cycle_ts,
            equity=equity,
            positions=positions,
            instruments=instruments,
        )


def _is_finite(value: object) -> bool:
    """True iff ``value`` is a finite float (NaN/inf -> not a usable mu)."""
    import math

    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _build_ccxt_client(exchange_id: str) -> object:
    """Construct a rate-limited ccxt client for live order-book snapshots.

    Mirrors :class:`~alphaforge.data.sources.ccxt_source.CCXTDataSource`'s own
    client construction so the paper book source pulls real depth from the same
    venue. Imported lazily (never at module load); only the live ``af paper run``
    path reaches here, never the offline test suite (which injects a fake book).
    """
    import ccxt

    from alphaforge.core.errors import ConfigError

    exchange_cls = getattr(ccxt, exchange_id, None)
    if exchange_cls is None:
        raise ConfigError(f"unknown ccxt exchange id {exchange_id!r}: no such class on ccxt")
    # HARD per-request timeout (15s): a live order-book fetch with no timeout can
    # stall the whole cycle indefinitely (the fill has no other clock). With it, a
    # stalled fetch raises RequestTimeout fast and the snapshot retry / the loop's
    # own exception backstop take over instead of hanging.
    return exchange_cls({"enableRateLimit": True, "timeout": 15000})


# --------------------------------------------------------------------------- run


@paper_app.callback()
def _paper() -> None:
    """24/7 PAPER trading (PAPER money only; real trading is NotArmed)."""
    # Explicit callback keeps run/status/arm as named subcommands.


@paper_app.command()
def run(
    once: Annotated[
        bool,
        typer.Option(
            "--once/--forever",
            help="Run exactly one cycle for the current bar then exit "
            "(soak/cron/crash-test), or loop forever.",
        ),
    ] = False,
    cash: Annotated[
        float,
        typer.Option("--cash", min=0.0, help="Initial paper cash in quote units (USDT)."),
    ] = 100_000.0,
    profile: _ProfileOpt = None,
) -> None:
    """Start the live PAPER loop (the SAME decision stack as the backtest, live).

    Boots crash recovery + reconcile, then runs the hourly cycle: drive ingest ->
    read the closed bar -> signals -> portfolio -> risk -> PaperBroker (walks the
    real book) -> persist. ``--once`` runs a single cycle for the current bar (for
    the soak/cron and the SIGKILL crash test); ``--forever`` runs the single-timer
    tick loop until the process is signalled or the KILL sentinel engages.
    """
    from alphaforge.core.logging import setup_logging

    settings = _load_settings(profile)
    setup_logging(settings.paths.var_dir / "log")
    if not settings.live.paper:
        typer.echo(
            "refusing to run: live.paper is False but v1 trades PAPER only "
            "(real money is a NotArmed Phase-8+ flip). Set live.paper=true.",
            err=True,
        )
        raise typer.Exit(code=2)

    with _build_loop(settings, cash=cash) as loop:
        if once:
            from alphaforge.core.time import floor_bar

            loop.recover_on_boot()
            cycle_ts = floor_bar(now_ms(), settings.data.timeframe)
            report = loop.run_cycle(cycle_ts)
            typer.echo(
                f"cycle {report.cycle_ts} -> {report.status} "
                f"(orders={report.n_orders} filled={report.n_filled} "
                f"rejected={report.n_rejected}): {report.detail}"
            )
        else:
            typer.echo("starting live PAPER loop (ctrl-c or `touch var/KILL` to stop)")
            loop.run_forever()


# --------------------------------------------------------------------------- status


@paper_app.command()
def status(
    window_hours: Annotated[
        int,
        typer.Option("--window-hours", min=1, help="Cycle-accounting lookback window."),
    ] = 24,
    profile: _ProfileOpt = None,
) -> None:
    """Show the last cycle, N/M cycle accounting, the paper book, and open intents."""
    settings = _load_settings(profile)
    from alphaforge.live.store import TradingStore

    tf = settings.data.timeframe
    db = _trading_db_path(settings)
    if not db.exists():
        typer.echo(f"no trading store yet at {db} (run `af paper run` first)")
        return
    with TradingStore(db) as store:
        _print_status(settings, store, tf=tf, window_hours=window_hours)


def _print_status(
    settings: Settings,
    store: TradingStore,
    *,
    tf: object,
    window_hours: int,
) -> None:
    """Render the operator dashboard from the trading store (plain text)."""
    from alphaforge.core.time import Timeframe

    bar_ms = tf.ms if isinstance(tf, Timeframe) else Timeframe.H1.ms
    last = store.last_cycle()
    typer.echo("== af paper status ==")
    if last is None:
        typer.echo("no cycles recorded yet")
    else:
        typer.echo(
            f"last cycle: {_fmt_ts(last.cycle_ts)}  status={last.status}  "
            f"finished={_fmt_ts(last.finished_ms)}"
        )
        typer.echo(f"  detail: {last.detail}")

    # N/M cycle accounting over the window (buildabilityCritique.md section 4).
    if last is not None:
        end = last.cycle_ts
        start = end - (window_hours - 1) * bar_ms
        expected, run_, skipped = store.expected_vs_run(start, end, bar_ms)
        typer.echo(f"cycles last {window_hours}h: {run_}/{expected} run ({skipped} skipped/missed)")

    # Current paper book + equity.
    curve = store.equity_curve()
    if curve:
        cycle_ts, equity, cash, n_pos = curve[-1]
        typer.echo(
            f"equity: {equity:.2f}  cash: {cash:.2f}  positions: {n_pos}  "
            f"(as of {_fmt_ts(cycle_ts)})"
        )
        for pos in store.positions_at(cycle_ts):
            typer.echo(
                f"  {pos.instrument_id:<28} qty={pos.qty:+.6f} avg_entry={pos.avg_entry_price:.4f}"
            )
    else:
        typer.echo("equity: (no snapshot yet)")

    # Drawdown-ladder state: the TRUE live ladder the loop persisted (read-only).
    _print_ladder(store)

    # Open intents (orders left non-terminal -- a crash mid-cycle leaves these).
    open_intents = store.open_intents()
    if open_intents:
        typer.echo(f"open intents: {len(open_intents)}")
        for rec in open_intents:
            typer.echo(
                f"  {rec.client_order_id:<34} {rec.instrument_id:<24} "
                f"{rec.side.value:<4} status={rec.status} filled={rec.filled_qty:.6f}"
            )
    else:
        typer.echo("open intents: none")

    # KILL sentinel.
    kill_path = settings.paths.var_dir / _KILL_FILE
    typer.echo(f"kill switch: {'ENGAGED' if kill_path.exists() else 'clear'} ({kill_path})")


def _print_ladder(store: TradingStore) -> None:
    """Print the TRUE live drawdown-ladder state from the persisted snapshot.

    Reads the single latest :class:`~alphaforge.live.store.LadderSnapshot` the
    running loop recorded via ``store.record_ladder_state`` -- the SAME ladder the
    strategy sizes off, including its absorbing FLAT_HALTED state and any operator
    rearm. This deliberately does NOT replay a fresh ladder over the stored equity
    curve: a fresh replay has no memory of a rearm (which freezes the HWM and
    resets the state to NORMAL), so it would re-trip FLAT_HALTED on the historical
    drawdown and LIE about the current state. ``None`` (never recorded) prints a
    plain notice rather than a misleading estimate.
    """
    snapshot = store.last_ladder_state()
    if snapshot is None:
        typer.echo("ladder: no ladder snapshot yet")
        return
    typer.echo(
        f"ladder: {snapshot.state}  dd={snapshot.drawdown:.4f}  "
        f"gross_mult={snapshot.gross_mult:.2f}  hwm={snapshot.hwm:.2f}  "
        f"(as of {_fmt_ts(snapshot.cycle_ts)})"
    )


# --------------------------------------------------------------------------- arm


@paper_app.command()
def arm(profile: _ProfileOpt = None) -> None:
    """Print the real-money arming contract and REFUSE (v1 trades PAPER only).

    This command exists to DOCUMENT what arming will require, never to perform it.
    The real-money broker (:class:`~alphaforge.execution.ccxt_broker.CCXTBroker`)
    is a NotArmed stub: even with both gates set it raises on every order in v1.
    Arming is a deliberate Phase-8+ step, never reachable from this CLI.
    """
    settings = _load_settings(profile)
    from alphaforge.execution.ccxt_broker import ARM_ENV_VAR

    armed_env = os.environ.get(ARM_ENV_VAR)
    typer.echo("== real-money arming contract (REFUSED in v1) ==")
    typer.echo("AlphaForge trades PAPER money in v1. Real trading is NOT armable here.")
    typer.echo("")
    typer.echo("When real trading lands (Phase 8+), arming will require ALL of:")
    typer.echo("  1. config  live.paper = False           (a reviewed YAML change)")
    typer.echo(f"  2. env     {ARM_ENV_VAR}=1   (a typed, audited launch step)")
    typer.echo("  3. a deliberate code path placing real orders via CCXTBroker")
    typer.echo("")
    typer.echo("current gate state:")
    typer.echo(f"  live.paper            = {settings.live.paper}  (must be False to arm)")
    typer.echo(f"  {ARM_ENV_VAR:<20} = {armed_env!r}  (must be '1' to arm)")
    typer.echo("")
    typer.echo("REFUSED: real-money trading is disabled. Use `af paper run` for PAPER trading.")
    raise typer.Exit(code=1)


# --------------------------------------------------------------------------- wiring


class _LoopBundle:
    """Context-managed bundle owning every store the live loop opened.

    Closing it closes the trading store and the ops stores in one place so the
    CLI never leaks SQLite handles, whether the loop exits cleanly or raises.
    """

    __slots__ = ("_closers", "loop")

    def __init__(self, loop: LiveLoop, closers: Sequence[object]) -> None:
        self.loop = loop
        self._closers = tuple(closers)

    def __enter__(self) -> LiveLoop:
        return self.loop

    def __exit__(self, *exc: object) -> None:
        for closer in reversed(self._closers):
            close = getattr(closer, "close", None)
            if callable(close):
                close()


def _build_loop(settings: Settings, *, cash: float) -> _LoopBundle:
    """Compose the full live PAPER stack into a :class:`LiveLoop` (production wiring).

    Mirrors ``af backtest``/``af data``: builds the lake reader, the SCD2
    instrument record + ingest checkpoints, the PIT universe, the Phase-4 signal
    service, the live :class:`BlendStrategy`, the optimizer/risk surfaces, the
    :class:`PaperBroker` (over a live ccxt order-book source), the order
    manager/reconciler, the trading store, the alerter, and the ingest updater.
    Returns a :class:`_LoopBundle` so the caller closes every opened store.
    """
    import alphaforge.features.library  # noqa: F401  (registers the factor library)
    from alphaforge.backtest.engine import LakeCostInputs
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.ingest.backfill import BackfillJob
    from alphaforge.data.ingest.checkpoints import CheckpointStore
    from alphaforge.data.ingest.retry import RateBudget
    from alphaforge.data.sources.ccxt_source import CCXTDataSource
    from alphaforge.data.sources.vision import BinanceVisionClient
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.store.writer import LakeWriter
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.execution.order_manager import OrderManager
    from alphaforge.execution.paper import CCXTOrderBookSource, PaperBroker
    from alphaforge.execution.reconcile import Reconciler
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.live.alerts import build_alerter
    from alphaforge.live.loop import LiveLoop
    from alphaforge.live.store import TradingStore
    from alphaforge.portfolio.strategy import BlendStrategy
    from alphaforge.risk import (
        DrawdownLadder,
        KillSwitch,
        PreTradeChecker,
        RiskLimits,
        StalenessBreaker,
    )
    from alphaforge.signals.service import SignalService

    paths = LakePaths(settings.paths.lake_dir)
    reader = PITDataReader(paths)
    universe = UniverseStore(paths)
    cost_model = TransactionCostModel.from_settings(settings)

    ops_db = settings.paths.var_dir / _OPS_DB
    instruments = InstrumentStore(ops_db)
    checkpoints = CheckpointStore(ops_db)
    store = TradingStore(_trading_db_path(settings))

    # The Phase-4 signal seam -> the live mu_provider for the strategy.
    service = SignalService(
        FeatureEngine(reader, instruments, universe), universe, default_registry(), settings.signals
    )
    # Bound the live IC-estimation lookback to a trailing window. estimate_weights
    # EWMA-weights the Rank-IC (halflife ~60d), so 180 days = 3 halflives carries
    # >87% of the cumulative weight -- a numerically-equal estimate to the full
    # history, at a fraction of the compute. 180d keeps a fresh-boot --once cycle
    # to ~12-14 min (well inside the 30-min watchdog); the prior 400d ran ~27 min,
    # right at the watchdog edge. Older IC data (>180d) carries <13% EWMA weight.
    _LIVE_IC_LOOKBACK_MS = 180 * 86_400_000
    window_start = max(settings.data.backfill_start_ms, now_ms() - _LIVE_IC_LOOKBACK_MS)
    # Per-sleeve weight cache (crypto and equity blend weights differ); refreshed
    # at most daily so the hourly cycle is the cheap on_bar_close, not a re-estimate.
    weights_cache = settings.paths.var_dir / f"signal_weights_{settings.data.asset_class.value}.pkl"
    mu_provider = _MuProviderAdapter(service, window_start, weights_cache)

    # The SAME drawdown ladder instance the strategy uses (the loop never updates
    # it separately -- the strategy owns the equity marks).
    r = settings.risk
    ladder = DrawdownLadder(dd_half_frac=abs(r.dd_halve_gross), dd_flat_frac=abs(r.dd_flat_halt))
    strategy = BlendStrategy(settings, mu_provider=mu_provider)
    # Bind the loop's ladder to the strategy's so status/risk are consistent.
    ladder = strategy.ladder

    pretrade = PreTradeChecker(RiskLimits.from_cfg(settings.risk), cost_model)
    staleness = StalenessBreaker(max_bars=settings.risk.staleness_max_bars)
    kill = KillSwitch(settings.paths.var_dir / _KILL_FILE)
    alerter = build_alerter(os.environ.get(_TELEGRAM_TOKEN_ENV), os.environ.get(_TELEGRAM_CHAT_ENV))

    # Scope to THIS profile's asset class. The shared instrument record holds every
    # asset class (crypto perps + the equities universe); a single-asset live loop must
    # only ever ingest/trade its own class, or it would try to fetch a different class's
    # instruments (e.g. equity tickers) from the crypto source -- 404s that never
    # converge. The PaperBroker still covers every member the monthly universe can
    # select, WITHIN the class. The live ccxt order-book client is built the same way
    # CCXTDataSource builds its client (never imported at module load).
    book_source = CCXTOrderBookSource(_build_ccxt_client(settings.data.exchange))
    asset_class = settings.data.asset_class
    sleeve_instruments = [
        inst for inst in instruments.all_known(as_of=now_ms()) if inst.asset_class == asset_class
    ]
    broker_instruments = {inst.instrument_id: inst for inst in sleeve_instruments}
    broker = PaperBroker(
        broker_instruments,
        cost_model,
        book_source=book_source,
        initial_cash=cash,
    )
    order_manager = OrderManager(broker, store)
    reconciler = Reconciler(broker, store)

    budget = RateBudget()
    job = BackfillJob(
        CCXTDataSource(settings.data.exchange, rate_budget=budget),
        BinanceVisionClient(delay_s=_VISION_DELAY_S),
        LakeWriter(paths),
        checkpoints,
        instruments,
        rate_budget=budget,
        tf=settings.data.timeframe,
        lock_path=settings.paths.var_dir / "ingest.lock",
    )

    # One instruments factory, shared by the loop (what to trade) and the updater
    # (what to ingest) so the per-cycle ingest is exactly the current universe.
    instr_factory = _InstrumentsAdapter(universe, instruments, asset_class)
    loop = LiveLoop(
        settings,
        store=store,
        broker=broker,
        order_manager=order_manager,
        reconciler=reconciler,
        strategy=strategy,
        pretrade=pretrade,
        ladder=ladder,
        staleness=staleness,
        kill=kill,
        alerter=alerter,
        updater=_UpdaterAdapter(job, lambda ts: sorted(instr_factory(ts))),
        watermark=_WatermarkAdapter(reader, settings.data.timeframe),
        cost_inputs_factory=_CostInputsFactory(reader, LakeCostInputs.WARMUP_MS),
        ctx_factory=_ContextFactory(reader, settings.data.timeframe),
        instruments_factory=instr_factory,
        initial_cash=cash,
    )
    return _LoopBundle(loop, (store, checkpoints, instruments))
