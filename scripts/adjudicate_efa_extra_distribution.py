"""Current-vintage EFA exclusion using audited split-adjusted fiscal totals."""

import hashlib
import json
import math
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-efa-event-review-20260912"
PRIOR = ROOT / "evidence/alphatrend-qqq-event-review-20260912"
ISSUER = ROOT / "evidence/alphatrend-dividend-adjudication-20260912"


def main():
    for directory in (PRIOR, ISSUER):
        for name, digest in json.loads((directory / "closure.json").read_text())["files"].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    note = json.loads((OUT / "filing_review.json").read_text())
    actions = pd.read_parquet(PRIOR / "revised_actions_v2.parquet")
    dates = pd.to_datetime(actions.session_ms, unit="ms").dt.strftime("%Y-%m-%d")
    period = actions[
        (actions.symbol == "EFA")
        & (actions.kind == "dividend")
        & (dates >= note["period_start"])
        & (dates <= note["period_end"])
    ]
    source = {}
    for i, row in period.iterrows():
        cash = Decimal(str(row.source_value)) * Decimal(str(row.later_split_product))
        assert math.isclose(
            float(cash), row.raw_value, rel_tol=0, abs_tol=2 * math.ulp(row.raw_value)
        )
        source[dates.loc[i]] = cash
    assert len(source) == len(period) == 2
    ratio = Decimal(note["split_ratio"])
    splits = actions[
        (actions.symbol == "EFA") & (actions.kind == "split") & (dates > note["period_end"])
    ]
    assert len(splits) == 1 and dates.loc[splits.index[0]] == note["split_effective_date"]
    assert Decimal(str(splits.iloc[0].raw_value)) == ratio
    assert all(Decimal(str(x)) == ratio for x in period.later_split_product)
    reference = pd.read_parquet(ISSUER / "issuer_distributions.parquet")
    reference = reference[
        (reference.symbol == "EFA")
        & (reference.exDate >= note["period_start"])
        & (reference.exDate <= note["period_end"])
    ]
    assert len(reference) == 1
    suspect = note["suspect_ex_date"]
    assert set(source) - set(reference.exDate) == {suspect}
    assert source[suspect] == Decimal(note["suspect_raw_cash"])
    unit = Decimal(note["rounding_unit"])
    reported = Decimal(note["reported_distribution"])
    original = sum(source.values()) / ratio
    retained = (sum(source.values()) - source[suspect]) / ratio
    issuer_total = Decimal(reference.iloc[0].totalDistribution)
    assert issuer_total.quantize(unit, rounding=ROUND_HALF_UP) == reported
    assert retained.quantize(unit, rounding=ROUND_HALF_UP) == reported
    assert original.quantize(unit, rounding=ROUND_HALF_UP) != reported
    removed = period[dates.loc[period.index] == suspect]
    assert len(removed) == 1
    revised = actions.drop(index=removed.index)
    pd.testing.assert_frame_equal(revised, actions[~actions.event_id.isin(removed.event_id)])
    removed.to_parquet(OUT / "excluded_source_event.parquet", index=False)
    revised.to_parquet(OUT / "revised_actions_v3.parquet", index=False)
    coverage = pd.read_parquet(PRIOR / "coverage_v4.parquet")
    mask = (coverage.symbol == "EFA") & (coverage.ex_date == suspect)
    assert mask.sum() == 1 and coverage.loc[mask, "adjudicated_pay_date"].isna().all()
    coverage = coverage[~mask].copy()
    coverage.to_parquet(OUT / "coverage_v5.parquet", index=False)
    gaps = coverage[coverage.adjudicated_pay_date.isna()]
    gaps.to_parquet(OUT / "remaining_gaps.parquet", index=False)
    result = {
        **note,
        "excluded_event_id": removed.iloc[0].event_id,
        "source_adjusted_total": str(original),
        "retained_adjusted_total": str(retained),
        "issuer_adjusted_total": str(issuer_total),
        "retained_cash_precision_difference": str(retained - issuer_total),
        "decision": "exclude_unsupported_extra_event_from_research_snapshot",
        "inference": True,
        "retained_action_rows": len(revised),
        "retained_dividends": len(coverage),
        "unresolved_events": len(gaps),
        "strategy_trials": 0,
        "hypothesis_union": 238,
        "price_panel_rebuilt": False,
        "payment_schedule_approved": False,
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
