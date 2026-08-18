"""Benchmark the two built-in next-open fill paths on a deterministic workload.

This is an engineering microbenchmark, not investment-performance evidence. It
uses synthetic immutable inputs, consumes no hypothesis budget, and writes a
machine-specific timing snapshot with deterministic output checksums.

Run: uv run python scripts/benchmark_execution_models.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from alphaforge.backtest import BarView, FillModel, NextOpenFill, ParticipationCappedFill
from alphaforge.core.instruments import Instrument
from alphaforge.core.types import AssetClass, MarketType, OrderRequest, OrderType, Side
from alphaforge.costs import TransactionCostModel

REPO: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT: Final[Path] = REPO / "artifacts" / "benchmarks" / "execution_models.json"
DEFAULT_CALLS: Final[int] = 100_000
DEFAULT_REPEATS: Final[int] = 7
DEFAULT_WARMUP: Final[int] = 10_000
ADV_QUOTE: Final[float] = 100_000_000.0
SIGMA_DAILY: Final[float] = 0.02


@dataclass(frozen=True, slots=True)
class Workload:
    """Fixed inputs shared by every benchmark case."""

    instrument: Instrument
    order: OrderRequest
    bar: BarView


def build_workload() -> Workload:
    """Return a fixed workload where the participation path fills 50 of 100 units."""
    instrument_id = "BINANCE:PERP:BTCUSDT"
    ts = 1_704_157_200_000
    return Workload(
        instrument=Instrument(
            instrument_id=instrument_id,
            asset_class=AssetClass.CRYPTO_PERP,
            market_type=MarketType.PERP,
            base="BTC",
            quote="USDT",
            tick_size=0.1,
            lot_size=1.0,
            min_qty=1.0,
            min_notional=10.0,
            contract_multiplier=1.0,
            can_short=True,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            funding_interval_hours=8,
            listed_ts=1_577_836_800_000,
            delisted_ts=None,
        ),
        order=OrderRequest(
            client_order_id="benchmark-next-open",
            instrument_id=instrument_id,
            side=Side.BUY,
            qty=100.0,
            order_type=OrderType.MARKET,
            decision_ts=ts,
            decision_price=100.0,
            reason="deterministic engineering benchmark",
        ),
        bar=BarView(
            ts_open=ts,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=500.0,
            quote_volume=50_000.0,
        ),
    )


def execute_workload(model: FillModel, workload: Workload, calls: int) -> float:
    """Execute ``calls`` fills and return a deterministic anti-dead-code checksum."""
    if calls <= 0:
        raise ValueError(f"calls must be > 0, got {calls}")
    checksum = 0.0
    for _ in range(calls):
        fill = model.fill(
            workload.order,
            workload.instrument,
            workload.bar,
            adv_quote=ADV_QUOTE,
            sigma_daily=SIGMA_DAILY,
        )
        checksum += fill.qty + fill.price + fill.fee_quote
    return checksum


def benchmark_case(
    name: str,
    model: FillModel,
    workload: Workload,
    *,
    calls: int,
    repeats: int,
    warmup: int,
) -> dict[str, object]:
    """Measure one model and retain all samples plus deterministic checksums."""
    if repeats <= 0:
        raise ValueError(f"repeats must be > 0, got {repeats}")
    if warmup < 0:
        raise ValueError(f"warmup must be >= 0, got {warmup}")
    if warmup:
        execute_workload(model, workload, warmup)
    samples: list[int] = []
    checksums: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        checksum = execute_workload(model, workload, calls)
        samples.append(time.perf_counter_ns() - started)
        checksums.append(checksum)
    if len(set(checksums)) != 1:
        raise RuntimeError(f"non-deterministic checksum in {name}: {checksums}")
    per_call = [sample / calls for sample in samples]
    return {
        "name": name,
        "calls_per_repeat": calls,
        "repeats": repeats,
        "warmup_calls": warmup,
        "elapsed_ns_samples": samples,
        "ns_per_call_median": statistics.median(per_call),
        "ns_per_call_min": min(per_call),
        "deterministic_checksum": checksums[0],
    }


def sha256(path: Path) -> str:
    """Return a source-file SHA-256."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_report(*, calls: int, repeats: int, warmup: int) -> dict[str, object]:
    """Run both fill paths and return the publication-ready report."""
    workload = build_workload()
    cost_model = TransactionCostModel()
    cases = [
        benchmark_case(
            "next_open_full_fill",
            NextOpenFill(cost_model),
            workload,
            calls=calls,
            repeats=repeats,
            warmup=warmup,
        ),
        benchmark_case(
            "participation_capped_partial_fill",
            ParticipationCappedFill(cost_model, max_bar_participation=0.10),
            workload,
            calls=calls,
            repeats=repeats,
            warmup=warmup,
        ),
    ]
    baseline = cast(float, cases[0]["ns_per_call_median"])
    capped = cast(float, cases[1]["ns_per_call_median"])
    return {
        "schema": "alphaforge.execution-model-benchmark.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "classification": "local engineering microbenchmark; not return evidence",
        "workload": {
            "synthetic": True,
            "market_data_opened": False,
            "hypotheses_spent": 0,
            "expected_full_fill_qty": 100.0,
            "expected_capped_fill_qty": 50.0,
            "inputs": {
                "adv_quote": ADV_QUOTE,
                "sigma_daily": SIGMA_DAILY,
                "max_bar_participation": 0.10,
                "order_qty": workload.order.qty,
                "open": workload.bar.open,
                "quote_volume": workload.bar.quote_volume,
            },
        },
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "architecture": platform.machine(),
            "system": platform.system(),
        },
        "source_sha256": {
            "benchmark": sha256(Path(__file__)),
            "fills": sha256(REPO / "src" / "alphaforge" / "backtest" / "fills.py"),
            "cost_model": sha256(REPO / "src" / "alphaforge" / "costs" / "model.py"),
        },
        "cases": cases,
        "participation_capped_to_baseline_median_ratio": capped / baseline,
        "interpretation_guardrails": [
            "Timings describe this local runtime and synthetic workload only.",
            "The benchmark measures fill-model call overhead, not end-to-end backtest throughput.",
            "Checksums verify deterministic executed outputs; timing samples are expected to vary.",
        ],
    }


def parse_args() -> argparse.Namespace:
    """Parse benchmark controls."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=DEFAULT_CALLS)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    """Run the benchmark and write canonical pretty JSON."""
    args = parse_args()
    report = build_report(calls=args.calls, repeats=args.repeats, warmup=args.warmup)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
