"""Audited fiscal totals plus exact issuer event agreement support two exclusions.

This is a current-vintage research adjudication, not a historical knowledge claim.
Original source events are retained in an explicit exclusion archive.
"""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-qqq-event-review-20260912"
PAYMENTS = ROOT / "evidence/alphatrend-payment-source-review-20260912"
CASH = ROOT / "evidence/alphatrend-dividend-recovery-20260912"


def main():
    for directory in (PAYMENTS, CASH):
        for name, digest in json.loads((directory / "closure.json").read_text())["files"].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    actions = pd.read_parquet(CASH / "revised_actions.parquet")
    dates = pd.to_datetime(actions.session_ms, unit="ms").dt.strftime("%Y-%m-%d")
    issuer = json.loads((PAYMENTS / "QQQ_distribution.json").read_text())["distributions"]
    notes = json.loads((OUT / "annual_report_review.json").read_text())
    reviews = []
    excluded_ids = []
    for note in notes:
        lo, hi = note["period_start"], note["period_end"]
        selected = actions[
            (actions.symbol == "QQQ") & (actions.kind == "dividend") & (dates >= lo) & (dates <= hi)
        ]
        actual = {dates.loc[i]: Decimal(str(row.raw_value)) for i, row in selected.iterrows()}
        assert len(actual) == len(selected)
        expected_rows = [r for r in issuer if lo <= r["exDate"] <= hi]
        expected = {
            r["exDate"]: Decimal(str(r["distributionAmountPerUnit"])) for r in expected_rows
        }
        assert len(expected) == len(expected_rows) == 4
        suspect = note["suspect_ex_date"]
        assert set(actual) - set(expected) == {suspect}
        assert not set(expected) - set(actual)
        assert actual[suspect] == Decimal(note["suspect_cash"])
        assert all(actual[d] == expected[d] for d in expected)
        original_total = sum(actual.values())
        revised_total = sum(expected.values())
        reported = Decimal(note["reported_distribution_per_share"])
        unit = Decimal(note["rounding_unit"])
        assert revised_total.quantize(unit, rounding=ROUND_HALF_UP) == reported
        assert original_total.quantize(unit, rounding=ROUND_HALF_UP) != reported
        row = selected[dates.loc[selected.index] == suspect]
        assert len(row) == 1
        event_id = row.iloc[0].event_id
        excluded_ids.append(event_id)
        reviews.append(
            {
                **note,
                "original_total": str(original_total),
                "retained_total": str(revised_total),
                "excluded_event_id": event_id,
                "decision": "exclude_unsupported_extra_event_from_research_snapshot",
                "inference": True,
                "historical_publication_proven": False,
            }
        )
    assert len(set(excluded_ids)) == 2
    excluded = actions[actions.event_id.isin(excluded_ids)].copy()
    revised = actions[~actions.event_id.isin(excluded_ids)].copy()
    assert len(revised) + len(excluded) == len(actions)
    pd.testing.assert_frame_equal(revised, actions.drop(index=excluded.index))
    excluded.to_parquet(OUT / "excluded_source_events.parquet", index=False)
    revised.to_parquet(OUT / "revised_actions_v2.parquet", index=False)
    (OUT / "exclusion_reviews.json").write_text(json.dumps(reviews, indent=2) + "\n")
    coverage = pd.read_parquet(PAYMENTS / "coverage_v3.parquet")
    excluded_keys = set(zip(excluded.symbol, excluded.session_ms, strict=True))
    mask = coverage.apply(lambda r: (r.symbol, r.session_ms) in excluded_keys, axis=1)
    assert mask.sum() == 2 and coverage.loc[mask, "adjudicated_pay_date"].isna().all()
    coverage = coverage[~mask].copy()
    coverage.to_parquet(OUT / "coverage_v4.parquet", index=False)
    gaps = coverage[coverage.adjudicated_pay_date.isna()]
    gaps.to_parquet(OUT / "remaining_gaps.parquet", index=False)
    summary = {
        "original_action_rows": len(actions),
        "retained_action_rows": len(revised),
        "excluded_events": len(excluded),
        "retained_dividends": len(coverage),
        "accepted_payment_dates": int(coverage.adjudicated_pay_date.notna().sum()),
        "unresolved_events": len(gaps),
        "hypothesis_union": 238,
        "strategy_trials": 0,
        "price_panel_rebuilt": False,
        "historical_payment_schedule_approved": False,
    }
    (OUT / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
