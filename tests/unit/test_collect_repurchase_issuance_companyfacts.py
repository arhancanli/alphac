from __future__ import annotations

from pathlib import Path
from runpy import run_path

MODULE = run_path(
    str(Path(__file__).parents[2] / "scripts" / "collect_repurchase_issuance_companyfacts.py")
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
                    "units": {"USD": [{"val": 2, "filed": "2020-01-01", "form": "10-K"}]}
                },
                "StockIssuedDuringPeriodSharesAcquisitions": {
                    "units": {"shares": [{"val": 3, "filed": "2020-01-01", "form": "10-K"}]}
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
                    "units": {"shares": [{"val": 100, "filed": "2020-01-01", "form": "10-K"}]}
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
                    "units": {"shares": [{"val": 10, "filed": "2020-01-01", "form": "10-K"}]}
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


def test_invalid_cached_entity_is_not_complete_and_retains_source_bytes(tmp_path: Path) -> None:
    import gzip
    import hashlib
    import json

    raw = json.dumps({"cik": "0000000001", "entityName": "", "facts": {}}).encode()
    source = tmp_path / "CIK0000000001.json.gz"
    source.write_bytes(gzip.compress(raw))
    before = source.read_bytes()
    status, facts = MODULE["process_issuer"](object(), 1, tmp_path)
    assert status["source_status"] == "invalid_payload"
    assert status["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert status["raw_from_cache"] is True
    assert facts == []
    assert source.read_bytes() == before
    parts = tmp_path / "parts"
    write_parts(parts, 0, [status], facts)
    assert completed_ciks(parts) == set()
    report = summarize(parts, {1}, {"content_hash": "sealed", "sample_sha256": "manifest"})
    assert report["complete"] is False
    assert report["successful_ciks"] == 0
    assert report["collection_error_ciks"] == 1


def test_corrupt_gzip_is_preserved_and_does_not_trigger_silent_refetch(tmp_path: Path) -> None:
    source = tmp_path / "CIK0000000001.json.gz"
    source.write_bytes(b"damaged historical gzip")
    status, facts = MODULE["process_issuer"](object(), 1, tmp_path)
    assert status["source_status"] == "error"
    assert source.read_bytes() == b"damaged historical gzip"
    assert facts == []


def test_invalid_json_and_shapes_cannot_be_successful_fetches(tmp_path: Path) -> None:
    import gzip
    import json

    valid = {"cik": 1, "entityName": "Example issuer", "facts": {}}
    cases = [b"{broken", json.dumps([]).encode()]
    for field, value in [("cik", True), ("cik", 2), ("entityName", "  "), ("facts", [])]:
        cases.append(json.dumps({**valid, field: value}).encode())
    cases.append(
        json.dumps({**valid, "facts": {"us-gaap": {"Assets": {"units": {"USD": {}}}}}}).encode()
    )
    source = tmp_path / "CIK0000000001.json.gz"
    for raw in cases:
        source.write_bytes(gzip.compress(raw))
        status, facts = MODULE["process_issuer"](object(), 1, tmp_path)
        assert status["source_status"] == "invalid_payload"
        assert facts == []


def test_valid_entity_with_no_relevant_tags_is_not_conflated_with_invalid_response(
    tmp_path: Path,
) -> None:
    import gzip
    import json

    source = tmp_path / "CIK0000000001.json.gz"
    source.write_bytes(
        gzip.compress(json.dumps({"cik": 1, "entityName": "Example", "facts": {}}).encode())
    )
    status, facts = MODULE["process_issuer"](object(), 1, tmp_path)
    assert status["source_status"] == "fetched"
    assert status["relevant_fact_rows"] == 0
    assert facts == []


def test_prior_parser_success_does_not_skip_new_identity_validation(tmp_path: Path) -> None:
    status = {
        "cik": 1,
        "parser_version": "repurchase-issuance-companyfacts-v3",
        "source_status": "fetched",
        "error": None,
    }
    write_parts(tmp_path, 0, [status], [])
    assert completed_ciks(tmp_path) == set()


def test_legacy_or_missing_status_cannot_be_counted_as_current_success(tmp_path: Path) -> None:
    status = {
        "cik": 1,
        "parser_version": "repurchase-issuance-companyfacts-v3",
        "source_status": "fetched",
        "error": None,
    }
    write_parts(tmp_path, 0, [status], [])
    report = summarize(tmp_path, {1}, {"content_hash": "sealed", "sample_sha256": "manifest"})
    assert report["successful_ciks"] == 0
    assert report["legacy_parser_ciks"] == 1
    assert report["complete"] is False
    status.update(parser_version=MODULE["PARSER_VERSION"], source_status=None)
    write_parts(tmp_path, 1, [status], [])
    assert completed_ciks(tmp_path) == set()


def test_fresh_invalid_response_is_retained_but_not_counted_as_success(tmp_path: Path) -> None:
    import gzip

    raw = b'{"cik": 1, "entityName": "", "facts": {}}'

    class Client:
        def get_bytes(self, url: str) -> bytes:
            assert url.endswith("CIK0000000001.json")
            return raw

    status, facts = MODULE["process_issuer"](Client(), 1, tmp_path)
    assert status["source_status"] == "invalid_payload"
    assert status["raw_from_cache"] is False
    assert gzip.decompress((tmp_path / "CIK0000000001.json.gz").read_bytes()) == raw
    assert facts == []


def test_capture_receipt_binds_new_bytes_and_legacy_cache_time_stays_unknown(
    tmp_path: Path,
) -> None:
    import gzip
    import json

    raw = b'{"cik": 1, "entityName": "Example", "facts": {}}'

    class Client:
        def get_bytes(self, url: str) -> bytes:
            return raw

    status, _ = MODULE["process_issuer"](Client(), 1, tmp_path)
    assert status["captured_at"] is not None
    receipt_path = tmp_path / "CIK0000000001.capture.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["raw_sha256"] == status["raw_sha256"]
    receipt["raw_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt))
    status, _ = MODULE["process_issuer"](object(), 1, tmp_path)
    assert status["source_status"] == "invalid_payload"
    assert status["captured_at"] is None
    receipt_path.unlink()
    status, _ = MODULE["process_issuer"](object(), 1, tmp_path)
    assert status["source_status"] == "fetched"
    assert status["captured_at"] is None
    assert gzip.decompress((tmp_path / "CIK0000000001.json.gz").read_bytes()) == raw
