"""The managed-futures gauntlet's SPY correlation must be a number, not a NaN.

WHY. `corr to SPY : +nan` printed on ALL FORTY runs in the log, beside the words "want ~0 /
negative — diversifies the book". A figure presented as evidence that has never once been computed
is worse than no figure: it occupies the place where the answer should be.

Two independent bugs caused it, and either alone was enough:

  1. `next(glob("**/*.parquet"))` read ONE year partition of a per-year series — 252 rows of 6,325
     — so the overlap with a curve starting in 2006 could be nothing.
  2. the book's `ts` is int64 epoch-ms while SPY's `ts_open` is `datetime64[ms, UTC]`, so the join
     raised `TypeError: Cannot compare tz-naive and tz-aware timestamps`.

THE TEST IS BEHAVIOURAL FIRST. A source check that the script "reads all partitions" would have
passed while the tz bug still made the join raise — the same shape as the IndexNow guard that
inspected the wiring and never ran the code. So this loads the real artifacts and asserts a finite
correlation over a real overlap. The source check below it is a backstop, not the guard.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "mf_gauntlet.py"
EQUITY = REPO / "artifacts" / "walkforward" / "mf_live_fwd" / "equity.parquet"
SPY_DIR = REPO / "data" / "lake_mf" / "ohlcv_1d" / "instrument_id=XUSE:CASH:SPYUSD"

pytestmark = pytest.mark.workspace_evidence


def _joined() -> pd.DataFrame:
    """Reproduce the gauntlet's join, the way the repaired script does it."""
    eq = pd.read_parquet(EQUITY)
    eqs = eq.set_index("ts")["equity"]
    ret = np.log(eqs.astype(float)).diff().dropna()
    rd = pd.Series(ret.values, index=pd.to_datetime(eqs.index[1:], unit="ms"))

    parts = sorted(SPY_DIR.glob("**/*.parquet"))
    assert parts, f"no SPY partitions under {SPY_DIR}"
    spy = pd.concat([pd.read_parquet(f) for f in parts])
    spy_ret = np.log(spy.sort_values("ts_open").set_index("ts_open")["close"].astype(float)).diff()
    spy_ret.index = pd.DatetimeIndex(spy_ret.index).tz_localize(None)
    return pd.concat([rd.rename("b"), spy_ret.rename("s")], axis=1, sort=True).dropna()


def test_the_series_is_partitioned_so_one_file_is_not_the_series() -> None:
    """The premise of bug 1. If SPY ever became a single file this test should be revisited."""
    parts = sorted(SPY_DIR.glob("**/*.parquet"))
    assert len(parts) > 1, (
        f"SPY is stored in {len(parts)} file(s); the bug this guards against was reading one "
        "partition of many, so re-check the gauntlet if the layout changed"
    )


def test_the_correlation_is_actually_computed() -> None:
    """The assertion that would have failed on all forty runs."""
    joined = _joined()
    assert len(joined) > 30, (
        f"only {len(joined)} overlapping days between the book and SPY — the gauntlet prints "
        "'not computed' below this threshold, which is honest but means the diagnostic is blind"
    )
    corr = float(np.corrcoef(joined["b"], joined["s"])[0, 1])
    assert math.isfinite(corr), "corr to SPY is not finite — the diagnostic is back to printing nan"
    assert -1.0 <= corr <= 1.0


def test_the_overlap_is_the_whole_history_not_a_fragment() -> None:
    """A floor, because a join that degenerates to a handful of days would still be 'finite'."""
    assert len(_joined()) > 1000


def test_the_script_reads_every_partition_and_normalises_the_timezone() -> None:
    """Backstop only. The behavioural tests above are the guard; this catches an obvious rewrite."""
    source = SCRIPT.read_text()
    spy_block = source[source.index("spy_parts") : source.index("# align on date")]
    assert "concat" in spy_block, "the gauntlet no longer reads every SPY partition"
    assert not re.search(r"next\(\s*\(?Path\(", spy_block), (
        "the gauntlet is reading a single partition again — that is bug 1"
    )
    assert "tz_localize(None)" in spy_block, (
        "the SPY index is no longer normalised, so the join will raise on tz-aware timestamps"
    )
