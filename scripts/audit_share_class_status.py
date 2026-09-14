"""Join source status to the existing fixed quote-clock audit; no inferred SSR state."""

import hashlib
import json
from pathlib import Path

import databento as db
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main():
    outputs = []
    for dataset, quote_dir, legs in [
        ("XNAS.ITCH", "share-class-quotes-sdk-fix", ["GOOG", "GOOGL"]),
        ("XNYS.PILLAR", "share-class-quotes-nyse", ["BRK A", "BRK B"]),
    ]:
        folder = ROOT / "evidence/share-class-status" / dataset
        receipt = json.loads((folder / "receipt.json").read_text())
        if receipt["status"] != "COMPLETE":
            raise ValueError("incomplete acquisition")
        request = receipt["requests"][0]
        path = folder / request["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != request["sha256"]:
            raise ValueError("status hash mismatch")
        status = db.DBNStore.from_file(path).to_df()
        if not status.index.is_monotonic_increasing:
            raise ValueError("unordered status timestamps")
        coverage = json.loads((ROOT / "evidence" / quote_dir / "pair-coverage.json").read_text())
        pair = next(
            p
            for r in coverage["results"]
            if r["dataset"] == dataset
            for p in r["pairs"]
            if p["legs"] == legs
        )
        quote = db.DBNStore.from_file(ROOT / "evidence" / quote_dir / f"{dataset}.dbn.zst").to_df()
        observations = []
        for record in pair["observations"]:
            at = pd.Timestamp(record["as_of"])
            states = []
            for symbol in legs:
                ids = quote[quote.symbol == symbol].instrument_id.unique()
                if len(ids) != 1:
                    raise ValueError("ambiguous quote identity")
                known = status[(status.index <= at) & (status.instrument_id == ids[0])]
                state = {"symbol": symbol, "open": False, "short_unrestricted": False}
                if len(known):
                    row = known.iloc[-1]
                    valid = not pd.isna(row.ts_event) and row.ts_event <= known.index[-1]
                    state.update(
                        received_at=str(known.index[-1]),
                        action=int(row.action),
                        open=bool(valid and row.is_trading == "Y" and row.is_quoting == "Y"),
                        short_unrestricted=bool(valid and row.is_short_sell_restricted == "N"),
                        source_ssr=row.is_short_sell_restricted,
                    )
                states.append(state)
            observations.append(
                {
                    **record,
                    "states": states,
                    "quote_and_open": record["status"] == "both_valid"
                    and all(s["open"] for s in states),
                    "both_short_unrestricted": all(s["short_unrestricted"] for s in states),
                }
            )
        outputs.append(
            {
                "dataset": dataset,
                "status_records": len(status),
                "legs": legs,
                "quote_and_open_clocks": sum(r["quote_and_open"] for r in observations),
                "quote_open_and_both_short_unrestricted_clocks": sum(
                    r["quote_and_open"] and r["both_short_unrestricted"] for r in observations
                ),
                "observations": observations,
            }
        )
    output = {
        "results": outputs,
        "borrow_verified": False,
        "execution_eligible": False,
        "scope": "Feed-local status; unrestricted SSR is not a borrow locate",
        "return_trials": 0,
    }
    (ROOT / "evidence/share-class-status/audit.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )
    print(
        [
            (
                r["dataset"],
                r["status_records"],
                r["quote_and_open_clocks"],
                r["quote_open_and_both_short_unrestricted_clocks"],
            )
            for r in outputs
        ]
    )


if __name__ == "__main__":
    main()
