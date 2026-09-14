"""Four bounded Nasdaq control requests; distinguish empty table from filters."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-sfp-controls-20260912"


def main():
    OUT.mkdir(exist_ok=False)
    key = dotenv_values(Path.home() / ".config/alphaforge/sharadar.env")["SHARADAR_API_KEY"]
    requests = [
        ("sfp_unfiltered", "SFP.json", {"qopts.per_page": 1}),
        ("sep_aapl", "SEP.json", {"ticker": "AAPL", "qopts.per_page": 1}),
        ("sfp_metadata", "SFP/metadata.json", {}),
        ("ticker_sfp_spy", "TICKERS.json", {"table": "SFP", "ticker": "SPY", "qopts.per_page": 1}),
    ]
    results = []
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        for name, suffix, params in requests:
            row = {
                "name": name,
                "path": suffix,
                "params": params,
                "requested_at": datetime.now(UTC).isoformat(),
            }
            try:
                response = client.get(
                    "https://data.nasdaq.com/api/v3/datatables/SHARADAR/" + suffix,
                    params={**params, "api_key": key},
                )
                (OUT / (name + ".bin")).write_bytes(response.content)
                row.update(
                    http_status=response.status_code,
                    received_at=datetime.now(UTC).isoformat(),
                    sha256=hashlib.sha256(response.content).hexdigest(),
                )
                if response.status_code == 200:
                    body = response.json()
                    table = body.get("datatable", {})
                    row["rows"] = (
                        len(table["data"]) if isinstance(table.get("data"), list) else None
                    )
                    row["top_level_keys"] = list(body)
                    row["column_names"] = [c["name"] for c in table.get("columns", [])]
                    # Do not print raw error bodies or metadata URLs.
                else:
                    row["usable_data_access"] = False
            except (httpx.HTTPError, ValueError):
                row["error"] = "REQUEST_OR_PARSE_FAILURE"
            results.append(row)
            (OUT / (name + ".json")).write_text(json.dumps(row, indent=2) + "\n")
    (OUT / "result.json").write_text(
        json.dumps(
            {
                "scope": "BOUNDED_READ_ONLY_ACCESS_DIAGNOSIS",
                "max_requests": 4,
                "retries": 0,
                "results": results,
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "new_hypotheses": 0,
                "union_hypotheses": 238,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            [{k: r.get(k) for k in ["name", "http_status", "rows", "error"]} for r in results],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
