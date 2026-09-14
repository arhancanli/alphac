"""Link two fixed legal-review cases to local identity and corporate-action evidence.

This is a source audit, not a PIT universe, valuation signal, order or return trial.
"""

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = Path("/Users/arhancanli/alphaforge/data/sharadar_raw/ACTIONS.zip")
DEST = ROOT / "evidence/share-class-rights"
CASES = [
    {
        "id": "alphabet_public_classes",
        "tickers": ["GOOG", "GOOGL"],
        "economic_units": {"GOOG": 1, "GOOGL": 1},
        "ordinary_conversion_edges": [],
        "voting_rights_equal": False,
        "convergence_enforced": False,
        "source_urls": [
            "https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm",
            "https://www.sec.gov/Archives/edgar/data/1652044/000165204422000019/googexhibit420q42021.htm",
        ],
        "classification": "RELATIVE_VALUE_WITH_UNRESOLVED_VOTING_PREMIUM",
        "historical_limit": (
            "2024 economic rights and 2021 conversion description; "
            "amendments not exhaustively traced"
        ),
    },
    {
        "id": "berkshire_public_classes",
        "tickers": ["BRK.A", "BRK.B"],
        "economic_units": {"BRK.A": 1500, "BRK.B": 1},
        "ordinary_conversion_edges": [
            {"from": "BRK.A", "quantity_from": 1, "to": "BRK.B", "quantity_to": 1500}
        ],
        "voting_rights_equal": False,
        "convergence_enforced": False,
        "source_urls": ["https://berkshirehathaway.com/2024ar/2024ar.pdf"],
        "classification": "ONE_WAY_CONVERSION_WITH_OPERATIONS_AND_BORROW_GATES",
        "historical_limit": "2024 rights reviewed; do not apply 1500 ratio before 2010 B split",
    },
]


def main():
    screen = ROOT / "evidence/equity-breadth-screen/share-class-candidates.json"
    candidates = json.loads(screen.read_text())["pairs"]
    actions = []
    with zipfile.ZipFile(ACTIONS) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError("ambiguous action archive")
        with archive.open(names[0]) as source:
            reader = csv.DictReader(io.TextIOWrapper(source))
            for row in reader:
                if (
                    row["ticker"] in {"GOOG", "GOOGL", "BRK.A", "BRK.B"}
                    and row["action"] == "split"
                ):
                    actions.append(row)
    results = []
    for case in CASES:
        matching = [
            row
            for row in candidates
            if {leg["ticker"] for leg in row["legs"]} == set(case["tickers"])
        ]
        if len(matching) != 1:
            raise ValueError("missing or ambiguous screened pair")
        results.append(
            {
                **case,
                "metadata_identity": matching[0],
                "actions": [a for a in actions if a["ticker"] in case["tickers"]],
                "point_in_time_identity_verified": False,
                "execution_eligible": False,
                "return_trials": 0,
                "open_gates": [
                    "Legal amendment history",
                    "Synchronized executable quotes",
                    "Borrow, settlement, conversion fees and latency",
                    "Fixed model and lineage review",
                ],
            }
        )
    split_match = [
        a
        for a in actions
        if a["ticker"] == "BRK.B" and a["date"] == "2010-01-21" and a["value"] == "50.0"
    ]
    if len(split_match) != 1:
        raise ValueError("Berkshire source split not corroborated locally")
    output = {
        "cases": results,
        "candidate_pairs_reviewed": 2,
        "new_admissions": 0,
        "split_check": "Berkshire 2010-01-21 50-for-1 matches issuer/SEC history",
        "split_source": "https://www.sec.gov/Archives/edgar/data/1067983/000119312510018135/dex992.htm",
        "metadata_sha256": hashlib.sha256(screen.read_bytes()).hexdigest(),
        "actions_sha256": hashlib.sha256(ACTIONS.read_bytes()).hexdigest(),
        "caution": "Economic units do not establish a fair-price ratio or a permitted trade",
    }
    (DEST / "rights-audit.json").write_text(json.dumps(output, indent=2) + "\n")
    print("Two legal-review cases linked; Berkshire split corroborated; zero return trials")


if __name__ == "__main__":
    main()
