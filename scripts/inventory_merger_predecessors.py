"""Date/CIK metadata workload screen; no announcement or transaction resolution."""

import gzip
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/merger-predecessor-inventory-20260913"
META = ROOT / "evidence/merger-confirmation-metadata-20260913"
PROD = Path("/Users/arhancanli/alphaforge")
FORMS = {"8-K", "PREM14A", "DEFA14A", "SC TO-T"}


def main():
    sample_path = META / "selected_anchors.parquet"
    sample = pd.read_parquet(sample_path)
    seal = json.loads((META / "result.json").read_text())
    assert (
        hashlib.sha256(sample_path.read_bytes()).hexdigest()
        == seal["source_sha256"][str(sample_path)]
    )
    ciks = set(sample.cik)
    records, bindings = [], {}
    for year in range(2005, 2016):
        for quarter in range(1, 5):
            if year == 2005:
                folder = OUT / "indices"
            elif year < 2010:
                folder = META / "indices"
            else:
                folder = PROD / "data/raw/sec_active_ownership_13d/indexes"
            path = folder / f"{year}-Q{quarter}.idx.gz"
            raw = path.read_bytes()
            bindings[str(path)] = hashlib.sha256(raw).hexdigest()
            for line in gzip.decompress(raw).decode("utf-8").splitlines():
                parts = line.split("|")
                if len(parts) != 5 or parts[2] not in FORMS:
                    continue
                cik, _company, form, filed, filename = parts
                assert cik.isdigit()
                if int(cik) not in ciks and form != "SC TO-T":
                    continue
                records.append(
                    {
                        "cik": int(cik),
                        "form": form,
                        "filing_date": filed,
                        "accession": Path(filename).stem,
                        "url": f"https://www.sec.gov/Archives/{filename}",
                        "index_path": str(path),
                    }
                )
    pool = pd.DataFrame(records)
    pool["date"] = pd.to_datetime(pool.filing_date)
    assert not pool.duplicated(["cik", "accession"]).any()
    relation_rows, summary = [], []
    for anchor in sample.itertuples():
        end = pd.Timestamp(anchor.filing_date)
        candidates = pool.loc[
            (pool.cik == anchor.cik) & pool.date.between(end - pd.Timedelta(days=365), end)
        ]
        summary.append(
            {
                "anchor_cik": int(anchor.cik),
                "anchor_accession": anchor.accession,
                "stratum": anchor.form,
                "year": int(anchor.year),
                "candidate_rows": len(candidates),
                **{f"count_{f}": int((candidates.form == f).sum()) for f in sorted(FORMS)},
            }
        )
        for row in candidates.itertuples():
            relation_rows.append(
                {
                    "anchor_cik": int(anchor.cik),
                    "anchor_accession": anchor.accession,
                    "candidate_accession": row.accession,
                    "candidate_form": row.form,
                    "candidate_filing_date": row.filing_date,
                    "candidate_url": row.url,
                    "candidate_index_path": row.index_path,
                }
            )
    relation = pd.DataFrame(relation_rows)
    summary = pd.DataFrame(summary)
    outputs = {
        "candidate_relations.parquet": relation,
        "anchor_counts.parquet": summary,
        "all_tender_index_rows.parquet": pool.loc[pool.form == "SC TO-T"].drop(columns="date"),
    }
    for name, frame in outputs.items():
        path = OUT / name
        if path.exists():
            raise FileExistsError("Preserve measured inventory")
        frame.to_parquet(path, index=False)
        bindings[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {
        "scope": "CIK/filing-date workload screen only",
        "index_files": len(bindings) - 3,
        "anchor_rows": len(sample),
        "distinct_index_ciks": len(ciks),
        "candidate_relations": len(relation),
        "distinct_candidate_accessions": int(relation.candidate_accession.nunique()),
        "all_tender_index_rows": int((pool.form == "SC TO-T").sum()),
        "strata": {
            form: {
                "anchors": len(g),
                "zero_candidates": int((g.candidate_rows == 0).sum()),
                "candidate_count_min": int(g.candidate_rows.min()),
                "candidate_count_median": float(g.candidate_rows.median()),
                "candidate_count_max": int(g.candidate_rows.max()),
            }
            for form, g in summary.groupby("stratum")
        },
        "source_sha256": bindings,
        "return_hypotheses_spent": 0,
        "announcement_coverage_established": False,
        "limitations": "Indexed CIK may not be target. Filing dates are not exact acceptance "
        "clocks.8-K items unknown. Global tender rows need subject-company header links. "
        "No transaction identity, eligibility, independence or human review established.",
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "source_sha256"}, indent=2))


if __name__ == "__main__":
    main()
