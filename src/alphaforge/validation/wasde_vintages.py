"""Strict extraction of selected US grain tables; no publication-time inference."""

import re

TITLES = {
    "wheat": "U.S. Wheat Supply and Use",
    "corn": "U.S. Feed Grain and Corn Supply and Use",
    "soybeans": "U.S. Soybeans and Products Supply and Use",
}
FIELDS = {
    "beginning_stocks": "Beginning Stocks",
    "production": "Production",
    "imports": "Imports",
    "supply": "Supply, Total",
    "exports": "Exports",
    "use": "Use, Total",
    "ending_stocks": "Ending Stocks",
}


def extract_tables(text: str) -> list[dict]:
    """Preserve rightmost published column per crop year, never the prior-month column."""
    reports = set(re.findall(r"WASDE\s*-\s*(\d+)\s*-", text))
    if len(reports) != 1:
        raise ValueError("missing or ambiguous report number")
    output = []
    for crop, title in TITLES.items():
        if text.count(title) != 1:
            raise ValueError(f"missing or ambiguous {crop} table")
        section = text.split(title, 1)[1]
        section = re.split(r"WASDE\s*-", section, maxsplit=1)[0]
        headers = [
            line for line in section.splitlines() if len(re.findall(r"\d{4}/\d{2}", line)) >= 2
        ]
        if not headers:
            raise ValueError(f"missing {crop} crop-year header")
        years = re.findall(r"\d{4}/\d{2}", headers[0])
        if crop != "wheat":
            marker = re.search(rf"(?m)^\s*{crop.upper()}\s*$", section)
            if marker is None:
                raise ValueError(f"missing {crop} subsection")
            section = section[marker.end() :]
        # Only the first balance sheet, before wheat classes or soybean products.
        units = section.find("Million Bushels")
        beginning = re.search(r"(?m)^Beginning Stocks\s", section)
        if units < 0 or beginning is None or units > beginning.start():
            raise ValueError(f"unexpected {crop} units")
        section = section[units + len("Million Bushels") :]
        end = re.search(r"(?m)^Ending Stocks\s+[^\n]+", section)
        if end is None:
            raise ValueError(f"missing {crop} ending stocks")
        section = section[: end.end()]
        columns = {}
        for field, label in FIELDS.items():
            matches = re.findall(
                rf"(?m)^\s*{re.escape(label)}(?:\s+\d+/)?\s{{2,}}([^\n]+)$", section
            )
            if len(matches) != 1:
                raise ValueError(f"missing or ambiguous {crop}/{field}")
            tokens = matches[0].split()
            if len(tokens) != len(years) or any(
                token != "NA" and re.fullmatch(r"\d+(?:\.\d+)?", token) is None for token in tokens
            ):
                raise ValueError(f"unexpected {crop}/{field} numeric columns")
            columns[field] = [None if token == "NA" else float(token) for token in tokens]
        for year in dict.fromkeys(years):
            index = max(i for i, candidate in enumerate(years) if candidate == year)
            values = {field: series[index] for field, series in columns.items()}
            if any(value is None for value in values.values()):
                raise ValueError(f"missing selected {crop}/{year} value")
            if abs(values["supply"] - values["use"] - values["ending_stocks"]) > 2:
                raise ValueError(f"{crop}/{year} supply-use balance mismatch")
            if (
                abs(
                    values["beginning_stocks"]
                    + values["production"]
                    + values["imports"]
                    - values["supply"]
                )
                > 2
            ):
                raise ValueError(f"{crop}/{year} supply-components mismatch")
            if values["use"] <= 0:
                raise ValueError("nonpositive total use")
            output.append(
                {
                    "report_id": next(iter(reports)),
                    "crop": crop,
                    "crop_year": year,
                    "units": "million_bushels",
                    "geography": "US",
                    "values": values,
                    "stocks_to_use": values["ending_stocks"] / values["use"],
                    "source_column_index": index,
                }
            )
    return output
