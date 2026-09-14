"""Two GET-only current paper asset observations; no orders, locates or historical inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values


def classify(asset):
    status = asset.get("borrow_status")
    if status is None:
        return "UNKNOWN_NEW_FIELD_ABSENT"
    if asset.get("tradable") is not True or asset.get("shortable") is not True:
        return "NOT_SHORTABLE_OR_TRADABLE"
    if status == "easy_to_borrow":
        return "CURRENT_PAPER_ETB_OBSERVATION_ONLY"
    if status == "hard_to_borrow":
        return "HTB_APPROVED_LOCATE_REQUIRED"
    return "UNKNOWN_BORROW_STATUS"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    values = dotenv_values(args.credentials)
    if (
        values.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
        != "https://paper-api.alpaca.markets"
    ):
        raise ValueError("Paper origin required")
    headers = {
        "APCA-API-KEY-ID": values["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": values["APCA_API_SECRET_KEY"],
    }
    receipt = {
        "schema": "alphac.alphabet-borrow-observation.v1",
        "method": "GET",
        "execution_basis": "paper",
        "orders_submitted": 0,
        "locates_requested": 0,
        "clock_calibrated": False,
        "historically_usable": False,
        "source_event_timestamp": None,
        "records": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Claim a new file before contacting the service; previous observations are immutable.
    with args.output.open("x") as output:
        with httpx.Client(
            headers=headers, timeout=8, follow_redirects=False, trust_env=False
        ) as client:
            for symbol in ("GOOG", "GOOGL"):
                row = {"symbol": symbol, "requested_at_local": datetime.now(UTC).isoformat()}
                try:
                    response = client.get(f"https://paper-api.alpaca.markets/v2/assets/{symbol}")
                    row.update(
                        received_at_local=datetime.now(UTC).isoformat(),
                        server_date=response.headers.get("date"),
                        http_status=response.status_code,
                    )
                    if response.status_code == 200:
                        asset = response.json()
                        if asset.get("symbol") != symbol or asset.get("class") != "us_equity":
                            raise ValueError("Identity mismatch")
                        fields = (
                            "symbol",
                            "class",
                            "exchange",
                            "status",
                            "tradable",
                            "marginable",
                            "shortable",
                            "borrow_status",
                            "easy_to_borrow",
                        )
                        row["asset"] = {k: asset.get(k) for k in fields}
                        row["classification"] = classify(asset)
                        row["body_sha256"] = hashlib.sha256(response.content).hexdigest()
                    else:
                        row["classification"] = "UNAVAILABLE_HTTP_ERROR"
                except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                    row["classification"] = "UNVERIFIED_ERROR"
                receipt["records"].append(row)
        json.dump(receipt, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
