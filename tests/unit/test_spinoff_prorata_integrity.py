from __future__ import annotations

import gzip
import hashlib
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).parents[2] / 'scripts' / 'analyze_spinoff_prorata_gate.py'
SPEC = importlib.util.spec_from_file_location('spinoff_prorata_integrity', SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, Path]:
    docs = tmp_path / 'docs'
    docs.mkdir()
    hashes = []
    for i in range(98):
        raw = f'<html>Frozen document {i}</html>'.encode()
        hashes.append(hashlib.sha256(raw).hexdigest())
        (docs / f'{i:03d}.gz').write_bytes(gzip.compress(raw))
    schema = tmp_path / 'schema.parquet'
    pd.DataFrame({'primary_document_sha256': hashes}).to_parquet(schema)
    return schema, docs


def test_complete_population_replays(corpus: tuple[Path, Path]) -> None:
    assert len(MODULE.verified_documents(*corpus)) == 98


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'duplicate', 'altered', 'bad_schema'])
def test_untrusted_population_fails_before_replacing_report(
    corpus: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    schema, docs = corpus
    if mutation == 'missing':
        (docs / '000.gz').unlink()
    elif mutation == 'extra':
        (docs / 'extra.gz').write_bytes((docs / '000.gz').read_bytes())
    elif mutation == 'duplicate':
        (docs / '001.gz').write_bytes((docs / '000.gz').read_bytes())
    elif mutation == 'altered':
        (docs / '000.gz').write_bytes(gzip.compress(b'altered evidence'))
    else:
        rows = pd.read_parquet(schema)
        rows.loc[0, 'primary_document_sha256'] = None
        rows.to_parquet(schema)
    output = schema.parent / 'result.json'
    output.write_text('previous accepted report')
    monkeypatch.setattr(MODULE, 'SCHEMA', schema)
    monkeypatch.setattr(MODULE, 'DOCS', docs)
    monkeypatch.setattr(MODULE, 'OUTPUT', output)
    with pytest.raises(ValueError):
        MODULE.main()
    assert output.read_text() == 'previous accepted report'


def test_verdict_changes_with_measured_ceiling() -> None:
    assert MODULE.gate_verdict(16, 98) == 'GATE_UNREACHABLE_BY_DETECTOR_REPAIR'
    assert MODULE.gate_verdict(30, 98).startswith('LANGUAGE_CEILING_DOES_NOT_RULE_OUT')
