# Grand Backtest — self-driving, checkpointed honest-robustness harness

> A SELF-DRIVING, RESUMABLE grand-backtest harness that runs a BOUNDED, HONEST
> robustness matrix over the full crypto-perp history and writes a DEFLATED
> verdict. The matrix logic lives in a tested `src/` module
> (`analytics.grand_matrix`); the driver is a thin `scripts/` orchestrator
> launched DETACHED (`caffeinate -dimsu nohup …`) so it survives the laptop
> closing. **Agents BUILD + SMOKE-TEST only (tiny/fast); they NEVER run the full
> matrix.** This sheet pins the bounded config matrix, the `src/` interface the
> driver calls, the artifact layout, and the checkpoint/resume rule.

The harness mirrors the SHIPPED wiring in
`src/alphaforge/cli/walkforward_cmds.py` verbatim (do NOT redefine it): per
config it constructs `LakePaths(settings.paths.lake_dir)` → `PITDataReader`,
`InstrumentStore(settings.paths.var_dir / "ops.sqlite")`, `UniverseStore`,
`FeatureEngine(reader, store, universe)`,
`SignalService(FeatureEngine, universe, default_registry(), settings.signals,
alpha_names=…)`, `TransactionCostModel.from_settings(settings)`, and —
ONLY when `regime=True` — `_PITDailyBtcReader(reader)` for the HMM gate. It
then calls `WalkForwardRunner(reader, store, universe, cost_model,
service, settings, daily_btc_reader=…).run(start, end, …)` and
`WalkForwardResult.save(out_dir)`. Heavy imports stay deferred; the InstrumentStore
is used as a context manager (`with InstrumentStore(...) as store:`), exactly as the CLI does.
`import alphaforge.features.library` once before constructing the registry (it
registers the factor library on import).

All epoch-ms timestamps are `alphaforge.core.time.Ms` (int64); CLI dates are bare
`YYYY-MM-DD` = UTC midnight via `parse_utc`. 1h-aligned. Style: frozen
`@dataclass(slots=True, kw_only=True)`, `Final` constants, full type hints,
`mypy --strict` + `ruff` clean, match neighbour idioms. Non-finite floats → `None`
in JSON (the `_json_float` convention used across `walkforward.py` / `dsr.py`).

---

## 0. The data window (probed, not guessed)

Probed from the live lake (`UniverseStore.read_intervals()` + `PITDataReader.ohlcv`):

- Lake spans **2020-03-01 → 2026-05-31** (65 distinct instruments, 138 SCD2
  intervals, ~2.75M H1 rows). Cross-section depth grows over time: 2020 is thin
  (20 insts by 2020-07, 30 by 2020-09); **43 insts span Jan-2021**, 51 span
  Jan-2022, 60+ by 2024.
- **The broadest CLEAN window = `2021-01-01 → 2026-06-01`** (exclusive end): a
  deep cross-section (43→60+ instruments) for the entire span, no thin-universe
  warm-up artefacts from 2020-H1. The driver does NOT hardcode this — it derives
  the usable range from the universe/reader at launch and clamps the requested
  window into it (`max(probed_first_clean, requested_start)` …
  `min(probed_last_bar, requested_end)`), logging the resolved window.
- Reference legs: `train_days=365`, `test_days=91`, `embargo=168` (7d > `purge =
  horizon_bars = 72`). Over the clean window this yields **~17 OOS legs**, first
  OOS test opening ~2022-01-01. The capacity + robustness runs use the SAME legs.

The honest frame (Phase 10): crypto-perps-alone was judged NOISE (PSR 0.73, DSR
0.35–0.44, PBO 0.62). This study is the definitive confirm/refute over the full
history with the Phase-12 gates (ML meta + HMM regime) as the real lever.

---

## 1. The bounded config matrix (~16 runs — NOT a full grid)

A full cross of {capital × rebalance × band × allocator × alphas × 4 gate
variants} is hundreds of trials — a dishonest search that would ratchet `N` and
deflate every Sharpe to zero by construction. Instead the matrix is **bounded and
structured** into three blocks, varying ONE thing at a time off a single
reference config. Total: **16 runs, of which 13 are DISTINCT trials** on the
shared ledger (the 4 capacity runs share a trial hash with their gate variant —
`initial_cash` is excluded from `trial_config` by design, so a capacity sweep is
NOT a search dimension and does not inflate `N`).

### Reference config (`R`)

| knob | value |
| --- | --- |
| window | `2021-01-01 → 2026-06-01` (broadest clean) |
| train_days / test_days / embargo | 365 / 91 / 168 |
| initial_cash | 1_000_000 |
| rebalance_bars | 72 (= horizon; the low-turnover reference) |
| no_trade_band | 0.0030 (30 bps) |
| allocator | rank |
| alpha_names | None (ALL registered directional alphas) |

### Block A — GATE COMPARISON at `R` (4 runs, 4 distinct trials) — THE core test

The must-beat-baseline gate. Each gated run internally re-runs the blend-only
baseline on the IDENTICAL purged legs (the runner does this automatically and
attaches it as `validation.baseline`), so the `clears_baseline_gate` predicate is
measured on the same legs net of costs. `blend` is the baseline reference itself.

| config_id | ml | regime | role |
| --- | --- | --- | --- |
| `A_blend`        | F | F | baseline reference (not itself baseline-gate-eligible) |
| `A_ml`           | T | F | + ML meta-gate |
| `A_regime`       | F | T | + HMM regime gate (the real lever) |
| `A_ml_regime`    | T | T | + both |

### Block B — CAPACITY CURVE (4 runs, 0 new trials) — where impact kills the edge

Take the **best gate variant from Block A** (selected by DEFLATED metrics — see
§2a, NOT raw Sharpe), hold every search knob at `R`, sweep only `initial_cash`.
These share Block A's trial hash (`initial_cash` is not in `trial_config`), so
they add **zero** to `N`; their per-capital `sr_ann / max_dd / turnover / dsr` are
reported for the capacity curve ONLY.

| config_id | initial_cash | inherits |
| --- | --- | --- |
| `B_cap_100k` | 100_000     | best-of-A knobs |
| `B_cap_1M`   | 1_000_000   | best-of-A knobs |
| `B_cap_10M`  | 10_000_000  | best-of-A knobs |
| `B_cap_100M` | 100_000_000 | best-of-A knobs |

`B_cap_1M` is numerically identical to the best-of-A run at `R`; it is re-listed so
the capacity curve has its anchor point and the driver may skip it via the
checkpoint rule (its out_dir already holds a valid `walkforward.json`).

### Block C — ROBUSTNESS at the reference variant (4 runs, 4 distinct trials)

On the `A_blend` reference variant, vary ONE knob at a time. Each is a DISTINCT
trial (a real search dimension), so each adds 1 to `N`.

| config_id | knob changed vs R | value |
| --- | --- | --- |
| `C_rebal24`   | rebalance_bars | 24 (daily; higher turnover) |
| `C_band10`    | no_trade_band  | 0.0010 (10 bps; let weak trades through) |
| `C_mvo`       | allocator      | mvo |
| `C_carry`     | alpha_names    | `carry_fund_21,carry_fund_90,mr_res_72` (carry-tilt) |

> Resolve `C_carry`'s names against `default_registry()` at build time; if any name
> is absent the driver fails loudly (a typo'd factor is a silent mis-trial). The
> smoke test asserts these three names resolve.

### Trial accounting (the whole point)

- **Distinct trials logged on the shared ledger: 13** = Block A (4) + the 4
  blend-only baselines the 3 gated A-runs spawn internally **minus the 1 that
  equals `A_blend`** (the runner records each baseline as its own trial keyed by
  `base_trial_config`; `A_ml`, `A_regime`, `A_ml_regime` each emit a baseline, but
  all three baselines hash IDENTICALLY to `A_blend`'s own trial — same
  `base_trial_config` — so they collapse to ONE ledger line via `record`'s
  idempotency) + Block C (4). Net: A contributes 4 variant trials + 1 shared
  baseline trial (= `A_blend`); C contributes 4. **N converges to ~9 distinct
  trials**, and the harness reports the HONEST `log.n_trials()` it observes.
- Block B contributes **0** (shared hash).
- `N` rises as configs are logged → `expected_max_sharpe(N, V[SR])` rises → DSR
  deflates correctly. The matrix uses a **DEDICATED ledger**
  (`<run_ts>/experiments.jsonl`), NOT the global `var/experiments.jsonl`, so `N`
  is exactly the trials THIS matrix logs (reproducible; not polluted by prior CLI
  runs). The driver passes this ledger as `experiment_log=` to every `run(...)`.

---

## 2. The pinned `src/alphaforge/analytics/grand_matrix.py` interface

Pure, deterministic, offline analysis the thin driver calls. NOT exported from
`analytics/__init__` (it imports `walkforward`, which imports the engine → cycle;
same rule as `walkforward.py`). Import as
`from alphaforge.analytics.grand_matrix import …`. Every function below is unit-
tested on synthetic fixtures (never the live lake).

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from alphaforge.analytics.walkforward import WalkForwardResult
    from alphaforge.core.time import Ms
    from alphaforge.validation.dsr import DSRReport
    from alphaforge.validation.experiments import ExperimentLog

# Deployment gates (alphaDesign.md §7.3/§7.4) — the same constants the engine uses.
DSR_GATE: Final[float] = 0.95
PBO_GATE: Final[float] = 0.20


# ----- the bounded config spec (one row of the matrix) -------------------------

@dataclass(frozen=True, slots=True, kw_only=True)
class GrandConfig:
    """One row of the bounded matrix — a stable config_id + the knobs run(...) takes.

    ``block`` is "A" | "B" | "C". ``shares_trial_with`` is set ONLY for Block B
    capacity runs (the config_id of the gate variant whose trial hash they share);
    it documents — and the verdict writer enforces — that a capacity run never
    counts as a new trial. ``initial_cash`` is the only knob that differs across a
    capacity sweep and is intentionally NOT part of the trial identity.
    """

    config_id: str
    block: Literal["A", "B", "C"]
    # run(...) knobs — defaults match the reference config R.
    initial_cash: float = 1_000_000.0
    rebalance_bars: int = 72
    no_trade_band: float = 0.0030
    allocator: Literal["rank", "mvo"] = "rank"
    alpha_names: tuple[str, ...] | None = None
    ml: bool = False
    regime: bool = False
    shares_trial_with: str | None = None

    def out_dirname(self) -> str:
        """The checkpoint dir name (== config_id; stable, filesystem-safe)."""


def reference_matrix(*, best_variant: GrandConfig | None = None) -> tuple[GrandConfig, ...]:
    """The bounded ~16-run matrix (Blocks A, B, C) as ordered GrandConfigs.

    Block A (4 distinct gate trials) + Block C (4 distinct robustness trials) are
    always present. Block B (4 capacity runs) is materialized off ``best_variant``
    — the gate variant chosen by DEFLATED metrics from Block A (see
    :func:`select_deflated_winner`). When ``best_variant`` is None (first pass,
    before A has run), the driver emits Blocks A+C, then calls again with the
    winner to append Block B. Every Block-B config carries ``shares_trial_with =
    best_variant.config_id`` and varies only ``initial_cash`` ∈
    {100k, 1M, 10M, 100M}. config_ids are stable strings (``A_blend`` … ``C_carry``).
    """


# ----- (a) cross-config DSR over the SHARED ExperimentLog ----------------------

@dataclass(frozen=True, slots=True, kw_only=True)
class CrossConfigDSR:
    """The matrix-level deflation context read off the shared ledger AFTER all
    distinct trials are recorded (so every config sees the SAME final N / V[SR])."""

    n_trials: int                 # log.n_trials() — HONEST distinct-trial count
    sr_trials_variance: float     # log.trial_sharpe_variance() — V[SR]
    expected_max_sr: float        # expected_max_sharpe(max(2, N), V[SR]) — SR*


def cross_config_dsr(log: ExperimentLog) -> CrossConfigDSR:
    """Read the final deflation context off the shared ledger.

    Calls ``log.n_trials()`` and ``log.trial_sharpe_variance()`` (the blessed
    ExperimentLog API) and ``expected_max_sharpe(max(2, N), V[SR])`` from
    validation.dsr. This is the SHARED ``SR*`` every config's deflated verdict is
    judged against — the matrix-level honest deflation. Pure read; never records.
    """


# ----- (b) PBO via CSCV over the VARIANT set's OOS daily-returns matrix ---------

def oos_returns_matrix(
    results: Mapping[str, WalkForwardResult],
    variant_ids: Sequence[str],
) -> pd.DataFrame:
    """Build the T×N per-config OOS DAILY-returns matrix pbo_cscv consumes.

    Columns are exactly ``variant_ids`` (the DISTINCT-trial configs — Blocks A+C,
    NOT the capacity sweep, which would be N duplicate columns of one config and
    bias the rank). Each column is ``analytics.metrics.daily_returns(result.equity)``
    for that config. Rows are the UTC-daily grid INNER-JOINED across all columns
    (the legs tile identically across variants, so the daily index is shared; an
    inner join drops the at-most-one boundary day a variant might miss). Rows are
    chronological — pbo_cscv partitions rows in time order. Raises ValueError if
    fewer than 2 variant columns or fewer than n_splits aligned rows survive.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class PBOSummary:
    pbo: float
    n_combinations: int
    n_configs: int
    n_obs: int
    clears_pbo_gate: bool   # pbo < PBO_GATE (0.20)


def matrix_pbo(
    results: Mapping[str, WalkForwardResult],
    variant_ids: Sequence[str],
    *,
    n_splits: int = 16,
    max_combinations: int = 5000,
    seed: int = 42,
) -> PBOSummary:
    """PBO via ``validation.pbo.pbo_cscv`` over :func:`oos_returns_matrix`.

    Wraps the SHIPPED ``pbo_cscv`` (BBLZ CSCV) on the variant OOS-returns matrix
    and applies the ``pbo < 0.20`` gate. Deterministic for fixed
    (matrix, n_splits, max_combinations, seed). With ~17 daily*legs the row count
    is ample for the default n_splits=16; the driver may pass a smaller even
    n_splits if a short window leaves < 16 aligned rows (the smoke test does).
    """


# ----- (c) the capacity-curve builder -----------------------------------------

@dataclass(frozen=True, slots=True, kw_only=True)
class CapacityPoint:
    initial_cash: float
    sr_ann: float
    max_dd: float
    turnover: float          # annualized, from analytics.metrics.turnover
    dsr: float               # deflated against the SHARED SR* (capacity != new trial)
    final_equity: float


def capacity_curve(
    results: Mapping[str, WalkForwardResult],
    capacity_ids: Sequence[str],
    cross: CrossConfigDSR,
) -> tuple[CapacityPoint, ...]:
    """The capacity curve from the Block-B runs, ascending by ``initial_cash``.

    For each capacity config_id pulls ``result.summary`` (sr_ann/max_dd/turnover/
    final_equity) and deflates its OOS daily Sharpe against the SHARED ``cross``
    context (NOT a fresh per-capital N — a capacity sweep is not a search). The
    point of the curve is to show where MARKET IMPACT (cost model scaling with
    notional/ADV in the engine's cost_inputs) erodes ``sr_ann`` and lifts
    ``turnover``-adjusted cost — i.e. where the (thin) edge dies as capital grows.
    """


# ----- (d) the winner selector + verdict.md / matrix.json writers --------------

def select_deflated_winner(
    results: Mapping[str, WalkForwardResult],
) -> str | None:
    """The DEPLOYABLE winner among Block-A gate variants — by DEFLATED metrics, never
    raw Sharpe.

    Eligible iff, on the SAME purged legs net of costs:
    ``validation.clears_baseline_gate`` (must-beat-baseline: dsr>=0.95 AND dsr >
    baseline.dsr AND sr_ann > baseline.sr_ann — read straight off the runner) AND
    ``validation.clears_dsr_gate`` (dsr>=0.95). Among the eligible, the winner is
    the highest ``validation.dsr`` (ties broken by higher ``sr_ann``). Returns None
    when NO gate variant is live-eligible — the HONEST null result (which is the
    expected outcome given Phase 10). ``A_blend`` is never eligible (it has no
    baseline; the gate is meaningful only for a gated variant). The PBO gate
    (§2b) is applied at the MATRIX level by :func:`write_verdict`, not here.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class MatrixRow:
    """One config's row in matrix.json (per-config block of the schema)."""

    config_id: str
    block: str
    knobs: dict[str, object]          # the GrandConfig knobs that define this run
    psr: float
    dsr: float
    sr_ann: float
    max_dd: float
    turnover: float
    clears_dsr_gate: bool
    clears_baseline_gate: bool
    is_distinct_trial: bool           # False for Block-B capacity rows
    baseline_dsr: float | None        # the must-beat reference (gated runs only)


def build_matrix_rows(
    configs: Sequence[GrandConfig],
    results: Mapping[str, WalkForwardResult],
) -> tuple[MatrixRow, ...]:
    """Assemble one MatrixRow per config from its WalkForwardResult.validation +
    summary (non-finite floats normalized via the _json_float convention)."""


def write_matrix_json(
    path: Path,
    *,
    rows: Sequence[MatrixRow],
    cross: CrossConfigDSR,
    pbo: PBOSummary,
    capacity: Sequence[CapacityPoint],
    winner: str | None,
    window: tuple[Ms, Ms],
    run_ts: str,
) -> None:
    """Write the machine-readable matrix.json (schema in §3). Atomic write
    (tmp + os.replace), sorted keys, the _json_float non-finite convention."""


def write_verdict(
    path: Path,
    *,
    rows: Sequence[MatrixRow],
    cross: CrossConfigDSR,
    pbo: PBOSummary,
    capacity: Sequence[CapacityPoint],
    winner: str | None,
    window: tuple[Ms, Ms],
) -> None:
    """Write verdict.md — the human-readable, plainly-stated true result.

    States: (1) the resolved clean window + N distinct trials + V[SR] + SR*; (2)
    the full Block-A gate table (psr/dsr/sr_ann/max_dd/turnover/clears_dsr_gate/
    clears_baseline_gate, baseline-deltas) — NO cherry-picking, every variant
    shown; (3) the DEPLOYMENT VERDICT = (winner is not None) AND pbo<0.20 —
    i.e. a variant cleared must-beat-baseline AND dsr>=0.95 AND the matrix PBO is
    below 0.20 on the SAME legs; when no variant qualifies it states the null
    plainly (crypto-perps-alone confirmed noise, per Phase 10); (4) the CAPACITY
    CURVE table showing where impact kills the thin edge; (5) whether the REGIME
    gate (the real lever) changed the verdict vs blend-only. The winner is judged
    by DEFLATED metrics only; raw Sharpe is reported but never decisive.
    """
```

**Why the deployment verdict is a conjunction (do not weaken):** a config is
DEPLOYABLE iff `select_deflated_winner(...) is not None` (must-beat-baseline AND
dsr≥0.95 on the same purged legs net of costs) **AND** `pbo < 0.20` on the variant
OOS matrix. All three on the SAME legs. The full matrix is always reported; the
winner is the deflated winner, never the raw-Sharpe leader.

---

## 3. Artifact layout + matrix.json schema + checkpoint/resume

### Layout under `artifacts/grand_backtest/<run_ts>/`

```
artifacts/grand_backtest/<run_ts>/            run_ts = UTC %Y%m%dT%H%M%SZ
  manifest.json        resolved window, the full ordered GrandConfig list, git sha,
                       settings profile, schema_version — written FIRST, the resume anchor
  experiments.jsonl    the DEDICATED ledger (matrix N only; not var/experiments.jsonl)
  progress.jsonl       append-only: one line per config on completion
                       {config_id, out_dirname, status:"done", finished_ms}
  matrix.json          the machine verdict (schema below) — written at the END
  verdict.md           the human verdict (§2d) — written at the END
  configs/
    A_blend/           == WalkForwardResult.save(out_dir): equity.parquet,
    A_ml/                walkforward.json, summary.txt, tearsheet.{png,txt}, legs/
    A_regime/
    A_ml_regime/
    B_cap_100k/  B_cap_1M/  B_cap_10M/  B_cap_100M/
    C_rebal24/  C_band10/  C_mvo/  C_carry/
  harness.log          driver stdout/stderr (nohup target)
```

`<run_ts>` resolved ONCE at launch and reused on every resume (the driver takes
`--run-ts` to resume an existing run; absent → new timestamp). `artifacts/` is
git-ignored.

### matrix.json schema

```jsonc
{
  "schema_version": 1,
  "run_ts": "20260616T...Z",
  "window": { "start_ms": 1609459200000, "end_ms": 1780272000000,
              "start_iso": "2021-01-01", "end_iso": "2026-06-01" },
  "git_sha": "73fdae4...",
  "matrix": {                              // matrix-level deflation + overfit context
    "n_trials": 9,                         // HONEST log.n_trials() (distinct only)
    "sr_trials_variance": 0.43,            // V[SR] off the dedicated ledger
    "expected_max_sr": 0.71,               // SR* = expected_max_sharpe(max(2,N), V[SR])
    "pbo": 0.55, "pbo_n_combinations": 12870, "pbo_n_configs": 8, "pbo_n_obs": 1580,
    "clears_pbo_gate": false,              // pbo < 0.20
    "deflated_winner": null,               // config_id or null (the HONEST result)
    "deployment_verdict": false            // winner != null AND clears_pbo_gate
  },
  "configs": [                             // one row per config (Blocks A, B, C)
    { "config_id": "A_blend", "block": "A",
      "knobs": { "initial_cash": 1000000.0, "rebalance_bars": 72,
                 "no_trade_band": 0.003, "allocator": "rank",
                 "alpha_names": null, "ml": false, "regime": false },
      "psr": 0.73, "dsr": 0.41, "sr_ann": 0.55, "max_dd": -0.34,
      "turnover": 18.2, "clears_dsr_gate": false, "clears_baseline_gate": false,
      "is_distinct_trial": true, "baseline_dsr": null }
    // … A_ml, A_regime, A_ml_regime (baseline_dsr set; is_distinct_trial true),
    //    B_cap_* (is_distinct_trial false; shares A-winner's trial),
    //    C_* (is_distinct_trial true)
  ],
  "capacity_curve": [                      // ascending initial_cash; gate-variant winner
    { "initial_cash": 100000.0,   "sr_ann": 0.58, "max_dd": -0.31,
      "turnover": 17.9, "dsr": 0.43, "final_equity": 138000.0 }
    // … 1M, 10M, 100M — sr_ann should DECAY as impact bites at 10M/100M
  ]
}
```

Every float follows the non-finite → `null` convention. `psr/dsr/sr_ann/
clears_dsr_gate/clears_baseline_gate/baseline_dsr` come straight off
`WalkForwardResult.validation` (and its nested `.baseline`); `max_dd/turnover`
from `result.summary`.

### Checkpoint / resume rule (the self-driving core)

The driver is **idempotent and restartable**. For each `GrandConfig` in order:

1. **Skip if already done:** if `configs/<config_id>/walkforward.json` exists AND
   parses AND carries a non-null `validation` block (or, for the rare 0-daily-
   return run, a finished marker), the config is COMPLETE — load that result and
   move on. This is the "skip a config whose out_dir already has a valid
   walkforward.json" rule. A partial/corrupt dir (no parseable
   `walkforward.json`) is treated as NOT done and re-run (the runner's
   `out_dir.mkdir(..., exist_ok=True)` overwrites cleanly).
2. **Run otherwise:** build the per-config wiring (mirror `walkforward_cmds.py`),
   call `runner.run(..., out_dir=configs/<config_id>, experiment_log=<dedicated
   ledger>, now_ms=now_ms())`, then append a `progress.jsonl` line.
3. **Ledger idempotency dovetails with checkpointing:** `ExperimentLog.record` is
   idempotent on the config hash, so a resume that re-runs a half-finished config
   does NOT double-count `N`. The dedicated ledger therefore always reflects
   exactly the distinct trials whose configs completed.

**Two-pass ordering for Block B** (capacity needs the Block-A winner):

- Pass 1: run Blocks A + C (the 8 distinct-trial configs). Re-runnable/skippable
  per the rule above.
- After Pass 1 completes: `select_deflated_winner(results_A)` → materialize Block
  B off the winner via `reference_matrix(best_variant=winner)` and append those 4
  configs to `manifest.json`. If NO variant is deflated-eligible, default the
  capacity sweep to `A_regime` (the documented "real lever"; the verdict states it
  is shown for capacity context only, not as a deployable config).
- Pass 2: run Block B (skippable). Then write `matrix.json` + `verdict.md` from
  ALL results. The final write is the last step, so a crash before it leaves every
  per-config artifact intact and a resume regenerates only the two top-level files.

After both passes the verdict files are regenerated from on-disk results on every
invocation (cheap, pure), so a resumed run that finds everything done still emits a
fresh, correct verdict.

---

## 4. Detached launch + smoke test (build/test scope ONLY)

**Driver** `scripts/grand_backtest.py` — thin orchestrator: parse `--run-ts`
(resume) / `--window` / `--smoke` / `--profile`; build wiring once per config
(mirror `walkforward_cmds.py`); drive the two-pass loop via the checkpoint rule;
call the `grand_matrix` writers. No analysis logic in the script.

**Launch (NOT run by agents — operator only):**
```
export PATH="$HOME/.local/bin:$PATH" && cd /Users/arhancanli/alphaforge
caffeinate -dimsu nohup uv run python scripts/grand_backtest.py \
    > artifacts/grand_backtest/harness.log 2>&1 &
```
`caffeinate -dimsu` keeps the run alive with the lid closed; `nohup` + `&`
detaches it from the shell. The driver discovers/creates `<run_ts>` and from then
on logs into `artifacts/grand_backtest/<run_ts>/harness.log`.

**Smoke test (what agents run — TINY/FAST, never the full matrix):**
`scripts/grand_backtest.py --smoke` runs the WHOLE control flow on a hermetic
synthetic fixture (a stub `SignalSource` + tiny instrument set, a few legs, a
small even `n_splits`, a synthetic daily-BTC frame) so it finishes in seconds and
NEVER touches the live lake. It must exercise: a Block-A run + its baseline, a
Block-C distinct trial, a Block-B capacity run sharing a trial hash, the
checkpoint skip on a second invocation, `matrix_pbo`, `capacity_curve`,
`select_deflated_winner`, and both writers. `pytest tests/.../test_grand_matrix.py`
covers the `src/` functions on fixtures. Agents verify with
`uv run ruff check`, `uv run mypy --strict src`, and the smoke + unit tests — then
STOP. The full matrix is launched detached by the operator.

---

## 14-line summary

1. Goal: a self-driving, checkpointed, RESUMABLE harness that runs a bounded honest-robustness matrix over the full crypto-perp history and writes a deflated verdict; agents BUILD + SMOKE-TEST only, the operator launches the full run detached.
2. Probed window: lake = 2020-03 → 2026-05; broadest CLEAN window = 2021-01-01 → 2026-06-01 (43→60+ instruments throughout); ~17 OOS legs at train365/test91/embargo168, first OOS ~2022-01. Driver clamps to the probed range, never hardcodes.
3. Matrix = 16 runs, structured (NOT a full grid): Block A gate comparison at reference R, Block B capacity curve, Block C one-knob robustness; each run has a stable config_id used as its checkpoint dir name.
4. Block A (4 distinct trials) at R (1M, rebal72, band30bps, rank, all alphas, clean window): A_blend / A_ml / A_regime / A_ml_regime — the core must-beat-baseline test (the runner attaches the blend-only baseline on the same purged legs automatically).
5. Block B (4 runs, 0 new trials): best-of-A gate variant across initial_cash {100k,1M,10M,100M}; shares A's trial hash (initial_cash excluded from trial_config), so it does NOT inflate N — its per-capital metrics feed the capacity curve only.
6. Block C (4 distinct trials) off A_blend, one knob each: rebalance 24, band 10bps, allocator mvo, alphas=carry-tilt (carry_fund_21,carry_fund_90,mr_res_72).
7. Honest N: ~9 distinct trials converge on a DEDICATED per-run ledger (experiments.jsonl in the run dir, not the global one); ExperimentLog.record idempotency means resumes/re-runs never double-count N → DSR deflates correctly against the shared SR*.
8. src interface = analytics/grand_matrix.py (tested, NOT exported — engine import cycle): GrandConfig + reference_matrix; cross_config_dsr(log); oos_returns_matrix + matrix_pbo (pbo_cscv over the VARIANT OOS daily-return matrix, gate pbo<0.20); capacity_curve; select_deflated_winner; build_matrix_rows; write_matrix_json + write_verdict.
9. PBO matrix runs CSCV over the per-config OOS daily-returns matrix of the DISTINCT-trial set (Blocks A+C, never the capacity duplicates), inner-joined on the shared UTC-daily grid in chronological order.
10. Deployment verdict (do not weaken): a variant clears the must-beat-baseline gate (clears_baseline_gate read off validation) AND dsr≥0.95 AND matrix pbo<0.20, all on the SAME purged legs net of costs; winner judged by DEFLATED dsr, never raw Sharpe; full matrix always reported, no cherry-picking.
11. matrix.json schema pinned: per-config {config_id, block, knobs, psr, dsr, sr_ann, max_dd, turnover, clears_dsr_gate, clears_baseline_gate, is_distinct_trial, baseline_dsr} + matrix-level {n_trials, sr_trials_variance, expected_max_sr, pbo, clears_pbo_gate, deflated_winner, deployment_verdict} + capacity_curve points; non-finite floats → null.
12. Artifacts under artifacts/grand_backtest/<run_ts>/: manifest.json (resume anchor, written first), dedicated experiments.jsonl, progress.jsonl, per-config dirs (== WalkForwardResult.save), matrix.json + verdict.md (written last), harness.log.
13. Checkpoint/resume rule: skip any config whose out_dir already holds a parseable walkforward.json with a validation block; partial/corrupt dirs re-run cleanly; two-pass ordering (A+C, then B off the winner); verdict files regenerated from on-disk results on every invocation.
14. Honest frame: Phase 10 judged crypto-perps-alone as noise (PSR 0.73, DSR 0.35–0.44, PBO 0.62); verdict.md states the true result plainly — the full gate table, where market impact kills the thin edge on the capacity curve, and whether the regime gate (the real lever) changes the verdict; the expected outcome is a null and the harness reports it without flinching.
```
