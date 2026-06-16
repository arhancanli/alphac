# Grand Backtest — detached launch / resume / results

Operator guide for the self-driving, checkpointed grand-backtest harness. The
harness runs a **bounded, honest robustness matrix** (Blocks A/B/C, ~16 runs / 8
distinct trials) over the full crypto-perp history and writes a **deflated
verdict**. Design + matrix spec: `docs/design/build/GRAND_BACKTEST.md`.

- **Analysis lives in `src/`**: `alphaforge.analytics.grand_matrix` (tested on
  synthetic fixtures, never the live lake).
- **Driver**: `scripts/grand_backtest.py` — thin orchestrator; owns the
  checkpoint/resume loop and the `matrix.json` / `verdict.md` writers.
- **Launcher**: `scripts/run_grand_backtest.sh` — the detached `caffeinate +
  nohup` wrapper. Owns the run timestamp, the PID file, and the
  `STARTED` / `DONE` / `FAILED` sentinels.

> **Operator-only.** The full matrix runs for hours and reads the live lake.
> Engineers/agents only **smoke-test** the driver (seconds, hermetic synthetic
> fixture — see "Smoke test" below); they never launch the full matrix.

---

## Launch (start a new run, detached)

```sh
export PATH="$HOME/.local/bin:$PATH" && cd /Users/arhancanli/alphaforge
scripts/run_grand_backtest.sh
```

This:

1. resolves a fresh `run_ts` = UTC `%Y%m%dT%H%M%SZ` and creates
   `artifacts/grand_backtest/<run_ts>/`;
2. launches the driver under `caffeinate -dimsu nohup … & ; disown` so it
   survives the terminal closing and (on AC) the lid closing;
3. writes the `STARTED` sentinel + `harness.pid`, then prints the exact commands
   to tail the log, check liveness, read the sentinel, and resume.

The launcher passes its `run_ts` to the driver via `--run-ts`, so the run
directory is fixed up front. The detached process logs to
`artifacts/grand_backtest/run_<run_ts>.log` (the nohup capture); the driver may
also keep its own `<run_ts>/harness.log`.

Forward extra args to the driver after `--`, e.g. a non-default settings profile:

```sh
scripts/run_grand_backtest.sh -- --profile paper
```

Narrow the window (otherwise the driver clamps to the broadest clean lake range,
`2021-01-01 → 2026-06-01`):

```sh
scripts/run_grand_backtest.sh --window 2021-01-01 2026-06-01
```

---

## Watch a running launch

The launch prints these; reproduced here with `<run_ts>` as a placeholder:

```sh
RUN=artifacts/grand_backtest/<run_ts>

tail -f artifacts/grand_backtest/run_<run_ts>.log     # live driver output

kill -0 $(cat $RUN/harness.pid) && echo RUNNING || echo NOT-RUNNING

ls -l $RUN/DONE $RUN/FAILED 2>/dev/null   # exactly one appears when it finishes
cat $RUN/DONE      # {"status":"done","rc":0,...}   -> verdict is ready
cat $RUN/FAILED    # {"status":"failed","rc":N,...} -> inspect the launch log
```

---

## Resume (after a crash, a sleep/wake, or a deliberate stop)

The harness is **idempotent and restartable**. Re-launch with the same `run_ts`;
the driver skips every config whose `configs/<id>/walkforward.json` already exists
and parses with a `validation` block, and re-runs only what is missing or partial.
The dedicated per-run experiment ledger is idempotent on the config hash, so a
resume never double-counts trials (`N` stays honest).

```sh
# resume a specific run
scripts/run_grand_backtest.sh --run-ts <run_ts>

# or resume the most recent run dir automatically
scripts/run_grand_backtest.sh --resume-latest
```

If a live process for that `run_ts` is still running, the launcher refuses to
double-launch and tells you the PID. A stale PID file (process gone) is detected
and cleared automatically before resuming; a resume clears any prior
`DONE`/`FAILED` marker so the verdict is regenerated cleanly from on-disk results.

To stop a run and resume it later:

```sh
kill $(cat artifacts/grand_backtest/<run_ts>/harness.pid)
scripts/run_grand_backtest.sh --run-ts <run_ts>      # picks up where it left off
```

---

## Where results land

```
artifacts/grand_backtest/
  run_<run_ts>.log                  the detached nohup capture (tail this)
  <run_ts>/
    STARTED            launcher sentinel: {run_ts, mode, started_utc, pid}
    DONE               written on rc==0: {status:"done", rc:0, finished_utc}
    FAILED             written on rc!=0: {status:"failed", rc:N, finished_utc}
    harness.pid        the detached process PID (removed on completion)
    driver.log         the driver's own structured log (driver-written)
    manifest.json      resolved window + ordered config list + git sha (resume anchor)
    experiments.jsonl  the DEDICATED trial ledger (matrix N only)
    progress.jsonl     one append-only line per completed config
    matrix.json        the machine verdict (schema in GRAND_BACKTEST.md §3) — written last
    verdict.md         the human verdict — written last
    configs/
      A_blend/  A_ml/  A_regime/  A_ml_regime/      Block A (gate comparison)
      B_cap_100k/  B_cap_1M/  B_cap_10M/  B_cap_100M/  Block B (capacity curve)
      C_rebal24/  C_band10/  C_mvo/  C_carry/        Block C (one-knob robustness)
```

Each `configs/<id>/` is a full `WalkForwardResult.save(...)` directory
(`equity.parquet`, `walkforward.json`, `summary.txt`, tearsheet, `legs/`).

Read the verdict when `DONE` appears:

```sh
cat artifacts/grand_backtest/<run_ts>/verdict.md
```

`artifacts/` is git-ignored; nothing here is committed.

---

## The laptop-close caveat (read this)

`caffeinate -dimsu` prevents display, idle, and disk sleep and asserts a system /
user-active hold. Its effect depends on power:

- **On AC power, the run holds through a closed lid.** The system-sleep + idle
  assertions keep the CPU scheduled in clamshell, so the matrix keeps running
  with the laptop shut (lid closed, plugged in).
- **On battery, a closed lid still sleeps the machine.** macOS clamshell sleep on
  battery overrides the assertion; the laptop naps. **This PAUSES the run — it
  does not lose it.** The driver checkpoints per config and the experiment ledger
  is idempotent, so on wake the same process resumes the in-flight config (or, if
  the process was reaped, re-launch with `--run-ts <run_ts>` / `--resume-latest`
  and it continues from the last completed config). No work is lost; only wall
  time is.

Practical guidance: run the full matrix **plugged in**, and either leave the lid
open or keep it on AC if closing it. For a guaranteed-uninterrupted run, use a
small always-on arm64 VPS (see `docs/RUNBOOK.md` §0) and drop the `caffeinate`
wrapper (`uv run python scripts/grand_backtest.py` under `nohup`/systemd) — the
driver is identical.

Do **not** put the repo under an iCloud-synced path (`~/Desktop`, `~/Documents`);
iCloud sync corrupts the live SQLite WAL. `~/alphaforge` is safe. The launcher
hard-stops if it detects an iCloud path.

---

## Smoke test (engineers/agents — TINY/FAST, hermetic)

Exercises the whole control flow on a synthetic fixture in seconds; never touches
the live lake and never runs detached:

```sh
export PATH="$HOME/.local/bin:$PATH" && cd /Users/arhancanli/alphaforge
uv run python scripts/grand_backtest.py --smoke
uv run pytest tests/unit/test_grand_matrix.py -q
uv run ruff check scripts/grand_backtest.py src/alphaforge/analytics/grand_matrix.py
uv run mypy --strict src/alphaforge/analytics/grand_matrix.py
```

A `--foreground` flag on the launcher runs the driver attached (no
`caffeinate`/`nohup`) for local rehearsal/debug:

```sh
scripts/run_grand_backtest.sh --foreground -- --smoke
```
