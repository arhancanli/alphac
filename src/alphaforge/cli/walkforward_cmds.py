"""``af research walkforward`` — the purged walk-forward OOS evaluation.

Wiring follows ``af backtest``/``af research``: lake at
``settings.paths.lake_dir``, SCD2 instruments in ``settings.paths.var_dir /
"ops.sqlite"``, artifacts under ``settings.paths.artifacts_dir /
"walkforward" / <run_id>``. All CLI timestamps are UTC (bare ``YYYY-MM-DD``
= UTC midnight).

Heavy imports (pandas, duckdb, cvxpy via the portfolio layer, matplotlib via
analytics) are deferred into the command body so ``af --help`` stays fast.
This module is not registered in ``cli/main.py`` here — the phase auditor
wires it (e.g. ``research_app.add_typer(walkforward_app)`` or
``research_app.command("walkforward")(walkforward)``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final

import typer

from alphaforge.core.errors import NaiveDatetimeError
from alphaforge.core.time import Ms, Timeframe, floor_bar, now_ms, parse_utc

if TYPE_CHECKING:
    import pandas as pd
    import pyarrow as pa

    from alphaforge.config.settings import Settings
    from alphaforge.data.store.reader import PITDataReader

__all__ = ["walkforward", "walkforward_app"]

walkforward_app = typer.Typer(
    name="walkforward",
    help="Purged walk-forward out-of-sample evaluation of the blend strategy.",
    no_args_is_help=False,
)

_OPS_DB: Final[str] = "ops.sqlite"


def _parse_cli_utc(value: str, *, param: str) -> Ms:
    """Parse a CLI timestamp to epoch ms UTC (bare ``YYYY-MM-DD`` = UTC midnight)."""
    try:
        return parse_utc(value)
    except NaiveDatetimeError:
        candidate = f"{value}T00:00:00Z" if len(value) == 10 else f"{value}Z"
        try:
            return parse_utc(candidate)
        except (NaiveDatetimeError, ValueError) as exc:
            raise typer.BadParameter(
                f"{param}: cannot parse {value!r} as a UTC timestamp "
                "(use YYYY-MM-DD or ISO-8601 with an explicit offset)"
            ) from exc
    except ValueError as exc:
        raise typer.BadParameter(f"{param}: invalid timestamp {value!r}: {exc}") from exc


def _load_settings(profile: str | None) -> Settings:
    from alphaforge.config.settings import load_settings

    return load_settings(profile)


# The "market" the HMM regime gate observes (regime_features.py's documented BTC
# anchor): the one place the daily-BTC instrument is defined, reused here so the
# regime gate and the regime-correlation factors agree on what "the market" is.
_BTC_ANCHOR: Final[str] = "BINANCE:PERP:BTCUSDT"


class _PITDailyBtcReader:
    """Concrete :class:`~alphaforge.analytics.walkforward.DailyBtcReader` over the lake.

    Returns daily BTC OHLC over ``[start, end)`` as the int64-``ts_open``-indexed float
    OHLC frame :func:`alphaforge.regime.hmm.build_observations` consumes. The
    point-in-time read is clamped at ``end`` (the runner already slices the result to
    ``ts_open < test_start`` per leg, so the only freshness ``end`` adds is "no bar that
    closes after the run window"). Daily bars come from the resampler-derived
    ``ohlcv_1d`` dataset (``PITDataReader.ohlcv(tf=Timeframe.D1)``); when the lake has
    no derived daily bars yet, falls back to the SANCTIONED in-memory resampler
    (:func:`alphaforge.data.store.resample.resample_bars`, 1h→1d) — never an ad-hoc
    pandas resample (D3 / dataDesign.md §4.4: one source of truth for derived bars).
    """

    def __init__(self, reader: PITDataReader, instrument_id: str = _BTC_ANCHOR) -> None:
        self._reader = reader
        self._instrument_id = instrument_id

    def read_daily_btc(self, start: Ms, end: Ms) -> pd.DataFrame:
        """Daily BTC OHLC over ``[start, end)`` indexed by int64 ``ts_open``."""
        daily = self._reader.ohlcv(
            [self._instrument_id], start=start, end=end, as_of=end, tf=Timeframe.D1
        )
        if daily.num_rows == 0:
            # No derived 1d bars in the lake: resample the 1h BTC bars in-memory via the
            # sanctioned resampler (closed-bucket + completeness rules), never ad hoc.
            from alphaforge.data.store.resample import resample_bars

            hourly = self._reader.ohlcv(
                [self._instrument_id], start=start, end=end, as_of=end, tf=Timeframe.H1
            )
            daily = resample_bars(hourly, source=Timeframe.H1, target=Timeframe.D1, now=end).table
        return self._to_frame(daily)

    @staticmethod
    def _to_frame(daily: pa.Table) -> pd.DataFrame:
        """Arrow daily OHLC -> int64-``ts_open``-indexed float OHLC frame (build_observations)."""
        import pandas as pd
        import pyarrow as pa

        ts = daily.column("ts_open").cast(pa.int64()).to_numpy(zero_copy_only=False)
        return pd.DataFrame(
            {
                "open": daily.column("open").to_numpy(zero_copy_only=False),
                "high": daily.column("high").to_numpy(zero_copy_only=False),
                "low": daily.column("low").to_numpy(zero_copy_only=False),
                "close": daily.column("close").to_numpy(zero_copy_only=False),
            },
            index=pd.Index(ts, dtype="int64", name="ts_open"),
        )


@walkforward_app.command()
def walkforward(
    start: Annotated[
        str,
        typer.Option("--start", help="Window start, UTC (YYYY-MM-DD or ISO-8601), 1h-aligned."),
    ],
    end: Annotated[
        str | None,
        typer.Option("--end", help="Window end (exclusive), UTC; default: now, floored to 1h."),
    ] = None,
    train_days: Annotated[
        int,
        typer.Option("--train-days", min=4, help="Train/warm-up window per leg, in days."),
    ] = 365,
    test_days: Annotated[
        int,
        typer.Option("--test-days", min=1, help="Out-of-sample test span per leg, in days."),
    ] = 91,
    allocator: Annotated[
        str,
        typer.Option("--allocator", help="Portfolio allocator: 'rank' (v1 primary) or 'mvo'."),
    ] = "rank",
    rebalance_bars: Annotated[
        int,
        typer.Option(
            "--rebalance-bars",
            min=1,
            help="Bars between rebalances (turnover knob). Default 24 (daily); set to "
            "signals.horizon_bars (72) to match the 3-day signal horizon and cut turnover.",
        ),
    ] = 24,
    no_trade_band: Annotated[
        float | None,
        typer.Option(
            "--no-trade-band",
            min=0.0,
            help="No-trade band as a fraction of equity (turnover knob). Default: "
            "settings.portfolio.no_trade_band (0.0010 = 10bps). Widen (e.g. 0.0030) to "
            "suppress sub-cost-hurdle churn.",
        ),
    ] = None,
    cash: Annotated[
        float,
        typer.Option("--cash", min=0.0, help="Initial cash in quote units (USDT), leg 0 only."),
    ] = 100_000.0,
    ids: Annotated[
        str | None,
        typer.Option(
            "--ids",
            help="Comma-separated canonical instrument ids; default: the PIT "
            "universe members overlapping the window.",
        ),
    ] = None,
    out: Annotated[
        str | None,
        typer.Option(
            "--out",
            help="Artifact directory. Default: <artifacts_dir>/walkforward/<UTC timestamp>.",
        ),
    ] = None,
    alphas: Annotated[
        str | None,
        typer.Option(
            "--alphas",
            help="Comma-separated directional factor names to blend (factor-subset knob). "
            "Default: all registered directional alphas. Use to drop high-turnover/flat "
            "factors and tilt the book, e.g. 'carry_fund_21,carry_fund_90,mr_res_72'.",
        ),
    ] = None,
    ml: Annotated[
        bool,
        typer.Option(
            "--ml/--no-ml",
            help="Gate the blend by a per-leg-trained meta-model (|size| scales Ã; never "
            "flips). Default OFF — byte-identical to the shipped blend-only run.",
        ),
    ] = False,
    regime: Annotated[
        bool,
        typer.Option(
            "--regime/--no-regime",
            help="Multiply mu_ann by the per-leg-refit HMM gross multiplier G (filtered "
            "through day d-1; no same-day leak). Default OFF.",
        ),
    ] = False,
    profile: Annotated[
        str | None,
        typer.Option("--profile", help="Config profile overlay (configs/<profile>.yaml)."),
    ] = None,
) -> None:
    """Run the purged walk-forward and persist stitched equity + per-leg artifacts."""
    # Argument parsing FIRST — bad input must exit before any filesystem touch.
    from alphaforge.config.sleeve import sleeve_for

    start_ms = _parse_cli_utc(start, param="--start")
    settings = _load_settings(profile)
    sleeve = sleeve_for(settings.data.asset_class)
    # Days are ANCHOR-TF bars: 24 for H1 (crypto), 1 for D1 (equity, one bar per session).
    bars_per_day = 86_400_000 // sleeve.anchor_tf.ms
    # Default end floors to the sleeve anchor (D1 midnight for equity, the hour for crypto).
    end_ms = (
        floor_bar(now_ms(), sleeve.anchor_tf) if end is None else _parse_cli_utc(end, param="--end")
    )
    if allocator not in ("rank", "rank_long", "mvo"):
        raise typer.BadParameter(
            f"--allocator: must be 'rank', 'rank_long', or 'mvo', got {allocator!r}"
        )
    alloc: str = allocator
    instrument_ids: list[str] | None = None
    if ids is not None:
        instrument_ids = [tok.strip() for tok in ids.split(",") if tok.strip()]
        if not instrument_ids:
            raise typer.BadParameter(f"--ids: no instrument ids in {ids!r}")

    # Heavy wiring deferred (registers the factor library on import).
    from datetime import UTC, datetime

    import alphaforge.features.library  # noqa: F401  (registers the factor library)
    from alphaforge.analytics import render_text
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.logging import setup_logging
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService

    setup_logging(settings.paths.var_dir / "log")
    if out is not None:
        out_dir = Path(out)
    else:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_dir = settings.paths.artifacts_dir / "walkforward" / run_id

    alpha_names: list[str] | None = None
    if alphas is not None:
        alpha_names = [tok.strip() for tok in alphas.split(",") if tok.strip()]
        if not alpha_names:
            raise typer.BadParameter(f"--alphas: no factor names in {alphas!r}")

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / _OPS_DB) as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            default_registry(),
            settings.signals,
            sleeve=sleeve,
            alpha_names=alpha_names,
        )
        # The regime gate needs a daily-BTC source for the per-leg expanding HMM fit
        # (D3). Construct the thin PIT adapter ONLY when --regime is on; the blend-only
        # and --ml paths never touch it, so their wiring is byte-identical to today.
        daily_btc_reader = _PITDailyBtcReader(reader) if regime else None
        runner = WalkForwardRunner(
            reader,
            store,
            universe,
            TransactionCostModel.from_settings(settings),
            service,
            settings,
            daily_btc_reader=daily_btc_reader,
        )
        try:
            result = runner.run(
                start_ms,
                end_ms,
                train_bars=train_days * bars_per_day,
                test_bars=test_days * bars_per_day,
                allocator=alloc,  # "rank" | "rank_long" | "mvo" (validated above)
                embargo_bars=sleeve.embargo_bars,
                rebalance_bars=rebalance_bars,
                no_trade_band=no_trade_band,
                initial_cash=cash,
                instrument_ids=instrument_ids,
                out_dir=out_dir,
                # The wall-clock read happens HERE (the CLI edge), passed in so
                # the runner stays deterministic; it stamps the experiment-ledger
                # trial. alpha_names feeds the trial's anti-overfit config hash.
                now_ms=now_ms(),
                alpha_names=alpha_names,
                ml=ml,
                regime=regime,
            )
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc

    typer.echo(render_text(result.summary))
    typer.echo("")
    for leg in result.legs:
        s = leg.result.summary
        typer.echo(
            f"leg {leg.leg:02d}  test [{leg.test_start} .. {leg.test_end})  "
            f"equity {s.initial_equity:,.2f} -> {s.final_equity:,.2f}  "
            f"sharpe {s.sharpe:.2f}  max_dd {s.max_dd:.2%}"
        )
    if result.validation is not None:
        v = result.validation
        verdict = "CLEARS" if v.clears_dsr_gate else "FAILS"
        typer.echo("")
        typer.echo(
            f"validation  PSR {v.psr:.4f}  DSR {v.dsr:.4f}  (gate 0.95: {verdict})  "
            f"SR_ann {v.sr_ann:.2f}  N_trials {v.n_trials}  SR* {v.expected_max_sr:.4f}"
        )
        # Phase-12 gate line: only when a gate is on (a gated run carries a baseline);
        # the blend-only run's output is byte-identical to today.
        if v.baseline is not None:
            beats = "True" if v.clears_baseline_gate else "False"
            typer.echo(
                f"variant {v.variant}  DSR {v.dsr:.4f} vs baseline {v.baseline.dsr:.4f}  "
                f"beats-baseline: {beats}  gate-inactive {v.gate_inactive_frac:.0%}"
            )
    typer.echo(f"artifacts: {out_dir}")
