"""Bound revision statements to retained evidence; never infer publication dates."""

import gzip
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = Path("/Users/arhancanli/alphaforge/data/raw/natural_gas_storage_weather")
OUT = ROOT / "evidence/gas-revision-lineage-20260913"


def main():
    workbook = RAW / "revisions.xls"
    captures_path = ROOT / "evidence/gas-original-source-audit-20260913/all_capture_comparisons.csv"
    frame = pd.read_excel(workbook, sheet_name="original_data", header=1)
    frame["Week ending"] = pd.to_datetime(frame["Week ending"])
    frame = frame[frame["Week ending"].between("2017-01-06", "2025-12-31")]
    rows = []
    pattern = re.compile(
        r"stocks for ([A-Za-z]+ \d{1,2},? \d{4}),? to change from ([\d,]+) Bcf to ([\d,]+) Bcf",
        re.I,
    )
    for _, row in frame[frame.Explanation.notna()].iterrows():
        note = str(row.Explanation)
        matches = pattern.findall(note)
        rows.append(
            {
                "workbook_week": row["Week ending"].isoformat(),
                "note": note,
                "explicit_stock_corrections": [
                    {
                        "affected_week_text": date,
                        "old_bcf": int(old.replace(",", "")),
                        "revised_bcf": int(new.replace(",", "")),
                    }
                    for date, old, new in matches
                ],
                "publication_time": None,
                "classification": "explicit_stock_correction" if matches else "unresolved_note",
            }
        )
    captures = pd.read_csv(captures_path, dtype={"timestamp": str})
    captures["known_by_capture_utc"] = pd.to_datetime(
        captures.timestamp, format="%Y%m%d%H%M%S", utc=True
    )
    captures["reported_release_date"] = pd.to_datetime(captures.release_date, utc=True)
    assert (captures.known_by_capture_utc >= captures.reported_release_date).all()
    # Keep source header times as text; report dates are not instrument-specific tradable times.
    boundaries = captures[
        [
            "period_end",
            "timestamp",
            "known_by_capture_utc",
            "release_date",
            "release_time_text",
            "reported_total_bcf",
            "reported_prior_total_bcf",
            "reported_net_change_bcf",
            "raw_sha256",
            "capture_url",
        ]
    ]
    boundaries.to_csv(OUT / "observed_availability_bounds.csv", index=False)
    mismatch = captures[captures.change_difference != 0]
    assert len(mismatch) == 1
    row = mismatch.iloc[0]
    prior_note = next(r for r in rows if r["workbook_week"].startswith("2018-06-15"))
    correction = prior_note["explicit_stock_corrections"]
    assert (
        len(correction) == 1
        and correction[0]["old_bcf"] == 2004
        and correction[0]["revised_bcf"] == 2008
    )
    assert row.reported_prior_total_bcf == 2008 and row.reported_total_bcf == 2074
    assert (
        row.reported_total_bcf - row.reported_prior_total_bcf == row.reported_net_change_bcf == 66
    )
    hashes = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [workbook, captures_path, Path(__file__)]
    }
    for capture in captures.itertuples():
        p = RAW / "wayback_wngsr" / f"{capture.timestamp}.csv.gz"
        assert hashlib.sha256(gzip.decompress(p.read_bytes())).hexdigest() == capture.raw_sha256
        hashes[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    (OUT / "revision_notes.json").write_text(json.dumps(rows, indent=2) + "\n")
    result = {
        "notes": len(rows),
        "notes_with_explicit_correction": sum(bool(r["explicit_stock_corrections"]) for r in rows),
        "expected_weeks": len(frame),
        "weeks_with_archived_known_by_bound": boundaries.period_end.nunique(),
        "mismatch_numerically_explained": True,
        "revision_publication_times_inferred": False,
        "full_revision_timeline_reconstructed": False,
        "decision": "PARK_SOURCE_INCOMPLETE",
        "new_return_identities": 0,
        "source_sha256": hashes,
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "source_sha256"}, indent=2))


if __name__ == "__main__":
    main()
