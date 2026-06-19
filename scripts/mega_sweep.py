#!/usr/bin/env python
"""Mega config sweep — the exhaustive, HONEST equity backtest grid.

Runs a principled grid (allocator x factor-set x rebalance cadence) of purged walk-forwards
via the `af` CLI, in parallel, RESUMABLE (skips configs already in results.jsonl), writing one
JSON row per config. Each row carries the net Sharpe, DSR (deflated for the grid's trial
count by the validator), PSR, total return, vol, maxDD, turnover.

HONESTY: running a large grid and picking the raw-best Sharpe is overfitting; the DSR column
is what matters (it deflates), and a synthesis step compares long-only configs against the
buy-and-hold benchmark (alpha = return - beta). This is a search for any config with REAL
alpha that survives deflation, not a cherry-pick machine.

Resumable + caffeinated: safe to kill/sleep and rerun; done configs are skipped.
Run:  caffeinate -dimsu uv run python scripts/mega_sweep.py
"""

from __future__ import annotations

import concurrent.futures
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
RESULTS = REPO / "var" / "sweep" / "results.jsonl"
ARTIFACTS = REPO / "artifacts" / "sweep"
START, END = "2022-07-01", "2026-06-01"
TRAIN_DAYS, TEST_DAYS = "252", "63"
MAX_WORKERS = 6  # parallel `af` processes (laptop-friendly)
PER_RUN_TIMEOUT_S = 2400

ALLOCATORS = ["rank", "rank_long", "mvo"]
REBALANCE = ["5", "10", "21", "42", "63"]

# Principled factor sets (single factors + economically-motivated blends). Names are the
# registered eq_* specs; blends are comma-joined.
ALPHA_SETS: dict[str, str] = {
    "mom": "eq_mom_252_21",
    "rev": "eq_rev_21",
    "residrev": "eq_rev_resid_21",
    "ep": "eq_earnings_yield",
    "bp": "eq_book_to_price",
    "sp": "eq_sales_to_price",
    "margin": "eq_operating_margin",
    "roe": "eq_roe",
    "gp": "eq_gross_profitability",
    "lowvol": "eq_lowvol_252",
    "bab": "eq_bab_252",
    "mom_rev": "eq_mom_252_21,eq_rev_21",
    "mom_margin": "eq_mom_252_21,eq_operating_margin",
    "mom_ep": "eq_mom_252_21,eq_earnings_yield",
    "mom_sp": "eq_mom_252_21,eq_sales_to_price",
    "value3": "eq_earnings_yield,eq_book_to_price,eq_sales_to_price",
    "quality3": "eq_operating_margin,eq_roe,eq_gross_profitability",
    "mom_value3": "eq_mom_252_21,eq_earnings_yield,eq_book_to_price,eq_sales_to_price",
    "mom_quality3": "eq_mom_252_21,eq_operating_margin,eq_roe,eq_gross_profitability",
    "mom_margin_ep": "eq_mom_252_21,eq_operating_margin,eq_earnings_yield",
    "all_qv": (
        "eq_mom_252_21,eq_earnings_yield,eq_book_to_price,eq_sales_to_price,"
        "eq_operating_margin,eq_roe,eq_gross_profitability"
    ),
}

_VALIDATION = re.compile(
    r"PSR\s+([\-\d.]+)\s+DSR\s+([\-\d.]+).*?SR_ann\s+([\-\d.]+)\s+N_trials\s+(\d+)"
)
_SUMMARY = {
    k: re.compile(rf"^{k}\s+([\-\d.eE]+)", re.M)
    for k in ("total_return", "cagr", "vol_ann", "sharpe", "max_dd", "turnover_ann")
}


def _done() -> set[tuple[str, str, str]]:
    if not RESULTS.exists():
        return set()
    out: set[tuple[str, str, str]] = set()
    for line in RESULTS.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out.add((r["allocator"], r["alpha_set"], str(r["rebalance"])))
    return out


def _run(cfg: tuple[str, str, str]) -> dict | None:
    allocator, alpha_set, rebalance = cfg
    alphas = ALPHA_SETS[alpha_set]
    out_dir = ARTIFACTS / f"{allocator}__{alpha_set}__{rebalance}"
    cmd = [
        "uv",
        "run",
        "af",
        "research",
        "walkforward",
        "--profile",
        "equity",
        "--start",
        START,
        "--end",
        END,
        "--train-days",
        TRAIN_DAYS,
        "--test-days",
        TEST_DAYS,
        "--rebalance-bars",
        rebalance,
        "--allocator",
        allocator,
        "--alphas",
        alphas,
        "--out",
        str(out_dir),
    ]
    row: dict = {
        "allocator": allocator,
        "alpha_set": alpha_set,
        "rebalance": rebalance,
        "alphas": alphas,
    }
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO), capture_output=True, text=True, timeout=PER_RUN_TIMEOUT_S
        )
        text = proc.stdout + "\n" + proc.stderr
        m = _VALIDATION.search(text)
        if m:
            row.update(psr=float(m[1]), dsr=float(m[2]), sr_ann=float(m[3]), n_trials=int(m[4]))
        for k, rx in _SUMMARY.items():
            sm = rx.search(text)
            if sm:
                row[k] = float(sm[1])
        row["ok"] = m is not None
        if not row["ok"]:
            row["err"] = (proc.stderr or proc.stdout)[-400:]
    except subprocess.TimeoutExpired:
        row.update(ok=False, err="timeout")
    except Exception as exc:  # never let one config kill the sweep
        row.update(ok=False, err=repr(exc)[-400:])
    return row


def main() -> int:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    done = _done()
    grid = [(a, name, r) for a in ALLOCATORS for name in ALPHA_SETS for r in REBALANCE]
    todo = [c for c in grid if c not in done]
    print(f"grid={len(grid)} done={len(done)} todo={len(todo)} workers={MAX_WORKERS}", flush=True)
    n = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for row in ex.map(_run, todo):
            if row is not None:
                with RESULTS.open("a") as f:
                    f.write(json.dumps(row) + "\n")
                n += 1
                sr = row.get("sharpe", float("nan"))
                dsr = row.get("dsr", float("nan"))
                ok = row.get("ok")
                tag = f"sr={sr:.3f} dsr={dsr:.3f}" if ok else f"FAIL {row.get('err', '')[:40]}"
                lbl = f"{row['allocator']}/{row['alpha_set']}/r{row['rebalance']}"
                print(f"[{n}/{len(todo)}] {lbl}  {tag}", flush=True)
    print(f"sweep complete: wrote {n} new rows to {RESULTS}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
