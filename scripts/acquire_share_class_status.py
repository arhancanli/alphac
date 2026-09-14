"""Capture full-day status snapshots/updates for the fixed equity sample."""

from pathlib import Path

import probe_share_class_quote_access as sample

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    for dataset, symbols in [("XNAS.ITCH", ["GOOG", "GOOGL"]), ("XNYS.PILLAR", ["BRK A", "BRK B"])]:
        sample.OUT = ROOT / "evidence/share-class-status" / dataset
        sample.OUT.parent.mkdir(exist_ok=True)
        sample.DATASETS = [dataset]
        sample.PARAMETERS = {
            "schema": "status",
            "symbols": symbols,
            "stype_in": "raw_symbol",
            "stype_out": "instrument_id",
            "start": "2025-08-12",
            "end": "2025-08-13",
        }
        sample.main()
