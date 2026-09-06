"""Measure every scale figure the site puts on a page, with a definition for each.

WHY. `/systems` and `/progress` each carry a panel of round numbers — bars, instruments, years,
fundamentals, tests — and every one of them was typed by hand. Two were wrong when measured on
2026-08-22:

  * "392K+ point-in-time fundamentals" — there are **380,878**. The claim is OVERSTATED, which is
    the only kind of stale that actually matters.
  * "8,436 US stocks, survivorship-free" — matches neither store: the equity lake holds bars for
    18,015 US instruments and the point-in-time membership store knows 6,835.

The rest were understated and technically true because they carry a "+", which is not a defence:
"3.5M+ hourly bars" against 13.7M tells a reader something false about the size of the thing.

A number typed onto a page is right on the day it is typed. This measures each one and publishes
it, so the site can quote a figure that traces to something — and so the number-trace guard fires
when the lake moves and the copy does not.

EVERY FIGURE CARRIES ITS DEFINITION. "How many US stocks" has at least two defensible answers and
they differ by 2.6x; publishing the number without saying which one it is would replace a stale
figure with an ambiguous one.

Reads the lakes read-only. Runs no backtest, opens no return data: 0 trials.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "engineering" / "data_lake_scale.json"


def _rows_and_files(base: Path) -> tuple[int, int]:
    """Row count from parquet FOOTERS — metadata only, never loading a column."""
    files = list(base.rglob("*.parquet")) if base.is_dir() else []
    total = 0
    for file in files:
        try:
            total += pq.ParquetFile(file).metadata.num_rows
        except Exception:  # an unreadable partition is data, not a crash
            continue
    return total, len(files)


def _instruments(base: Path, prefix: str | None = None) -> int:
    if not base.is_dir():
        return 0
    ids = [p.name.split("=", 1)[1] for p in base.glob("instrument_id=*")]
    return len([i for i in ids if prefix is None or i.startswith(prefix)])


def _year_span(base: Path) -> tuple[str, str] | None:
    if not base.is_dir():
        return None
    years = sorted(
        {q.name.split("=")[1] for p in base.glob("instrument_id=*") for q in p.glob("year=*")}
    )
    return (years[0], years[-1]) if years else None


def _collected_tests() -> int:
    """What pytest actually collects, counted from its own per-file report."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "--collect-only", "--no-cov",
         "-p", "no:cacheprovider", "-n0"],
        cwd=REPO, capture_output=True, text=True,
    )
    total = 0
    for line in result.stdout.splitlines():
        if line.startswith("tests/") and ": " in line:
            tail = line.rsplit(": ", 1)[-1].strip()
            if tail.isdigit():
                total += int(tail)
    return total


def main() -> int:
    equity_daily = REPO / "data" / "lake" / "ohlcv_1d"
    crypto_hourly = REPO / "data" / "lake" / "ohlcv"
    fundamentals = REPO / "data" / "lake" / "fundamentals"
    membership = REPO / "data" / "lake" / "universe_membership"

    eq_rows, eq_files = _rows_and_files(equity_daily)
    cx_rows, cx_files = _rows_and_files(crypto_hourly)
    fx_rows, fx_files = _rows_and_files(fundamentals)
    span = _year_span(equity_daily)

    facts: dict[str, dict[str, Any]] = {
        "equity_daily_bars": {
            "value": eq_rows,
            "definition": "rows across every partition of data/lake/ohlcv_1d, counted from "
            "parquet footers",
            "partitions": eq_files,
        },
        "equity_instruments_with_bars": {
            "value": _instruments(equity_daily, "XUSE:CASH:"),
            "definition": "distinct US-listed instrument ids that have at least one daily bar, "
            "including delisted ones — the broadest defensible answer to 'how many stocks'",
        },
        "equity_instruments_in_pit_membership": {
            "value": _instruments(membership, "XUSE:CASH:"),
            "definition": "distinct US-listed instrument ids the point-in-time universe store "
            "has ever admitted — the narrower answer, and the one that means "
            "'survivorship-free research universe'",
        },
        "equity_year_span": {
            "value": f"{span[0]}-{span[1]}" if span else None,
            "definition": "first and last year partition present in the equity daily lake",
            "years": (int(span[1]) - int(span[0]) + 1) if span else None,
        },
        "point_in_time_fundamentals": {
            "value": fx_rows,
            "definition": "rows in data/lake/fundamentals — one (instrument, fiscal period) "
            "record carrying an available_at stamp, which is what makes it point-in-time",
            "partitions": fx_files,
        },
        "crypto_hourly_bars": {
            "value": cx_rows,
            "definition": "rows across every partition of data/lake/ohlcv, counted from parquet "
            "footers",
            "partitions": cx_files,
        },
        "crypto_instruments_with_bars": {
            "value": _instruments(crypto_hourly),
            "definition": "distinct instrument ids with at least one hourly bar, live and "
            "delisted. NOT the traded universe, which is a much smaller subset chosen by the "
            "sleeve's own filters",
        },
        "automated_tests": {
            "value": _collected_tests(),
            "definition": "tests pytest collects under tests/, summed from its own per-file "
            "collection report",
        },
    }

    result = {
        "schema": "canli.alphac-data-lake-scale.v1",
        "claim_boundary": (
            "Counts what is on disk and what pytest collects. It says nothing about data quality, "
            "coverage gaps, or whether any of it supports a trading claim — only how much there "
            "is. Runs no backtest, opens no return data, registers no hypothesis. 0 trials."
        ),
        "why_each_figure_carries_a_definition": (
            "'How many US stocks' has at least two defensible answers here and they differ by "
            "2.6x: 18,015 instruments have bars, and 6,835 have ever been in the point-in-time "
            "universe. Publishing one without saying which it is would replace a stale number "
            "with an ambiguous one."
        ),
        "corrections_this_measurement_forced": [
            "'392K+ point-in-time fundamentals' was OVERSTATED — the true figure is "
            f"{fx_rows:,}. An overstated count is the only kind of staleness that matters.",
            "'8,436 US stocks, survivorship-free' matched neither store and has been replaced by "
            "the point-in-time membership count, which is what the phrase means.",
            "'3.5M+ hourly bars' and '2,820+ automated tests' were understated by enough to "
            "mislead in the other direction; the '+' made them true and uninformative.",
        ],
        "facts": facts,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    for name, fact in facts.items():
        print(f"  {name:38} {fact['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
