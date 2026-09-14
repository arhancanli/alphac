"""Fixed equity quote feasibility sample; price before purchase, no return trial."""

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import databento as db
from dotenv import dotenv_values

OUT = Path(__file__).resolve().parents[1] / "evidence/share-class-quotes-sdk-fix"
DATASETS = ["EQUS.MINI", "XNAS.ITCH"]
PARAMETERS = {
    "schema": "mbp-1",
    "symbols": ["GOOG", "GOOGL", "BRK.A", "BRK.B"],
    "stype_in": "raw_symbol",
    "stype_out": "instrument_id",
    "start": "2025-08-12T14:00:00Z",
    "end": "2025-08-12T14:02:00Z",
}


def main():
    OUT.mkdir(exist_ok=False)
    key = dotenv_values(Path.home() / ".config/alphaforge/databento.env").get("DATABENTO_API_KEY")
    if not key:
        raise RuntimeError("saved data credential missing")
    client = db.Historical(key)
    receipt = {
        "observed_at": datetime.now(UTC).isoformat(),
        "cap_usd": 1,
        "status": "PRICING",
        "requests": [],
        "return_trials": 0,
        "scope": "Fixed feed coverage sample; not SIP NBBO or executable fills",
    }

    def save():
        temp = OUT / "receipt.tmp"
        temp.write_text(json.dumps(receipt, indent=2) + "\n")
        temp.replace(OUT / "receipt.json")

    save()
    try:
        for dataset in DATASETS:
            params = {"dataset": dataset, **PARAMETERS}
            cost = float(
                client.metadata.get_cost(**{k: v for k, v in params.items() if k != "stype_out"})
            )
            if not math.isfinite(cost) or cost < 0:
                raise ValueError("invalid quote")
            receipt["requests"].append(
                {"parameters": params, "quoted_usd": cost, "status": "PRICED"}
            )
        receipt["quoted_total_usd"] = sum(r["quoted_usd"] for r in receipt["requests"])
        if receipt["quoted_total_usd"] > receipt["cap_usd"]:
            receipt["status"] = "OVER_CAP"
            save()
            return
        receipt["status"] = "PRICED"
        save()
        print("Fixed sample quoted USD", receipt["quoted_total_usd"], flush=True)
        for request in receipt["requests"]:
            path = OUT / (request["parameters"]["dataset"] + ".dbn.zst")
            request["status"] = "ATTEMPT_STARTED"
            save()
            client.timeseries.get_range(**request["parameters"], path=path)
            request.update(
                status="COMPLETE",
                file=path.name,
                bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            save()
        receipt["status"] = "COMPLETE"
    except Exception as error:
        receipt.update(status="FAILED", error_type=type(error).__name__)
    save()
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
