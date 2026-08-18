from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from ingest_eia_wpsr import discover_releases, parse_table4


def test_discovers_unique_dated_archive_csv_urls() -> None:
    html = """
    <a href="archive/2024/2024_07_03/wpsr_2024_07_03.php">3</a>
    <a href="archive/2011/2011_08_03/wpsr_2011_08_03.html">3</a>
    <a href="archive/2024/2024_07_03/wpsr_2024_07_03.php">duplicate</a>
    """
    releases = discover_releases(html)
    assert [released for released, _ in releases] == [date(2011, 8, 3), date(2024, 7, 3)]
    assert releases[-1][1].endswith("/2024/2024_07_03/csv/table4.csv")


def test_parses_required_first_release_rows_and_reconciles_difference() -> None:
    payload = (
        b'"STUB_1","6/28/24","6/21/24","Difference"\n'
        b'"Commercial (Excluding SPR)","448.539","460.696","-12.157"\n'
        b'"Total Motor Gasoline","231.672","233.886","-2.214"\n'
    )
    rows = parse_table4(
        payload,
        release_date=date(2024, 7, 3),
        source_url="https://example.test/table4.csv",
        source_sha256="abc",
    )
    assert len(rows) == 2
    assert rows[0]["proxy"] == "USO"
    assert rows[0]["change_million_barrels"] == -12.157
    assert rows[1]["proxy"] == "UGA"


def test_rejects_a_source_difference_that_does_not_reconcile() -> None:
    payload = (
        b'"STUB_1","12/22/23","12/15/23","Difference"\n'
        b'"Commercial (Excluding SPR)","436.568","443.682","-6.911"\n'
        b'"Total Motor Gasoline","226.054","224.013","2.041"\n'
    )
    with pytest.raises(ValueError, match="does not reconcile"):
        parse_table4(
            payload,
            release_date=date(2023, 12, 28),
            source_url="https://example.test/table4.csv",
            source_sha256="abc",
        )
