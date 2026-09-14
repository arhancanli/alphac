"""Mechanical header lineage only; no deal-eligibility labels or announcement inference."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/merger-header-acquisition-20260913"
SAMPLE = ROOT / "evidence/merger-confirmation-metadata-20260913/selected_anchors.parquet"
ROLES = ("FILER", "SUBJECT-COMPANY", "FILED-BY", "REPORTING-OWNER", "ISSUER")


def parse_header(text):
    def single(tag):
        values = re.findall(rf"(?m)^<{tag}>([^\r\n<]+)", text)
        if len(values) != 1:
            raise ValueError(f"Expected exactly one {tag}")
        return values[0].strip()

    accession = single("ACCESSION-NUMBER")
    accepted = single("ACCEPTANCE-DATETIME")
    if not re.fullmatch(r"\d{14}", accepted):
        raise ValueError("Malformed acceptance clock")
    datetime.strptime(accepted, "%Y%m%d%H%M%S")  # noqa: DTZ007 — validate raw clock only
    roles = {}
    for role in ROLES:
        blocks = re.findall(rf"<{role}>(.*?)</{role}>", text, flags=re.DOTALL)
        roles[role] = sorted(
            {int(cik) for block in blocks for cik in re.findall(r"(?m)^<CIK>(\d+)\s*$", block)}
        )
    return {
        "accession": accession,
        "acceptance_raw": accepted,
        "form": single("TYPE"),
        "roles": roles,
        "acceptance_utc_verified": False,
    }


def main():
    done = json.loads((OUT / "acquisition_result.json").read_text())
    if done != {"success": 395, "failed": 0, "skipped": 0}:
        raise ValueError("Acquisition incomplete; preserve receipts and resolve before full audit")
    scope = json.loads((OUT / "scope.json").read_text())
    assert hashlib.sha256(SAMPLE.read_bytes()).hexdigest() == scope["sample_sha256"]
    receipts = [json.loads(line) for line in (OUT / "receipts.jsonl").read_text().splitlines()]
    assert len(receipts) == 395 and len({r["accession"] for r in receipts}) == 395
    parsed = {}
    for receipt in receipts:
        path = OUT / "headers" / f"{receipt['accession']}.sgml"
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == receipt["sha256"]
        result = parse_header(data.decode("utf-8"))
        assert result["accession"] == receipt["accession"]
        parsed[result["accession"]] = result
    sample = pd.read_parquet(SAMPLE)
    rows = []
    for row in sample.itertuples():
        result = parsed[row.accession]
        assert result["form"] == row.form
        roles = [role for role, ciks in result["roles"].items() if row.cik in ciks]
        rows.append(
            {
                "accession": row.accession,
                "index_cik": int(row.cik),
                "form": row.form,
                "acceptance_raw": result["acceptance_raw"],
                "header_roles_for_index_cik": roles,
                "all_header_roles": result["roles"],
                "multiple_index_ciks": int((sample.accession == row.accession).sum()) > 1,
                "transaction_target_verified": False,
            }
        )
    counts = {}
    for row in rows:
        key = "+".join(row["header_roles_for_index_cik"]) or "UNMATCHED"
        counts[key] = counts.get(key, 0) + 1
    result = {
        "header_count": len(parsed),
        "index_rows": len(rows),
        "role_counts": counts,
        "accepted_raw_clocks": len(parsed),
        "verified_utc_clocks": 0,
        "primary_document_lineage_complete": False,
        "human_labels": 0,
        "return_hypotheses_spent": 0,
        "qualified": False,
        "all_receipt_hashes_verified": True,
    }
    (OUT / "header_mapping.json").write_text(json.dumps(rows, indent=2) + "\n")
    (OUT / "shared_accession_roles.json").write_text(
        json.dumps([r for r in rows if r["multiple_index_ciks"]], indent=2) + "\n"
    )
    (OUT / "audit_result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
