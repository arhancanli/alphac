"""Assemble a new source manifest, retaining the first collection unchanged."""

import hashlib
import json
from pathlib import Path

from alphaforge.validation.wasde_vintages import extract_tables
from alphaforge.validation.wasde_xml import extract_xml

ROOT = Path(__file__).resolve().parents[1] / "evidence"


def main():
    recovery = ROOT / "wasde-format-recovery"
    dest = ROOT / "wasde-reconstructed"
    dest.mkdir(exist_ok=False)
    original = json.loads((ROOT / "wasde-vintages/manifest.json").read_text())
    recovered = json.loads((recovery / "manifest.json").read_text())
    retry = json.loads((recovery / "retry.json").read_text())
    recovered = [retry if r["url"] == retry["url"] else r for r in recovered]
    variants = [
        r
        for r in recovered
        if r["date_label"] == "2019-11-08" and r["file"].endswith((".txt", ".xml"))
    ]
    if len(variants) != 6 or any(r["status"] != "RETRIEVED" for r in variants):
        raise ValueError("incomplete November comparison")
    tables = []
    for r in variants:
        raw = (recovery / r["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != r["sha256"]:
            raise ValueError("November source hash mismatch")
        tables.append(
            extract_xml(raw, "November 2019")
            if r["file"].endswith(".xml")
            else extract_tables(raw.decode())
        )
    if any(t != tables[0] for t in tables):
        raise ValueError("November selected grain fields differ")
    # Canonical representative by URL only after full selected-field equivalence.
    representative = min(
        (r for r in variants if r["file"].endswith(".txt")), key=lambda r: r["url"]
    )
    output = []
    for r in original["files"]:
        day = r["release_date_label"]
        if r["status"] == "RETRIEVED":
            output.append({**r, "file": "../wasde-vintages/" + r["file"], "format": "text"})
            continue
        if day == "2019-11-08":
            replacement = representative
        else:
            matches = [
                item
                for item in recovered
                if item["date_label"] == day
                and item["file"].endswith(".xml")
                and item["status"] == "RETRIEVED"
            ]
            if len(matches) != 1:
                raise ValueError(f"unresolved recovery {day}")
            replacement = matches[0]
        output.append(
            {
                **replacement,
                "release_date_label": day,
                "file": "../wasde-format-recovery/" + replacement["file"],
                "format": "xml" if replacement["file"].endswith(".xml") else "text",
                "intraday_publication_time_verified": False,
            }
        )
    (dest / "manifest.json").write_text(
        json.dumps(
            {
                "files": output,
                "november_selected_field_equivalence": variants,
                "historical_publication_times_verified": False,
                "return_trials_run": 0,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Assembled {len(output)} source dates; all six November variants retained in evidence")


if __name__ == "__main__":
    main()
