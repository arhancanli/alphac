"""Acquire the owner-authorized fixed data-quality sample, capped at $10 quoted cost."""

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import databento as db
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1] / "evidence"
DEST = ROOT / "wasde-market-sample"


def save(receipt):
    temporary = DEST / "receipt.tmp"
    temporary.write_text(json.dumps(receipt, indent=2) + "\n")
    temporary.replace(DEST / "receipt.json")


def main():
    DEST.mkdir(exist_ok=False)  # Never repeat billable requests implicitly.
    key = dotenv_values(Path.home() / ".config/alphaforge/databento.env")["DATABENTO_API_KEY"]
    client = db.Historical(
        dotenv_values(Path.home() / ".config/alphaforge/databento.env")["DATABENTO_API_KEY"]
    )
    source = json.loads((ROOT / "wasde-market-feasibility/metadata.json").read_text())
    requests = [
        r["parameters"]
        for r in source["requests"]
        if r["endpoint"] == "get_cost"
        and r["parameters"]["schema"] in ("mbp-10", "definition", "status")
    ]
    receipt = {
        "purpose": "fixed quality sample; no return trial",
        "cost_cap_usd": 10,
        "started_at": datetime.now(UTC).isoformat(),
        "requests": [],
    }
    for params in requests:
        cost_params = {k: v for k, v in params.items() if k != "stype_out"}
        price = client.metadata.get_cost(**cost_params)
        receipt["requests"].append(
            {"parameters": params, "estimate_usd": price, "status": "PRICED"}
        )
    total = sum(r["estimate_usd"] for r in receipt["requests"])
    receipt["total_estimate_usd"] = total
    save(receipt)
    if not math.isfinite(total) or total < 0 or total > 10:
        raise ValueError("cost cap exceeded")
    print(f"Fresh estimated retrieval cost ${total:.4f}; nine fixed requests", flush=True)
    for row in receipt["requests"]:
        params = row["parameters"]
        path = DEST / (params["start"] + "-" + params["schema"] + ".dbn.zst")
        row.update(status="ATTEMPT_STARTED", file=path.name)
        save(receipt)
        try:
            client.timeseries.get_range(**params, path=path)
            digest = hashlib.sha256()
            with path.open("rb") as f:
                for block in iter(lambda: f.read(1_048_576), b""):
                    digest.update(block)
            row.update(
                status="COMPLETE",
                bytes=path.stat().st_size,
                sha256=digest.hexdigest(),
                completed_at=datetime.now(UTC).isoformat(),
            )
            save(receipt)
            print(path.name, row["bytes"], "bytes saved", flush=True)
        except Exception as error:
            row.update(
                status="FAILED_NO_AUTOMATIC_RETRY",
                error_type=type(error).__name__,
                sanitized_message=str(error).replace(key, "[REDACTED]")[:1500],
            )
            save(receipt)
            print("Acquisition stopped; sanitized failure retained", flush=True)
            return
    receipt["status"] = "COMPLETE"
    save(receipt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEST)
    DEST = parser.parse_args().destination
    main()
