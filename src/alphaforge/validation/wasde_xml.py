"""Adapt bounded USDA XML grain matrices to the validated text-table extractor."""

import re
import xml.etree.ElementTree as ET

from alphaforge.validation.wasde_vintages import FIELDS, TITLES, extract_tables

MATRICES = {
    "wheat": ("sr11", "matrix1", "1"),
    "corn": ("sr12", "matrix2", "2"),
    "soybeans": ("sr15", "matrix1", "4"),
}


def extract_xml(raw: bytes, report_month: str) -> list[dict]:
    if (
        len(raw) > 5_000_000
        or b"\x00" in raw
        or b"<!DOCTYPE" in raw.upper()
        or b"<!ENTITY" in raw.upper()
    ):
        raise ValueError("unsafe or oversized XML")
    raw.decode("utf-8-sig")  # Reject alternate encodings before XML parsing.
    root = ET.fromstring(raw)  # Bounded UTF-8 input; DTD and entities rejected above.
    if root.tag not in ("Report", "{wasde}Report"):
        raise ValueError("unknown XML namespace")
    namespace = "{wasde}" if root.tag.startswith("{") else ""
    sections = []
    for crop, (page, matrix_name, suffix) in MATRICES.items():
        reports = root.findall(f"{namespace}{page}/{namespace}Report")
        if len(reports) != 1 or reports[0].get("Report_Month") != report_month:
            raise ValueError("XML report month or identity mismatch")
        report = reports[0]
        if not report.get("sub_report_title", "").startswith(TITLES[crop]):
            raise ValueError("XML crop title mismatch")
        matrices = report.findall(namespace + matrix_name)
        if len(matrices) != 1:
            raise ValueError("XML matrix ambiguity")
        matrix = matrices[0]
        units = {
            value.strip()
            for e in matrix.iter()
            for key, value in e.attrib.items()
            if "unit_descr3" in key and value.strip()
        }
        if units != {"Million Bushels"}:
            raise ValueError("XML grain units mismatch")
        rows = []
        expected_columns = None
        for label in FIELDS.values():
            matches = [e for e in matrix.iter() if e.get("attribute" + suffix, "").strip() == label]
            if len(matches) != 1:
                raise ValueError(f"XML missing or duplicate field {crop}/{label}")
            columns, values = [], []
            year_nodes = [e for e in matches[0].iter() if "market_year" + suffix in e.attrib]
            for year in year_nodes:
                year_label = year.get("market_year" + suffix)
                match = re.fullmatch(r"(\d{4}/\d{2})(?:\s+(?:Est\.|Proj\.))?\s*", year_label)
                if match is None:
                    raise ValueError("XML crop-year syntax")
                months = [e for e in year.iter() if "forecast_month" + suffix in e.attrib]
                if len(months) != 1:
                    raise ValueError("XML month grouping ambiguity")
                cells = [
                    e.get("cell_value" + suffix)
                    for e in months[0].iter()
                    if "cell_value" + suffix in e.attrib
                ]
                if len(cells) != 1:
                    raise ValueError("XML cell ambiguity")
                columns.append((match[1], months[0].get("forecast_month" + suffix)))
                value = cells[0]
                if not re.fullmatch(r"(?:NA|\d+(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?)", value):
                    raise ValueError("XML numeric syntax")
                values.append(value.replace(",", ""))
            if not columns or (expected_columns is not None and columns != expected_columns):
                raise ValueError("XML inconsistent field columns")
            expected_columns = columns
            rows.append(label + "  " + "  ".join(values))
        if columns[-1][1] not in (report_month[:3], report_month.split()[0]):
            raise ValueError("XML final column is not current month")
        sections.append(
            "\n".join(
                [
                    report.get("page_title", ""),
                    TITLES[crop],
                    "  ".join(year for year, _ in expected_columns),
                    crop.upper() if crop != "wheat" else "",
                    "Million Bushels",
                    *rows,
                ]
            )
        )
    return extract_tables("\n".join(sections))
