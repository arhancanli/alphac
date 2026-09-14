"""Replay issuer payment recovery without changing frozen source snapshots."""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from alphaforge.validation.trend_issuer_payments import parse_invesco_distributions

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-payment-source-review-20260912"
PRIOR = ROOT / "evidence/alphatrend-dividend-recovery-20260912"


def check(path, receipt_path):
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == 200
    assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["sha256"]
    return receipt


def main():
    for name, digest in json.loads((PRIOR / "closure.json").read_text())["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    records = []
    files = [
        ("FXE", "fxe.html", "fxe_receipt.json", "fxe_distribution"),
        ("DBA", "DBA.html", "DBA_page_receipt.json", "DBA_distribution"),
        ("DBC", "DBC.html", "DBC_page_receipt.json", "DBC_distribution"),
        ("UUP", "UUP.html", "UUP_page_receipt.json", "UUP_distribution"),
        ("QQQ", "QQQ_series1.html", "QQQ_series1.html.receipt.json", "QQQ_distribution"),
    ]
    for symbol, page, page_receipt, stem in files:
        check(OUT / page, OUT / page_receipt)
        html = (OUT / page).read_text()
        assert re.search(r'<meta name="ticker" content="([^"]+)', html).group(1) == symbol
        cusip = re.search(r'<meta name="cusip" content="([^"]+)', html).group(1)
        filename = stem + ".json"
        receipt_name = filename + ".receipt.json" if symbol == "QQQ" else stem + "_receipt.json"
        receipt = check(OUT / filename, OUT / receipt_name)
        rows = parse_invesco_distributions(json.loads((OUT / filename).read_text()), cusip=cusip)
        for row in rows:
            records.append(
                {
                    **row,
                    "symbol": symbol,
                    "source_file": filename,
                    "source_sha256": receipt["sha256"],
                    "observed_at": receipt["received_at"],
                }
            )
    reference = pd.DataFrame(records)
    reference.to_parquet(OUT / "issuer_reference.parquet", index=False)
    coverage = pd.read_parquet(PRIOR / "coverage_v2.parquet")
    original_gaps = coverage.adjudicated_pay_date.isna()
    overlap = coverage.merge(
        reference, left_on=["symbol", "ex_date"], right_on=["symbol", "exDate"]
    )
    conflicts = overlap[
        overlap.adjudicated_pay_date.notna() & (overlap.adjudicated_pay_date != overlap.payDate)
    ][["symbol", "ex_date", "adjudicated_pay_date", "payDate", "source_file", "source_sha256"]]
    conflicts.to_parquet(OUT / "existing_payment_conflicts.parquet", index=False)
    filings = json.loads((OUT / "filing_date_adjudications.json").read_text())
    filing_lookup = {(r["symbol"], r["ex_date"]): r for r in filings}
    review = []
    for index, old in coverage[original_gaps].iterrows():
        matches = reference[(reference.symbol == old.symbol) & (reference.exDate == old.ex_date)]
        if len(matches) != 1:
            continue
        r = matches.iloc[0]
        pay = r.payDate
        source = r.source_file
        decision = "issuer_feed"
        if (old.symbol, old.ex_date) in filing_lookup:
            filing = filing_lookup[(old.symbol, old.ex_date)]
            assert filing["feed_pay_date"] == pay and filing["record_date"] == r.recordDate
            assert float(filing["cash"]) == float(r.raw_cash) == old.raw_cash
            pay = filing["reviewed_pay_date"]
            source = "filing_date_adjudications.json"
            decision = "issuer_filing_over_current_feed"
        assert old.ex_date <= r.recordDate <= pay
        review.append(
            {
                "symbol": old.symbol,
                "ex_date": old.ex_date,
                "feed_pay_date": r.payDate,
                "reviewed_pay_date": pay,
                "source": source,
                "decision": decision,
                "source_raw_cash": old.raw_cash,
                "issuer_raw_cash": float(r.raw_cash),
            }
        )
        coverage.loc[index, "adjudicated_pay_date"] = pay
        coverage.loc[index, "new_source"] = source
        coverage.loc[index, "reference_total"] = float(r.raw_cash)
        coverage.loc[index, "reviewed_cash_difference"] = old.raw_cash - float(r.raw_cash)
        coverage.loc[index, "cash_review"] = "issuer_reference_only"
    pd.DataFrame(review).to_parquet(OUT / "recovered_payment_review.parquet", index=False)
    missing = coverage[coverage.adjudicated_pay_date.isna()]
    missing.to_parquet(OUT / "unmatched_events.parquet", index=False)
    for conflict in conflicts.itertuples():
        mask = (coverage.symbol == conflict.symbol) & (coverage.ex_date == conflict.ex_date)
        coverage.loc[mask, "adjudicated_pay_date"] = None
        coverage.loc[mask, "cash_review"] = "payment_date_disagreement"
    coverage.to_parquet(OUT / "coverage_v3.parquet", index=False)
    gaps = coverage[coverage.adjudicated_pay_date.isna()]
    gaps.to_parquet(OUT / "remaining_gaps.parquet", index=False)
    summary = {
        "issuer_rows": len(reference),
        "previous_gaps": int(original_gaps.sum()),
        "recovered_dates": len(review),
        "remaining_gaps": len(gaps),
        "unmatched_events": len(missing),
        "newly_disputed_existing_payments": len(conflicts),
        "missing_by_symbol": gaps.groupby("symbol").size().to_dict(),
        "filing_overrides": sum(r["decision"] != "issuer_feed" for r in review),
        "payment_schedule_approved": False,
        "historical_first_publication_proven": False,
        "real_strategy_trials": 0,
        "hypothesis_union": 238,
    }
    (OUT / "recovery.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
