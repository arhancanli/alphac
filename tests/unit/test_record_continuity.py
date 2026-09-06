"""The forward record must be continuous, and a gap must be as loud as a configuration change.

WHY. The forward record is the only evidence that can defeat deflation — a pre-registered book
run forward is N=1, so its hurdle is 0.877 at five years against 2.44 for a backtest selected from
228 hypothesis identities. Its entire value is being ONE continuous test of ONE specification.

A configuration change is now guarded three ways. A GAP was guarded nowhere, and a gap breaks
continuity just as surely: a sleeve that quietly stops marking produces a shorter record, which
looks like a younger book rather than a broken one.

Reads the artifact produced by scripts/audit_record_continuity.py.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
ARTIFACT = REPO / "artifacts" / "engineering" / "record_continuity.json"
SCRIPT = REPO / "scripts" / "audit_record_continuity.py"
SPEC = importlib.util.spec_from_file_location("audit_record_continuity", SCRIPT)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def _audit() -> dict:
    if not ARTIFACT.exists():
        pytest.skip("no continuity artifact; run scripts/audit_record_continuity.py")
    return json.loads(ARTIFACT.read_text())


def test_no_sleeve_exceeds_the_declared_gap_rate() -> None:
    """The gate itself."""
    audit = _audit()
    threshold = audit["max_gap_rate_threshold"]
    offenders = {
        key: sleeve["gap_rate"]
        for key, sleeve in audit["sleeves"].items()
        if sleeve["gap_rate"] > threshold
    }
    assert not offenders, (
        f"these sleeves exceed the declared {threshold:.0%} gap rate: {offenders}. The forward "
        "record's value is its continuity — a sleeve that stops marking produces a record that "
        "looks younger rather than broken. Find out why the marks stopped before extending it."
    )


def test_continuity_artifact_is_authored_and_hash_bound() -> None:
    audit = _audit()
    content_hash = audit.pop("content_hash")
    canonical = json.dumps(audit, sort_keys=True, separators=(",", ":")).encode()
    assert content_hash == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert audit["author"] == "Arhan Canli"


def test_the_audit_covers_every_sleeve_in_the_published_book() -> None:
    """An audit that silently skips a sleeve reads as coverage."""
    state_path = REPO / "data" / "paper" / "state.json"
    if not state_path.exists():
        pytest.skip("no published state")
    published = {s["key"] for s in json.loads(state_path.read_text())["book"]["sleeves"]}
    audited = set(_audit()["sleeves"])
    assert published <= audited, (
        f"these sleeves are in the published book but not in the continuity audit: "
        f"{sorted(published - audited)}"
    )


def test_every_sleeve_has_a_database_to_audit() -> None:
    """A missing database yields zero marks, which would read as a total gap rather than as
    'nothing was measured'. Distinguish the two rather than letting one masquerade as the other."""
    for key, sleeve in _audit()["sleeves"].items():
        assert sleeve["database_exists"], (
            f"{key} has no trading database at {sleeve['database']} — the audit measured an "
            "absence of data, not an absence of marks, and those are different findings"
        )


def test_a_gap_is_classified_against_the_sleeve_that_owns_it() -> None:
    """A closed market and a broken loop must not look identical.

    A weekend absence is legitimate for a sleeve that does not trade weekends and a real gap for
    one that trades around the clock. Counting them the same way for all four would make the
    equity sleeves look permanently broken and hide a genuine crypto hole.
    """
    audit = _audit()
    for key, sleeve in audit["sleeves"].items():
        if sleeve["trades_24_7"]:
            assert sleeve["legitimate_absences"] == 0, (
                f"{key} trades 24/7, so no absence is legitimate for it"
            )
            assert sleeve["days_expected"] == audit["days_since_go_live"]
        else:
            for day in sleeve["legitimate_absence_days"]:
                assert dt.date.fromisoformat(day).weekday() >= 5, (
                    f"{key} counts {day} as a legitimate absence but it is a weekday"
                )


def test_systemic_gaps_are_named() -> None:
    """A day missing on EVERY sleeve is the tick failing, not a sleeve failing.

    This does not fail on their presence — a systemic gap is a fact to surface, and failing the
    suite over a historical one would only invite deleting the record of it. It fails if the
    field that surfaces them is absent.
    """
    audit = _audit()
    assert "systemic_gap_days" in audit
    assert isinstance(audit["systemic_gap_days"], list)


def test_the_threshold_is_declared_not_fitted() -> None:
    """A threshold derived from the observed gap rate passes whatever the gap rate happens to be.

    Pinned as a relationship rather than a constant: the declared threshold must not sit exactly
    at the worst observed rate, which is the signature of a bar fitted to its own data.
    """
    audit = _audit()
    threshold = audit["max_gap_rate_threshold"]
    assert 0 < threshold < 1
    assert "threshold_basis" in audit
    worst = audit["worst_gap_rate"]
    if worst is not None and worst > 0:
        assert threshold != pytest.approx(worst, abs=1e-9) or threshold in (0.20, 0.25, 0.10), (
            "the threshold equals the worst observed rate to floating precision, which is what a "
            "fitted bar looks like"
        )


def test_alpaca_midnight_rows_map_to_the_preceding_xnys_session() -> None:
    monday_close_stamp = int(
        dt.datetime(2026, 8, 11, tzinfo=dt.UTC).timestamp() * 1000
    )
    friday_close_stamp = int(
        dt.datetime(2026, 8, 8, tzinfo=dt.UTC).timestamp() * 1000
    )

    assert MOD.mark_session_date(monday_close_stamp, trades_24_7=False) == "2026-08-10"
    assert MOD.mark_session_date(friday_close_stamp, trades_24_7=False) == "2026-08-07"
    assert MOD.mark_session_date(monday_close_stamp, trades_24_7=True) == "2026-08-11"


def test_weekend_current_snapshot_does_not_manufacture_an_equity_mark() -> None:
    saturday_snapshot = int(
        dt.datetime(2026, 8, 22, 22, 17, tzinfo=dt.UTC).timestamp() * 1000
    )
    assert MOD.mark_session_date(saturday_snapshot, trades_24_7=False) is None


def test_equity_expectations_use_xnys_sessions_not_weekdays() -> None:
    days = MOD.expected_days(
        dt.date(2021, 1, 1), dt.date(2021, 1, 5), trades_24_7=False
    )
    assert days == ["2021-01-04", "2021-01-05"]  # New Year's Day is not a session.
