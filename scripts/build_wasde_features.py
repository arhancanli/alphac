"""Reconstruct source-only forecast revisions. These are not executable signals."""

import argparse
import calendar
import hashlib
import json
from pathlib import Path

from alphaforge.validation.wasde_vintages import extract_tables
from alphaforge.validation.wasde_xml import extract_xml

ROOT = Path(__file__).resolve().parents[1] / "evidence/wasde-vintages"


def main(root=ROOT):
    manifest = json.loads((root / "manifest.json").read_text())
    tables, failures, features = [], [], []
    prior = {}
    seen_reports = set()
    for source in sorted(manifest["files"], key=lambda row: row["release_date_label"]):
        label = source["release_date_label"]
        if source["status"] != "RETRIEVED":
            failures.append({"date": label, "error": source["status"]})
            prior.clear()  # Do not silently bridge a failed source.
            continue
        try:
            raw = (root / source["file"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise ValueError("source hash mismatch")
            if source.get("format", "text") == "xml":
                month = calendar.month_name[int(label[5:7])] + " " + label[:4]
                parsed = extract_xml(raw, month)
            elif source.get("format", "text") == "text":
                parsed = extract_tables(raw.decode())
            else:
                raise ValueError("unsupported source format")
        except (ValueError, UnicodeError) as error:
            failures.append({"date": label, "error": str(error)})
            prior.clear()
            continue
        report = parsed[0]["report_id"]
        repeat = report in seen_reports
        for row in parsed:
            row.update(
                release_date_label=label,
                source_sha256=source["sha256"],
                available_at=None,
                tradable=False,
            )
        for crop in ("wheat", "corn", "soybeans"):
            current = max(
                (row for row in parsed if row["crop"] == crop), key=lambda row: row["crop_year"]
            )
            key = (crop, current["crop_year"])
            earlier = prior.get(key)
            feature = {
                "crop": crop,
                "crop_year": current["crop_year"],
                "date_label": label,
                "report_id": report,
                "source_sha256": source["sha256"],
                "available_at": None,
                "tradable": False,
                "status": "CORRECTION_VERSION"
                if repeat
                else "NO_PRIOR_SAME_CROP_YEAR"
                if earlier is None
                else "REVISION_OBSERVED",
            }
            if earlier is not None:
                feature.update(
                    prior_date_label=earlier["release_date_label"],
                    prior_source_sha256=earlier["source_sha256"],
                    stocks_to_use_change=current["stocks_to_use"] - earlier["stocks_to_use"],
                    ending_stocks_change_million_bushels=(
                        current["values"]["ending_stocks"] - earlier["values"]["ending_stocks"]
                    ),
                )
            features.append(feature)
        # Preserve all crop years for the next release, including correction versions.
        prior = {(row["crop"], row["crop_year"]): row for row in parsed}
        seen_reports.add(report)
        tables.extend(parsed)
    output = {
        "schema": "alphac.wasde-source-features.v1",
        "tables": tables,
        "features": features,
        "failures": failures,
        "return_trials_run": 0,
        "prices_opened": False,
        "publication_times_verified": False,
    }
    (root / "source-features.json").write_text(json.dumps(output, indent=2) + "\n")
    summary = {
        "parsed_date_labels": len({row["release_date_label"] for row in tables}),
        "table_rows": len(tables),
        "failed_date_labels": len(failures),
        "revision_rows": sum(row["status"] == "REVISION_OBSERVED" for row in features),
        "correction_rows": sum(row["status"] == "CORRECTION_VERSION" for row in features),
        "no_comparable_prior_rows": sum(
            row["status"] == "NO_PRIOR_SAME_CROP_YEAR" for row in features
        ),
        "tradable_rows": 0,
        "return_trials_run": 0,
    }
    (root / "feature-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))
    print(json.dumps(failures[:15]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=ROOT)
    main(parser.parse_args().dataset_dir)
