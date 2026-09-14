"""Build a price-blind share-class investigation list, not a historical universe."""

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SOURCE = Path("/Users/arhancanli/alphaforge/data/sharadar_raw/TICKERS.zip")
OUT = Path(__file__).resolve().parents[1] / "evidence/equity-breadth-screen"


def main():
    groups = defaultdict(list)
    with zipfile.ZipFile(SOURCE) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".csv"))
        with archive.open(name) as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw)):
                if row["table"] != "SEP" or row["category"] not in (
                    "Domestic Common Stock Primary Class",
                    "Domestic Common Stock Secondary Class",
                ):
                    continue
                cik = parse_qs(urlparse(row["secfilings"]).query).get("CIK", [""])[0]
                if cik:
                    groups[cik].append(row)
    exclusions = Counter()
    pairs = []
    for cik, rows in groups.items():
        for i, a in enumerate(rows):
            for b in rows[i + 1 :]:
                if a["permaticker"] == b["permaticker"] or a["category"] == b["category"]:
                    exclusions["same_security_or_same_class"] += 1
                    continue
                if any(not r[k] for r in (a, b) for k in ("firstpricedate", "lastpricedate")):
                    exclusions["missing_date_bounds"] += 1
                    continue
                start = max(a["firstpricedate"], b["firstpricedate"])
                end = min(a["lastpricedate"], b["lastpricedate"])
                if start > end:
                    exclusions["no_metadata_date_overlap"] += 1
                    continue
                if any(
                    "unit" in r["name"].lower().split()
                    or r["industry"].lower() == "shell companies"
                    for r in (a, b)
                ):
                    exclusions["possible_unit_or_shell"] += 1
                    continue
                if any(re.search(r"(?:\.U|U\d*)$", r["ticker"]) for r in (a, b)):
                    exclusions["possible_unit_symbol_suffix"] += 1
                    continue
                if a["name"] != b["name"]:
                    exclusions["different_current_names"] += 1
                    continue
                keys = [
                    "ticker",
                    "permaticker",
                    "name",
                    "category",
                    "sector",
                    "industry",
                    "firstpricedate",
                    "lastpricedate",
                    "isdelisted",
                ]
                pairs.append(
                    {
                        "cik": cik,
                        "legs": [{k: r[k] for k in keys} for r in (a, b)],
                        "metadata_overlap_start": start,
                        "metadata_overlap_end": end,
                    }
                )
    result = {
        "source": str(SOURCE),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "candidate_pairs": len(pairs),
        "issuer_groups": len({p["cik"] for p in pairs}),
        "exclusions": dict(exclusions),
        "pairs": pairs,
        "filter": "same CIK and current name, different primary/secondary permatickers, "
        "overlapping price-date bounds, heuristic units/shell exclusion",
        "historical_identity_verified": False,
        "legal_economic_equivalence_verified": False,
        "not_a_point_in_time_universe": True,
        "return_trials_run": 0,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "share-class-candidates.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "pairs"}))


if __name__ == "__main__":
    main()
