"""Audit frozen timing evidence; never manufacture a public-availability timestamp."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import databento as db
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "evidence/wasde-timing-lifecycle"


def main():
    receipt = json.loads((DEST / "receipt.json").read_text())
    timing = []
    for row in receipt["files"]:
        if row["status"] != "RETRIEVED":
            continue
        body = (DEST / row["file"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != row["sha256"]:
            raise ValueError("source hash mismatch: " + row["file"])
        if not row["file"].startswith("release-"):
            continue
        stamps = re.findall(r'<time\b[^>]*datetime="([^"]+)"', body.decode())
        if len(stamps) != 1:
            raise ValueError("ambiguous archive time element")
        stamp = datetime.fromisoformat(stamps[0])
        if stamp.tzinfo is None:
            raise ValueError("naive archive time")
        local = stamp.astimezone(ZoneInfo("America/New_York"))
        scheduled = datetime.combine(local.date(), datetime.min.time()).replace(
            hour=12, tzinfo=ZoneInfo("America/New_York")
        )
        timing.append(
            {
                "source_file": row["file"],
                "source_sha256": row["sha256"],
                "html_datetime": stamps[0],
                "new_york_time": local.isoformat(),
                "scheduled_reference": scheduled.isoformat(),
                "difference_seconds": (local - scheduled).total_seconds(),
                "classification": "DATE_LABEL_METADATA_NOT_PUBLIC_AVAILABILITY",
                "verified_available_at": None,
            }
        )
    # Reviewed CBOT rows, not the similarly named NYMEX/COMEX first-notice columns.
    notices = [
        {
            "notice": "18-462",
            "notice_date": "2018-11-20",
            "sample": "2018-08-10",
            "symbols": ["ZCZ8", "ZWZ8"],
            "first_intent": "2018-11-29",
            "last_trade": "2018-12-14",
            "url": "https://www.cmegroup.com/notices/clearing/2018/11/Chadv18-462.pdf",
        },
        {
            "notice": "18-053",
            "notice_date": "2018-10-19",
            "sample": "2018-08-10",
            "symbols": ["ZSX8"],
            "first_intent": "2018-10-30",
            "last_trade": "2018-11-14",
            "url": "https://www.cmegroup.com/notices/clearing/2018/10/Chadv18-053.pdf",
        },
        {
            "notice": "25-328",
            "notice_date": "2025-10-17",
            "sample": "2025-08-12",
            "symbols": ["ZSX5"],
            "first_intent": "2025-10-30",
            "last_trade": "2025-11-14",
            "url": "https://www.cmegroup.com/content/dam/cmegroup/notices/clearing/2025/10/chadv25-328.pdf",
        },
    ]
    lifecycle = []
    for notice in notices:
        path = (
            ROOT
            / "evidence/wasde-market-sample-after-budget-fix"
            / (notice["sample"] + "-definition.dbn.zst")
        )
        frame = db.DBNStore.from_file(path).to_df()
        decision = pd.Timestamp(notice["sample"] + " 12:05:00", tz="America/New_York")
        for symbol in notice["symbols"]:
            known = frame[
                (frame.index <= decision) & (frame.ts_event <= decision) & (frame.symbol == symbol)
            ]
            if known.instrument_id.nunique() != 1:
                raise ValueError("ambiguous contract identity")
            expiration = known.iloc[-1].expiration
            lifecycle.append(
                {
                    **notice,
                    "symbol": symbol,
                    "instrument_id": int(known.iloc[-1].instrument_id),
                    "definition_expiration": expiration.isoformat(),
                    "definition_matches_notice_last_trade": str(
                        expiration.tz_convert("America/Chicago").date()
                    )
                    == notice["last_trade"],
                    "notice_postdates_decision": notice["notice_date"] > notice["sample"],
                    "source_access": "WEB_TOOL_TEXT; direct PDF request failed",
                    "first_notice": None,
                    "eligibility_verified": False,
                }
            )
    result = {
        "timing": timing,
        "lifecycle": lifecycle,
        "return_trials": 0,
        "retrieved_source_hashes_verified": sum(
            row["status"] == "RETRIEVED" for row in receipt["files"]
        ),
        "note": (
            "Hash checks cover successfully downloaded receipt entries only; "
            "CME facts are web-reviewed"
        ),
    }
    (DEST / "audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
