"""Fixed modern-sample depth scenarios; no signal selection, fees, or return trial."""

import hashlib
import json
from pathlib import Path

import databento as db
import databento_dbn as dbn
import pandas as pd

from alphaforge.validation.depth_probe import sweep_book

DIRECTORY = Path("evidence/wasde-market-sample-after-budget-fix")
# Chosen for diagnostics before inspecting fills, not certified lifecycle eligibility.
SAMPLES = [
    ("2018-08-10", "2018-08-13", ["ZCZ8", "ZWZ8", "ZSX8"]),
    ("2025-08-12", "2025-08-13", ["ZCZ5", "ZWZ5", "ZSX5"]),
]


def probe(day, exit_day, symbols):
    definitions = db.DBNStore.from_file(DIRECTORY / f"{day}-definition.dbn.zst").to_df()
    statuses = db.DBNStore.from_file(DIRECTORY / f"{day}-status.dbn.zst").to_df()
    if not definitions.index.is_monotonic_increasing or not statuses.index.is_monotonic_increasing:
        raise ValueError("Reference receive timestamps are unordered")
    targets = []
    for label, date in [("entry_clock", day), ("exit_clock", exit_day)]:
        clock = pd.Timestamp(date + " 12:05:00", tz="America/New_York")
        at = clock + pd.Timedelta(milliseconds=250)
        for symbol in symbols:
            known = definitions[
                (definitions.index <= clock)
                & (definitions.ts_event <= clock)
                & (definitions.symbol == symbol)
            ]
            ids = known.instrument_id.unique()
            if len(ids) != 1:
                raise ValueError(f"Ambiguous or missing dated identity: {symbol}")
            instrument = int(ids[0])
            status = statuses[(statuses.index <= at) & (statuses.instrument_id == instrument)]
            last_status = status.iloc[-1] if len(status) else None
            opened = (
                last_status is not None
                and last_status.ts_event <= status.index[-1]
                and last_status.is_trading == "Y"
                and last_status.is_quoting == "Y"
            )
            targets.append(
                {
                    "label": label,
                    "symbol": symbol,
                    "instrument_id": instrument,
                    "at": at,
                    "market_open": bool(opened),
                    "latest": None,
                    "status_received": str(status.index[-1]) if len(status) else None,
                }
            )
    # Preserve file order and every row, including bad rows: no cherry-picking good quotes.
    previous_receive = None
    for frame in db.DBNStore.from_file(DIRECTORY / f"{day}-mbp-10.dbn.zst").to_df(count=100000):
        if len(frame) == 0:
            continue
        if not frame.index.is_monotonic_increasing or (
            previous_receive is not None and frame.index[0] < previous_receive
        ):
            raise ValueError("Depth receive timestamps are unordered")
        previous_receive = frame.index[-1]
        for target in targets:
            selected = frame[
                (frame.instrument_id == target["instrument_id"]) & (frame.index <= target["at"])
            ]
            if len(selected):
                row = selected.iloc[-1]
                recv = selected.index[-1]
                previous = target["latest"]
                if previous is not None and recv.value < previous["recv_ns"]:
                    raise ValueError("Receive timestamps regressed across chunks")
                flags = int(row["flags"])
                target["latest"] = {
                    "recv_ns": recv.value,
                    "event_ns": row.ts_event.value,
                    "action": str(row.action),
                    "flags": flags,
                    "sequence": int(row.sequence),
                    "market_open": target["market_open"],
                    "quality_ok": bool(flags & dbn.F_LAST)
                    and not bool(
                        flags & (dbn.F_BAD_TS_RECV | dbn.F_MAYBE_BAD_BOOK | dbn.F_SNAPSHOT)
                    ),
                    "bids": [
                        (float(row[f"bid_px_{i:02}"]), int(row[f"bid_sz_{i:02}"]))
                        for i in range(10)
                    ],
                    "asks": [
                        (float(row[f"ask_px_{i:02}"]), int(row[f"ask_sz_{i:02}"]))
                        for i in range(10)
                    ],
                }
    results = []
    for target in targets:
        for side in ["buy", "sell"]:
            for quantity in [1, 10, 100]:
                results.append(
                    {k: v for k, v in target.items() if k not in {"latest", "at"}}
                    | {
                        "as_of": target["at"].isoformat(),
                        "side": side,
                        "book_received_ns": target["latest"]["recv_ns"]
                        if target["latest"]
                        else None,
                        "book_event_ns": target["latest"]["event_ns"] if target["latest"] else None,
                        "book_action": target["latest"]["action"] if target["latest"] else None,
                        "book_flags": target["latest"]["flags"] if target["latest"] else None,
                        "book_sequence": target["latest"]["sequence"] if target["latest"] else None,
                        **sweep_book(
                            target["latest"],
                            as_of_ns=target["at"].value,
                            side=side,
                            quantity=quantity,
                        ),
                    }
                )
    return results


def main():
    results = []
    for sample in SAMPLES:
        results.extend(probe(*sample))
        print(f"{sample[0]} complete", flush=True)
    inputs = {}
    for day, _, _ in SAMPLES:
        for schema in ["definition", "status", "mbp-10"]:
            path = DIRECTORY / f"{day}-{schema}.dbn.zst"
            with path.open("rb") as source:
                inputs[path.name] = hashlib.file_digest(source, "sha256").hexdigest()
    output = {
        "input_sha256": inputs,
        "implementation_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [Path(__file__), Path("src/alphaforge/validation/depth_probe.py")]
        },
        "scope": "Independent displayed-depth scenarios; not orders or strategy fills",
        "latency_ms": 250,
        "max_book_age_ms": 1000,
        "return_trials": 0,
        "contract_eligibility_verified": False,
        "report_availability_verified": False,
        "limitations": [
            "No queue, impact, fees, margin or unit conversion model",
            "No channel-level continuity certification",
            "Entry/exit clocks are not linked positions",
            "Each size and side scenario reuses the book independently",
        ],
        "results": results,
    }
    (DIRECTORY / "execution-depth-probe.json").write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
