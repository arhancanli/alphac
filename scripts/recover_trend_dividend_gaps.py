"""Offline SSGA recovery and three independently corroborated cash revisions."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import openpyxl
import pandas as pd

from alphaforge.validation.trend_cash_corrections import apply_cash_corrections

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-dividend-recovery-20260912"
PRIOR = ROOT / "evidence/alphatrend-dividend-adjudication-20260912"


def verified(path, receipt):
    r = json.loads(receipt.read_text())
    assert r["status"] == 200
    assert hashlib.sha256(path.read_bytes()).hexdigest() == r["sha256"]
    return r


def main():
    # Verify the sealed prior inputs before making a new derivative.
    for name, digest in json.loads((PRIOR / "closure.json").read_text())["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    book = OUT / "ssga_historical.xlsx"
    receipt = verified(book, OUT / "ssga_historical.xlsx.receipt.json")
    workbook = openpyxl.load_workbook(book, read_only=True, data_only=True)
    sheet = workbook["dividend"]
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][:7] == (
        "FUND NAME",
        "TICKER",
        "CUSIP",
        "EX-DATE",
        "RECORD DATE",
        "PAYABLE DATE",
        "DIVIDEND ($)",
    )
    records = []
    for row_number, row in enumerate(rows[1:], 2):
        if row[1] != "SPY":
            continue
        assert row[2] == "78462F103"
        ex, record, pay = [
            pd.to_datetime(x, format="%m/%d/%Y").strftime("%Y-%m-%d") for x in row[3:6]
        ]
        cash = sum(
            Decimal(str(x).strip()) if x is not None and str(x).strip() else Decimal(0)
            for x in row[6:9]
        )
        assert cash >= 0
        records.append(
            {
                "symbol": "SPY",
                "ex_date": ex,
                "record_date": record,
                "pay_date": pay,
                "raw_cash": float(cash),
                "sheet_row": row_number,
                "valid_date_order": ex <= record <= pay,
                "source_sha256": receipt["sha256"],
                "observed_at": receipt["received_at"],
            }
        )
    spy = pd.DataFrame(records)
    assert not spy.ex_date.duplicated().any()
    spy.to_parquet(OUT / "spy_issuer_distributions.parquet", index=False)
    coverage = pd.read_parquet(PRIOR / "adjudicated_coverage.parquet")
    recoveries = []
    for index, row in coverage[coverage.adjudicated_pay_date.isna()].iterrows():
        matches = spy[(spy.symbol == row.symbol) & (spy.ex_date == row.ex_date)]
        if len(matches) != 1:
            continue
        issuer = matches.iloc[0]
        recoveries.append(
            {
                "symbol": row.symbol,
                "ex_date": row.ex_date,
                "issuer_pay_date": issuer.pay_date,
                "sheet_row": int(issuer.sheet_row),
                "accepted_date": bool(issuer.valid_date_order),
                "source_raw_cash": row.raw_cash,
                "issuer_raw_cash": issuer.raw_cash,
            }
        )
        if issuer.valid_date_order:
            coverage.loc[index, "adjudicated_pay_date"] = issuer.pay_date
            coverage.loc[index, "new_source"] = "ssga_historical.xlsx"
            coverage.loc[index, "reference_total"] = issuer.raw_cash
            coverage.loc[index, "reviewed_cash_difference"] = row.raw_cash - issuer.raw_cash
            coverage.loc[index, "cash_review"] = "precision_review_pending"
    pd.DataFrame(recoveries).to_parquet(OUT / "spy_gap_review.parquet", index=False)
    coverage.to_parquet(OUT / "coverage_v2.parquet", index=False)
    gaps = coverage[coverage.adjudicated_pay_date.isna()]
    gaps.to_parquet(OUT / "remaining_gaps.parquet", index=False)

    actions = pd.read_parquet(
        ROOT / "evidence/alphatrend-action-validation-20260912/normalized_actions.parquet"
    )
    issuer = pd.read_parquet(PRIOR / "issuer_distributions.parquet")
    polygon_dir = ROOT / "evidence/alphatrend-full-dividend-reference-20260912"
    polygon_seal = json.loads((polygon_dir / "closure.json").read_text())["sha256"]
    revisions = []
    for symbol, ex in [("EEM", "2010-12-29"), ("TLT", "2010-07-01"), ("TLT", "2010-11-01")]:
        ir = issuer[(issuer.symbol == symbol) & (issuer.exDate == ex)]
        assert len(ir) == 1
        ir = ir.iloc[0]
        raw_file = polygon_dir / f"{symbol}_dividends.bin"
        raw = raw_file.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == polygon_seal[str(raw_file.relative_to(ROOT))]
        pr = json.loads(raw)
        matches = [
            r for r in pr["results"] if r["ticker"] == symbol and r["ex_dividend_date"] == ex
        ]
        assert len(matches) == 1 and matches[0]["currency"] == "USD"
        match = matches[0]
        assert Decimal(str(match["cash_amount"])) == Decimal(ir.totalDistribution)
        assert match["pay_date"] == ir.payableDate
        stamp = int(pd.Timestamp(ex, tz="UTC").timestamp() * 1000)
        old = actions[(actions.symbol == symbol) & (actions.session_ms == stamp)]
        assert len(old) == 1 and old.iloc[0].later_split_product == 1
        old = old.iloc[0]
        revisions.append(
            {
                "symbol": symbol,
                "session_ms": stamp,
                "original_event_id": old.event_id,
                "previous_raw_cash": old.raw_value,
                "reviewed_raw_cash": ir.totalDistribution,
                "observed_ms": int(pd.Timestamp(ir.observed_at).timestamp() * 1000),
                "evidence_sha256": [ir.source_sha256, hashlib.sha256(raw).hexdigest()],
                "issuer_file": ir.source_file,
                "polygon_file": str(raw_file.relative_to(ROOT)),
                "pay_date": ir.payableDate,
                "historical_publication_proven": False,
            }
        )
    revised = apply_cash_corrections(actions, revisions)
    assert len(revised) == len(actions)
    untouched = ~actions.event_id.isin([c["original_event_id"] for c in revisions])
    pd.testing.assert_frame_equal(actions.loc[untouched], revised.loc[untouched, actions.columns])
    revised.to_parquet(OUT / "revised_actions.parquet", index=False)
    (OUT / "cash_corrections.json").write_text(json.dumps(revisions, indent=2) + "\n")
    summary = {
        "previous_gaps": 39,
        "recovered_dates": 39 - len(gaps),
        "remaining_gaps": len(gaps),
        "missing_by_symbol": gaps.groupby("symbol").size().to_dict(),
        "reviewed_cash_revisions": len(revisions),
        "untouched_action_rows": int(untouched.sum()),
        "historical_panel_rebuilt": False,
        "payment_schedule_approved": False,
        "strategy_trials": 0,
        "hypothesis_union": 238,
    }
    (OUT / "recovery.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
