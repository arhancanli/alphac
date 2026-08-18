from __future__ import annotations

import gzip
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "download_sec_10k_item1a.py"
SPEC = importlib.util.spec_from_file_location("download_sec_10k_item1a", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parse_sic_from_immutable_filing_index() -> None:
    raw = b'<a href="/cgi-bin/browse-edgar?action=getcompany&amp;SIC=4911&amp;owner=include">'
    assert MODULE.parse_sic(raw) == "4911"
    assert MODULE.parse_sic(b"no classification") is None


def test_gzip_cache_is_deterministic(tmp_path: Path) -> None:
    raw = b"SEC source bytes" * 100
    left, right = tmp_path / "left.gz", tmp_path / "right.gz"
    MODULE.gzip_write(left, raw)
    MODULE.gzip_write(right, raw)
    assert left.read_bytes() == right.read_bytes()
    assert gzip.decompress(left.read_bytes()) == raw


def test_corrupt_gzip_cache_is_replaced_from_source(tmp_path: Path) -> None:
    class Client:
        def get_bytes(self, url: str) -> bytes:
            assert url == "https://example.test/immutable"
            return b"recovered SEC bytes"

    path = tmp_path / "filing.html.gz"
    path.write_bytes(b"truncated")
    raw, from_cache = MODULE.cached_response(Client(), "https://example.test/immutable", path)
    assert raw == b"recovered SEC bytes"
    assert from_cache is False
    assert MODULE.gzip_read(path) == raw
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_parts_lineage_changes_with_part_bytes(tmp_path: Path) -> None:
    MODULE.write_part(tmp_path, 0, [{"filing_identity": "1|a", "error": None}])
    count, before = MODULE.parts_lineage(tmp_path)
    assert count == 1
    MODULE.write_part(tmp_path, 1, [{"filing_identity": "2|a", "error": None}])
    assert MODULE.parts_lineage(tmp_path)[1] != before


def test_part_publish_leaves_no_partial_name(tmp_path: Path) -> None:
    path = MODULE.write_part(tmp_path, 0, [{"filing_identity": "1|a", "error": None}])
    assert path.exists()
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_completed_identities_reads_partition_keys(tmp_path: Path) -> None:
    MODULE.write_part(
        tmp_path,
        0,
        [
            {
                "filing_identity": "1|a",
                "parser_version": MODULE.PARSER_VERSION,
                "sic": "4911",
                "section_text": "one",
                "error": None,
            }
        ],
    )
    MODULE.write_part(
        tmp_path,
        1,
        [
            {
                "filing_identity": "2|a",
                "parser_version": MODULE.PARSER_VERSION,
                "sic": "2834",
                "section_text": "two",
                "error": None,
            }
        ],
    )
    assert MODULE.completed_identities(tmp_path) == {"1|a", "2|a"}


def test_failed_accession_is_retried_on_resume(tmp_path: Path) -> None:
    MODULE.write_part(
        tmp_path,
        0,
        [
            {
                "filing_identity": "1|a",
                "parser_version": MODULE.PARSER_VERSION,
                "sic": None,
                "error": "temporary",
            }
        ],
    )
    assert MODULE.completed_identities(tmp_path) == set()


def test_source_missing_filing_time_sic_is_sealed_not_retried(tmp_path: Path) -> None:
    MODULE.write_part(
        tmp_path,
        0,
        [
            {
                "filing_identity": "1|a",
                "parser_version": MODULE.PARSER_VERSION,
                "sic": None,
                "error": None,
            }
        ],
    )
    assert MODULE.completed_identities(tmp_path) == {"1|a"}


def test_stale_parser_row_is_retried_on_resume(tmp_path: Path) -> None:
    MODULE.write_part(
        tmp_path,
        0,
        [{"filing_identity": "1|a", "parser_version": "stale", "sic": "4911", "error": None}],
    )
    assert MODULE.completed_identities(tmp_path) == set()


def test_summary_never_marks_error_row_complete(tmp_path: Path) -> None:
    MODULE.write_part(
        tmp_path,
        0,
        [
            {
                "filing_identity": "1|a",
                "accession": "a",
                "cik": 1,
                "parser_version": MODULE.PARSER_VERSION,
                "extracted": False,
                "sic": None,
                "error": "timeout",
                "section_words": 0,
            }
        ],
    )
    manifest = tmp_path / "manifest.parquet"
    manifest.write_bytes(b"sealed manifest")
    result = MODULE.summarize(tmp_path, manifest, manifest_rows=1, eligible_rows=1)
    assert result["complete"] is False
    assert result["source_manifest"]["sha256"] == MODULE.file_sha256(manifest)


def test_summary_discloses_source_missing_sic_without_blocking_corpus(tmp_path: Path) -> None:
    MODULE.write_part(
        tmp_path,
        0,
        [
            {
                "filing_identity": "1|a",
                "accession": "a",
                "cik": 1,
                "parser_version": MODULE.PARSER_VERSION,
                "extracted": True,
                "sic": None,
                "error": None,
                "section_words": 600,
            }
        ],
    )
    manifest = tmp_path / "manifest.parquet"
    manifest.write_bytes(b"sealed manifest")
    result = MODULE.summarize(tmp_path, manifest, manifest_rows=1, eligible_rows=1)
    assert result["complete"] is True
    assert result["sic_missing_at_source"] == 1
    assert result["sic_rate"] == 0.0
