from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path
from types import SimpleNamespace

MODULE = run_path(
    str(Path(__file__).parents[2] / "scripts" / "build_repurchase_issuance_manifest.py")
)
canonical_issuers = MODULE["canonical_issuers"]
locked_sample = MODULE["locked_sample"]
run = MODULE["run"]


def payload() -> dict:
    return {
        "0": {"cik_str": 30, "ticker": "CCC", "title": "Company C"},
        "1": {"cik_str": 10, "ticker": "AAA", "title": "Company A"},
        "2": {"cik_str": 20, "ticker": "BBB.B", "title": "Company B"},
        "3": {"cik_str": 20, "ticker": "BBB.A", "title": "Company B"},
        "4": {"cik_str": "bad", "ticker": "BAD", "title": "Bad"},
    }


def test_canonical_issuers_deduplicates_share_classes() -> None:
    frame = canonical_issuers(payload())

    assert frame["cik"].tolist() == [10, 20, 30]
    assert frame.loc[frame["cik"].eq(20), "tickers"].item() == "BBB.A|BBB.B"
    assert frame["cik_padded"].tolist() == ["CIK0000000010", "CIK0000000020", "CIK0000000030"]


def test_locked_sample_is_order_invariant_and_unique() -> None:
    frame = canonical_issuers(payload())
    first = locked_sample(frame, 2)
    second = locked_sample(frame.sample(frac=1, random_state=7), 2)

    assert first["cik"].tolist() == second["cik"].tolist()
    assert first["cik"].nunique() == 2
    assert first["sample_rank"].is_monotonic_increasing


def test_invalid_sample_size_fails_closed() -> None:
    frame = canonical_issuers(payload())

    try:
        locked_sample(frame, 4)
    except ValueError as error:
        assert "invalid" in str(error)
    else:
        raise AssertionError("oversized sample must fail closed")


def test_payload_fixture_is_valid_json() -> None:
    assert json.loads(json.dumps(payload())) == payload()


def test_manifest_content_hash_covers_generated_timestamp(tmp_path: Path) -> None:
    raw = tmp_path / "tickers.json"
    raw.write_text(json.dumps(payload()))
    result = run(
        SimpleNamespace(
            raw=raw,
            out=tmp_path / "sample.parquet",
            result=tmp_path / "result.json",
            sample_size=2,
        )
    )
    body = {key: value for key, value in result.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()

    assert result["content_hash"] == f"sha256:{MODULE['sha256_bytes'](canonical)}"
