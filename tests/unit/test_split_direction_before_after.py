"""The published before/after measurement of the 2026-09-14 split-direction defect
(artifacts/audit/split_direction_before_after.json, published to the glassbox).

The size of the defect lived only in a merge message; this artifact is what the site cites. The
tests pin that the historical kernel really is the one that multiplied (loaded from git, not
re-typed), and that the artifact says what the note says: the old kernel doubled most splits and
the current one neutralizes them.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_split_direction_before_after.py"
ARTIFACT = REPO / "artifacts" / "audit" / "split_direction_before_after.json"
AAPL = "XUSE:CASH:AAPLUSD"


def _module():
    spec = importlib.util.spec_from_file_location("split_direction_before_after_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ms(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp() * 1000)


def test_the_historical_kernel_multiplied_and_the_current_one_divides() -> None:
    module = _module()
    probe = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--verify", module.PRE_FIX_COMMIT],
        capture_output=True,
    )
    if probe.returncode != 0:
        pytest.skip("shallow checkout: the pre-fix commit is not in this clone's history")
    old, _sha, source_hash = module.kernel_at(module.PRE_FIX_COMMIT)
    from alphaforge.features.library import equity_price as current

    day = module.DAY_MS
    idx = [_ms(dt.date(2020, 8, 28)), _ms(dt.date(2020, 8, 31))]
    raw = pd.DataFrame({AAPL: [499.23, 129.04]}, index=idx)
    actions = pd.DataFrame(
        {
            "instrument_id": [AAPL],
            "ex_date": [idx[1]],
            "available_at": [idx[1]],
            "action_type": ["split"],
            "ratio": [4.0],
            "cash_amount": [float("nan")],
        }
    )
    before_old = old.adjusted_close(raw, actions, tf_ms=day, include_dividends=False)[AAPL]
    before_new = current.adjusted_close(raw, actions, tf_ms=day, include_dividends=False)[AAPL]
    assert before_old.iloc[0] == pytest.approx(499.23 * 4.0)
    assert before_new.iloc[0] == pytest.approx(499.23 / 4.0)
    assert source_hash.startswith("sha256:")


def test_the_published_artifact_is_hash_bound_and_shows_the_defect() -> None:
    if not ARTIFACT.exists():
        pytest.skip("run scripts/audit_split_direction_before_after.py")
    document = json.loads(ARTIFACT.read_text())
    content_hash = document.pop("content_hash")
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    assert content_hash == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert document["author"] == "Arhan Canli"
    assert {lake["lake"] for lake in document["lakes"]} == {"data/lake", "data/lake_sharadar"}
    for lake in document["lakes"]:
        before, after = lake["pre_fix"], lake["current"]
        assert before["counts"].get("DOUBLED", 0) > 0.8 * before["determined"], lake["lake"]
        assert after["counts"].get("DOUBLED", 0) < 0.05 * after["determined"], lake["lake"]
        assert after["counts"]["NEUTRALIZED"] > 0.75 * after["determined"], lake["lake"]
        apple = lake["apple_2020"]
        assert apple["pre_fix_adjusted_close_before"] == pytest.approx(
            apple["raw_close_before"] * apple["stored_ratio"], abs=0.01
        )
        assert apple["current_adjusted_close_before"] == pytest.approx(
            apple["raw_close_before"] / apple["stored_ratio"], abs=0.01
        )
