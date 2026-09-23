"""The v4 re-baseline: one start date, in every place that decides where the record begins.

On 2026-09-23 the owner withdrew the v3 record. The record's start lives in two files that nothing
else ties together: scripts/paper_trading_state.py (where every sleeve's published curve is floored)
and config/live_change_contract.json (whose latest contaminating change_log entry starts the
forward-evidence epoch, scripts/evaluate_forward_evidence_maturity.py). If they disagree, the
published curve and the Sharpe evidence describe different experiments, or a sleeve silently keeps
v3 days in v4. These tests make the two agree, and keep v3 published as withdrawn, not erased.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location(
    "paper_trading_state_v4", REPO / "scripts" / "paper_trading_state.py"
)
assert _spec is not None and _spec.loader is not None
paper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(paper)

_eval_spec = importlib.util.spec_from_file_location(
    "forward_evidence_maturity_v4", REPO / "scripts" / "evaluate_forward_evidence_maturity.py"
)
assert _eval_spec is not None and _eval_spec.loader is not None
maturity = importlib.util.module_from_spec(_eval_spec)
_eval_spec.loader.exec_module(maturity)


def test_every_sleeve_and_the_book_start_on_the_v4_date() -> None:
    assert paper.GO_LIVE == paper.V4_GO_LIVE == paper.V3_ENDED
    for name in ("EQ_GO_LIVE", "MF_GO_LIVE", "VINTAGE_V4_GO_LIVE"):
        assert getattr(paper, name) == paper.GO_LIVE, name
    assert paper.WEIGHT_SCHEDULE[0][0] == paper.GO_LIVE


def test_the_evidence_epoch_starts_on_the_same_day_as_the_published_record() -> None:
    contract = json.loads((REPO / "config" / "live_change_contract.json").read_text())
    epoch = maturity.evidence_epoch(contract)
    assert epoch is not None
    assert epoch["starts_on"] == paper.GO_LIVE


def test_v3_stays_published_as_withdrawn_with_its_reasons() -> None:
    assert paper.V3_WEIGHT_SCHEDULE[0][0] == paper.V3_GO_LIVE
    source = (REPO / "scripts" / "paper_trading_state.py").read_text()
    assert '"status": "WITHDRAWN"' in source
    assert '"withdrawn_because": [' in source
    last = paper.transparency_entries()[-1]
    assert "v3 is WITHDRAWN" in last
    assert paper.V4_GO_LIVE in last
    # The disclosure claims no v3 result; a withdrawn number must not be restated as a finding.
    assert "NO v3 result is claimed" in last


def test_a_suspended_sleeve_is_in_no_part_of_the_book() -> None:
    """AlphaForge is suspended (owner, 2026-09-23): out of the weights, the live schedule and the
    composition every study rebuilds, and listed as suspended, never silently missing."""
    assert "alphaforge" in paper.SUSPENDED_SLEEVES
    assert paper.CRYPTO_WF not in paper.BOOK_WEIGHTS
    assert set(paper.WEIGHT_SCHEDULE[-1][1]) == {"equity", "mf", "vintage"}
    assert abs(sum(paper.BOOK_WEIGHTS.values()) - 1.0) < 1e-12
    assert paper.N_SLEEVES == len(paper.BOOK_WEIGHTS) == 3
    source = (REPO / "scripts" / "paper_trading_state.py").read_text()
    assert 'if a["key"] in SUSPENDED_SLEEVES:' in source
    assert '"suspended_sleeves": [' in source


@pytest.mark.workspace_evidence
def test_the_published_correlation_is_the_one_the_book_curves_give() -> None:
    """RHO_BAR is typed for the import-time prose; this recomputes it from the book's own curves."""
    import itertools

    import numpy as np
    import pandas as pd

    def daily(curve: object) -> pd.Series:
        days = pd.to_datetime(np.asarray(curve.ts_ms), unit="ms").normalize()  # type: ignore[attr-defined]
        values = pd.Series(np.asarray(curve.equity, dtype=float), index=days)  # type: ignore[attr-defined]
        return values.groupby(level=0).last().pct_change().dropna()

    frame = pd.concat([daily(c) for c in paper.book_sleeve_curves()], axis=1, sort=True).dropna()
    frame = frame.loc[paper.RHO_BAR_WINDOW[0] : paper.RHO_BAR_WINDOW[1]]
    corr = frame.corr().to_numpy()
    pairs = itertools.combinations(range(corr.shape[0]), 2)
    measured = float(np.mean([corr[i, j] for i, j in pairs]))
    assert abs(measured - paper.RHO_BAR) < 5e-5, measured


@pytest.mark.workspace_evidence
def test_the_published_v3_freeze_digest_is_the_archive_manifests() -> None:
    """The digest the record publishes is recomputed from the frozen archive, never trusted."""
    import hashlib

    archive = REPO / "artifacts" / "archive" / "live_record_20260923T234009Z"
    digest = hashlib.sha256((archive / "MANIFEST.json").read_bytes()).hexdigest()
    assert digest == paper.V3_FREEZE_MANIFEST_SHA256
    assert (archive / "MANIFEST.sha256").read_text().strip() == digest
