#!/usr/bin/env python3
"""Self-driving, checkpointed grand-backtest harness (thin driver).

See ``docs/design/build/GRAND_BACKTEST.md``. This is the THIN ``scripts/``
orchestrator: it owns NO analysis logic. All matrix/deflation/verdict logic
lives in the tested ``alphaforge.analytics.grand_matrix`` module; here we only

  1. resolve the run timestamp + the clean window (probed from the live lake,
     never hardcoded — clamped into the requested ``--window``),
  2. build the bounded ~16-run matrix from ``grand_matrix.reference_matrix``,
  3. per config MIRROR the SHIPPED ``cli/walkforward_cmds.py`` wiring
     (``LakePaths`` -> ``PITDataReader`` -> ``InstrumentStore`` ctx-mgr ->
     ``UniverseStore`` -> ``FeatureEngine`` -> ``SignalService(...,
     default_registry(), settings.signals, alpha_names=...)`` ->
     ``TransactionCostModel.from_settings`` -> ``_PITDailyBtcReader`` only when
     ``regime=True``) and call ``WalkForwardRunner(...).run(...,
     experiment_log=<dedicated ledger>, out_dir=configs/<config_id>,
     now_ms=...)`` then ``WalkForwardResult.save``,
  4. CHECKPOINT/RESUME by skipping any config whose ``out_dir`` already holds a
     valid ``walkforward.json``,
  5. drive the two-pass ordering (Blocks A+C, then Block B off the deflated
     winner) and finally call the ``grand_matrix`` writers
     (``write_matrix_json`` + ``write_verdict`` + the capacity plot).

It is launched DETACHED by the operator (``caffeinate -dimsu nohup uv run
python scripts/grand_backtest.py > .../harness.log 2>&1 &``) so it survives the
laptop closing. Agents BUILD + SMOKE-TEST only: ``--smoke`` runs the WHOLE
control flow on a hermetic synthetic fixture (a tiny ``tmp`` lake + a synthetic
daily-BTC frame, ``instrument_ids`` passed explicitly so the live lake is never
touched, a small even PBO ``n_splits``) in seconds, exercising a Block-A run +
its baseline, a Block-C distinct trial, a Block-B capacity run sharing a trial
hash, the checkpoint skip on a second invocation, ``matrix_pbo``,
``capacity_curve``, ``select_deflated_winner`` and both writers — then STOPS.

All epoch-ms timestamps are :data:`alphaforge.core.time.Ms`; ``--window`` dates
are bare ``YYYY-MM-DD`` = UTC midnight via :func:`parse_utc`. 1h-aligned.
Heavy imports stay deferred so ``--help`` is fast and the smoke path never pays
for the live-lake adapters it does not use.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

# scripts/ is outside the package import root; make ``alphaforge`` importable when
# the driver is invoked as a plain script (``uv run python scripts/...``).
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alphaforge.core.time import (  # noqa: E402  (after sys.path bootstrap)
    Ms,
    Timeframe,
    floor_bar,
    now_ms,
    parse_utc,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np
    import numpy.typing as npt
    import pandas as pd
    import pyarrow as pa

    from alphaforge.analytics.grand_matrix import GrandConfig
    from alphaforge.analytics.metrics import PerfSummary
    from alphaforge.analytics.walkforward import ValidationReport, WalkForwardResult
    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import Instrument
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore

__all__ = ["main"]

_LOG: Final = logging.getLogger("alphaforge.grand_backtest")

# ---- artifact layout (GRAND_BACKTEST.md §3) ----------------------------------
_ROOT_SUBDIR: Final[str] = "grand_backtest"
_CONFIGS_DIR: Final[str] = "configs"
_LEDGER_FILE: Final[str] = "experiments.jsonl"
_MANIFEST_FILE: Final[str] = "manifest.json"
_PROGRESS_FILE: Final[str] = "progress.jsonl"
_MATRIX_FILE: Final[str] = "matrix.json"
_VERDICT_FILE: Final[str] = "verdict.md"
_CAPACITY_PLOT: Final[str] = "capacity_curve.png"
_WALKFORWARD_JSON: Final[str] = "walkforward.json"
_SCHEMA_VERSION: Final[int] = 1
_OPS_DB: Final[str] = "ops.sqlite"
_BARS_PER_DAY: Final[int] = 24
_BTC_ANCHOR: Final[str] = "BINANCE:PERP:BTCUSDT"

# ---- reference legs (GRAND_BACKTEST.md §0) -----------------------------------
_TRAIN_DAYS: Final[int] = 365
_TEST_DAYS: Final[int] = 91
_EMBARGO_BARS: Final[int] = 168

# ---- the broadest CLEAN window (requested; clamped to the probed lake range) -
_DEFAULT_START_ISO: Final[str] = "2021-01-01"
_DEFAULT_END_ISO: Final[str] = "2026-06-01"  # exclusive

# ---- the documented capacity fallback when no variant is deflated-eligible ---
_CAPACITY_FALLBACK: Final[str] = "A_regime"

# ---- smoke fixture (hermetic; NEVER the live lake) ---------------------------
# Deterministic wall-clock + a tiny recent window with several OOS legs, mirroring
# tests/integration/test_experiments_honest_trial_count.py's shape but with a test
# span long enough that the reference rebalance_bars=72 trades MULTIPLE times per
# leg (so every config — even the low-turnover A_blend — yields a non-degenerate,
# non-zero-variance OOS daily-return curve the REAL DSR path can consume).
_SMOKE_HOUR: Final[int] = 3_600_000
_SMOKE_T0: Final[int] = 1_672_531_200_000  # 2023-01-01T00:00:00Z (1h-aligned)
_SMOKE_N_BARS: Final[int] = 2400  # 100 days: train(31d) + ~7 OOS legs of 10d
_SMOKE_TRAIN_BARS: Final[int] = 31 * _BARS_PER_DAY  # 744
_SMOKE_TEST_BARS: Final[int] = 10 * _BARS_PER_DAY  # 240 (>= 3 rebalances at rebal=72)
_SMOKE_EMBARGO_BARS: Final[int] = 72  # < test so the tiny grid still tiles legs
_SMOKE_END: Final[int] = _SMOKE_T0 + _SMOKE_N_BARS * _SMOKE_HOUR
_SMOKE_NOW_MS: Final[int] = 1_700_000_000_000
_SMOKE_PBO_SPLITS: Final[int] = 4  # small even n_splits for the short OOS span
_SMOKE_MEMBERS: Final[tuple[str, ...]] = (
    _BTC_ANCHOR,
    *(f"BINANCE:PERP:{b}USDT" for b in ("ETH", "SOL", "ADA", "DOGE", "XRP", "BNB")),
)
# Heterogeneous drifts + a higher vol so the cross-section actually rotates and
# the book turns over within each short leg (no flat / zero-variance curve).
_SMOKE_DRIFTS: Final[tuple[float, ...]] = (
    0.002,
    -0.002,
    0.0015,
    -0.0015,
    0.001,
    -0.001,
    0.0008,
)


# =============================================================================
# CLI
# =============================================================================


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grand_backtest",
        description="Self-driving checkpointed honest-robustness grand backtest.",
    )
    p.add_argument(
        "--run-ts",
        default=None,
        help="Resume an existing run under artifacts/grand_backtest/<run-ts>/; "
        "absent => mint a fresh UTC %%Y%%m%%dT%%H%%M%%SZ timestamp.",
    )
    p.add_argument(
        "--window",
        default=None,
        help="Override the requested window as START:END (UTC YYYY-MM-DD, END "
        "exclusive); clamped into the probed clean lake range. Default: "
        f"{_DEFAULT_START_ISO}:{_DEFAULT_END_ISO}.",
    )
    p.add_argument(
        "--profile",
        default=None,
        help="Config profile overlay (configs/<profile>.yaml).",
    )
    p.add_argument(
        "--smoke",
        action="store_true",
        help="Run the WHOLE control flow on a hermetic synthetic fixture in "
        "seconds (never touches the live lake). Build/test scope ONLY.",
    )
    return p


def _parse_window(value: str | None) -> tuple[Ms, Ms]:
    """``START:END`` (UTC dates, END exclusive) -> requested ``(start_ms, end_ms)``."""
    raw = value if value is not None else f"{_DEFAULT_START_ISO}:{_DEFAULT_END_ISO}"
    parts = raw.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise SystemExit(f"--window: expected START:END (UTC dates), got {raw!r}")
    start = parse_utc(f"{parts[0]}T00:00:00Z")
    end = parse_utc(f"{parts[1]}T00:00:00Z")
    if end <= start:
        raise SystemExit(f"--window: end ({parts[1]}) must be > start ({parts[0]})")
    return start, end


# =============================================================================
# Window probing (derive the usable range from the live lake; clamp, never guess)
# =============================================================================


def _probe_clean_window(
    universe: UniverseStore,
    reader: PITDataReader,
    requested: tuple[Ms, Ms],
    *,
    as_of: Ms,
) -> tuple[Ms, Ms]:
    """Clamp the requested window into the probed-clean lake range (§0).

    The first clean bar is the earliest membership ``effective_from`` in the
    universe; the last bar is the freshest fully-available BTC-anchor H1 close.
    Resolves ``[max(probed_first, requested_start), min(probed_last, requested_end))``,
    floored to the 1h grid. Raises if the clamp collapses (a misconfigured lake).
    """
    import pyarrow as pa

    intervals = universe.read_intervals(as_of=as_of)
    if intervals.num_rows == 0:
        raise SystemExit("grand_backtest: empty universe — cannot probe a clean window")
    froms = intervals.column("effective_from").cast(pa.int64()).to_pylist()
    probed_first = int(min(int(v) for v in froms))
    probed_last_open = reader.latest_bar_open(_BTC_ANCHOR, as_of=as_of, tf=Timeframe.H1)
    if probed_last_open is None:
        raise SystemExit(f"grand_backtest: no {_BTC_ANCHOR} bars in the lake — cannot probe")
    # latest_bar_open is the freshest bar OPEN; its window CLOSES one H1 later, which is
    # the exclusive upper bound for a half-open [start, end) test grid.
    probed_last = int(probed_last_open) + Timeframe.H1.ms

    req_start, req_end = requested
    start = floor_bar(max(probed_first, req_start), Timeframe.H1)
    end = floor_bar(min(probed_last, req_end), Timeframe.H1)
    if end <= start:
        raise SystemExit(
            f"grand_backtest: resolved window collapsed "
            f"(start={start}, end={end}; probed [{probed_first}, {probed_last}), "
            f"requested [{req_start}, {req_end}))"
        )
    return start, end


# =============================================================================
# Checkpoint / resume
# =============================================================================


def _is_config_done(out_dir: Path) -> bool:
    """A config is COMPLETE iff ``walkforward.json`` parses AND carries both the
    ``validation`` and ``summary`` keys ``save`` always writes (the ``validation``
    value may be ``null`` for the rare < 2-day-OOS run — that run still COMPLETED;
    only ``save`` writes these keys, and it does so atomically at the end of a run,
    so their presence marks a finished config).

    A partial/corrupt dir (no parseable ``walkforward.json``) is NOT done and is
    re-run cleanly (the runner's ``mkdir(exist_ok=True)`` overwrites). The §3 rule.
    """
    meta = out_dir / _WALKFORWARD_JSON
    if not meta.is_file():
        return False
    try:
        obj = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(obj, dict):
        return False
    # A finished run always has a "validation" key; it is non-null when >=2 OOS
    # days exist, and explicitly null only for the degenerate short-leg case the
    # runner still finishes and persists. Either way the key's PRESENCE marks a
    # completed save (save() always writes the key; a crash mid-save leaves no file).
    return "validation" in obj and "summary" in obj


def _append_jsonl(path: Path, obj: dict[str, object]) -> None:
    """Append one JSON line (the progress ledger; one line per completed config)."""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, sort_keys=True) + "\n")


# =============================================================================
# Per-config wiring (MIRRORS cli/walkforward_cmds.py verbatim) + run
# =============================================================================


def _run_one_config(
    config: GrandConfig,
    *,
    settings: Settings,
    run_dir: Path,
    now: Ms,
    window: tuple[Ms, Ms],
    train_bars: int,
    test_bars: int,
    embargo_bars: int,
    instrument_ids: list[str] | None,
    daily_btc_factory: object | None = None,
    signal_factory: object | None = None,
) -> WalkForwardResult:
    """Build the per-config wiring and call ``runner.run(...)`` + ``result.save``.

    Mirrors ``cli/walkforward_cmds.py``: ``LakePaths`` -> ``PITDataReader`` ->
    ``InstrumentStore`` (ctx-mgr) -> ``UniverseStore`` -> ``FeatureEngine`` ->
    ``SignalService(..., default_registry(), settings.signals,
    alpha_names=...)`` -> ``TransactionCostModel.from_settings`` ->
    ``_PITDailyBtcReader`` ONLY when ``regime=True`` -> ``WalkForwardRunner``.
    The dedicated per-run ``experiment_log`` is shared across every call so N is
    honest; ``out_dir`` is ``configs/<config_id>`` so the checkpoint rule applies.

    ``daily_btc_factory`` overrides the regime daily-BTC source (the smoke
    fixture injects a synthetic reader); ``None`` => the live PIT adapter.
    ``signal_factory(reader, store, universe, alpha_names) -> SignalSource``
    overrides the signal layer (the smoke fixture injects a deterministic stub
    that actually trades so the REAL DSR path runs on a non-degenerate curve);
    ``None`` => the live ``SignalService`` (the byte-identical CLI wiring).
    """
    import alphaforge.features.library  # noqa: F401  (registers the factor library)
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.cli.walkforward_cmds import _PITDailyBtcReader
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService
    from alphaforge.validation.experiments import ExperimentLog

    out_dir = run_dir / _CONFIGS_DIR / config.out_dirname()
    ledger = ExperimentLog(run_dir / _LEDGER_FILE)
    start, end = window
    alpha_names = list(config.alpha_names) if config.alpha_names is not None else None

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / _OPS_DB) as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = (
            SignalService(
                FeatureEngine(reader, store, universe),
                universe,
                default_registry(),
                settings.signals,
                alpha_names=alpha_names,
            )
            if signal_factory is None
            else signal_factory(reader, store, universe, alpha_names)  # type: ignore[operator]
        )
        # The regime gate needs a daily-BTC source for the per-leg expanding HMM
        # fit (D3); construct it ONLY when regime=True so the blend/ml paths stay
        # byte-identical to the shipped CLI wiring.
        daily_btc_reader = None
        if config.regime:
            daily_btc_reader = (
                _PITDailyBtcReader(reader) if daily_btc_factory is None else daily_btc_factory()  # type: ignore[operator]
            )
        runner = WalkForwardRunner(
            reader,
            store,
            universe,
            TransactionCostModel.from_settings(settings),
            service,
            settings,
            daily_btc_reader=daily_btc_reader,
        )
        result = runner.run(
            start,
            end,
            train_bars=train_bars,
            test_bars=test_bars,
            allocator=config.allocator,
            embargo_bars=embargo_bars,
            initial_cash=config.initial_cash,
            instrument_ids=instrument_ids,
            rebalance_bars=config.rebalance_bars,
            no_trade_band=config.no_trade_band,
            out_dir=out_dir,
            now_ms=now,
            alpha_names=alpha_names,
            experiment_log=ledger,
            ml=config.ml,
            regime=config.regime,
        )
    return result


# =============================================================================
# The two-pass driver
# =============================================================================


def _resolve_run_ts(run_ts: str | None, now: Ms) -> str:
    """``--run-ts`` (resume) or a fresh UTC ``%Y%m%dT%H%M%SZ`` minted from ``now``."""
    if run_ts is not None:
        return run_ts
    return datetime.fromtimestamp(now / 1000.0, tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _git_sha() -> str:
    """Best-effort short git sha for the manifest (``unknown`` off-tree)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def _write_manifest(
    run_dir: Path,
    *,
    run_ts: str,
    window: tuple[Ms, Ms],
    configs: Sequence[GrandConfig],
    profile: str | None,
    smoke: bool,
) -> None:
    """Write/refresh ``manifest.json`` — the resume anchor (the full ordered config list)."""
    start, end = window
    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "run_ts": run_ts,
        "git_sha": _git_sha(),
        "profile": profile,
        "smoke": smoke,
        "window": {
            "start_ms": int(start),
            "end_ms": int(end),
            "start_iso": datetime.fromtimestamp(start / 1000.0, tz=UTC).strftime("%Y-%m-%d"),
            "end_iso": datetime.fromtimestamp(end / 1000.0, tz=UTC).strftime("%Y-%m-%d"),
        },
        "train_days": _TRAIN_DAYS if not smoke else None,
        "test_days": _TEST_DAYS if not smoke else None,
        "embargo_bars": _EMBARGO_BARS,
        "configs": [
            {
                "config_id": c.config_id,
                "block": c.block,
                "initial_cash": c.initial_cash,
                "rebalance_bars": c.rebalance_bars,
                "no_trade_band": c.no_trade_band,
                "allocator": c.allocator,
                "alpha_names": list(c.alpha_names) if c.alpha_names is not None else None,
                "ml": c.ml,
                "regime": c.regime,
                "shares_trial_with": c.shares_trial_with,
            }
            for c in configs
        ],
    }
    tmp = run_dir / (_MANIFEST_FILE + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, run_dir / _MANIFEST_FILE)


def _run_block(
    configs: Sequence[GrandConfig],
    *,
    settings: Settings,
    run_dir: Path,
    now: Ms,
    window: tuple[Ms, Ms],
    train_bars: int,
    test_bars: int,
    embargo_bars: int,
    instrument_ids: list[str] | None,
    daily_btc_factory: object | None,
    signal_factory: object | None,
    results: dict[str, WalkForwardResult],
) -> None:
    """Run (or skip-if-done) every config in ``configs``, threading the shared ledger.

    Loads an already-complete config off disk (checkpoint rule) instead of
    re-running it; appends a ``progress.jsonl`` line on each completion; records
    timing + the headline DSR/Sharpe into the driver log.
    """
    from alphaforge.analytics.walkforward import WalkForwardResult

    for config in configs:
        out_dir = run_dir / _CONFIGS_DIR / config.out_dirname()
        if _is_config_done(out_dir):
            _LOG.info("skip %s — already complete (%s)", config.config_id, out_dir)
            results[config.config_id] = _load_result(out_dir, WalkForwardResult)
            continue
        t0 = now_ms()
        _LOG.info(
            "run  %s  block=%s ml=%s regime=%s alloc=%s rebal=%d band=%.4f cash=%.0f",
            config.config_id,
            config.block,
            config.ml,
            config.regime,
            config.allocator,
            config.rebalance_bars,
            config.no_trade_band,
            config.initial_cash,
        )
        try:
            result = _run_one_config(
                config,
                settings=settings,
                run_dir=run_dir,
                now=now,
                window=window,
                train_bars=train_bars,
                test_bars=test_bars,
                embargo_bars=embargo_bars,
                instrument_ids=instrument_ids,
                daily_btc_factory=daily_btc_factory,
                signal_factory=signal_factory,
            )
        except Exception as exc:  # one config must not kill the whole matrix run
            # A config can legitimately fail: e.g. at very large capital the order
            # notional exceeds the liquidity the cost model can honestly price
            # (CostModelMisuse, the capacity ceiling the sweep exists to find). Record
            # it as a failed config and CONTINUE, so the verdict still writes over the
            # configs that did complete. The failure (and its reason) is the finding.
            elapsed_ms = now_ms() - t0
            _LOG.exception(
                "FAILED %s after %.1fs: %s", config.config_id, elapsed_ms / 1000.0, exc
            )
            _append_jsonl(
                run_dir / _PROGRESS_FILE,
                {
                    "config_id": config.config_id,
                    "out_dirname": config.out_dirname(),
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_ms": int(elapsed_ms),
                    "finished_ms": int(now_ms()),
                },
            )
            continue
        results[config.config_id] = result
        elapsed_ms = now_ms() - t0
        v = result.validation
        headline = (
            f"dsr={v.dsr:.4f} psr={v.psr:.4f} sr_ann={v.sr_ann:.2f}"
            if v is not None
            else "validation=None (short OOS span)"
        )
        _LOG.info("done %s in %.1fs  %s", config.config_id, elapsed_ms / 1000.0, headline)
        _append_jsonl(
            run_dir / _PROGRESS_FILE,
            {
                "config_id": config.config_id,
                "out_dirname": config.out_dirname(),
                "status": "done",
                "elapsed_ms": int(elapsed_ms),
                "finished_ms": int(now_ms()),
            },
        )


def _load_result(out_dir: Path, result_cls: type[WalkForwardResult]) -> WalkForwardResult:
    """Reconstruct a ``WalkForwardResult`` from a completed config's on-disk artifacts.

    The matrix writers read ``result.validation`` / ``result.summary`` /
    ``result.equity``; rebuild exactly those off ``walkforward.json`` +
    ``equity.parquet`` so a fully-resumed run (everything already done) still
    produces a correct verdict without re-running any leg.
    """
    import pandas as pd

    obj = json.loads((out_dir / _WALKFORWARD_JSON).read_text(encoding="utf-8"))
    eq = pd.read_parquet(out_dir / "equity.parquet")
    equity = pd.Series(
        eq["equity"].to_numpy(dtype="float64"),
        index=pd.Index(eq["ts"].to_numpy(dtype="int64"), name="ts_open"),
        name="equity",
    )
    summary = _summary_from_json(obj["summary"])
    validation = _validation_from_json(obj.get("validation"))
    return result_cls(
        equity=equity,
        legs=(),
        summary=summary,
        config=dict(obj.get("config", {})),
        validation=validation,
    )


def _as_float(value: object) -> float:
    """JSON scalar -> float; ``null`` (a non-finite the writer dropped) -> ``nan``."""
    import math

    if value is None:
        return math.nan
    if isinstance(value, bool):  # guard: bool is an int subclass
        raise TypeError(f"expected a numeric float, got bool {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    raise TypeError(f"expected a numeric float, got {type(value).__name__}: {value!r}")


def _as_int(value: object) -> int:
    """JSON scalar -> int (counts/timestamps are always present + finite in the artifact)."""
    if isinstance(value, bool):
        raise TypeError(f"expected an int, got bool {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise TypeError(f"expected an int, got {type(value).__name__}: {value!r}")


def _summary_from_json(obj: dict[str, object]) -> PerfSummary:
    """``walkforward.json`` summary dict -> ``PerfSummary`` (None floats -> NaN).

    ``save`` writes non-finite summary floats as JSON ``null``; the dataclass fields
    are ``float``, so restore ``null`` as ``nan`` (the same sentinel the writers map
    back to ``null`` via the ``_json_float`` convention). Each field is coerced by
    its declared int/float type so the reconstruction is ``mypy --strict`` clean.
    """
    import dataclasses

    from alphaforge.analytics.metrics import PerfSummary

    int_fields = {f.name for f in dataclasses.fields(PerfSummary) if f.type in ("int", "Ms")}
    kwargs: dict[str, int | float] = {}
    for f in dataclasses.fields(PerfSummary):
        if f.name not in obj:
            continue
        kwargs[f.name] = _as_int(obj[f.name]) if f.name in int_fields else _as_float(obj[f.name])
    return PerfSummary(**kwargs)  # type: ignore[arg-type]


def _validation_from_json(obj: dict[str, object] | None) -> ValidationReport | None:
    """``walkforward.json`` ``validation`` block -> ``ValidationReport`` (or ``None``).

    ``ValidationReport`` has no ``from_json_obj`` (only ``to_json_obj``), so the
    resume path rebuilds it field-by-field — including the nested blend-only
    ``baseline`` of a gated run. Non-finite floats stored as ``null`` are restored
    as ``nan``. This is plumbing for the checkpoint rule, NOT analysis: the matrix
    writers re-deflate every config against the shared final SR* off the equity
    curve (the BLOCKING B1/GB1 fix), so the round-tripped ``dsr`` here is only the
    runner's audit-time record.
    """
    if obj is None:
        return None

    from alphaforge.analytics.walkforward import ValidationReport

    nested = obj.get("baseline")
    baseline = _validation_from_json(nested if isinstance(nested, dict) else None)
    return ValidationReport(
        psr=_as_float(obj["psr"]),
        dsr=_as_float(obj["dsr"]),
        sr_ann=_as_float(obj["sr_ann"]),
        n_trials=_as_int(obj["n_trials"]),
        n_trials_used=_as_int(obj["n_trials_used"]),
        expected_max_sr=_as_float(obj["expected_max_sr"]),
        sr_trials_variance=_as_float(obj["sr_trials_variance"]),
        n_obs=_as_int(obj["n_obs"]),
        clears_dsr_gate=bool(obj["clears_dsr_gate"]),
        variant=str(obj.get("variant", "blend")),
        gate_inactive_frac=_as_float(obj.get("gate_inactive_frac", 0.0)),
        baseline=baseline,
        clears_baseline_gate=bool(obj.get("clears_baseline_gate", False)),
    )


def _write_verdict_artifacts(
    run_dir: Path,
    *,
    all_configs: Sequence[GrandConfig],
    results: dict[str, WalkForwardResult],
    window: tuple[Ms, Ms],
    run_ts: str,
    pbo_splits: int,
) -> None:
    """Regenerate ``matrix.json`` + ``verdict.md`` + the capacity plot from on-disk
    results (cheap, pure; the LAST step so a crash before it leaves every per-config
    artifact intact and a resume regenerates only these top-level files)."""
    from alphaforge.analytics.grand_matrix import (
        build_matrix_rows,
        capacity_curve,
        cross_config_dsr,
        matrix_pbo,
        select_deflated_winner,
        write_matrix_json,
        write_verdict,
    )
    from alphaforge.validation.experiments import ExperimentLog

    # Tolerate configs that failed to produce a result (e.g. a capacity point whose
    # orders exceeded the liquidity the cost model can price): the verdict is written
    # over the configs that DID complete; the failed ones are recorded in
    # progress.jsonl + the driver log. This keeps the run resilient and the verdict
    # honest about what ran.
    present = [c for c in all_configs if c.config_id in results]
    failed_ids = [c.config_id for c in all_configs if c.config_id not in results]
    if failed_ids:
        _LOG.warning(
            "verdict excludes %d config(s) with no result (failed/capacity-exceeded): %s",
            len(failed_ids),
            failed_ids,
        )
    block_b_ids = [c.config_id for c in present if c.block == "B"]
    variant_ids = [c.config_id for c in present if c.block in ("A", "C")]

    # The shared deflation context: read off the dedicated ledger AFTER every distinct
    # trial is recorded, so EVERY config is judged against the SAME final N / V[SR] /
    # SR* (the B1/GB1 fix — the matrix-level honest deflation, run-order invariant).
    ledger = ExperimentLog(run_dir / _LEDGER_FILE)
    cross = cross_config_dsr(ledger)
    pbo = matrix_pbo(results, variant_ids, n_splits=pbo_splits)
    capacity = capacity_curve(results, block_b_ids, cross) if block_b_ids else ()
    winner = select_deflated_winner(results, cross)
    rows = build_matrix_rows(present, results, cross)

    write_matrix_json(
        run_dir / _MATRIX_FILE,
        rows=rows,
        cross=cross,
        pbo=pbo,
        capacity=capacity,
        winner=winner,
        window=window,
        run_ts=run_ts,
        git_sha=_git_sha(),
    )
    write_verdict(
        run_dir / _VERDICT_FILE,
        rows=rows,
        cross=cross,
        pbo=pbo,
        capacity=capacity,
        winner=winner,
        window=window,
    )
    _maybe_plot_capacity(run_dir / _CAPACITY_PLOT, capacity)
    _LOG.info(
        "verdict written: winner=%s deployment=%s pbo=%.4f n_trials=%d",
        winner,
        bool(winner is not None and pbo.clears_pbo_gate),
        pbo.pbo,
        cross.n_trials,
    )


def _maybe_plot_capacity(path: Path, capacity: object) -> None:
    """Render the capacity curve (sr_ann vs initial_cash) — best-effort, Agg-only.

    The plot is a presentation nicety; a headless/matplotlib-less environment must
    not crash the detached run, so any failure is logged and swallowed.
    """
    points = list(capacity)  # type: ignore[call-overload]
    if not points:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        cashes = [float(p.initial_cash) for p in points]
        srs = [float(p.sr_ann) for p in points]
        fig, ax = plt.subplots(figsize=(6.0, 4.0))
        ax.plot(cashes, srs, marker="o")
        ax.set_xscale("log")
        ax.set_xlabel("initial_cash (quote units, log scale)")
        ax.set_ylabel("OOS annualized Sharpe")
        ax.set_title("Capacity curve — where market impact kills the edge")
        ax.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)
    except Exception as exc:  # best-effort plot; never crash the detached run
        _LOG.warning("capacity plot skipped: %s", exc)


# =============================================================================
# Live + smoke orchestration
# =============================================================================


def _orchestrate(
    *,
    settings: Settings,
    run_dir: Path,
    run_ts: str,
    now: Ms,
    window: tuple[Ms, Ms],
    train_bars: int,
    test_bars: int,
    embargo_bars: int,
    instrument_ids: list[str] | None,
    daily_btc_factory: object | None,
    signal_factory: object | None,
    profile: str | None,
    smoke: bool,
    pbo_splits: int,
) -> None:
    """The two-pass control flow (§3): Pass 1 = Blocks A+C; materialize Block B off
    the deflated winner; Pass 2 = Block B; then write the verdict artifacts."""
    from alphaforge.analytics.grand_matrix import reference_matrix

    # ---- Pass 1: Blocks A + C (the 8 distinct-trial configs) ----------------
    pass1 = reference_matrix()  # best_variant=None => Blocks A + C only
    _write_manifest(
        run_dir,
        run_ts=run_ts,
        window=window,
        configs=pass1,
        profile=profile,
        smoke=smoke,
    )
    results: dict[str, WalkForwardResult] = {}
    _run_block(
        pass1,
        settings=settings,
        run_dir=run_dir,
        now=now,
        window=window,
        train_bars=train_bars,
        test_bars=test_bars,
        embargo_bars=embargo_bars,
        instrument_ids=instrument_ids,
        daily_btc_factory=daily_btc_factory,
        signal_factory=signal_factory,
        results=results,
    )

    # ---- materialize Block B off the deflated winner (or the documented fallback) ----
    block_b = _materialize_block_b(pass1, results, run_dir=run_dir)
    all_configs = (*pass1, *block_b)
    _write_manifest(
        run_dir,
        run_ts=run_ts,
        window=window,
        configs=all_configs,
        profile=profile,
        smoke=smoke,
    )

    # ---- Pass 2: Block B (capacity sweep; shares the winner's trial hash) ----
    _run_block(
        block_b,
        settings=settings,
        run_dir=run_dir,
        now=now,
        window=window,
        train_bars=train_bars,
        test_bars=test_bars,
        embargo_bars=embargo_bars,
        instrument_ids=instrument_ids,
        daily_btc_factory=daily_btc_factory,
        signal_factory=signal_factory,
        results=results,
    )

    # ---- the verdict (LAST step; regenerated from on-disk results) ----------
    _write_verdict_artifacts(
        run_dir,
        all_configs=all_configs,
        results=results,
        window=window,
        run_ts=run_ts,
        pbo_splits=pbo_splits,
    )


def _materialize_block_b(
    pass1: Sequence[GrandConfig],
    results: dict[str, WalkForwardResult],
    *,
    run_dir: Path,
) -> tuple[GrandConfig, ...]:
    """Append Block B (capacity sweep) off the Block-A deflated winner.

    Selects the winner by DEFLATED metrics against the SHARED post-Pass-1 SR*
    (``select_deflated_winner(results, cross)``); when NO variant is
    deflated-eligible (the expected honest null, per Phase 10) the capacity sweep
    defaults to the documented "real lever" ``A_regime`` for capacity CONTEXT only
    (the verdict states it is not a deployable config).
    """
    from alphaforge.analytics.grand_matrix import (
        cross_config_dsr,
        reference_matrix,
        select_deflated_winner,
    )
    from alphaforge.validation.experiments import ExperimentLog

    # Pass 1 has recorded every distinct trial, so the ledger now carries the FINAL
    # N / V[SR]; the winner is judged against that shared SR*, not a partial one.
    cross = cross_config_dsr(ExperimentLog(run_dir / _LEDGER_FILE))
    winner_id = select_deflated_winner(results, cross)
    if winner_id is None:
        winner_id = _CAPACITY_FALLBACK
        _LOG.info(
            "no deflated-eligible variant — capacity sweep anchored on %s (context only)",
            winner_id,
        )
    else:
        _LOG.info("deflated winner = %s — anchoring the capacity sweep on it", winner_id)
    by_id = {c.config_id: c for c in pass1}
    best = by_id[winner_id]
    full = reference_matrix(best_variant=best)
    return tuple(c for c in full if c.block == "B")


# =============================================================================
# Entry point
# =============================================================================


def _configure_logging(run_dir: Path) -> None:
    """Stream the driver log to stdout (the operator's ``harness.log`` nohup target,
    per the §3 layout) AND, as a self-contained in-run copy, to ``<run_ts>/driver.log``
    (a distinct name so it never fights the operator's redirect)."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    with contextlib.suppress(OSError):  # a read-only fs must not block logging to stdout
        handlers.append(logging.FileHandler(run_dir / "driver.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    now = _SMOKE_NOW_MS if args.smoke else now_ms()
    run_ts = _resolve_run_ts(args.run_ts, now)

    if args.smoke:
        return _run_smoke(run_ts=run_ts)

    from alphaforge.config.settings import load_settings

    settings = load_settings(args.profile)
    run_dir = settings.paths.artifacts_dir / _ROOT_SUBDIR / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(run_dir)

    requested = _parse_window(args.window)
    window = _probe_window_live(settings, requested, as_of=now)
    _LOG.info(
        "grand backtest run_ts=%s window=[%s, %s) profile=%s",
        run_ts,
        datetime.fromtimestamp(window[0] / 1000.0, tz=UTC).strftime("%Y-%m-%d"),
        datetime.fromtimestamp(window[1] / 1000.0, tz=UTC).strftime("%Y-%m-%d"),
        args.profile,
    )
    _orchestrate(
        settings=settings,
        run_dir=run_dir,
        run_ts=run_ts,
        now=now,
        window=window,
        train_bars=_TRAIN_DAYS * _BARS_PER_DAY,
        test_bars=_TEST_DAYS * _BARS_PER_DAY,
        embargo_bars=_EMBARGO_BARS,
        instrument_ids=None,  # live: the runner derives the PIT universe window
        daily_btc_factory=None,  # live: the PIT daily-BTC adapter
        signal_factory=None,  # live: the real SignalService (byte-identical CLI wiring)
        profile=args.profile,
        smoke=False,
        pbo_splits=16,
    )
    return 0


def _probe_window_live(
    settings: Settings,
    requested: tuple[Ms, Ms],
    *,
    as_of: Ms,
) -> tuple[Ms, Ms]:
    """Probe + clamp the clean window against the live lake (one short read)."""
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore

    paths = LakePaths(settings.paths.lake_dir)
    universe = UniverseStore(paths)
    reader = PITDataReader(paths)
    return _probe_clean_window(universe, reader, requested, as_of=as_of)


# ---- smoke (hermetic synthetic fixture; the build/test path) -----------------


def _run_smoke(*, run_ts: str) -> int:
    """Run the WHOLE control flow on a hermetic synthetic fixture in seconds.

    Builds a tiny ``tmp`` lake + SCD2 instruments + PIT universe + a synthetic
    daily-BTC frame (mirroring the honest-trial-count integration fixture),
    passes ``instrument_ids`` explicitly so the live lake is NEVER touched, uses
    a short recent window with three OOS legs and a small even PBO ``n_splits``,
    drives BOTH passes (Block-A run + baseline, a Block-C distinct trial, a
    Block-B capacity run sharing a trial hash), proves the checkpoint skip on a
    SECOND invocation, then writes + asserts the verdict artifacts.
    """
    import tempfile

    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.data.schemas import Dataset
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.writer import LakeWriter
    from alphaforge.data.universe.store import UniverseStore

    with tempfile.TemporaryDirectory(prefix="gb_smoke_") as tmp_s:
        tmp = Path(tmp_s)
        run_dir = tmp / "artifacts" / _ROOT_SUBDIR / run_ts
        run_dir.mkdir(parents=True, exist_ok=True)
        _configure_logging(run_dir)
        _LOG.info("SMOKE: hermetic synthetic run under %s", tmp)

        # ---- tiny synthetic lake + instruments + universe -------------------
        paths = LakePaths(tmp / "lake")
        members = list(_SMOKE_MEMBERS)
        closes = {
            iid: _smoke_closes(101 + k, _SMOKE_N_BARS, 50.0 * (k + 1), _SMOKE_DRIFTS[k])
            for k, iid in enumerate(members)
        }
        LakeWriter(paths).write(Dataset.OHLCV, _smoke_ohlcv_table(closes))
        universe = UniverseStore(paths)
        universe.write_intervals(_smoke_universe_table(members))
        store = InstrumentStore(tmp / _OPS_DB)
        for iid in members:
            store.upsert(_smoke_instrument(iid), as_of=_SMOKE_T0 - 365 * 24 * _SMOKE_HOUR)
        store.close()

        # ---- a Settings pointing every path at the tmp tree -----------------
        settings = _smoke_settings(tmp)
        window = (_SMOKE_T0, _SMOKE_END)

        # ---- DRIVE BOTH PASSES (full control flow) --------------------------
        _orchestrate(
            settings=settings,
            run_dir=run_dir,
            run_ts=run_ts,
            now=_SMOKE_NOW_MS,
            window=window,
            train_bars=_SMOKE_TRAIN_BARS,
            test_bars=_SMOKE_TEST_BARS,
            embargo_bars=_SMOKE_EMBARGO_BARS,  # < test so the tiny grid still tiles legs
            instrument_ids=members,  # NEVER the live lake
            daily_btc_factory=_SmokeDailyBtc,
            signal_factory=_smoke_signal_factory,  # stub that actually trades
            profile=None,
            smoke=True,
            pbo_splits=_SMOKE_PBO_SPLITS,
        )

        _assert_smoke_artifacts(run_dir)

        # ---- second invocation must SKIP every config (checkpoint rule) -----
        ledger_first = (run_dir / _LEDGER_FILE).read_text(encoding="utf-8")
        progress_lines_first = (run_dir / _PROGRESS_FILE).read_text(encoding="utf-8").count("\n")
        _orchestrate(
            settings=settings,
            run_dir=run_dir,
            run_ts=run_ts,
            now=_SMOKE_NOW_MS,
            window=window,
            train_bars=_SMOKE_TRAIN_BARS,
            test_bars=_SMOKE_TEST_BARS,
            embargo_bars=_SMOKE_EMBARGO_BARS,
            instrument_ids=members,
            daily_btc_factory=_SmokeDailyBtc,
            signal_factory=_smoke_signal_factory,
            profile=None,
            smoke=True,
            pbo_splits=_SMOKE_PBO_SPLITS,
        )
        ledger_second = (run_dir / _LEDGER_FILE).read_text(encoding="utf-8")
        progress_lines_second = (run_dir / _PROGRESS_FILE).read_text(encoding="utf-8").count("\n")
        if ledger_first != ledger_second:
            raise SystemExit("SMOKE FAIL: ledger changed on resume — N is not idempotent")
        if progress_lines_second != progress_lines_first:
            raise SystemExit("SMOKE FAIL: a config re-ran on resume — checkpoint skip broken")
        _assert_smoke_artifacts(run_dir)

    _LOG.info("SMOKE OK")
    return 0


def _assert_smoke_artifacts(run_dir: Path) -> None:
    """Assert the verdict artifacts + the matrix invariants the smoke must exercise."""
    for name in (_MANIFEST_FILE, _LEDGER_FILE, _PROGRESS_FILE, _MATRIX_FILE, _VERDICT_FILE):
        if not (run_dir / name).is_file():
            raise SystemExit(f"SMOKE FAIL: missing artifact {name}")
    matrix = json.loads((run_dir / _MATRIX_FILE).read_text(encoding="utf-8"))
    cfg_ids = {row["config_id"] for row in matrix["configs"]}
    # Block A (4) + Block C (4) + Block B (4) must all be present.
    expected = {
        "A_blend",
        "A_ml",
        "A_regime",
        "A_ml_regime",
        "C_rebal24",
        "C_band10",
        "C_mvo",
        "C_carry",
        "B_cap_100k",
        "B_cap_1M",
        "B_cap_10M",
        "B_cap_100M",
    }
    if not expected.issubset(cfg_ids):
        raise SystemExit(f"SMOKE FAIL: missing configs {sorted(expected - cfg_ids)}")
    # The capacity rows must be flagged as NON-distinct trials (share the winner's hash).
    cap_rows = [r for r in matrix["configs"] if r["block"] == "B"]
    if any(r["is_distinct_trial"] for r in cap_rows):
        raise SystemExit("SMOKE FAIL: a Block-B capacity run is flagged as a distinct trial")
    # The capacity curve must have been built.
    if not matrix.get("capacity_curve"):
        raise SystemExit("SMOKE FAIL: empty capacity_curve")
    # The matrix-level deflation context must be present + honest.
    m = matrix["matrix"]
    if m["n_trials"] < 1:
        raise SystemExit("SMOKE FAIL: n_trials < 1 — the ledger did not record")


# ---- smoke fixture builders --------------------------------------------------


class _SmokeSignalSource:
    """A deterministic stub ``SignalSource`` (the design's §4 sanctioned smoke seam).

    The production ``SignalService`` needs realized-IC warm-up history that a tiny
    synthetic window cannot supply, so its ``alpha_blend`` is all-NaN there and the
    engine never trades — a flat, zero-variance OOS curve the REAL ``dsr_from_returns``
    rejects. This stub instead emits the ``(ts_open, instrument_id)`` MultiIndex frame
    with a FINITE ``mu_ann`` contract the strategy consumes: a per-instrument
    phase-shifted sine in time so the rank/MVO allocators take real, ROTATING positions
    (turnover + non-zero return variance) while staying well under the ``|mu_ann| < 3.0``
    tripwire. It honours ``alpha_names`` only as a deterministic seed tweak (a non-None
    subset shifts the phases) so a Block-C alpha-subset run differs from the reference —
    enough to exercise the control flow without pretending to model factor semantics.
    """

    def __init__(self, members: list[str], alpha_names: list[str] | None) -> None:
        self._members = sorted(members)
        # A non-None subset deterministically perturbs the cross-section so C_carry's
        # curve is not byte-identical to A_blend's (a distinct trial with its own OOS).
        self._seed_shift = 0.0 if alpha_names is None else float(len(alpha_names)) * 0.37

    def compute_research(self, start: Ms, end: Ms) -> pd.DataFrame:
        import numpy as np
        import pandas as pd

        ts = np.arange(int(start), int(end), _SMOKE_HOUR, dtype=np.int64)
        n_inst = len(self._members)
        # Per-instrument phase spread the book across the cross-section; a ~30-day
        # period rotates leaders/laggards several times across the window.
        period = 30.0 * 24.0  # bars
        phases = np.linspace(0.0, 2.0 * np.pi, n_inst, endpoint=False) + self._seed_shift
        bar_idx = (ts - int(start)) / _SMOKE_HOUR
        rows_ts: list[int] = []
        rows_iid: list[str] = []
        rows_mu: list[float] = []
        rows_a: list[float] = []
        for j, iid in enumerate(self._members):
            mu = 0.6 * np.sin(2.0 * np.pi * bar_idx / period + phases[j])
            rows_ts.extend(int(t) for t in ts)
            rows_iid.extend([iid] * ts.size)
            rows_mu.extend(float(v) for v in mu)
            # alpha_blend = the processed, direction-signed blend the ML meta-gate
            # reads as its feature/label sign (unit-scaled mu, same cross-section).
            rows_a.extend(float(v) for v in (mu / 0.6))
        index = pd.MultiIndex.from_arrays(
            [np.asarray(rows_ts, dtype=np.int64), rows_iid],
            names=["ts_open", "instrument_id"],
        )
        return pd.DataFrame(
            {
                "alpha_blend": np.asarray(rows_a, dtype=np.float64),
                "mu_ann": np.asarray(rows_mu, dtype=np.float64),
            },
            index=index,
        )


def _smoke_signal_factory(
    reader: object,
    store: object,
    universe: object,
    alpha_names: list[str] | None,
) -> _SmokeSignalSource:
    """Build the stub signal source over the universe's members (smoke path only)."""
    import pyarrow as pa

    del reader, store
    intervals = universe.read_intervals()  # type: ignore[attr-defined]
    members = [str(v) for v in intervals.column("instrument_id").cast(pa.string()).to_pylist()]
    return _SmokeSignalSource(sorted(set(members)), alpha_names)


class _SmokeDailyBtc:
    """A synthetic ``DailyBtcReader`` (window << ``MIN_FIT_DAYS`` => IdentityRegime cold-start).

    Mirrors ``tests/integration/test_experiments_honest_trial_count.py::_SyntheticDailyBtc``
    so the regime variant rides the documented D3 fallback in the smoke path.
    """

    def read_daily_btc(self, start: Ms, end: Ms) -> pd.DataFrame:
        import numpy as np
        import pandas as pd

        day = 24 * _SMOKE_HOUR
        ts = np.arange(int(start), int(end), day, dtype=np.int64)
        k = np.arange(ts.size, dtype=float)
        close = 30_000.0 * (1.0 + 0.05 * np.sin(k / 7.0))
        return pd.DataFrame(
            {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close},
            index=pd.Index(ts, dtype="int64", name="ts_open"),
        )


def _smoke_closes(seed: int, n: int, level: float, drift: float) -> npt.NDArray[np.float64]:
    import numpy as np

    rng = np.random.default_rng(seed)
    return np.asarray(level * np.exp(np.cumsum(rng.normal(drift, 0.020, n))), dtype=np.float64)


def _smoke_ohlcv_table(per_inst: dict[str, npt.NDArray[np.float64]]) -> pa.Table:
    import pyarrow as pa

    iids: list[str] = []
    ts: list[int] = []
    opens: list[float] = []
    closes: list[float] = []
    for iid, close in per_inst.items():
        n = len(close)
        iids.extend([iid] * n)
        ts.extend(_SMOKE_T0 + k * _SMOKE_HOUR for k in range(n))
        opens.append(float(close[0]))
        opens.extend(float(v) for v in close[:-1])
        closes.extend(float(v) for v in close)
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(opens, type=pa.float64()),
            "high": pa.array([v * 1.001 for v in closes], type=pa.float64()),
            "low": pa.array([v * 0.999 for v in closes], type=pa.float64()),
            "close": pa.array(closes, type=pa.float64()),
            "volume": pa.array([100.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([1.0e7] * n_rows, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + _SMOKE_HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _smoke_universe_table(members: list[str]) -> pa.Table:
    import pyarrow as pa

    return pa.table(
        {
            "instrument_id": pa.array(members, type=pa.string()),
            "effective_from": pa.array(
                [_SMOKE_T0] * len(members), type=pa.timestamp("ms", tz="UTC")
            ),
            "effective_to": pa.array([None] * len(members), type=pa.timestamp("ms", tz="UTC")),
            "rank": pa.array([1] * len(members), type=pa.int32()),
            "reason": pa.array(["enter_top40"] * len(members), type=pa.string()),
        }
    )


def _smoke_instrument(instrument_id: str) -> Instrument:
    from alphaforge.core.instruments import Instrument
    from alphaforge.core.types import AssetClass, MarketType

    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=instrument_id.split(":")[2].removesuffix("USDT"),
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=_SMOKE_T0 - 365 * 24 * _SMOKE_HOUR,
        delisted_ts=None,
    )


def _smoke_settings(tmp: Path) -> Settings:
    """A ``Settings`` with every path rooted at the tmp tree (no var/ or lake/ leak).

    The config sections are frozen pydantic models, so the tmp paths are supplied
    at CONSTRUCTION via a ``PathsCfg`` rather than mutated after the fact.
    """
    from alphaforge.config.settings import PathsCfg, Settings

    paths = PathsCfg(
        lake_dir=tmp / "lake",
        var_dir=tmp,
        artifacts_dir=tmp / "artifacts",
    )
    return Settings(paths=paths)


if __name__ == "__main__":
    raise SystemExit(main())
