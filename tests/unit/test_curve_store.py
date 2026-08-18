"""Tests for the canonical curve store — and the tripwire that stops the defect recurring.

The last test in this file is the important one. Three validated candidates persisted a scalar
verdict and threw their return series away, which is why `infl_surprise_size` passed all four of
its pre-registered gates and STILL cannot be measured against the real book. A fix without a test
is how a defect comes back: this repo already had one deploy-gate bug recur four times in a single
day because each fix was narrower than the work being done. So the rule is enforced by a test that
reads the probe scripts, not by remembering.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alphaforge.analytics.curve_store import (
    CurveFormatError,
    read_curve,
    write_curve,
)

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"


def _returns(n: int = 300, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.Series(rng.normal(0.0004, 0.008, n), index=idx)


def test_roundtrip_is_log1p_of_the_input(tmp_path: Path) -> None:
    """write(simple returns) -> read() must give exactly log1p(simple returns).

    This is the contract the module's docstring states. Asserting it here means the sign/compounding
    convention can never drift silently, which is how a candidate's Sharpe would change sign
    between the probe that measured it and the book that consumes it.
    """
    r = _returns()
    path = write_curve(r, tmp_path)
    got = read_curve(path)
    want = np.log1p(r).iloc[1:]  # first bar is the base of the curve, so it has no return
    # check_index_type=False: the round trip normalises to ms resolution while the source index is
    # pandas 3's default us. Index VALUES are still compared exactly — only the dtype label differs.
    pd.testing.assert_series_equal(
        got, want, check_names=False, check_index_type=False, atol=1e-12, rtol=0
    )


def test_written_schema_is_byte_compatible_with_a_walkforward_artifact(tmp_path: Path) -> None:
    """A candidate curve and a sleeve curve must be interchangeable, or book math needs a branch."""
    import pyarrow.parquet as pq

    reference = _REPO / "artifacts/walkforward/crypto_carry_wk/equity.parquet"
    if not reference.exists():
        pytest.skip("reference walk-forward artifact not present")
    ours = pq.read_table(write_curve(_returns(), tmp_path)).schema
    theirs = pq.read_table(reference).schema
    assert [f.name for f in ours] == [f.name for f in theirs] == ["ts", "equity"]
    assert [str(f.type) for f in ours] == [str(f.type) for f in theirs]


def test_reads_a_real_sleeve_curve_identically_to_the_analysis_scripts() -> None:
    """read_curve must match scripts/analyze_sleeve_scaling.py::daily_logret on real data."""
    reference = _REPO / "artifacts/walkforward/crypto_carry_wk/equity.parquet"
    if not reference.exists():
        pytest.skip("reference walk-forward artifact not present")
    frame = pd.read_parquet(reference)
    series = pd.Series(
        frame["equity"].astype(float).to_numpy(), index=pd.to_datetime(frame["ts"], unit="ms")
    ).sort_index()
    series = series[~series.index.duplicated(keep="last")]
    want = np.log(series.resample("1D").last().dropna()).diff().dropna()
    pd.testing.assert_series_equal(read_curve(reference), want, check_names=False)


def test_hourly_curve_collapses_to_daily(tmp_path: Path) -> None:
    idx = pd.date_range("2024-01-01", periods=24 * 10, freq="h")
    r = pd.Series(np.full(len(idx), 0.0001), index=idx)
    assert len(read_curve(write_curve(r, tmp_path))) == 9  # 10 daily closes -> 9 diffs


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda s: s.reset_index(drop=True), "DatetimeIndex"),
        (lambda s: s.mask(s.index == s.index[3]), "NaN"),
        (lambda s: pd.concat([s, s.iloc[[0]]]).sort_index(), "duplicate"),
        (lambda s: s.iloc[::-1], "ascending"),
        (lambda s: s.mask(s.index == s.index[2], -1.5).fillna(-1.5), "-100%"),
        (lambda s: s.iloc[0:0], "empty"),
    ],
)
def test_rejects_series_that_would_corrupt_book_arithmetic(mutate, match, tmp_path: Path) -> None:
    with pytest.raises(CurveFormatError, match=match):
        write_curve(mutate(_returns()), tmp_path)


# ---------------------------------------------------------------------------------------
# THE TRIPWIRE. This is the test that has to exist.
# ---------------------------------------------------------------------------------------
_EXEMPT = re.compile(r"#\s*CURVE-EXEMPT:\s*\S+")

#: KNOWN DEBT, frozen 2026-08-07. Fourteen of this repo's 41 probes recorded a verdict and threw
#: the return stream away. Three were wired to `write_curve` the day the defect was found — the
#: two that are about to run (`cpi_surprise_size`, `macro_vintage_family`) and `lowvol720_reopen`
#: (exempt: its curve comes from the walk-forward runner). The rest are listed here rather than
#: silently skipped, because a defect you cannot count is a defect you will not fix.
#:
#: THIS SET MAY ONLY SHRINK. The test below fails if a NEW probe joins it, and fails if this list
#: names a probe that has since been fixed (delete the entry when you fix one). Every name here is
#: a candidate whose portfolio contribution cannot be computed without re-running it.
_KNOWN_CURVELESS_PROBES = frozenset({
    "probe_alphamax_smallaccount.py",
    "probe_bybit_carry.py",
    "probe_carry_gauntlet.py",
    "probe_cef_discount.py",
    "probe_econtrend.py",
    "probe_intraday_mom.py",
    "probe_multivenue_funding.py",
    "probe_returns_leverage.py",
    "probe_seasonality.py",
    "probe_short_interest.py",
    "probe_tom_diversifier.py",
})


def _curveless_probes() -> set[str]:
    out = set()
    for script in sorted(_SCRIPTS.glob("probe_*.py")):
        src = script.read_text(encoding="utf-8")
        if "result.json" not in src:
            continue
        if _EXEMPT.search(src) or "write_curve" in src:
            continue
        out.add(script.name)
    return out


def test_no_new_probe_may_record_a_verdict_without_its_curve() -> None:
    """The ratchet: known debt may shrink, never grow.

    Rationale, stated so a future reader does not weaken this test to make it pass: a verdict
    is neither reproducible nor composable. `crypto_lowvol_720` was killed on a number that
    turned out to be the wrong criterion, and re-deciding it required re-running the entire
    walk-forward because the curve was gone. `infl_surprise_size` passed every gate and remains
    un-deployable for the same reason. Persisting the curve costs one line and one file.
    """
    current = _curveless_probes()
    new = current - _KNOWN_CURVELESS_PROBES
    assert not new, (
        "NEW probe(s) record a verdict but persist no curve: " + ", ".join(sorted(new)) + "\n"
        "Call alphaforge.analytics.curve_store.write_curve(returns, OUT) next to the result.json "
        "write, or add an explicit '# CURVE-EXEMPT: <reason>'. Do NOT add the name to "
        "_KNOWN_CURVELESS_PROBES — that list is frozen debt and may only shrink."
    )


def test_the_known_debt_list_is_honest() -> None:
    """A name that has been fixed must leave the list, so the count always means something."""
    stale = _KNOWN_CURVELESS_PROBES - _curveless_probes()
    assert not stale, (
        "these probes are listed as debt but have been fixed: " + ", ".join(sorted(stale)) + "\n"
        "Delete them from _KNOWN_CURVELESS_PROBES so the remaining count stays truthful."
    )


def test_probes_wired_today_actually_persist_curves() -> None:
    """Pins the three fixed on 2026-08-07 so a refactor cannot quietly undo them."""
    for name in ("probe_cpi_surprise_size.py", "probe_macro_vintage_family.py"):
        src = (_SCRIPTS / name).read_text(encoding="utf-8")
        assert "write_curve(" in src, f"{name} no longer persists its curve"
    src = (_SCRIPTS / "probe_lowvol720_reopen.py").read_text(encoding="utf-8")
    assert _EXEMPT.search(src), "probe_lowvol720_reopen.py lost its documented exemption"
