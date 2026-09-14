"""Read-only inspection of an isolated AlphaTrend observation journal."""

import argparse
import json
import sqlite3
from pathlib import Path

from alphaforge.validation.trend_observation import TrendObservationJournal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journal", type=Path)
    args = parser.parse_args()
    conn = sqlite3.connect(args.journal.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        journal = object.__new__(TrendObservationJournal)
        journal.conn = conn
        journal.epoch = json.loads(
            conn.execute("SELECT payload FROM epoch WHERE id=1").fetchone()[0]
        )
        receipt = journal.verify()
        receipt["epoch_id"] = journal.epoch["epoch_id"]
        receipt["candidate_id"] = journal.epoch["candidate_id"]
        receipt["statuses"] = dict(
            conn.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind").fetchall()
        )
        print(json.dumps(receipt, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
