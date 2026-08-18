from __future__ import annotations

from pathlib import Path
from runpy import run_path

MODULE = run_path(
    str(Path(__file__).parents[2] / "scripts" / "parse_repurchase_item703_documents.py")
)
parse_html = MODULE["parse_html"]


def test_item703_table_and_shape_are_detected() -> None:
    html = b"""
    <html><p>No tender offer was conducted.</p><table>
      <tr><th>Period</th><th>Total Number of Shares Purchased</th>
      <th>Average Price Paid per Share</th>
      <th>Total Number of Shares Purchased as Part of Publicly Announced Plans or Programs</th></tr>
      <tr><td>January 1 - January 31</td><td>10</td><td>$4</td><td>8</td></tr>
      <tr><td>Feb. 1 - Feb. 28</td><td>11</td><td>$5</td><td>9</td></tr>
      <tr><td>Total</td><td>21</td><td>$4.50</td><td>17</td></tr>
    </table></html>
    """

    result = parse_html(html)

    assert result["has_item703_table"] is True
    assert result["candidate_table_count"] == 1
    assert result["month_rows"] == 2
    assert result["has_total_row"] is True
    assert result["tender_offer_mention"] is True
    assert len(result["candidate_table_sha256"]) == 64


def test_unrelated_table_is_not_item703() -> None:
    result = parse_html(b"<table><tr><th>Revenue</th><td>10</td></tr></table>")

    assert result["table_count"] == 1
    assert result["candidate_table_count"] == 0
    assert result["has_item703_table"] is False
    assert result["month_rows"] == 0
    assert result["tender_offer_mention"] is False


def test_malformed_utf8_fails_open_as_text_not_as_prediction() -> None:
    result = parse_html(b"\xff<table><tr><td>not a disclosure</td></tr></table>")

    assert result["table_count"] == 1
    assert result["has_item703_table"] is False
