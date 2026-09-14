"""Offline, current-vintage reference adjudication; never changes action inputs."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-dividend-adjudication-20260912"
OLD = ROOT / "evidence/alphatrend-full-dividend-reference-20260912"


class DistributionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "componentprops" and value:
                props = json.loads(value)
                if "distributionTableData" in props:
                    self.tables.append(props["distributionTableData"])


def extract(path: Path, symbol: str) -> list[dict]:
    receipt = json.loads(path.with_name(path.stem + "_receipt.json").read_text())
    raw = path.read_bytes()
    assert receipt["status"] == 200
    assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
    parser = DistributionParser()
    parser.feed(raw.decode())
    assert len(parser.tables) == 1, (symbol, len(parser.tables))
    columns = {c["name"]: c["value"] for c in parser.tables[0]}
    assert len(columns) == len(parser.tables[0])
    assert len({len(v) for v in columns.values()}) == 1
    rows = []
    for i in range(len(columns["exDate"])):
        row = {k: v[i] for k, v in columns.items()}
        for k in ("exDate", "recordDate", "payableDate"):
            row[k] = pd.to_datetime(str(row[k]), format="%Y%m%d").strftime("%Y-%m-%d")
        total = Decimal(str(row["totalDistribution"]))
        component_values = [
            row[k]
            for k in (
                "incomeAmount",
                "shortTermCapitalGain",
                "longTermCapitalGain",
                "returnOnCapital",
            )
        ]
        row["total_minus_components"] = (
            str(total - sum(Decimal(str(v)) for v in component_values))
            if all(v is not None for v in component_values)
            else None
        )
        assert total >= 0 and row["payableDate"] >= row["exDate"]
        row.update(
            symbol=symbol,
            source_file=path.name,
            source_sha256=receipt["sha256"],
            observed_at=receipt["received_at"],
        )
        rows.append(row)
    assert len({r["exDate"] for r in rows}) == len(rows)
    return rows


def main():
    issuer = pd.DataFrame(
        [
            row
            for symbol in ("EEM", "IEF", "SHY", "TLT", "EFA", "IWM")
            for row in extract(
                OUT
                / (f"{symbol}_issuer.html" if symbol == "EEM" else f"{symbol}_issuer_full.html"),
                symbol,
            )
        ]
    )
    issuer.to_parquet(OUT / "issuer_distributions.parquet", index=False)
    original = pd.read_parquet(OLD / "coverage_comparison.parquet")
    actions = pd.read_parquet(
        ROOT / "evidence/alphatrend-action-validation-20260912/normalized_actions.parquet"
    )
    actions = actions[actions.kind == "dividend"].set_index(["symbol", "session_ms"])
    alias_bytes = (OUT / "QQQQ.bin").read_bytes()
    alias_receipt = json.loads((OUT / "QQQQ_receipt.json").read_text())
    assert hashlib.sha256(alias_bytes).hexdigest() == alias_receipt["sha256"]
    alias_response = json.loads(alias_bytes)
    assert alias_receipt["status"] == 200 and not alias_response.get("next_url")
    aliases = alias_response["results"]
    lifecycle = pd.read_parquet(
        ROOT / "evidence/alphatrend-sharadar-direct-20260912/vendor_actions.parquet"
    )
    change = lifecycle[
        (lifecycle.ticker == "QQQ")
        & (lifecycle.action == "tickerchangefrom")
        & (lifecycle.contraticker == "QQQQ")
    ]
    assert len(change) == 1 and str(change.iloc[0].date)[:10] == "2011-03-24"
    assert len({r["ex_dividend_date"] for r in aliases}) == len(aliases)
    assert all(r["ticker"] == "QQQQ" and r["ex_dividend_date"] < "2011-03-24" for r in aliases)
    lookup = issuer.set_index(["symbol", "exDate"])
    alias_lookup = {r["ex_dividend_date"]: r for r in aliases}
    results = []
    for old in original.to_dict("records"):
        symbol, ms = old["symbol"], old["session_ms"]
        ex = pd.to_datetime(ms, unit="ms", utc=True).strftime("%Y-%m-%d")
        result = dict(
            old,
            ex_date=ex,
            adjudicated_pay_date=old["pay_date"],
            new_source="",
            reference_total=None,
            raw_basis_assumed=False,
            cash_review="not_independently_reviewed",
        )
        if (symbol, ex) in lookup.index:
            r = lookup.loc[(symbol, ex)]
            # Issuer historical cash is on a later share basis. Retain the basis
            # inference explicitly; this comparison is not an approved replacement.
            factor = Decimal(str(actions.loc[(symbol, ms), "later_split_product"]))
            cash = Decimal(str(r.totalDistribution)) * factor
            result.update(
                new_source=r.source_file,
                reference_total=float(cash),
                adjudicated_pay_date=r.payableDate,
                raw_basis_assumed=factor != 1,
            )
        elif symbol == "QQQ" and ex < "2011-03-24" and ex in alias_lookup:
            r = alias_lookup[ex]
            assert r["currency"] == "USD" and r["pay_date"] >= ex
            result.update(
                new_source="QQQQ.bin",
                reference_total=r["cash_amount"],
                adjudicated_pay_date=r["pay_date"],
            )
        if result["new_source"]:
            difference = Decimal(str(old["raw_cash"])) - Decimal(str(result["reference_total"]))
            result["reviewed_cash_difference"] = float(difference)
            # Strict five-decimal comparison, not a claim about the vendor's
            # effective precision: older/newer rows can have fewer digits.
            factor = Decimal(str(actions.loc[(symbol, ms), "later_split_product"]))
            tolerance = Decimal("0.000006") * max(Decimal(1), factor)
            result["cash_review"] = (
                "within_source_rounding" if abs(difference) <= tolerance else "disagreement"
            )
            if pd.notna(old["pay_date"]) and old["pay_date"] != result["adjudicated_pay_date"]:
                result["cash_review"] = "payment_date_disagreement"
                result["adjudicated_pay_date"] = None
        results.append(result)
    frame = pd.DataFrame(results)
    frame.to_parquet(OUT / "adjudicated_coverage.parquet", index=False)
    missing = frame[frame.adjudicated_pay_date.isna()]
    missing.to_parquet(OUT / "remaining_payment_gaps.parquet", index=False)
    conflicts = frame[frame.cash_review.isin(["disagreement", "payment_date_disagreement"])]
    conflicts.to_parquet(OUT / "cash_conflicts.parquet", index=False)
    summary = {
        "source_dividends": len(frame),
        "issuer_reference_rows": len(issuer),
        "alias_reference_rows": len(aliases),
        "previous_payment_gaps": int(original.pay_date.isna().sum()),
        "remaining_payment_gaps": len(missing),
        "newly_matched_payment_dates": int(
            (original.pay_date.isna() & frame.adjudicated_pay_date.notna()).sum()
        ),
        "cash_conflicts": len(conflicts),
        "missing_by_symbol": missing.groupby("symbol").size().to_dict(),
        "cash_difference_over_one_cent": int((frame.reviewed_cash_difference.abs() > 0.01).sum()),
        "cash_difference_over_one_tenth_cent": int(
            (frame.reviewed_cash_difference.abs() > 0.001).sum()
        ),
        "newly_matched_by_source": frame[
            original.pay_date.isna() & frame.adjudicated_pay_date.notna()
        ]
        .groupby("new_source")
        .size()
        .to_dict(),
        "payment_schedule_approved": False,
        "historical_first_publication_proven": False,
        "real_strategy_trials_run": 0,
        "hypothesis_union": 238,
    }
    (OUT / "adjudication.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(
        conflicts[conflicts.reviewed_cash_difference.abs() > 0.001][
            ["symbol", "ex_date", "raw_cash", "reference_total", "cash_review"]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
