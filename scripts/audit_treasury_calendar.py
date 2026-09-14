"""Compare phase boundaries to source-backed SIFMA recommendations, not venue sessions."""

import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/treasury-calendar-20260912"
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
PATTERN = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),("
    + "|".join(MONTHS)
    + r")(\d{1,2})(?:,(20\d{2}))?",
    re.I,
)


def parse_cell(cell, year):
    compact = re.sub(r"\s+", "", cell)
    found = []
    for weekday, month, day, explicit in PATTERN.findall(compact):
        y = int(explicit) if explicit else year
        value = date(y, [m.lower() for m in MONTHS].index(month.lower()) + 1, int(day))
        if value.strftime("%A").lower() != weekday.lower():
            raise ValueError("weekday_date_mismatch")
        if y != year and not (
            (y == year - 1 and value.month == 12) or (y == year + 1 and value.month == 1)
        ):
            raise ValueError("unexpected_year")
        found.append(value.isoformat())
    if not found and re.search("|".join(MONTHS), compact, re.I):
        raise ValueError("unparsed_date")
    return found


def main():
    prior = ROOT / "evidence/treasury-trade-spec-20260912"
    for path, h in json.loads((prior / "closure.json").read_text())["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == h
    records, errors = [], []

    def add(cell, year, kind, source, page):
        try:
            dates = parse_cell(cell, year)
            for day in dates:
                records.append(
                    {
                        "date": day,
                        "recommendation": kind,
                        "source": source,
                        "page_zero_based": page,
                        "raw_cell": cell,
                    }
                )
        except ValueError as e:
            errors.append(
                {
                    "year": year,
                    "source": source,
                    "page_zero_based": page,
                    "raw_cell": cell,
                    "reason": str(e),
                }
            )

    reader = PdfReader(OUT / "sifma_history.pdf")
    for year in range(2013, 2020):
        i = year - 1995
        lines = reader.pages[i].extract_text(extraction_mode="layout").splitlines()
        header = next(x for x in lines if "RECOMMENDED EARLY" in x)
        early = header.index("RECOMMENDED EARLY") - 2
        full = header.index("RECOMMENDED FULL") - 2
        cells = []
        for line in lines:
            if re.match(r"\s*" + str(year) + r"\s+U.S.", line):
                if cells:
                    add(
                        " ".join(x[early:full] for x in cells),
                        year,
                        "early_close",
                        "sifma_history.pdf",
                        i,
                    )
                    add(
                        " ".join(x[full:] for x in cells),
                        year,
                        "full_close",
                        "sifma_history.pdf",
                        i,
                    )
                cells = [line]
            elif cells and line.strip():
                cells.append(line)
        if cells:
            add(" ".join(x[early:full] for x in cells), year, "early_close", "sifma_history.pdf", i)
            add(" ".join(x[full:] for x in cells), year, "full_close", "sifma_history.pdf", i)
    page_numbers = {2020: 47, 2021: 65, 2022: 53, 2023: 47, 2024: 59, 2025: 64}
    for year, page in page_numbers.items():
        text = PdfReader(OUT / f"sifma_{year}.pdf").pages[page].extract_text()
        (OUT / f"annual_{year}_plain.txt").write_text(text)
        # Annual table rows are in reading order: holiday, early date/None, full date/None.
        for line in text.splitlines():
            if not re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),", line):
                continue
            matches = list(
                re.finditer(
                    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*\w+\s+\d{1,2},\s*20\d{2}",
                    line,
                )
            )
            if not matches:
                errors.append({"year": year, "raw_cell": line, "reason": "annual_row_unparsed"})
                continue
            if len(matches) == 2:
                for match, kind in zip(matches, ["early_close", "full_close"], strict=True):
                    add(match.group(), year, kind, f"sifma_{year}.pdf", page)
            elif len(matches) == 1:
                match = matches[0]
                prefix = line[: match.start()]
                kind = "full_close" if "None" in prefix else "early_close"
                add(match.group(), year, kind, f"sifma_{year}.pdf", page)
            else:
                raise ValueError("unexpected table row")
    phases = json.loads((prior / "phase_plan.json").read_text())
    byday = {}
    for r in records:
        byday.setdefault(r["date"], []).append(r)
    boundaries = []
    for phase in phases:
        for action in ["entry", "exit"]:
            day = phase[action + "_date"]
            conflicts = byday.get(day, [])
            boundaries.append(
                {
                    "event_identity": phase["event_identity"],
                    "phase": phase["phase"],
                    "action": action,
                    "date": day,
                    "decision_local": "16:00 America/New_York",
                    "sifma_conflicts": conflicts,
                    "status": "recommendation_conflict" if conflicts else "venue_unverified",
                    "settlement_verified": False,
                }
            )
    result = {
        "phase_boundaries": len(boundaries),
        "unique_boundary_dates": len({r["date"] for r in boundaries}),
        "conflicting_boundaries": sum(bool(r["sifma_conflicts"]) for r in boundaries),
        "conflicting_dates": sorted({r["date"] for r in boundaries if r["sifma_conflicts"]}),
        "affected_phases": len(
            {(r["event_identity"], r["phase"]) for r in boundaries if r["sifma_conflicts"]}
        ),
        "recommendation_records": len(records),
        "source_parse_exceptions": len(errors),
        "records_by_source": dict(Counter(r["source"] for r in records)),
        "venue_calendar_complete": False,
        "settlement_calendar_complete": False,
        "market_prices_read": False,
        "return_ready": False,
        "hypothesis_union": 240,
    }
    for name, obj in [
        ("recommendations.json", records),
        ("parse_exceptions.json", errors),
        ("boundaries.json", boundaries),
        ("result.json", result),
    ]:
        (OUT / name).write_text(json.dumps(obj, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print("EXCEPTIONS", json.dumps(errors, indent=2))


if __name__ == "__main__":
    main()
