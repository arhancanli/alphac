from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "build_sec_item1a_pairs.py"
SPEC = importlib.util.spec_from_file_location("build_sec_item1a_pairs", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def row(cik: int, accession: str, text: str | None, *, words: int | None = None) -> dict:
    section_words = len(text.split()) if text is not None and words is None else int(words or 0)
    return {
        "filing_identity": f"{cik}|{accession}",
        "cik": cik,
        "accession": accession,
        "acceptance_datetime": f"20{accession}-01-01T00:00:00Z",
        "sic": "1234",
        "parser_version": "sec-filing-sections-v2",
        "error": None,
        "extracted": text is not None,
        "section_words": section_words,
        "section_sha256": hashlib.sha256(text.encode()).hexdigest() if text else None,
        "section_text": text,
    }


def test_pairs_only_immediate_predecessor() -> None:
    records = [
        row(1, "01", "alpha beta gamma delta epsilon zeta" * 100),
        row(1, "02", None),
        row(1, "03", "alpha beta gamma delta epsilon eta" * 100),
        row(1, "04", "alpha beta gamma delta epsilon theta" * 100),
    ]
    rejected: Counter[str] = Counter()
    pairs = list(MODULE.immediate_pairs(records, rejected))
    assert len(pairs) == 1
    assert pairs[0]["previous_accession"] == "03"
    assert pairs[0]["current_accession"] == "04"
    assert rejected == {
        "first_filing_for_issuer": 1,
        "invalid_current_section": 1,
        "invalid_immediate_predecessor": 1,
    }
    assert len(pairs) + sum(rejected.values()) == len(records)


def test_pair_never_crosses_cik_boundary() -> None:
    records = [row(1, "01", "one " * 600), row(2, "02", "two " * 600)]
    assert list(MODULE.immediate_pairs(records)) == []


def test_short_section_is_not_pairable() -> None:
    records = [row(1, "01", "one " * 400, words=400), row(1, "02", "two " * 600)]
    assert list(MODULE.immediate_pairs(records)) == []


def test_direction_free_pair_metric_is_bounded() -> None:
    records = [
        row(1, "01", "one two three four five " * 120),
        row(1, "02", "one two three four six " * 120),
    ]
    pair = next(iter(MODULE.immediate_pairs(records)))
    assert 0.0 <= pair["fivegram_jaccard"] <= 1.0


def test_section_hash_and_word_count_are_verified() -> None:
    valid = row(1, "01", "one " * 600)
    corrupt_hash = {**valid, "section_sha256": "0" * 64}
    corrupt_words = {**valid, "section_words": 601}
    assert MODULE.valid_section(valid)
    assert not MODULE.valid_section(corrupt_hash)
    assert not MODULE.valid_section(corrupt_words)


def test_only_current_filing_requires_point_in_time_sic() -> None:
    previous = {**row(1, "01", "one " * 600), "sic": None}
    current = row(1, "02", "two " * 600)
    missing_current = {**current, "sic": None}

    assert MODULE.make_pair(previous, current) is not None
    assert MODULE.make_pair(previous, missing_current) is None
    assert MODULE.pair_rejection_reason(previous, missing_current) == (
        "missing_current_filing_sic"
    )


def test_corpus_barrier_rejects_unbound_parts(tmp_path: Path) -> None:
    part = tmp_path / "part-00000.parquet"
    pd = __import__("pandas")
    pd.DataFrame([row(1, "01", "one " * 600)]).to_parquet(part, index=False)
    result = tmp_path / "corpus.json"
    result.write_text(
        json.dumps(
            {
                "stage": "corpus_ingest_no_prices_no_returns",
                "complete": True,
                "hypothesis_identities_spent": 0,
                "parser_version": MODULE.PARSER_VERSION,
                "part_count": 1,
                "parts_sha256": "wrong",
            }
        )
    )
    try:
        MODULE.require_complete_corpus(result, str(tmp_path / "part-*.parquet"))
    except RuntimeError as error:
        assert "lineage" in str(error)
    else:  # pragma: no cover
        raise AssertionError("pair builder must reject corpus bytes not sealed by the result")


def test_latest_rows_uses_newest_retry_and_preserves_issuer_chronology(
    tmp_path: Path,
) -> None:
    pd = __import__("pandas")
    first = row(1, "01", "one " * 600)
    failed = row(1, "02", None)
    retried = row(1, "02", "two " * 600)
    third = row(1, "03", "three " * 600)
    pd.DataFrame([first, failed]).to_parquet(tmp_path / "part-00000.parquet", index=False)
    pd.DataFrame([retried, third]).to_parquet(tmp_path / "part-00001.parquet", index=False)

    latest = list(MODULE.latest_rows(str(tmp_path / "part-*.parquet"), batch_size=1))

    assert [item["accession"] for item in latest] == ["01", "02", "03"]
    assert latest[1]["section_sha256"] == retried["section_sha256"]
    assert latest[1]["error"] is None


def test_manifest_lineage_is_byte_bound_and_fail_closed(tmp_path: Path) -> None:
    pd = __import__("pandas")
    path = tmp_path / "manifest.parquet"
    manifest = pd.DataFrame(
        [
            {
                key: value
                for key, value in row(1, accession, "text " * 600).items()
                if key
                in {"filing_identity", "cik", "accession", "form", "acceptance_datetime"}
            }
            | {"form": "10-K"}
            for accession in ("01", "02", "03")
        ]
    )
    manifest.to_parquet(path, index=False)
    corpus = {
        "manifest_rows": 3,
        "pair_eligible_manifest_rows": 3,
        "source_manifest": {"path": str(path), "sha256": MODULE.file_sha256(path)},
    }

    lineage = MODULE.require_bound_manifest(path, corpus)

    assert lineage["sha256"] == MODULE.file_sha256(path)
    assert lineage["rows"] == 3
    corrupted = manifest.copy()
    corrupted.loc[1, "form"] = "10-K/A"
    corrupted.to_parquet(path, index=False)
    with pytest.raises(RuntimeError, match=r"corpus_manifest_sha256_mismatch|non_10k_form"):
        MODULE.require_bound_manifest(path, corpus)


def test_exact_identity_coverage_is_bidirectional(tmp_path: Path) -> None:
    pd = __import__("pandas")
    manifest = pd.DataFrame(
        [
            {
                "filing_identity": f"1|{accession}",
                "cik": 1,
                "accession": accession,
            }
            for accession in ("01", "02")
        ]
    )
    manifest_path = tmp_path / "manifest.parquet"
    manifest.to_parquet(manifest_path, index=False)
    parts_glob = str(tmp_path / "part-*.parquet")
    pd.DataFrame(
        [
            {"filing_identity": "1|01"},
            {"filing_identity": "1|02"},
        ]
    ).to_parquet(tmp_path / "part-00000.parquet", index=False)
    assert MODULE.require_exact_identity_coverage(manifest_path, parts_glob) == {
        "eligible_manifest_identities": 2,
        "latest_corpus_identities": 2,
        "missing": 0,
        "unexpected": 0,
    }

    pd.DataFrame([{"filing_identity": "9|unexpected"}]).to_parquet(
        tmp_path / "part-00001.parquet", index=False
    )
    with pytest.raises(RuntimeError, match="missing=0, unexpected=1"):
        MODULE.require_exact_identity_coverage(manifest_path, parts_glob)
