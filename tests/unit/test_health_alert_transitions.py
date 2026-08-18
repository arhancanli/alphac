"""Regression: the health monitor's alert must distinguish NEW from STANDING.

Why this test exists (2026-08-01): `scripts/health_check.py` detected an
AlphaMax outage correctly for 14 consecutive days and the owner never noticed,
because the alert emailed an identical red digest every run — a board that had
been red for two weeks was indistinguishable from one that broke overnight.
The fix is a per-run memory (var/health/alert_state.json) plus a transition
classifier. These tests pin the RUNNING path: the same functions main() calls
(`classify_transitions` -> `build_alert` -> `next_alert_state`), driven by
synthetic prior/current state pairs. No network, no email, no real state file.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

HC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "health_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("health_check_under_test", HC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def hc():
    return _load_module()


# --- helpers ----------------------------------------------------------------

def _check(cid, status, title="check", severity="high", observed="obs", expected="exp"):
    return {"id": cid, "group": "loops", "title": title, "status": status, "severity": severity,
                "observed": observed, "expected": expected, "evidence": ""}


def _prior(updated_at="2026-07-31T03:10:00Z", **id_to_status):
    """Synthetic previous-run state file contents."""
    return {
        "schema": 1, "updated_at": updated_at, "run_count": 9,
        "checks": {cid: {"status": st, "title": f"{cid} title", "severity": "high",
                          "observed": "prior obs", "since": "2026-07-18T03:10:00Z",
                          "runs": 13, "last_seen": updated_at, "missed": 0}
                for cid, st in id_to_status.items()}}


def _status(hc, checks):
    counts = {"pass_": sum(1 for c in checks if c["status"] == "PASS"),
                  "warn": sum(1 for c in checks if c["status"] == "WARN"),
                  "fail": sum(1 for c in checks if c["status"] == "FAIL")}
    overall = "FAIL" if counts["fail"] else ("WARN" if counts["warn"] else "PASS")
    return {"schema": 1, "generated_at": "2026-08-01T03:10:00Z", "overall": overall,
                "counts": counts, "checks": checks, "remediation": []}


def _alert(hc, prev, checks):
    tr = hc.classify_transitions(prev, checks)
    subj, body = hc.build_alert(_status(hc, checks), tr)
    return tr, subj, body


# --- (a) PASS -> FAIL is NEW and leads the subject ---------------------------

def test_pass_to_fail_is_new_and_leads_subject(hc):
    prev = _prior(**{"C6d-equitydb": "PASS", "C7b-suite": "PASS"})
    checks = [_check("C6d-equitydb", "FAIL", title="AlphaMax DB accruing marks",
                     observed="27 rows, latest 375.1h", expected="<=30h"),
              _check("C7b-suite", "PASS", title="Full pytest suite")]
    tr, subj, body = _alert(hc, prev, checks)

    assert [e["id"] for e in tr["new_fails"]] == ["C6d-equitydb"]
    assert tr["standing_fails"] == []
    assert subj.startswith("AlphaForge NEW FAIL: C6d-equitydb")
    assert "AlphaMax DB accruing marks" in subj
    assert "NEW FAILURES" in body
    assert "375.1h" in body


def test_unknown_check_first_seen_red_counts_as_new(hc):
    """No prior record (new check, or wiped state) must read as NEW, not standing:
    the safe direction is louder, never quieter."""
    tr, subj, _ = _alert(hc, hc.load_alert_state("/nonexistent/alert_state.json"),
                         [_check("C5c-alphamax", "FAIL")])
    assert [e["id"] for e in tr["new_fails"]] == ["C5c-alphamax"]
    assert subj.startswith("AlphaForge NEW FAIL: C5c-alphamax")


# --- (b) FAIL -> FAIL is STANDING, still reported, never leads ---------------

def test_fail_to_fail_is_standing_and_does_not_lead(hc):
    prev = _prior(**{"C7b-suite": "FAIL", "C5c-alphamax": "FAIL"})
    checks = [_check("C7b-suite", "FAIL", title="Full pytest suite", observed="exit=124"),
              _check("C5c-alphamax", "FAIL", title="alphamax daily fired", observed="306.1h")]
    tr, subj, body = _alert(hc, prev, checks)

    assert tr["new_fails"] == []
    assert sorted(e["id"] for e in tr["standing_fails"]) == ["C5c-alphamax", "C7b-suite"]
    # quieter digest: does NOT claim a new breakage ...
    assert "NEW FAIL" not in subj
    assert subj.startswith("AlphaForge standing red x2")
    # ... but a red is NEVER silently suppressed: both ids still reported, with age
    assert "STANDING red (2)" in body
    assert "C7b-suite" in body and "C5c-alphamax" in body
    assert "red since 2026-07-18T03:10:00Z" in body


def test_new_fail_leads_and_standing_is_demoted_below_it(hc):
    prev = _prior(**{"C7b-suite": "FAIL", "C5c-alphamax": "FAIL", "C6d-equitydb": "PASS"})
    checks = [_check("C7b-suite", "FAIL", title="Full pytest suite"),
              _check("C5c-alphamax", "FAIL", title="alphamax daily fired"),
              _check("C6d-equitydb", "FAIL", title="AlphaMax stopped trading")]
    tr, subj, body = _alert(hc, prev, checks)

    assert [e["id"] for e in tr["new_fails"]] == ["C6d-equitydb"]
    assert len(tr["standing_fails"]) == 2
    assert subj.startswith("AlphaForge NEW FAIL: C6d-equitydb (AlphaMax stopped trading)")
    assert "2 standing" in subj
    # the standing ids must not hijack the lead
    assert "C7b-suite" not in subj and "C5c-alphamax" not in subj
    # ordering in the body: new section strictly above the standing section
    assert body.index("NEW FAILURES") < body.index("STANDING red")
    assert body.index("C6d-equitydb") < body.index("STANDING red")


# --- (c) FAIL -> PASS emits a recovery line ---------------------------------

def test_fail_to_pass_emits_recovery(hc):
    prev = _prior(**{"C5c-alphamax": "FAIL"})
    checks = [_check("C5c-alphamax", "PASS", title="alphamax daily fired", observed="2.0h")]
    tr, subj, body = _alert(hc, prev, checks)

    assert [e["id"] for e in tr["recovered"]] == ["C5c-alphamax"]
    assert subj.startswith("AlphaForge RECOVERED: C5c-alphamax")
    assert "all green" in subj
    assert "RECOVERED since last run:" in body
    assert "C5c-alphamax" in body and "had been red since 2026-07-18T03:10:00Z" in body


def test_recovery_alongside_standing_red_still_reports_the_red(hc):
    prev = _prior(**{"C5c-alphamax": "FAIL", "C7b-suite": "FAIL"})
    checks = [_check("C5c-alphamax", "PASS", title="alphamax daily fired"),
              _check("C7b-suite", "FAIL", title="Full pytest suite")]
    tr, subj, body = _alert(hc, prev, checks)

    assert [e["id"] for e in tr["recovered"]] == ["C5c-alphamax"]
    assert [e["id"] for e in tr["standing_fails"]] == ["C7b-suite"]
    assert "1 standing red" in subj
    assert "STANDING red (1)" in body


# --- state persistence semantics --------------------------------------------

def test_state_roundtrip_tracks_since_and_streak(hc, tmp_path):
    p = tmp_path / "alert_state.json"
    t0 = dt.datetime(2026, 8, 1, 3, 10, tzinfo=dt.UTC)
    checks = [_check("C6d-equitydb", "FAIL")]

    s1 = hc.next_alert_state(hc.load_alert_state(str(p)), checks, t0)
    hc.save_alert_state(s1, str(p))
    loaded = hc.load_alert_state(str(p))
    assert loaded["checks"]["C6d-equitydb"]["status"] == "FAIL"
    assert loaded["checks"]["C6d-equitydb"]["since"] == hc.iso(t0)
    assert loaded["checks"]["C6d-equitydb"]["runs"] == 1

    # second run, still failing: `since` is anchored, the streak grows, and the
    # transition classifier now calls it STANDING rather than NEW
    t1 = t0 + dt.timedelta(days=1)
    s2 = hc.next_alert_state(loaded, checks, t1)
    hc.save_alert_state(s2, str(p))
    again = hc.load_alert_state(str(p))
    assert again["checks"]["C6d-equitydb"]["since"] == hc.iso(t0)
    assert again["checks"]["C6d-equitydb"]["runs"] == 2
    tr = hc.classify_transitions(again, checks)
    assert tr["new_fails"] == [] and len(tr["standing_fails"]) == 1

    # ... and a subsequent recovery re-anchors `since`
    s3 = hc.next_alert_state(again, [_check("C6d-equitydb", "PASS")], t1 + dt.timedelta(days=1))
    assert s3["checks"]["C6d-equitydb"]["since"] == hc.iso(t1 + dt.timedelta(days=1))
    assert json.loads(json.dumps(s3)) == s3  # JSON-serializable


def test_corrupt_state_file_degrades_loud_not_quiet(hc, tmp_path):
    p = tmp_path / "alert_state.json"
    p.write_text("{not json at all")
    prev = hc.load_alert_state(str(p))
    assert prev["checks"] == {}
    tr = hc.classify_transitions(prev, [_check("C7b-suite", "FAIL")])
    assert len(tr["new_fails"]) == 1  # unreadable memory => treat as new, not standing


def test_unobserved_red_is_not_claimed_as_recovered(hc):
    """A --lite run skips the pytest checks; their absence must not be read as
    a fix (that would be a silent downgrade of a red)."""
    prev = _prior(**{"C7b-suite": "FAIL"})
    checks = [_check("C3-landing-apex", "PASS")]
    tr, subj, body = _alert(hc, prev, checks)
    assert tr["recovered"] == []
    assert [e["id"] for e in tr["unobserved_fails"]] == ["C7b-suite"]
    assert "not re-checked" in subj
    assert "RED BUT NOT RE-CHECKED THIS RUN" in body


def test_unobserved_entry_is_dropped_after_max_missed_runs(hc):
    prev = _prior(**{"C3-route-performance": "FAIL"})
    t = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    state = prev
    for i in range(hc.MAX_MISSED_RUNS):
        state = hc.next_alert_state(state, [_check("C3-landing-apex", "PASS")],
                                    t + dt.timedelta(days=i))
    assert "C3-route-performance" not in state["checks"]


def test_selftest_injection_is_not_remembered(hc):
    """--selftest-fail proves the alert path; it must not leave a phantom red
    that the next real run reports as 'not re-checked'."""
    t = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    state = hc.next_alert_state(None, [_check("SELFTEST", "FAIL"),
                                       _check("C7b-suite", "PASS")], t)
    assert "SELFTEST" not in state["checks"]
    assert state["checks"]["C7b-suite"]["status"] == "PASS"


def test_all_green_stays_quiet(hc):
    prev = _prior(**{"C7b-suite": "PASS"})
    _tr, subj, body = _alert(hc, prev, [_check("C7b-suite", "PASS")])
    assert subj.startswith("AlphaForge OK —")
    assert "NEW FAIL" not in subj and "STANDING" not in body


# --- sender configuration ----------------------------------------------------

def test_sender_is_configurable_and_sandbox_is_flagged(hc, tmp_path):
    env_file = tmp_path / "resend.env"
    env_file.write_text("# comment line\nRESEND_API_KEY=re_abc123\n"
                        "RESEND_TO=owner@example.com\nRESEND_FROM=alerts@verified.example\n")
    env = hc.read_env_file(str(env_file))
    assert env["RESEND_TO"] == "owner@example.com"
    assert hc.sender_address(env) == "alerts@verified.example"
    assert hc.is_sandbox_sender(hc.sender_address(env)) is False

    # missing / blank RESEND_FROM falls back to the sandbox sender, which is
    # exactly the spam-filed case the A-sender check must WARN about
    assert hc.sender_address({}) == hc.DEFAULT_RESEND_FROM
    assert hc.sender_address({"RESEND_FROM": "  "}) == hc.DEFAULT_RESEND_FROM
    assert hc.is_sandbox_sender(hc.DEFAULT_RESEND_FROM) is True
    assert hc.is_sandbox_sender("onboarding@RESEND.DEV") is True


def test_undeliverable_red_escalates_to_notification_and_log(hc, tmp_path, monkeypatch):
    """No Resend key: a red must still reach the owner via the local banner and
    leave a durable record — an alert that cannot be sent is never dropped."""
    calls = []
    monkeypatch.setattr(hc, "RESEND_ENV", str(tmp_path / "missing.env"))
    monkeypatch.setattr(hc, "HEALTH", str(tmp_path))
    monkeypatch.setattr(hc, "UNDELIVERED_LOG", str(tmp_path / "alerts_undelivered.log"))
    monkeypatch.setattr(
        hc,
        "sh",
        lambda cmd, timeout=120, env=None: (calls.append(cmd), (0, ""))[1],
    )

    status = _status(hc, [_check("C6d-equitydb", "FAIL")])
    sent = hc.send_alert("AlphaForge NEW FAIL: C6d-equitydb (x)", "body text", status, enabled=True)

    assert sent is False
    assert any("display notification" in c for c in calls)
    logged = (tmp_path / "alerts_undelivered.log").read_text()
    assert "UNDELIVERED" in logged and "C6d-equitydb" in logged and "body text" in logged
