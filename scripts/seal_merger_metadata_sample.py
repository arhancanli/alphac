"""Seal the predeclared full-index sample; never open filing text or market data."""

import gzip
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/merger-confirmation-metadata-20260913"
PROD = Path("/Users/arhancanli/alphaforge")
FORMS = ("DEFM14A", "SC 14D9")


def main():
    rows, bindings, missing = [], {}, []
    exploratory_path = (
        PROD / "artifacts/feasibility/merger_arbitrage/target_anchor_timeline.parquet"
    )
    excluded = set(pd.read_parquet(exploratory_path, columns=["accession"]).accession)
    for year in range(2006, 2016):
        for quarter in range(1, 5):
            filename = f"{year}-Q{quarter}.idx.gz"
            path = (
                OUT / "indices" / filename
                if year < 2010
                else PROD / "data/raw/sec_active_ownership_13d/indexes" / filename
            )
            if not path.exists():
                missing.append(filename)
                continue
            data = path.read_bytes()
            bindings[str(path)] = hashlib.sha256(data).hexdigest()
            lines = gzip.decompress(data).decode("utf-8", errors="strict").splitlines()
            assert "CIK|Company Name|Form Type|Date Filed|Filename" in lines
            for line in lines:
                fields = line.split("|")
                if len(fields) != 5 or fields[2] not in FORMS:
                    continue
                cik, company, form, filed, archive = fields
                assert cik.isdigit() and archive.startswith("edgar/data/")
                accession = Path(archive).stem
                assert len(accession) == 20 and accession not in excluded
                assert int(filed[:4]) == year
                digest = hashlib.sha256(
                    f"alphac-merger-announcement-confirmation-v2|{year}|{form}|{accession}".encode()
                ).hexdigest()
                rows.append(
                    {
                        "year": year,
                        "cik": int(cik),
                        "company": company,
                        "form": form,
                        "filing_date": filed,
                        "accession": accession,
                        "filing_text_url": f"https://www.sec.gov/Archives/{archive}",
                        "index_path": str(path),
                        "selection_hash": digest,
                    }
                )
    if missing:
        raise ValueError(f"Incomplete index corpus; refuse sample selection: {missing}")
    frame = pd.DataFrame(rows)
    assert not frame.duplicated(["cik", "accession"]).any()
    cells = []
    selected = []
    for year in range(2006, 2016):
        for form in FORMS:
            cell = frame.loc[(frame.year == year) & (frame.form == form)]
            cells.append({"year": year, "form": form, "available": len(cell)})
            if len(cell) < 20:
                raise ValueError(f"Underfilled cell {year}/{form}; no substitution")
            selected.append(cell.sort_values(["selection_hash", "accession"]).head(20))
    sample = pd.concat(selected, ignore_index=True)
    assert len(sample) == 400
    for name, table in [("anchor_pool.parquet", frame), ("selected_anchors.parquet", sample)]:
        path = OUT / name
        if path.exists():
            raise FileExistsError("Do not overwrite sealed selection")
        table.to_parquet(path, index=False)
        bindings[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    bindings[str(exploratory_path)] = hashlib.sha256(exploratory_path.read_bytes()).hexdigest()
    bindings[str(Path(__file__))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result = {
        "stage": "index_metadata_sample_only",
        "index_files": 40,
        "anchor_pool_rows": len(frame),
        "sample_rows": len(sample),
        "cells": cells,
        "source_sha256": bindings,
        "independent_labels": 0,
        "filing_documents_opened": 0,
        "return_hypotheses_spent": 0,
        "qualified": False,
        "limitations": "Index anchors are not verified eligible all-cash deals. "
        "Acceptance timestamps, primary documents, transaction identity and labels pending. "
        "Full indices may incorporate later corrections; no original-vintage claim.",
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ["index_files", "anchor_pool_rows", "sample_rows"]}))


if __name__ == "__main__":
    main()
