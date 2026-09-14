"""Metadata only: fixed-date sample estimates, no market-data downloads."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from datetime import date as calendar_date
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/sleeve-frontier-20260912"
DATES = ["2015-01-15", "2020-04-20", "2025-07-15"]


def main():
    key = dotenv_values(Path.home() / ".config/alphaforge/databento.env")["DATABENTO_API_KEY"]
    jobs = []
    for date in DATES:
        for schema in ["definition", "mbp-1"]:
            params = {
                "dataset": "GLBX.MDP3",
                "symbols": "CL.FUT,RB.FUT,HO.FUT",
                "stype_in": "parent",
                "schema": schema,
                "start": date + ("T00:00:00Z" if schema == "definition" else "T18:00:00Z"),
                "end": (str(calendar_date.fromisoformat(date) + timedelta(days=1)) + "T00:00:00Z")
                if schema == "definition"
                else date + "T18:10:00Z",
            }
            jobs.append(("metadata.get_cost", params))
        for symbol in ["CL.FUT", "RB.FUT", "HO.FUT"]:
            jobs.append(
                (
                    "metadata.get_record_count",
                    {
                        "dataset": "GLBX.MDP3",
                        "symbols": symbol,
                        "stype_in": "parent",
                        "schema": "mbp-1",
                        "start": date + "T18:00:00Z",
                        "end": date + "T18:10:00Z",
                    },
                )
            )

    def query(job):
        endpoint, params = job
        receipt = {"endpoint": endpoint, "parameters": params}
        try:
            response = requests.get(
                "https://hist.databento.com/v0/" + endpoint,
                params=params,
                auth=(key, ""),
                timeout=25,
            )
            receipt.update(
                http_status=response.status_code,
                received_at=datetime.now(UTC).isoformat(),
                response_sha256=hashlib.sha256(response.content).hexdigest(),
            )
            value = response.json()
            if (
                response.status_code == 200
                and isinstance(value, (float, int))
                and not isinstance(value, bool)
            ):
                receipt["value"] = value
            else:
                receipt["error"] = "unexpected status or nonnumeric metadata response"
        except requests.RequestException as exc:
            receipt["error_type"] = type(exc).__name__
        return receipt

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(query, jobs))
    costs = [r["value"] for r in receipts if r["endpoint"] == "metadata.get_cost" and "value" in r]
    counts = [
        r["value"]
        for r in receipts
        if r["endpoint"] == "metadata.get_record_count" and "value" in r
    ]
    result = {
        "received_at": datetime.now(UTC).isoformat(),
        "requests": receipts,
        "complete_estimate": len(costs) == 6,
        "sample_estimate_usd": sum(costs) if len(costs) == 6 else None,
        "all_nine_root_windows_nonempty": len(counts) == 9 and all(n > 0 for n in counts),
        "quote_records_downloaded": 0,
        "market_data_purchase": False,
        "scope": (
            "three roots, three fixed dates; daily definitions and ten-minute "
            "MBP-1 windows; no full-history estimate"
        ),
        "no_liquidity_or_execution_quality_claim": True,
    }
    (OUT / "refining_data_estimate.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "requests"}, indent=2))


if __name__ == "__main__":
    main()
