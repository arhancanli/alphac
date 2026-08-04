"""Regression: the health monitor's alert memory may only advance on DELIVERY.

Why this test exists (2026-08-02): `scripts/health_check.py` learned to tell a
NEW failure (PASS->FAIL since the last run) from a STANDING one, because a
sleeve once went dark for 14 days while the board was permanently red and the
new breakage was indistinguishable from the standing noise. But `main()` threw
away `send_alert()`'s return value and saved the new alert state unconditionally
— so if Resend rejected the mail or curl timed out, a NEW failure that reached
nobody was recorded as "already told them" and silently demoted to the next
run's quieter standing-red digest. That is precisely the failure class the
feature exists to prevent.

These tests pin the RUNNING path:
  (a) delivered  -> state advances, the failure is STANDING on the next run
  (b) undelivered-> state does NOT advance, the same failure is still NEW
  (c) an undeliverable red still escalates (banner + alerts_undelivered.log),
      and the bounded hold that stops an infinite re-alert loop escalates too
      (CHANNEL PRESUMED DEAD) rather than quietly giving up.
`main()` itself is driven end-to-end (checks stubbed, no network, no email) so
the assertions cover the wiring that was broken, not just the helpers.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

HC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "health_check.py"


@pytest.fixture()
def hc():
    """Fresh module per test — RESULTS/REMEDIATION are module-level globals."""
    spec = importlib.util.spec_from_file_location("health_check_delivery_gate", HC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T0 = dt.datetime(2026, 8, 2, 3, 10, tzinfo=dt.timezone.utc)


def _check(cid, status, title="check", severity="high", observed="obs", expected="exp"):
    return dict(id=cid, group="loops", title=title, status=status, severity=severity,
                observed=observed, expected=expected, evidence="")


def _prior(hc, updated_at="2026-08-01T03:10:00Z", **id_to_status):
    return dict(schema=1, updated_at=updated_at, run_count=9, undelivered_runs=0,
                checks={cid: dict(status=st, title=f"{cid} title", severity="high",
                                  observed="prior obs", since="2026-07-25T03:10:00Z",
                                  runs=7, last_seen=updated_at, missed=0)
                        for cid, st in id_to_status.items()})


def _subject(hc, prev, checks):
    tr = hc.classify_transitions(prev, checks)
    counts = dict(pass_=sum(1 for c in checks if c["status"] == "PASS"),
                  warn=sum(1 for c in checks if c["status"] == "WARN"),
                  fail=sum(1 for c in checks if c["status"] == "FAIL"))
    overall = "FAIL" if counts["fail"] else ("WARN" if counts["warn"] else "PASS")
    status = dict(schema=1, generated_at=hc.iso(T0), overall=overall, counts=counts,
                  checks=checks, remediation=[])
    subj, body = hc.build_alert(status, tr)
    return tr, subj, body


# --- (a) delivered: the state advances and the red becomes STANDING ----------

def test_delivered_alert_advances_state_and_next_run_is_standing(hc):
    prev = _prior(hc, **{"C6d-equitydb": "PASS"})
    checks = [_check("C6d-equitydb", "FAIL", title="AlphaMax DB accruing marks")]

    tr, subj, _ = _subject(hc, prev, checks)
    assert [e["id"] for e in tr["new_fails"]] == ["C6d-equitydb"]
    assert subj.startswith("AlphaForge NEW FAIL: C6d-equitydb")

    state = hc.next_alert_state(prev, checks, T0, delivered=True)
    assert state["checks"]["C6d-equitydb"]["status"] == "FAIL"
    assert state["undelivered_runs"] == 0

    tr2, subj2, _ = _subject(hc, state, checks)
    assert tr2["new_fails"] == []
    assert [e["id"] for e in tr2["standing_fails"]] == ["C6d-equitydb"]
    assert subj2.startswith("AlphaForge standing red x1")


# --- (b) undelivered: the state must NOT advance, the red stays NEW ----------

def test_undelivered_alert_does_not_advance_state_and_stays_new(hc):
    prev = _prior(hc, **{"C6d-equitydb": "PASS"})
    checks = [_check("C6d-equitydb", "FAIL", title="AlphaMax DB accruing marks")]

    state = hc.next_alert_state(prev, checks, T0, delivered=False)
    # the memory still says what the owner was last TOLD, not what we observed
    assert state["checks"]["C6d-equitydb"]["status"] == "PASS"
    assert state["checks"]["C6d-equitydb"]["since"] == "2026-07-25T03:10:00Z"
    assert state["undelivered_runs"] == 1

    tr2, subj2, body2 = _subject(hc, state, checks)
    assert [e["id"] for e in tr2["new_fails"]] == ["C6d-equitydb"]
    assert tr2["standing_fails"] == []
    assert subj2.startswith("AlphaForge NEW FAIL: C6d-equitydb")
    assert "NEW FAILURES" in body2


def test_undelivered_first_seen_red_is_not_recorded_at_all(hc):
    """No prior entry + undelivered => stay unrecorded, so the next run still
    reads it as a first-seen red (NEW). Recording it would be the same silent
    demotion by another route."""
    state = hc.next_alert_state(None, [_check("C5c-alphamax", "FAIL")], T0, delivered=False)
    assert "C5c-alphamax" not in state["checks"]
    tr, _, _ = _subject(hc, state, [_check("C5c-alphamax", "FAIL")])
    assert [e["id"] for e in tr["new_fails"]] == ["C5c-alphamax"]


def test_undelivered_run_still_advances_unchanged_checks(hc):
    """Only TRANSITIONS are withheld. Unchanged rows keep their bookkeeping so
    the streak counter and the stale-entry pruning keep working."""
    prev = _prior(hc, **{"C7b-suite": "PASS", "C6d-equitydb": "PASS"})
    checks = [_check("C7b-suite", "PASS"), _check("C6d-equitydb", "FAIL")]
    state = hc.next_alert_state(prev, checks, T0, delivered=False)
    assert state["checks"]["C7b-suite"]["status"] == "PASS"
    assert state["checks"]["C7b-suite"]["runs"] == 8          # 7 + 1, advanced
    assert state["checks"]["C7b-suite"]["last_seen"] == hc.iso(T0)
    assert state["checks"]["C6d-equitydb"]["status"] == "PASS"  # withheld
    assert state["checks"]["C6d-equitydb"]["runs"] == 7         # frozen


def test_undelivered_recovery_is_also_withheld(hc):
    """A recovery nobody read is not a recovery: the owner's last knowledge is
    still the red, so the memory stays FAIL and the recovery is re-reported."""
    prev = _prior(hc, **{"C5c-alphamax": "FAIL"})
    checks = [_check("C5c-alphamax", "PASS")]
    state = hc.next_alert_state(prev, checks, T0, delivered=False)
    assert state["checks"]["C5c-alphamax"]["status"] == "FAIL"
    tr, _, _ = _subject(hc, state, checks)
    assert [e["id"] for e in tr["recovered"]] == ["C5c-alphamax"]


def test_hold_is_bounded_then_advances_with_a_stamp(hc):
    """A permanently dead channel must not pin the board as NEW forever: the
    same news gets MAX_UNDELIVERED_HOLDS attempts, then the state advances."""
    checks = [_check("C6d-equitydb", "FAIL")]
    state = _prior(hc, **{"C6d-equitydb": "PASS"})
    new_count = 0
    for i in range(hc.MAX_UNDELIVERED_HOLDS):
        tr = hc.classify_transitions(state, checks)
        new_count += len(tr["new_fails"])
        state = hc.next_alert_state(state, checks, T0 + dt.timedelta(days=i), delivered=False)
    assert new_count == hc.MAX_UNDELIVERED_HOLDS      # re-alerted, bounded
    assert state["checks"]["C6d-equitydb"]["status"] == "FAIL"   # forced advance
    assert state["undelivered_forced_advance_at"] == hc.iso(
        T0 + dt.timedelta(days=hc.MAX_UNDELIVERED_HOLDS - 1))
    assert state["undelivered_runs"] == 0
    # from here on it is standing — the loop terminates
    tr = hc.classify_transitions(state, checks)
    assert tr["new_fails"] == [] and len(tr["standing_fails"]) == 1


def test_successful_delivery_resets_the_hold_counter(hc):
    checks = [_check("C6d-equitydb", "FAIL")]
    prev = _prior(hc, **{"C6d-equitydb": "PASS"})
    s1 = hc.next_alert_state(prev, checks, T0, delivered=False)
    assert s1["undelivered_runs"] == 1
    s2 = hc.next_alert_state(s1, checks, T0 + dt.timedelta(days=1), delivered=True)
    assert s2["undelivered_runs"] == 0
    assert s2["checks"]["C6d-equitydb"]["status"] == "FAIL"


def test_undelivered_run_with_nothing_to_hold_resets_the_counter(hc):
    prev = _prior(hc, **{"C7b-suite": "PASS"})
    prev["undelivered_runs"] = 2
    state = hc.next_alert_state(prev, [_check("C7b-suite", "PASS")], T0, delivered=False)
    assert state["undelivered_runs"] == 0


# --- main() wiring: send_alert's return value gates the save ------------------

def _drive_main(hc, monkeypatch, tmp_path, results, delivered, prev_state=None,
                argv=("health_check.py", "--lite", "--no-heal")):
    """Run main() with every board check stubbed out (no network, no pytest, no
    email) so the assertions isolate the alert-state wiring."""
    state_path = str(tmp_path / "alert_state.json")
    real_load, real_save = hc.load_alert_state, hc.save_alert_state
    if prev_state is not None:
        real_save(prev_state, state_path)
    saved: list = []
    monkeypatch.setattr(hc, "HEALTH", str(tmp_path))
    monkeypatch.setattr(hc, "HIST", str(tmp_path / "history"))
    monkeypatch.setattr(hc, "UNDELIVERED_LOG", str(tmp_path / "alerts_undelivered.log"))
    monkeypatch.setattr(hc, "sh", lambda cmd, timeout=120, env=None: (0, "abc1234"))
    monkeypatch.setattr(hc, "load_alert_state", lambda path=state_path: real_load(state_path))
    monkeypatch.setattr(hc, "save_alert_state",
                        lambda state, path=state_path: (saved.append(state),
                                                        real_save(state, state_path))[0])
    for name in ("check_sites", "check_data", "check_loops", "check_honesty",
                 "check_publisher", "check_alert_channel"):
        monkeypatch.setattr(hc, name, lambda *a, **k: None)
    monkeypatch.setattr(hc, "send_alert",
                        lambda subj, body, status, enabled: delivered)
    hc.RESULTS[:] = [dict(r) for r in results]
    monkeypatch.setattr(hc.sys, "argv", list(argv))
    with pytest.raises(SystemExit):
        hc.main()
    assert len(saved) == 1, "main() must persist exactly one alert state"
    return saved[0], state_path, real_load


def test_main_advances_state_when_delivery_succeeds(hc, monkeypatch, tmp_path):
    prev = _prior(hc, **{"C6d-equitydb": "PASS"})
    results = [_check("C6d-equitydb", "FAIL", title="AlphaMax DB accruing marks")]
    state, path, load = _drive_main(hc, monkeypatch, tmp_path, results, delivered=True,
                                    prev_state=prev)
    assert state["checks"]["C6d-equitydb"]["status"] == "FAIL"
    assert load(path)["checks"]["C6d-equitydb"]["status"] == "FAIL"
    tr = hc.classify_transitions(load(path), results)
    assert [e["id"] for e in tr["standing_fails"]] == ["C6d-equitydb"]


def test_main_does_not_advance_state_when_delivery_fails(hc, monkeypatch, tmp_path):
    """THE BUG: main() used to ignore send_alert()'s return value, so a NEW red
    that never reached an inbox became tomorrow's quiet standing-red line."""
    prev = _prior(hc, **{"C6d-equitydb": "PASS"})
    results = [_check("C6d-equitydb", "FAIL", title="AlphaMax DB accruing marks")]
    state, path, load = _drive_main(hc, monkeypatch, tmp_path, results, delivered=False,
                                    prev_state=prev)
    assert state["checks"]["C6d-equitydb"]["status"] == "PASS"
    persisted = load(path)
    assert persisted["checks"]["C6d-equitydb"]["status"] == "PASS"
    tr = hc.classify_transitions(persisted, results)
    assert [e["id"] for e in tr["new_fails"]] == ["C6d-equitydb"]
    assert tr["standing_fails"] == []
    _, subj, _ = _subject(hc, persisted, results)
    assert subj.startswith("AlphaForge NEW FAIL: C6d-equitydb")


def test_main_dry_run_never_touches_state(hc, monkeypatch, tmp_path):
    prev = _prior(hc, **{"C6d-equitydb": "PASS"})
    results = [_check("C6d-equitydb", "FAIL")]
    state_path = str(tmp_path / "alert_state.json")
    real_save = hc.save_alert_state
    real_save(prev, state_path)
    with pytest.raises(AssertionError):  # _drive_main asserts exactly one save
        _drive_main(hc, monkeypatch, tmp_path, results, delivered=True, prev_state=prev,
                    argv=("health_check.py", "--lite", "--dry-run"))
    assert hc.load_alert_state(state_path)["checks"]["C6d-equitydb"]["status"] == "PASS"


# --- (c) an undeliverable red always escalates -------------------------------

def test_undeliverable_red_escalates_to_banner_and_log(hc, tmp_path, monkeypatch):
    """No Resend key configured: the red must still reach the owner through the
    local banner and leave the full alert body on disk."""
    calls: list = []
    monkeypatch.setattr(hc, "RESEND_ENV", str(tmp_path / "missing.env"))
    monkeypatch.setattr(hc, "HEALTH", str(tmp_path))
    monkeypatch.setattr(hc, "UNDELIVERED_LOG", str(tmp_path / "alerts_undelivered.log"))
    monkeypatch.setattr(hc, "sh",
                        lambda cmd, timeout=120, env=None: (calls.append(cmd), (0, ""))[1])
    status = dict(schema=1, overall="FAIL", counts=dict(pass_=0, warn=0, fail=1),
                  checks=[_check("C6d-equitydb", "FAIL")], remediation=[])

    sent = hc.send_alert("AlphaForge NEW FAIL: C6d-equitydb (x)", "body text", status,
                         enabled=True)

    assert sent is False
    assert any("display notification" in c for c in calls)
    logged = (tmp_path / "alerts_undelivered.log").read_text()
    assert "UNDELIVERED" in logged and "C6d-equitydb" in logged and "body text" in logged


def test_resend_rejection_is_not_counted_as_delivered(hc, tmp_path, monkeypatch):
    """A key that sends is not mail that arrives: a non-2xx from Resend must
    return False so the caller withholds the state advance."""
    env = tmp_path / "resend.env"
    env.write_text("RESEND_API_KEY=re_abc123\nRESEND_TO=owner@example.com\n")
    monkeypatch.setattr(hc, "RESEND_ENV", str(env))
    monkeypatch.setattr(hc, "HEALTH", str(tmp_path))
    monkeypatch.setattr(hc, "UNDELIVERED_LOG", str(tmp_path / "alerts_undelivered.log"))
    monkeypatch.setattr(hc, "sh", lambda cmd, timeout=120, env=None: (0, ""))

    class _P:
        stdout = "422"

    monkeypatch.setattr(hc.subprocess, "run", lambda *a, **k: _P())
    status = dict(schema=1, overall="FAIL", counts=dict(pass_=0, warn=0, fail=1),
                  checks=[_check("C6d-equitydb", "FAIL")], remediation=[])
    assert hc.send_alert("subj", "body", status, enabled=True) is False
    assert "UNDELIVERED" in (tmp_path / "alerts_undelivered.log").read_text()


def test_forced_advance_escalates_channel_presumed_dead(hc, monkeypatch, tmp_path):
    """The bounded hold must not fail quiet: when the monitor gives up holding,
    it says so on disk next to the alert bodies it could not deliver."""
    prev = _prior(hc, **{"C6d-equitydb": "PASS"})
    prev["undelivered_runs"] = hc.MAX_UNDELIVERED_HOLDS - 1
    results = [_check("C6d-equitydb", "FAIL")]
    state, _path, _load = _drive_main(hc, monkeypatch, tmp_path, results, delivered=False,
                                     prev_state=prev)
    assert state["checks"]["C6d-equitydb"]["status"] == "FAIL"   # advanced at last
    assert state["undelivered_forced_advance_at"] == hc.iso(hc.NOW)
    logged = (tmp_path / "alerts_undelivered.log").read_text()
    assert "CHANNEL PRESUMED DEAD" in logged
    assert "C6d-equitydb" in logged
