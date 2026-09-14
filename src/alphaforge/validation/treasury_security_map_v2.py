"""Issued-security reference candidates, not a tradable on-the-run designation."""

from datetime import date


def classify(record):
    if record["floating_rate"] != "No" or record["inflation_index_security"] != "No":
        return None
    if record["security_type"] == "Bill" and record["security_term"] == "26-Week":
        return "bill_6m"
    if record["security_type"] == "Note" and record["security_term"] == "2-Year":
        return "note_2y"
    if record["security_type"] == "Note" and record["reopening"] == "No":
        return {"2-Year": "note_2y", "10-Year": "note_10y"}.get(record["original_security_term"])
    return None


def issued_candidate(records, decision_date, bucket):
    decision = date.fromisoformat(decision_date)
    eligible = []
    for record in records:
        if classify(record) != bucket:
            continue
        announcement, auction, issue, maturity = [
            date.fromisoformat(record[k])
            for k in ("announcemt_date", "auction_date", "issue_date", "maturity_date")
        ]
        if not announcement <= auction <= issue < maturity:
            raise ValueError("invalid_security_chronology")
        # Date-only notice is conservatively usable on a later date. No WI inference.
        if announcement < decision and auction < decision and issue <= decision < maturity:
            eligible.append(record)
    if not eligible:
        raise ValueError("no_issued_candidate")
    latest = max((r["issue_date"], r["auction_date"]) for r in eligible)
    selected = [r for r in eligible if (r["issue_date"], r["auction_date"]) == latest]
    if len(selected) != 1:
        raise ValueError("ambiguous_issued_candidate")
    return selected[0]
