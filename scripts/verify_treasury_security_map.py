"""Independent reference selection and security-versus-tranche issue audit."""

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/treasury-security-map-20260912/v2"


def main():
    for name in ("protocol.json", "../protocol.json"):
        for p, h in json.loads((OUT / name).read_text())["bindings"].items():
            assert hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
    raw = pd.DataFrame(json.loads((OUT / "fiscal_identity.json").read_text())["data"])
    nominal = raw[(raw.floating_rate == "No") & (raw.inflation_index_security == "No")]
    candidates = {
        "note_2y": nominal[(nominal.security_type == "Note") & (nominal.security_term == "2-Year")],
        "bill_6m": nominal[
            (nominal.security_type == "Bill") & (nominal.security_term == "26-Week")
        ],
        "note_10y": nominal[
            (nominal.security_type == "Note")
            & (nominal.original_security_term == "10-Year")
            & (nominal.reopening == "No")
        ],
    }
    rows = json.loads((OUT / "mapping.json").read_text())
    old = pd.read_parquet(OUT / "original_events.parquet")
    first = old.groupby("cusip").issue_date.min()
    cache, checks, annotations = {}, 0, []
    for row in rows:
        day = row["session"]
        for bucket, ref in row["references"].items():
            key = (day, bucket)
            if key not in cache:
                f = candidates[bucket]
                f = f[
                    (f.announcemt_date < day)
                    & (f.auction_date < day)
                    & (f.issue_date <= day)
                    & (f.maturity_date > day)
                ]
                f = f.sort_values(["issue_date", "auction_date"])
                assert len(f)
                cache[key] = f.iloc[-1].cusip
            assert ref["cusip"] == cache[key]
            checks += 1
        earliest = str(first[row["auction_cusip"]].date())
        annotations.append(
            {
                "event_identity": row["event_identity"],
                "session": day,
                "phase": row["phase"],
                "cusip": row["auction_cusip"],
                "first_issue_in_source": earliest,
                "auction_tranche_issue_date": row["auction_issue_date"],
                "before_auction_tranche_issue": day < row["auction_issue_date"],
                "before_security_first_issue_in_source": day < earliest,
            }
        )
    result = {
        "reference_checks": checks,
        "distinct_day_bucket_checks": len(cache),
        "post_rows_before_security_first_issue": sum(
            r["phase"] == "post" and r["before_security_first_issue_in_source"] for r in annotations
        ),
        "post_rows_before_tranche_but_security_already_issued": sum(
            r["phase"] == "post"
            and r["before_auction_tranche_issue"]
            and not r["before_security_first_issue_in_source"]
            for r in annotations
        ),
        "caveat": (
            "auction_security_issued describes the tranche only; "
            "use issue_lineage.json for security first issuance"
        ),
        "historical_vintages_verified": False,
        "tradability_verified": False,
    }
    (OUT / "issue_lineage.json").write_text(json.dumps(annotations, indent=2) + "\n")
    (OUT / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
