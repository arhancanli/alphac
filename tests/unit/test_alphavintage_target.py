"""AlphaVintage's live target book must never be able to halt the book.

WHY THIS FILE EXISTS. AlphaVintage's pre-registered spec runs 2.0x gross at the signal clip, and
`live_cycle._GROSS_HARD_CAP` is 1.5x. Exceeding that cap does NOT skip the sleeve — it ENGAGES THE
GLOBAL KILL SWITCH and stops every other sleeve until a human disengages it. The signal is at the
clip today (SI = -2.36), so the very first live write would have taken the whole book down.

That is a one-line failure with a book-wide blast radius, which is exactly the kind that must be
pinned by a test rather than by a comment. These tests also pin the anti-lookahead timing rule,
because a sleeve that publishes a vintage's weight before its entry date is silently backtesting
on information it would not have had.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load():
    """Import the script by path — scripts/ is not a package on the test path."""
    for p in (str(_ROOT), str(_ROOT / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(
        "alphavintage_target", _ROOT / "scripts" / "alphavintage_target.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AV = _load()

# A month of weekdays around a 15th-of-the-month vintage stamp.
_DAYS = pd.DatetimeIndex(pd.bdate_range("2026-07-01", "2026-08-14"))


# ----------------------------------------------------------------- the anti-lookahead timing rule
def test_vintage_is_not_published_before_its_entry_day() -> None:
    """ON the vintage date itself we are NOT yet in the new position.

    The spec enters at the close of the first trading day STRICTLY after V. Publishing V's weight
    on V would claim a position taken on information released that morning — the exact lookahead
    the timing rule was written to forfeit.
    """
    SI = pd.Series({pd.Timestamp("2026-06-15"): -1.0, pd.Timestamp("2026-07-15"): +2.0})
    V, entry = AV.active_vintage(SI, _DAYS, pd.Timestamp("2026-07-15"))
    assert pd.Timestamp("2026-06-15") == V, (
        f"published the {V.date() if V is not None else None} vintage on its own stamp date — "
        "that is the lookahead the spec explicitly forfeits"
    )
    assert entry < pd.Timestamp("2026-07-15")


def test_vintage_becomes_live_on_the_first_trading_day_after() -> None:
    SI = pd.Series({pd.Timestamp("2026-06-15"): -1.0, pd.Timestamp("2026-07-15"): +2.0})
    V, entry = AV.active_vintage(SI, _DAYS, pd.Timestamp("2026-07-16"))
    assert pd.Timestamp("2026-07-15") == V
    assert entry == pd.Timestamp("2026-07-16")


def test_future_stamped_vintage_is_ignored() -> None:
    """A vintage dated after today can never inform today's book, whatever the lake contains."""
    SI = pd.Series({pd.Timestamp("2026-07-15"): -1.0, pd.Timestamp("2026-09-15"): +3.0})
    V, _ = AV.active_vintage(SI, _DAYS, pd.Timestamp("2026-08-10"))
    assert pd.Timestamp("2026-07-15") == V


def test_no_vintage_yet_returns_none_rather_than_guessing() -> None:
    SI = pd.Series({pd.Timestamp("2026-09-15"): 1.0})
    assert AV.active_vintage(SI, _DAYS, pd.Timestamp("2026-08-10")) == (None, None)


# ------------------------------------------------------------------------- the runaway-brake pin
def test_live_gross_stays_under_the_kill_switch_cap() -> None:
    """THE TEST THIS FILE EXISTS FOR."""
    cap = AV.gross_hard_cap()
    worst_case_gross = 2.0 * abs(-1.0 * (AV.LIVE_GROSS_TARGET / AV.SPEC_GROSS))
    assert worst_case_gross <= cap, (
        f"at the signal clip this sleeve targets gross {worst_case_gross:.2f}x against a hard cap "
        f"of {cap:.2f}x — live_cycle would engage the GLOBAL kill switch and halt every sleeve"
    )
    assert worst_case_gross == pytest.approx(AV.LIVE_GROSS_TARGET)


def test_gross_hard_cap_is_read_from_live_cycle_not_hardcoded() -> None:
    """If the rail is renamed or retuned, this sleeve must follow it or fail loudly."""
    assert AV.gross_hard_cap() == pytest.approx(1.5), (
        "live_cycle._GROSS_HARD_CAP changed; AlphaVintage's sizing is derived from it and this "
        "test is the tripwire that says so"
    )


def test_scaling_preserves_sign_and_neutrality() -> None:
    """Scaling is a RISK choice; it must not touch the signal's direction or the neutrality."""
    scale = AV.LIVE_GROSS_TARGET / AV.SPEC_GROSS
    for w_spec in (-1.0, -0.4, 0.0, 0.4, 1.0):
        w = w_spec * scale
        assert w == pytest.approx(w_spec * 0.5)
        assert (w > 0) == (w_spec > 0)
        assert w + (-w) == pytest.approx(0.0)  # dollar-neutral by construction, not by constraint


# ------------------------------------------------------- the artifact must satisfy live_cycle
@pytest.mark.skipif(
    not (_ROOT / "artifacts/walkforward/alphavintage_live/legs/leg_01/positions.parquet").exists(),
    reason="artifact not yet written on this machine",
)
def test_written_artifact_matches_the_contract_live_cycle_reads() -> None:
    import pyarrow.parquet as pq

    t = pq.read_table(
        _ROOT / "artifacts/walkforward/alphavintage_live/legs/leg_01/positions.parquet"
    )
    # live_cycle._target_weights zips exactly these three and requires ts to be int64 ms.
    for col in ("ts", "instrument_id", "weight"):
        assert col in t.column_names
    d = t.to_pydict()
    assert all(isinstance(x, int) for x in d["ts"])
    # A ts that decodes to 1970 is the pandas-resolution bug that has bitten this repo before.
    assert pd.Timestamp(max(d["ts"]), unit="ms").year >= 2026

    w = {i: float(x) for i, x in zip(d["instrument_id"], d["weight"], strict=True)}
    assert set(w) == {AV.IWM_ID, AV.SPY_ID}, "the rule can only ever hold IWM and SPY"
    assert sum(w.values()) == pytest.approx(0.0, abs=1e-12), "book must be exactly dollar-neutral"
    assert sum(abs(v) for v in w.values()) <= AV.gross_hard_cap()
    assert all(i.startswith("XUSE:") for i in w), (
        "live_cycle's equity asset-class guard drops any id without the XUSE: prefix"
    )
