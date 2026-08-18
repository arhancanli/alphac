from __future__ import annotations

from pathlib import Path
from runpy import run_path

MODULE = run_path(
    str(
        Path(__file__).parents[2]
        / "scripts"
        / "collect_repurchase_issuance_companyfacts.py"
    )
)
parse_companyfacts = MODULE["parse_companyfacts"]
custom_fact_inventory = MODULE["custom_fact_inventory"]
completed_ciks = MODULE["completed_ciks"]
summarize = MODULE["summarize"]
write_parts = MODULE["write_parts"]


def test_parser_preserves_revisions_and_accession_lineage() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "PaymentsForRepurchaseOfCommonStock": {
                    "label": "Repurchases",
                    "description": "Cash outflow",
                    "units": {
                        "USD": [
                            {
                                "val": 100,
                                "accn": "0000000001-20-000001",
                                "start": "2019-01-01",
                                "end": "2019-12-31",
                                "filed": "2020-02-01",
                                "form": "10-K",
                                "fy": 2019,
                                "fp": "FY",
                            },
                            {
                                "val": 120,
                                "accn": "0000000001-20-000002",
                                "start": "2019-01-01",
                                "end": "2019-12-31",
                                "filed": "2020-03-01",
                                "form": "10-K/A",
                                "fy": 2019,
                                "fp": "FY",
                            },
                        ]
                    },
                },
                "Assets": {
                    "label": "Assets",
                    "description": "Irrelevant",
                    "units": {"USD": [{"val": 999, "filed": "2020-02-01", "form": "10-K"}]},
                },
            }
        }
    }

    rows = parse_companyfacts(1, payload)

    assert len(rows) == 2
    assert [row["value"] for row in rows] == [100, 120]
    assert [row["form"] for row in rows] == ["10-K", "10-K/A"]
    assert all(row["tag_family"] == "repurchase_cash" for row in rows)


def test_parser_drops_out_of_window_and_nonperiodic_forms() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "ProceedsFromIssuanceOfCommonStock": {
                    "units": {
                        "USD": [
                            {"val": 1, "filed": "2012-12-31", "form": "10-K"},
                            {"val": 2, "filed": "2019-01-01", "form": "8-K"},
                            {"val": 3, "filed": "2025-12-31", "form": "10-Q"},
                        ]
                    }
                }
            }
        }
    }

    rows = parse_companyfacts(2, payload)

    assert len(rows) == 1
    assert rows[0]["value"] == 3
    assert rows[0]["tag_family"] == "issuance_cash"


def test_stock_compensation_and_acquisitions_are_not_ordinary_issuance() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "ProceedsFromStockOptionsExercised": {
                    "units": {
                        "USD": [{"val": 2, "filed": "2020-01-01", "form": "10-K"}]
                    }
                },
                "StockIssuedDuringPeriodSharesAcquisitions": {
                    "units": {
                        "shares": [
                            {"val": 3, "filed": "2020-01-01", "form": "10-K"}
                        ]
                    }
                },
            }
        }
    }

    families = {row["tag_family"] for row in parse_companyfacts(2, payload)}

    assert families == {
        "contamination_stock_compensation",
        "contamination_acquisition",
    }


def test_custom_extensions_are_counted_but_not_auto_mapped() -> None:
    payload = {
        "facts": {
            "ACME": {
                "ShareBuybackThing": {
                    "units": {
                        "USD": [
                            {"val": 1, "filed": "2020-01-01", "form": "10-K"},
                            {"val": 2, "filed": "2020-01-01", "form": "8-K"},
                        ]
                    }
                }
            }
        }
    }

    inventory = custom_fact_inventory(payload)

    assert inventory == {
        "custom_namespaces": '["ACME"]',
        "custom_tags": 1,
        "custom_fact_rows": 1,
    }
    assert parse_companyfacts(2, payload) == []


def test_balance_sheet_common_shares_are_reconciliation_not_flow() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "CommonStockSharesIssued": {
                    "units": {
                        "shares": [
                            {"val": 100, "filed": "2020-01-01", "form": "10-K"}
                        ]
                    }
                }
            }
        }
    }

    assert parse_companyfacts(2, payload)[0]["tag_family"] == "reconciliation"


def test_missing_context_is_preserved_for_fail_closed_audit() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "CommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"val": 10, "filed": "2020-01-01", "form": "10-K"}
                        ]
                    }
                }
            }
        }
    }

    row = parse_companyfacts(3, payload)[0]

    assert row["accession"] is None
    assert row["start"] is None
    assert row["end"] is None
    assert row["tag_family"] == "reconciliation"


def test_empty_relevant_fact_batch_still_writes_auditable_parts(tmp_path: Path) -> None:
    status = {
        "cik": 9,
        "parser_version": MODULE["PARSER_VERSION"],
        "source_status": "fetched",
        "raw_sha256": "a" * 64,
        "raw_bytes": 100,
        "raw_from_cache": False,
        "relevant_fact_rows": 0,
        "relevant_tags": 0,
        "error": None,
    }

    write_parts(tmp_path, 0, [status], [])

    assert (tmp_path / "issuer-status-00000.parquet").is_file()
    assert (tmp_path / "facts-00000.parquet").is_file()
    assert completed_ciks(tmp_path) == {9}


def test_summary_requires_exact_manifest_cik_set(tmp_path: Path) -> None:
    statuses = [
        {
            "cik": cik,
            "parser_version": MODULE["PARSER_VERSION"],
            "source_status": "fetched",
            "raw_sha256": "a" * 64,
            "raw_bytes": 100,
            "raw_from_cache": False,
            "relevant_fact_rows": 0,
            "relevant_tags": 0,
            "custom_namespaces": "[]",
            "custom_tags": 0,
            "custom_fact_rows": 0,
            "error": None,
        }
        for cik in (1, 3)
    ]
    write_parts(tmp_path, 0, statuses, [])

    result = summarize(
        tmp_path,
        {1, 2},
        {"content_hash": "sealed", "sample_sha256": "manifest"},
    )

    assert result["complete"] is False
    assert result["missing_ciks"] == [2]
    assert result["unexpected_ciks"] == [3]


def test_summary_accounts_for_terminal_404_without_claiming_a_fetch(tmp_path: Path) -> None:
    status = {
        "cik": 7,
        "parser_version": MODULE["PARSER_VERSION"],
        "source_status": "not_available_404",
        "raw_sha256": None,
        "raw_bytes": 0,
        "raw_from_cache": False,
        "relevant_fact_rows": 0,
        "relevant_tags": 0,
        "custom_namespaces": "[]",
        "custom_tags": 0,
        "custom_fact_rows": 0,
        "error": None,
    }
    write_parts(tmp_path, 0, [status], [])

    result = summarize(
        tmp_path,
        {7},
        {"content_hash": "sealed", "sample_sha256": "manifest"},
    )

    assert result["complete"] is True
    assert result["successful_ciks"] == 0
    assert result["terminal_unavailable_404_ciks"] == 1
    assert result["terminal_accounted_ciks"] == 1
    assert result["collection_error_ciks"] == 0
