"""Bounded metadata and cost-estimate requests only; never retrieve market records."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

OUT = Path(__file__).resolve().parents[1] / "evidence/wasde-market-feasibility"
BASE = "https://hist.databento.com/v0/metadata."


def main():
    OUT.mkdir(exist_ok=False)
    key = dotenv_values(Path.home() / ".config/alphaforge/databento.env").get("DATABENTO_API_KEY")
    if not key:
        raise RuntimeError("saved data credential unavailable")
    requests = [
        ("GET", "get_dataset_range", {"dataset": "GLBX.MDP3"}),
        ("GET", "list_schemas", {"dataset": "GLBX.MDP3"}),
    ]
    for start, end in [
        ("2015-01-12", "2015-01-15"),
        ("2018-08-10", "2018-08-15"),
        ("2025-08-12", "2025-08-15"),
    ]:
        for schema in ("mbp-1", "mbp-10", "definition", "status"):
            requests.append(
                (
                    "POST",
                    "get_cost",
                    {
                        "dataset": "GLBX.MDP3",
                        "start": start,
                        "end": end,
                        "schema": schema,
                        "symbols": "ZC.FUT,ZW.FUT,ZS.FUT",
                        "stype_in": "parent",
                        "stype_out": "instrument_id",
                    },
                )
            )

    def request(item):
        method, endpoint, params = item
        result = {"endpoint": endpoint, "parameters": params}
        try:
            with httpx.Client(auth=(key, ""), timeout=20, follow_redirects=False) as client:
                response = (
                    client.get(BASE + endpoint, params=params)
                    if method == "GET"
                    else client.post(BASE + endpoint, data=params)
                )
            result["http_status"] = response.status_code
            if response.status_code == 200:
                result.update(status="OK", value=response.json())
            else:
                # Do not persist error bodies, request headers or credential material.
                result["status"] = "FAILED"
        except Exception as error:
            result.update(status="FAILED", error_type=type(error).__name__)
        return result

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(request, requests))
    output = {
        "observed_at": datetime.now(UTC).isoformat(),
        "requests": results,
        "market_records_requested": 0,
        "purchases_submitted": 0,
        "sample_estimates_only": True,
        "return_trials_run": 0,
    }
    (OUT / "metadata.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
