"""Primary-feed follow-up with 31 minutes warm-up; same fixed evaluation minute."""

import probe_share_class_quote_access as sample

sample.OUT = sample.OUT.parent / "share-class-quotes-nyse"
sample.DATASETS = ["XNYS.PILLAR"]
sample.PARAMETERS = {
    "schema": "mbp-1",
    "symbols": ["BRK A", "BRK B"],
    "stype_in": "raw_symbol",
    "stype_out": "instrument_id",
    "start": "2025-08-12T13:30:00Z",
    "end": "2025-08-12T14:02:00Z",
}

if __name__ == "__main__":
    sample.main()
