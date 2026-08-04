#!/usr/bin/env python3
"""Canli Capital / AlphaForge — daily health monitor.

Runs the full check board (tests, live sites, data freshness, engine loops,
honesty/consistency, publisher), performs ONLY the narrow allowlist of safe
self-heals, writes an atomic status.json + human log + history snapshot, and
alerts via Resend (osascript + log fallback). Stdlib only, so it never depends
on the uv env to RUN (it shells out to `uv run pytest` for the test checks).

ALERTING IS TRANSITION-AWARE (2026-08-01). The monitor used to email an
identical red digest on EVERY run with no memory, so a board that had been red
for weeks looked exactly like a board that broke five minutes ago — which is
how a 14-day AlphaMax outage went unnoticed despite the check FAILing correctly
the whole time. Each run now diffs against the previous run's per-check status
(var/health/alert_state.json) and the subject LEADS with what is NEW. A
standing red is still reported on every run (never suppressed, never
downgraded) — just visibly de-emphasized below the new breakage. FAIL->PASS
transitions are reported too, so self-heals are visible.

THE MEMORY ADVANCES ON DELIVERY, NOT ON ATTEMPT (2026-08-02). alert_state.json
records what the owner HAS BEEN TOLD, so it may only advance when the mail was
actually accepted. Advancing it on a failed send (Resend 4xx/5xx, curl timeout,
no channel configured) would demote a NEW failure nobody ever read into
tomorrow's quieter "standing red" digest — exactly the silent-outage class this
feature exists to prevent. So when send_alert() reports undelivered, every check
whose status CHANGED keeps its previous entry and the next run re-reports it as
NEW (see next_alert_state(delivered=False)).

Bounded, not infinite: a permanently dead channel would otherwise pin the board
as NEW forever. The same undelivered news is held for at most
MAX_UNDELIVERED_HOLDS consecutive runs (3 delivery attempts); on the last one
the state advances anyway, stamps `undelivered_forced_advance_at`, and writes an
explicit CHANNEL PRESUMED DEAD record to var/health/alerts_undelivered.log next
to the alert bodies — the red is escalated, never swallowed. A run with nothing
withheld (or a successful send) resets the counter.

HARD RULES (enforced in code, not just intent):
  - golden master runs FIRST and in isolation; a red there hard-gates the run
    (no self-heal, no publish, no deploy).
  - self-heal is a closed allowlist: re-run live_publish.sh, re-run
    paper_trading_state.py, launchctl kickstart a missed job. <=1 attempt each.
  - NEVER edits a published number, NEVER writes a DB/ledger, NEVER touches
    engine/strategy/golden-master code, NEVER removes var/KILL.
  - after any self-heal, an engine-untouched audit + golden re-run gate the run.
  - a red is never suppressed or downgraded; an undeliverable alert escalates.

Usage: health_check.py [--dry-run] [--no-heal] [--no-alert] [--lite]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
AF = os.path.join(HOME, "alphaforge")
HEALTH = os.path.join(AF, "var", "health")
HIST = os.path.join(HEALTH, "history")
STATE_JSON = os.path.join(AF, "data", "paper", "state.json")
CRYPTO_DB = os.path.join(AF, "var", "trading_crypto_perp.sqlite")  # the ONLY live crypto DB
MF_DB = os.path.join(AF, "var", "trading_managed_futures.sqlite")  # AlphaTrend realized curve
EQUITY_DB = os.path.join(AF, "var", "trading_equity.sqlite")       # AlphaMax realized curve
KILL = os.path.join(AF, "var", "KILL")
RESEND_ENV = os.path.join(HOME, ".config", "alphaforge", "resend.env")

# --- alert memory ------------------------------------------------------------
# Previous run's per-check status. Small, atomic, and the ONLY thing that lets
# the alert say "this is new" instead of shouting the same red every day.
ALERT_STATE = os.path.join(HEALTH, "alert_state.json")
ALERT_STATE_SCHEMA = 1
# A check id that stops appearing (e.g. --lite skips the pytest checks, and the
# per-route site rows are only emitted when they fail) is NOT evidence of
# recovery, so it is carried forward unchanged rather than claimed as fixed.
# After this many consecutive unobserved runs the stale entry is dropped.
MAX_MISSED_RUNS = 3
# --selftest-fail injects a fake red to prove the alert path; it must never be
# remembered, or the next real run would report a phantom "red not re-checked".
SYNTHETIC_IDS = ("SELFTEST",)
# Undeliverable reds land here (plus the osascript banner) so a red is never
# silently lost when Resend is down or unconfigured.
UNDELIVERED_LOG = os.path.join(HEALTH, "alerts_undelivered.log")
# How many consecutive runs may withhold the SAME undelivered news before the
# state advances anyway. Bounds the re-alert loop for a permanently dead
# channel: the news gets MAX_UNDELIVERED_HOLDS delivery attempts, then the run
# force-advances and records CHANNEL PRESUMED DEAD in UNDELIVERED_LOG.
MAX_UNDELIVERED_HOLDS = 3

# Resend sender. OWNER ACTION: `onboarding@resend.dev` is Resend's shared
# sandbox sender — Gmail routinely spam-files or drops it, which is a second
# way an alert can "fire" and still never reach a human. Point RESEND_FROM in
# ~/.config/alphaforge/resend.env at an address on a domain YOU have verified
# in the Resend dashboard (e.g. alerts@<a-domain-you-verified>) and alerts will
# authenticate (SPF/DKIM) and land in the inbox. Until that is done, alerts may
# land in spam. No domain is hardcoded here on purpose: sending "from" a domain
# that is not verified in Resend fails outright, so the default stays the
# sandbox sender and the A-sender check WARNs until the owner changes it.
DEFAULT_RESEND_FROM = "onboarding@resend.dev"
SANDBOX_SENDER_DOMAINS = ("resend.dev",)

LANDING = "https://canlicapital.com"
APP = "https://app.canlicapital.com"

# honesty keystones — these MUST hold; the monitor never edits them, only verifies
EXPECT_INSAMPLE = 1.46
# The honest DEFLATED forward band. Updated 2026-07-29 from the superseded "0.7 to 1.0" to the
# corrected "0.3 to 0.9" band that was deployed weeks earlier as a deliberate honesty fix — the
# keystone had gone stale and was FALSE-ALARMING on the CORRECT public value, which is how a
# perpetually-red monitor buried the genuine 13-day AlphaMax outage (alert fatigue). Matched by
# PREFIX so the honest qualifier text after the band ("...real chance of ~0 yr1") does not break it.
EXPECT_FORWARD = "0.3 to 0.9"
EXPECT_GRADE = "C+"

UV_ENV = dict(os.environ, PATH=f"{HOME}/.local/bin:" + os.environ.get("PATH", ""))
NOW = dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def sh(cmd: str, timeout: int = 120, env=None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, env=env or os.environ)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s"
    except Exception as e:  # noqa: BLE001
        return 1, f"ERR {e}"


def http(url: str, method: str = "GET", timeout: int = 20) -> int:
    rc, out = sh(f"/usr/bin/curl -sS -o /dev/null -w '%{{http_code}}' -X {method} "
                 f"--max-time {timeout} {url}", timeout=timeout + 5)
    try:
        return int(out.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return 0


def get_json(url: str, timeout: int = 20):
    rc, out = sh(f"/usr/bin/curl -sS --max-time {timeout} {url}", timeout=timeout + 5)
    try:
        return json.loads(out)
    except Exception:  # noqa: BLE001
        return None


def age_hours(iso_ts: str) -> float | None:
    try:
        t = dt.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return (NOW - t).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        return None


# --- check accumulator -------------------------------------------------------
RESULTS: list[dict] = []


def add(id, group, title, status, severity, observed="", expected="", evidence=""):
    RESULTS.append(dict(id=id, group=group, title=title, status=status,
                        severity=severity, observed=str(observed),
                        expected=str(expected), evidence=str(evidence)[:400]))
    return status


# === CHECKS ==================================================================

def check_golden() -> bool:
    """Critical hard-gate. Returns True iff green."""
    rc, out = sh(f"cd {AF} && uv run pytest tests/integration/test_golden_master.py "
                 f"-q -m 'not network' --no-cov", timeout=600, env=UV_ENV)
    ok = rc == 0  # pytest exit 0 == all selected tests passed (1=failed,5=none collected)
    add("C7a-golden", "tests", "Crypto golden-master byte-identity",
        "PASS" if ok else "FAIL", "critical",
        observed=f"exit={rc}", expected="exit=0",
        evidence=_summary_line(out))
    return ok


def _summary_line(out: str) -> str:
    for ln in reversed(out.splitlines()):
        if any(w in ln.lower() for w in ("passed", "failed", "error", "no tests")):
            return ln.strip()
    return out.splitlines()[-1].strip() if out else ""


def check_suite():
    # Exclude the integration test that inspects the LIVE var/experiments.jsonl ledger:
    # it asserts clean-checkout properties (no duplicate hashes) that the live system's
    # legitimate daily appends break. It belongs in CI on a clean checkout; the golden
    # master is the gating hermetic test here.
    rc, out = sh(f"cd {AF} && uv run pytest -q --no-cov "
                 f"--ignore=tests/integration/test_experiments_honest_trial_count.py",
                 timeout=900, env=UV_ENV)
    ok = rc == 0
    add("C7b-suite", "tests", "Full pytest suite",
        "PASS" if ok else "FAIL", "high", observed=f"exit={rc}",
        expected="exit=0", evidence=_summary_line(out))
    return ok


def check_sites(lite=False):
    for url, sev, name in [(LANDING, "critical", "landing-apex"),
                           (f"{LANDING.replace('//', '//www.')}", "high", "landing-www"),
                           (APP, "critical", "app-host")]:
        c = http(url)
        st = "PASS" if c == 200 else ("FAIL" if c >= 500 or c == 0 else "FAIL")
        add(f"C3-{name}", "sites", f"{name} 200", st, sev,
            observed=c, expected=200, evidence=url)
    if lite:
        return
    for r in ["performance", "progress", "systems", "open", "research"]:
        c = http(f"{LANDING}/{r}")
        if c != 200:
            add(f"C3-route-{r}", "sites", f"landing /{r}", "FAIL", "high",
                observed=c, expected=200, evidence=f"{LANDING}/{r}")
    add("C3-landing-routes", "sites", "landing CTA routes (5)", "PASS", "high",
        observed="all 200 unless a FAIL row above", expected="all 200")
    for r in ["sign-in", "sign-up", "how-it-works"]:
        c = http(f"{APP}/{r}")
        if c != 200:
            add(f"C3-app-{r}", "sites", f"app /{r}", "FAIL", "high",
                observed=c, expected=200, evidence=f"{APP}/{r}")
    add("C3-app-routes", "sites", "app CTA routes (3)", "PASS", "high",
        observed="all 200 unless a FAIL row above", expected="all 200")
    for r in ["sitemap.xml", "robots.txt"]:
        c = http(f"{LANDING}/{r}")
        add(f"C3-{r}", "sites", r, "PASS" if c == 200 else "WARN", "info",
            observed=c, expected=200)
    g = http(f"{LANDING}/api/waitlist", method="GET")
    add("C-waitlist", "sites", "waitlist endpoint alive (GET=405)",
        "PASS" if g == 405 else "FAIL", "high", observed=g, expected=405,
        evidence="404 here = api route dropped in deploy")


def _freshness(url, idc, title, warn_h, fail_h):
    d = get_json(url)
    if not d or "generated_at" not in d:
        return add(idc, "data", title, "FAIL", "high", observed="unreadable",
                   expected="json with generated_at", evidence=url), None
    a = age_hours(d["generated_at"])
    st = "PASS" if a is not None and a <= warn_h else ("WARN" if a is not None and a <= fail_h else "FAIL")
    add(idc, "data", title, st, "high", observed=f"{a:.1f}h" if a else "?",
        expected=f"<={warn_h}h", evidence=d["generated_at"])
    return st, d.get("generated_at")


def check_data():
    # Hourly web-deploy promise (2026-07-05, live_deploy_hourly.sh): the tick regenerates +
    # redeploys the served state every hour, so it should never be more than ~1-2h old. The 6h
    # warn absorbs laptop sleep / transient Vercel failures; >12h means the deploy is broken.
    _, ga_land = _freshness(f"{LANDING}/paper-state.json", "C1-landing-fresh",
                            "landing paper-state fresh", 6, 12)
    _, ga_app = _freshness(f"{APP}/paper-state.json", "C1-app-fresh",
                           "app paper-state fresh", 6, 12)
    if ga_land and ga_app:
        add("C1-hosts-match", "data", "both hosts same generated_at",
            "PASS" if ga_land == ga_app else "FAIL", "high",
            observed=f"{ga_land == ga_app}", expected="equal",
            evidence=f"land={ga_land} app={ga_app}")
    # local
    try:
        local = json.load(open(STATE_JSON))
        a = age_hours(local["generated_at"])
        st = "PASS" if a is not None and a <= 3 else ("WARN" if a is not None and a <= 6 else "FAIL")
        add("C3-local-fresh", "data", "local state.json regenerated by tick", st,
            "high", observed=f"{a:.1f}h" if a else "?", expected="<=3h",
            evidence=local["generated_at"])
    except Exception as e:  # noqa: BLE001
        add("C3-local-fresh", "data", "local state.json", "FAIL", "high",
            observed=f"unreadable {e}", expected="readable")


def _log_marker_age(logpath, marker):
    rc, out = sh(f"grep -aoE '{marker} [0-9T:Z-]+' {logpath} | tail -1 | "
                 f"grep -oE '[0-9]{{4}}-[0-9-]+T[0-9:]+Z'")
    ts = out.strip().splitlines()[-1] if out.strip() else ""
    return age_hours(ts) if ts else None, ts


def check_loops():
    kill_on = os.path.exists(KILL)
    add("S-kill", "safety", "kill-switch sentinel",
        "PASS", "info", observed="ENGAGED" if kill_on else "running",
        expected="running (no var/KILL)",
        evidence="loop-stall FAILs suppressed as intentional" if kill_on else "")
    # live_tick
    a, ts = _log_marker_age(f"{AF}/var/log/live_tick.log", "=== tick done")
    if kill_on:
        add("C5a-livetick", "loops", "live_tick fired", "PASS", "info",
            observed="KILL engaged", expected="intentional halt")
    else:
        st = "PASS" if a is not None and a <= 1.5 else ("WARN" if a is not None and a <= 3 else "FAIL")
        add("C5a-livetick", "loops", "live_tick hourly fired", st, "high",
            observed=f"{a:.1f}h" if a else "no marker", expected="<=1.5h", evidence=ts)
    # alphamax
    a, ts = _log_marker_age(f"{AF}/var/log/alphamax_tick.log", "alphamax_tick done")
    st = "PASS" if a is not None and a <= 26 else ("WARN" if a is not None and a <= 50 else "FAIL")
    add("C5c-alphamax", "loops", "alphamax daily fired", st, "high",
        observed=f"{a:.1f}h" if a else "no marker", expected="<=26h", evidence=ts)
    # crypto DB accrual + status
    rc, out = sh(f"sqlite3 'file:{CRYPTO_DB}?mode=ro' 'SELECT max(cycle_ts) FROM equity_curve;'")
    try:
        ms = int(out.strip().splitlines()[-1])
        a = (NOW.timestamp() * 1000 - ms) / 3600000.0
        if kill_on:
            add("C6a-cryptodb", "loops", "crypto DB accruing", "PASS", "info",
                observed="KILL engaged", expected="intentional halt")
        else:
            st = "PASS" if a <= 1.5 else ("WARN" if a <= 3 else "FAIL")
            add("C6a-cryptodb", "loops", "crypto DB accruing marks", st, "high",
                observed=f"{a:.1f}h", expected="<=1.5h")
    except Exception:  # noqa: BLE001
        add("C6a-cryptodb", "loops", "crypto DB accruing", "FAIL", "high",
            observed="no max(cycle_ts)", expected="recent ts", evidence=out[:120])
    rc, out = sh(f"sqlite3 'file:{CRYPTO_DB}?mode=ro' "
                 f"'SELECT status FROM cycles ORDER BY cycle_ts DESC LIMIT 1;'")
    stt = out.strip().splitlines()[-1] if out.strip() else "?"
    add("C6b-cryptodb-status", "loops", "latest crypto cycle status ok",
        "PASS" if stt == "ok" else "WARN", "high", observed=stt, expected="ok")
    # AlphaTrend (managed-futures) tick — previously a blind spot (no marker check at all)
    a, ts = _log_marker_age(f"{AF}/var/log/mf_tick.log", "mf_tick done")
    st = "PASS" if a is not None and a <= 26 else ("WARN" if a is not None and a <= 50 else "FAIL")
    add("C5d-alphatrend", "loops", "alphatrend (mf) daily fired", st, "high",
        observed=f"{a:.1f}h" if a else "no marker", expected="<=26h", evidence=ts)
    # Per-sleeve realized-DB accrual: the equity/MF curves can silently go to ZERO rows (e.g. after
    # a reset) and nothing detected it. WARN on empty (fresh restart -> next tick accrues); FAIL on a
    # DB with rows that has gone stale (a dead tick) — the source the public record is built on.
    sleeve_dbs = (("C6c-mfdb", "AlphaTrend", MF_DB), ("C6d-equitydb", "AlphaMax", EQUITY_DB))
    for idc, name, db in sleeve_dbs:
        _, out = sh(f"sqlite3 'file:{db}?mode=ro' 'SELECT count(*),max(ts) FROM equity_curve;'")
        row = out.strip().splitlines()[-1] if out.strip() else ""
        try:
            cnt_s, max_s = row.split("|")
            cnt = int(cnt_s)
            if cnt == 0:
                add(idc, "loops", f"{name} DB accruing", "WARN", "warn",
                    observed="0 rows", expected=">=1 (next daily tick should accrue)")
            else:
                ah = (NOW.timestamp() * 1000 - int(max_s)) / 3600000.0
                st = "PASS" if ah <= 30 else ("WARN" if ah <= 54 else "FAIL")
                add(idc, "loops", f"{name} DB accruing marks", st, "high",
                    observed=f"{cnt} rows, latest {ah:.1f}h", expected="<=30h")
        except Exception:  # noqa: BLE001
            add(idc, "loops", f"{name} DB accruing", "FAIL", "high",
                observed="unreadable", expected="recent row", evidence=(out or "")[:120])


def check_honesty():
    try:
        local = json.load(open(STATE_JSON))
        m = local["metrics"]
    except Exception as e:  # noqa: BLE001
        add("C4-local", "honesty", "local state metrics", "FAIL", "critical",
            observed=f"unreadable {e}", expected="readable")
        return
    # in_sample 1.46 local + served
    served = {h: get_json(f"https://{h}/paper-state.json") for h in
              ("canlicapital.com", "app.canlicapital.com")}
    li = m.get("in_sample_sharpe")
    drift = [h for h, d in served.items() if d and d.get("metrics", {}).get("in_sample_sharpe") != li]
    add("C4a-insample", "honesty", "in_sample_sharpe keystone",
        "PASS" if li == EXPECT_INSAMPLE and not drift else "FAIL", "critical",
        observed=f"local={li} drift_hosts={drift}", expected=EXPECT_INSAMPLE)
    # forward must be the deflated band on both hosts (prefix match tolerates the honest qualifier)
    def _fwd_ok(v):
        return isinstance(v, str) and v.startswith(EXPECT_FORWARD)
    bad = [h for h, d in served.items() if d and not _fwd_ok(d.get("metrics", {}).get("honest_forward_sharpe"))]
    add("C4b-forward", "honesty", "forward Sharpe deflated band",
        "PASS" if _fwd_ok(m.get("honest_forward_sharpe")) and not bad else "FAIL",
        "critical", observed=f"local={m.get('honest_forward_sharpe')} bad={bad}",
        expected=f"starts with '{EXPECT_FORWARD}'")
    # grade
    gp = "deflation" in (m.get("gauntlet_pass") or "")
    add("C4d-grade", "honesty", "gauntlet grade unchanged",
        "PASS" if m.get("gauntlet_grade") == EXPECT_GRADE and gp else "FAIL", "high",
        observed=f"{m.get('gauntlet_grade')} deflation_lang={gp}", expected=f"{EXPECT_GRADE}+deflation")
    # live_days truthful
    try:
        gl = dt.date.fromisoformat(local["go_live_date"])
        days = (NOW.date() - gl).days
        ld = m.get("live_days")
        add("C4c-livedays", "honesty", "live_days truthful",
            "PASS" if abs((ld or -99) - days) <= 1 else "FAIL", "high",
            observed=f"published={ld} actual={days}", expected=f"~{days}")
    except Exception:  # noqa: BLE001
        pass
    # ALPHAC + sleeves not day-0 seed
    try:
        algos = {a["key"]: a for a in local["algorithms"]}
        ac = len(algos["alphac"]["live_curve"])
        add("C9b-alphac-seed", "loops", "ALPHAC live_curve not DAY-0 seed",
            "PASS" if ac > 1 else "FAIL", "high", observed=f"{ac} points", expected=">1")
        for k in ("alphaforge", "alphamax", "managed_futures"):
            n = len(algos[k]["live_curve"])
            if n <= 1:
                add(f"C9c-{k}-seed", "loops", f"{k} live_curve not seed", "WARN",
                    "warn", observed=f"{n} points", expected=">1")
    except Exception:  # noqa: BLE001
        pass


def check_publisher():
    rc, out = sh(f"tail -40 {AF}/var/log/live_publish.log")
    ok = ("=== publish OK" in out and "[landing] prod:" in out
          and "[app] prod:" in out and "DEPLOY FAILED" not in out
          and "COMPLETED WITH ERRORS" not in out)
    add("P1-publish", "publisher", "last publish clean, both legs",
        "PASS" if ok else "WARN", "high",
        observed="both legs OK" if ok else "incomplete/old",
        evidence="\n".join(l for l in out.splitlines() if "prod:" in l or "publish" in l)[-300:])
    a, ts = _log_marker_age(f"{AF}/var/log/live_publish.log", "=== live_publish")
    st = "PASS" if a is not None and a <= 26 else ("WARN" if a is not None and a <= 50 else "FAIL")
    add("P2-publish-window", "publisher", "publish ran in daily window", st, "high",
        observed=f"{a:.1f}h" if a else "no marker", expected="<=26h", evidence=ts)
    _jobs = "livetick|alphamax|alphatrend|publish|health|aimonitor"
    rc, out = sh(f"launchctl list | grep -oE 'com.accapital.({_jobs})'")
    loaded = set(out.split())
    need = {"com.accapital.livetick", "com.accapital.alphamax", "com.accapital.alphatrend", "com.accapital.publish"}
    missing = need - loaded
    add("P3-launchd", "publisher", "scheduled jobs loaded",
        "PASS" if not missing else "FAIL", "high",
        observed=f"missing={sorted(missing)}" if missing else "all core loaded",
        expected="livetick+alphamax+publish loaded")


def read_env_file(path: str) -> dict:
    """Parse a KEY=VALUE env file (blank lines and #comments ignored)."""
    env: dict = {}
    try:
        with open(path) as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        return {}
    return env


def sender_address(env: dict) -> str:
    """From-address for alerts, configurable via RESEND_FROM in resend.env."""
    return (env.get("RESEND_FROM") or "").strip() or DEFAULT_RESEND_FROM


def is_sandbox_sender(addr: str) -> bool:
    dom = addr.rsplit("@", 1)[-1].lower()
    return any(dom == d or dom.endswith("." + d) for d in SANDBOX_SENDER_DOMAINS)


def check_alert_channel():
    has_resend = os.path.exists(RESEND_ENV) and "RESEND_API_KEY=re_" in open(RESEND_ENV).read()
    add("A-alert", "self", "deliverable alert channel exists",
        "PASS" if has_resend else "WARN", "high",
        observed="resend key present" if has_resend else "no resend -> osascript+log",
        expected="resend or telegram")
    # A key that sends is not the same as mail that ARRIVES: the shared Resend
    # sandbox sender is unauthenticated for our domain and gets spam-filed.
    frm = sender_address(read_env_file(RESEND_ENV))
    sandbox = is_sandbox_sender(frm)
    add("A-sender", "self", "alert from-address is a verified domain",
        "WARN" if sandbox else "PASS", "high", observed=frm,
        expected="RESEND_FROM on a domain verified in Resend",
        evidence=("shared sandbox sender — Gmail may spam-file these; set "
                  "RESEND_FROM in ~/.config/alphaforge/resend.env to an address "
                  "on a domain you have verified in Resend") if sandbox else "")
    return has_resend


# === SELF-HEAL (closed allowlist, gated) ====================================
REMEDIATION: list[dict] = []


def overall_status() -> str:
    if any(r["status"] == "FAIL" for r in RESULTS):
        return "FAIL"
    if any(r["status"] == "WARN" for r in RESULTS):
        return "WARN"
    return "PASS"


def by_id(idc):
    return next((r for r in RESULTS if r["id"] == idc), None)


def tests_green() -> bool:
    g, s = by_id("C7a-golden"), by_id("C7b-suite")
    return bool(g and g["status"] == "PASS" and s and s["status"] == "PASS")


def local_state_valid() -> bool:
    try:
        d = json.load(open(STATE_JSON))
        return all(len(a["live_curve"]) >= 1 for a in d["algorithms"])
    except Exception:  # noqa: BLE001
        return False


def engine_untouched() -> bool:
    rc, out = sh(f"cd {AF} && git status --porcelain src/alphaforge "
                 f"tests/integration/test_golden_master.py 2>/dev/null")
    return out.strip() == ""


def self_heal():
    """Only runs when tests are green (never heal off a red tree)."""
    if not tests_green():
        REMEDIATION.append(dict(check_id="*", action="self-heal DISABLED: tests not green",
                                auto_healed=False, exit=None, post_state="gated"))
        return
    if os.path.exists(KILL):
        return
    healed = False
    # 1) stale / divergent public data -> one republish (gated, build-safe script)
    data_bad = [r for r in RESULTS if r["group"] == "data"
                and r["status"] in ("WARN", "FAIL")
                and r["id"] in ("C1-landing-fresh", "C1-app-fresh", "C1-hosts-match")]
    if data_bad and local_state_valid():
        rc, out = sh(f"cd {AF} && /bin/zsh scripts/live_publish.sh", timeout=900, env=UV_ENV)
        healed = True
        REMEDIATION.append(dict(check_id=",".join(r["id"] for r in data_bad),
                                action="re-ran live_publish.sh (idempotent, build-gated, 1 attempt)",
                                auto_healed=(rc == 0), exit=rc, post_state=out.splitlines()[-1] if out else ""))
    # 2) local state stale but tick otherwise present -> regenerate state json
    ls = by_id("C3-local-fresh")
    lt = by_id("C5a-livetick")
    if ls and ls["status"] in ("WARN", "FAIL") and lt and lt["status"] == "PASS":
        rc, out = sh(f"cd {AF} && uv run python scripts/paper_trading_state.py", timeout=300, env=UV_ENV)
        healed = True
        REMEDIATION.append(dict(check_id="C3-local-fresh",
                                action="re-ran paper_trading_state.py (read DB ro -> write JSON)",
                                auto_healed=(rc == 0), exit=rc, post_state=out.splitlines()[-1] if out else ""))
    # 3) a core launchd job not loaded -> bootstrap/kickstart once
    p3 = by_id("P3-launchd")
    if p3 and p3["status"] == "FAIL":
        for job in ("livetick", "alphamax", "alphatrend", "publish"):
            if job in p3["observed"]:
                sh(f"launchctl bootstrap gui/$(id -u) {HOME}/Library/LaunchAgents/com.accapital.{job}.plist 2>/dev/null; "
                   f"launchctl kickstart -k gui/$(id -u)/com.accapital.{job} 2>/dev/null")
                REMEDIATION.append(dict(check_id="P3-launchd",
                                        action=f"bootstrap+kickstart com.accapital.{job} (1x)",
                                        auto_healed=True, exit=0, post_state="kicked"))
        healed = True
    # post-heal safety audit
    if healed:
        clean = engine_untouched()
        REMEDIATION.append(dict(check_id="S-engine-audit",
                                action="engine-untouched audit after self-heal",
                                auto_healed=clean, exit=0 if clean else 1,
                                post_state="clean" if clean else "ENGINE TOUCHED -> REVERT+PAGE"))
        if not clean:
            add("S-engine-touched", "safety", "engine touched by self-heal!", "FAIL",
                "critical", observed="uncommitted change under src/alphaforge",
                expected="clean", evidence="REVERT REQUIRED")


# === STATUS ARTIFACT + ALERT ================================================

def write_status(transitions: dict | None = None) -> dict:
    os.makedirs(HIST, exist_ok=True)
    rc, sha = sh(f"cd {AF} && git rev-parse --short HEAD 2>/dev/null")
    counts = dict(
        pass_=sum(1 for r in RESULTS if r["status"] == "PASS"),
        warn=sum(1 for r in RESULTS if r["status"] == "WARN"),
        fail=sum(1 for r in RESULTS if r["status"] == "FAIL"))
    status = dict(schema=1, generated_at=iso(NOW), host=os.uname().nodename,
                  git_sha=sha.strip(), overall=overall_status(), counts=counts,
                  checks=RESULTS, remediation=REMEDIATION,
                  next_run="daily 13:11Z (com.accapital.health)")
    if transitions is not None:
        status["transitions"] = {k: [e["id"] for e in transitions.get(k, [])]
                                 for k in ("new_fails", "standing_fails", "recovered",
                                           "new_warns", "unobserved_fails")}
        status["transitions"]["prev_run_at"] = transitions.get("prev_run_at")
    os.makedirs(HEALTH, exist_ok=True)
    tmp = os.path.join(HEALTH, "status.json.tmp")
    with open(tmp, "w") as f:
        json.dump(status, f, indent=2)
    os.replace(tmp, os.path.join(HEALTH, "status.json"))
    shutil.copy(os.path.join(HEALTH, "status.json"),
                os.path.join(HIST, f"status-{NOW.strftime('%Y%m%dT%H%M%SZ')}.json"))
    # prune history to last 30
    snaps = sorted(os.listdir(HIST))
    for old in snaps[:-30]:
        try:
            os.remove(os.path.join(HIST, old))
        except Exception:  # noqa: BLE001
            pass
    reds = [r for r in RESULTS if r["status"] == "FAIL"]
    line = (f"{iso(NOW)} OVERALL={status['overall']} pass={counts['pass_']} "
            f"warn={counts['warn']} fail={counts['fail']} "
            + (" ".join(f"[{r['id']} {r['observed']}]" for r in reds[:6]) if reds else ""))
    with open(os.path.join(HEALTH, "health.log"), "a") as f:
        f.write(line + "\n")
    return status


# --- transition engine (PASS->FAIL is the signal; FAIL->FAIL is background) ---
SEV_RANK = {"critical": 0, "high": 1, "warn": 2, "info": 3}


def _sev(e: dict) -> int:
    return SEV_RANK.get(str(e.get("severity", "")).lower(), 9)


def load_alert_state(path: str = ALERT_STATE) -> dict:
    """Previous run's per-check status. A missing/corrupt file is treated as
    'no memory' — every current red then reads as NEW, which is the safe
    direction (louder), never quieter."""
    try:
        with open(path) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("checks"), dict):
            return d
    except Exception:  # noqa: BLE001
        pass
    return dict(schema=ALERT_STATE_SCHEMA, updated_at=None, run_count=0, checks={})


def classify_transitions(prev_state: dict | None, results: list) -> dict:
    """Diff this run's board against the previous run.

    new_fails       PASS/WARN/unknown -> FAIL   (leads the subject)
    standing_fails  FAIL -> FAIL               (reported, de-emphasized)
    recovered       FAIL -> PASS/WARN          (the self-heal signal)
    new_warns       -> WARN from anything else
    unobserved_fails  was FAIL, not checked this run (e.g. --lite): NOT a recovery
    """
    prev_checks = dict((prev_state or {}).get("checks") or {})
    new_fails: list = []
    standing_fails: list = []
    recovered: list = []
    new_warns: list = []
    for r in results:
        p = prev_checks.get(r["id"]) or {}
        pstat = p.get("status")
        e = dict(r, prev_status=pstat, since=p.get("since"),
                 runs=int(p.get("runs") or 0), prev_observed=p.get("observed"))
        if r["status"] == "FAIL":
            (standing_fails if pstat == "FAIL" else new_fails).append(e)
        elif pstat == "FAIL":
            recovered.append(e)
        elif r["status"] == "WARN" and pstat != "WARN":
            new_warns.append(e)
    seen = set(r["id"] for r in results)
    unobserved_fails = [dict(id=cid, title=p.get("title", ""),
                             severity=p.get("severity", "high"),
                             status="FAIL", observed=p.get("observed", ""),
                             expected="", prev_status="FAIL", since=p.get("since"),
                             runs=int(p.get("runs") or 0))
                        for cid, p in prev_checks.items()
                        if cid not in seen and p.get("status") == "FAIL"]
    for lst in (new_fails, standing_fails, recovered, new_warns, unobserved_fails):
        lst.sort(key=lambda e: (_sev(e), e["id"]))
    return dict(new_fails=new_fails, standing_fails=standing_fails,
                recovered=recovered, new_warns=new_warns,
                unobserved_fails=unobserved_fails,
                prev_run_at=(prev_state or {}).get("updated_at"))


def undelivered_ids(prev_state: dict | None, results: list) -> list:
    """Checks whose CURRENT status differs from what the persisted memory says
    the owner was last told. These are exactly the rows an alert had news about,
    so if that alert never arrived they must not be recorded as 'told'."""
    prev_checks = dict((prev_state or {}).get("checks") or {})
    return [r["id"] for r in results
            if r["id"] not in SYNTHETIC_IDS
            and (prev_checks.get(r["id"]) or {}).get("status") != r["status"]]


def next_alert_state(prev_state: dict | None, results: list, now: dt.datetime,
                     delivered: bool = True) -> dict:
    """State to persist for the NEXT run's diff.

    delivered=False means the alert never reached the owner (Resend rejected it,
    curl timed out, no channel configured). The memory is a record of what the
    owner HAS BEEN TOLD, so an undelivered run records no status TRANSITION:
    every changed check keeps its previous entry, and the next run classifies it
    as NEW (or RECOVERED) again and re-alerts. Unchanged checks still advance
    their bookkeeping (last_seen/runs), so the stale-entry pruning keeps working.

    Bounded: holding the same news forever would make a permanently dead channel
    shout NEW on every run. After MAX_UNDELIVERED_HOLDS consecutive undelivered
    runs that had something to hold, the state advances anyway and stamps
    `undelivered_forced_advance_at` (main() then writes CHANNEL PRESUMED DEAD to
    UNDELIVERED_LOG). A delivered run — or an undelivered run with nothing
    withheld — resets the counter.
    """
    prev_checks = dict((prev_state or {}).get("checks") or {})
    now_iso = iso(now)
    checks: dict = {}
    for r in results:
        if r["id"] in SYNTHETIC_IDS:
            continue
        p = prev_checks.get(r["id"]) or {}
        same = p.get("status") == r["status"]
        checks[r["id"]] = dict(
            status=r["status"], title=r["title"], severity=r["severity"],
            observed=str(r["observed"])[:160],
            since=(p.get("since") or now_iso) if same else now_iso,
            runs=(int(p.get("runs") or 0) + 1) if same else 1,
            last_seen=now_iso, missed=0)
    for cid, p in prev_checks.items():
        if cid in checks:
            continue
        missed = int(p.get("missed") or 0) + 1
        if missed >= MAX_MISSED_RUNS:
            # Stale entry: stop carrying a check we no longer emit. If it is in
            # fact still broken, the next run that DOES emit it reports it as
            # NEW — louder than the truth, never quieter.
            continue
        carried = dict(p)
        carried["missed"] = missed
        checks[cid] = carried
    # --- delivery gate -------------------------------------------------------
    holds = int((prev_state or {}).get("undelivered_runs") or 0)
    forced_at = (prev_state or {}).get("undelivered_forced_advance_at")
    if delivered:
        holds = 0
    else:
        pending = undelivered_ids(prev_state, results)
        if not pending:
            holds = 0                       # nothing withheld -> streak broken
        elif holds + 1 >= MAX_UNDELIVERED_HOLDS:
            holds = 0                       # bounded: stop holding, advance
            forced_at = now_iso
        else:
            holds += 1
            for cid in pending:
                p = prev_checks.get(cid)
                if p is None:
                    # never recorded => leave it unrecorded, so the next run
                    # still sees a first-seen red and reports it as NEW
                    checks.pop(cid, None)
                else:
                    carried = dict(p)       # pin at the last TOLD status
                    carried["last_seen"] = now_iso
                    carried["missed"] = 0
                    checks[cid] = carried
    state = dict(schema=ALERT_STATE_SCHEMA, updated_at=now_iso,
                 prev_run_at=(prev_state or {}).get("updated_at"),
                 run_count=int((prev_state or {}).get("run_count") or 0) + 1,
                 undelivered_runs=holds, checks=checks)
    if forced_at:
        state["undelivered_forced_advance_at"] = forced_at
    return state


def save_alert_state(state: dict, path: str = ALERT_STATE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _age_note(e: dict) -> str:
    if not e.get("since"):
        return ""
    runs = e.get("runs") or 0
    return f" [red since {e['since']}, {runs} run{'s' if runs != 1 else ''}]"


def _fail_line(e: dict, note: str = "") -> str:
    want = f" (want {e['expected']})" if e.get("expected") else ""
    return f"  FAIL [{e.get('severity', '?')}] {e['id']} {e.get('title', '')}: {e.get('observed', '')}{want}{note}"


def build_alert(status: dict, tr: dict) -> tuple:
    """(subject, body). NEW breakage always leads; standing red always still
    reported, just below it. Never returns an empty/suppressed alert on a red."""
    overall = status["overall"]
    c = status["counts"]
    nf, sf = tr["new_fails"], tr["standing_fails"]
    rec, nw, uf = tr["recovered"], tr["new_warns"], tr["unobserved_fails"]
    prev_run = tr.get("prev_run_at")

    # --- subject -------------------------------------------------------------
    if nf:
        head = f"{nf[0]['id']} ({nf[0].get('title', '')})"
        subj = (f"AlphaForge NEW FAIL: {head}" if len(nf) == 1
                else f"AlphaForge {len(nf)} NEW FAILS: {head} +"
                     + ",".join(e["id"] for e in nf[1:4]))
        tail = []
        if sf:
            tail.append(f"{len(sf)} standing")
        if rec:
            tail.append(f"{len(rec)} recovered")
        if tail:
            subj += " | " + ", ".join(tail)
    elif rec:
        head = f"{rec[0]['id']} ({rec[0].get('title', '')})"
        subj = (f"AlphaForge RECOVERED: {head}" if len(rec) == 1
                else f"AlphaForge {len(rec)} RECOVERED: {head} +"
                     + ",".join(e["id"] for e in rec[1:4]))
        subj += (f" | {len(sf)} standing red, no new breakage" if sf
                 else (" — all green" if overall == "PASS" else f" | {c['warn']} warn"))
    elif sf:
        # quieter digest: still red, still emailed, but visibly "nothing changed"
        subj = (f"AlphaForge standing red x{len(sf)} (no change since {prev_run or 'first run'}) — "
                + ",".join(e["id"] for e in sf[:5]))
    elif nw:
        subj = f"AlphaForge new WARN: {nw[0]['id']} ({nw[0].get('title', '')})"
    elif overall == "WARN":
        subj = f"AlphaForge WARN x{c['warn']} (no change) {NOW.date()}"
    else:
        subj = f"AlphaForge OK — {c['pass_']} green {NOW.date()}"
    if uf:
        subj += f" | {len(uf)} red not re-checked"

    # --- body ----------------------------------------------------------------
    lines = [f"OVERALL={overall}  pass={c['pass_']} warn={c['warn']} fail={c['fail']}",
             f"since last run ({prev_run or 'none — no prior state'}): "
             f"{len(nf)} new fail, {len(sf)} standing, {len(rec)} recovered", ""]
    if nf:
        lines.append("NEW FAILURES (was not failing at the last run) <<< ACT ON THESE")
        for e in nf:
            was = e.get("prev_status") or "not previously recorded"
            lines.append(_fail_line(e, f" [was {was}]"))
        lines.append("")
    if rec:
        lines.append("RECOVERED since last run:")
        for e in rec:
            lines.append(f"  OK   {e['id']} {e.get('title', '')}: now {e['status']} "
                         f"({e.get('observed', '')}) — had been red since "
                         f"{e.get('since') or '?'} ({e.get('runs') or 0} runs)")
        lines.append("")
    if sf:
        lines.append(f"STANDING red ({len(sf)}) — already failing at the last run, unchanged:")
        for e in sf:
            lines.append(_fail_line(e, _age_note(e)))
        lines.append("")
    if uf:
        lines.append("RED BUT NOT RE-CHECKED THIS RUN (no recovery claimed):")
        for e in uf:
            lines.append(f"  ????  {e['id']} {e.get('title', '')}{_age_note(e)}")
        lines.append("")
    warns = [r for r in (status.get("checks") or []) if r["status"] == "WARN"]
    if warns:
        new_warn_ids = set(e["id"] for e in nw)
        lines.append("warnings:")
        for r in warns:
            flag = "NEW " if r["id"] in new_warn_ids else ""
            lines.append(f"  {flag}WARN {r['id']} {r['title']}: {r['observed']}")
        lines.append("")
    if status.get("remediation"):
        lines += ["self-heal:"] + [f"  {m['check_id']}: {m['action']} -> {m['post_state']}"
                                   for m in status["remediation"]] + [""]
    lines.append("state: var/health/alert_state.json (per-check memory used for the diff above)")
    return subj, "\n".join(lines)


def log_undelivered(subj: str, body: str) -> None:
    """Durable local record of something the owner was NOT told (best effort).

    Read from the module globals at call time on purpose so a test can redirect
    HEALTH/UNDELIVERED_LOG to a tmp dir.
    """
    try:
        os.makedirs(HEALTH, exist_ok=True)
        with open(UNDELIVERED_LOG, "a") as f:
            f.write(f"=== {iso(NOW)} UNDELIVERED {subj}\n{body}\n\n")
    except Exception:  # noqa: BLE001
        pass


def send_alert(subj: str, body: str, status: dict, enabled: bool) -> bool:
    """Deliver; on failure escalate loudly. Returns True iff Resend accepted."""
    overall = status["overall"]
    reds = [r for r in (status.get("checks") or []) if r["status"] == "FAIL"]
    if not enabled:
        print(subj + "\n" + body)
        return False
    sent = False
    env = read_env_file(RESEND_ENV)
    key = env.get("RESEND_API_KEY", "")
    if key:
        to = env.get("RESEND_TO", "arhancanli8@gmail.com")
        frm = sender_address(env)
        payload = json.dumps({"from": f"AlphaForge Health <{frm}>", "to": [to],
                              "subject": subj, "text": body})
        try:
            # -d with the JSON as an argv element: no shell, so no arg-escaping risk
            p = subprocess.run(["/usr/bin/curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                "https://api.resend.com/emails",
                                "-H", f"Authorization: Bearer {key}",
                                "-H", "Content-Type: application/json",
                                "-d", payload], capture_output=True, text=True, timeout=30)
            sent = p.stdout.strip().startswith("2")
        except Exception:  # noqa: BLE001
            sent = False
    if not sent and overall != "PASS":
        # never silent on a red: loud macOS banner + a durable local record
        sh(f"osascript -e 'display notification \"AlphaForge {overall} {len(reds)} red\" "
           f"with title \"health\"' 2>/dev/null")
        log_undelivered(subj, body)
    print(f"[alert] sent={sent} subject={subj!r}")
    return sent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="no heal, no alert")
    ap.add_argument("--no-heal", action="store_true")
    ap.add_argument("--no-alert", action="store_true")
    ap.add_argument("--lite", action="store_true", help="sites + data only (no pytest)")
    ap.add_argument("--selftest-fail", action="store_true",
                    help="inject one synthetic FAIL to prove the red->alert->exit2 path")
    a = ap.parse_args()

    if a.selftest_fail:
        add("SELFTEST", "self", "synthetic failure (selftest only)", "FAIL", "high",
            observed="injected", expected="(ignore — proving the alert path)")

    golden_ok = True
    if not a.lite:
        golden_ok = check_golden()
        if golden_ok:
            check_suite()
    check_sites(lite=a.lite)
    check_data()
    check_loops()
    check_honesty()
    check_publisher()
    check_alert_channel()

    if not (a.dry_run or a.no_heal):
        if golden_ok:
            self_heal()
        else:
            REMEDIATION.append(dict(check_id="C7a-golden", action="ALL self-heal disabled: golden RED",
                                    auto_healed=False, exit=None, post_state="hard-gate"))

    prev_state = load_alert_state()
    transitions = classify_transitions(prev_state, RESULTS)
    status = write_status(transitions)
    subj, body = build_alert(status, transitions)
    alerting = not (a.dry_run or a.no_alert)
    delivered = send_alert(subj, body, status, enabled=alerting)
    # Only advance the memory when the owner was actually told. A --dry-run /
    # --no-alert run must not turn an unreported red into tomorrow's "standing"
    # — and neither may a run whose mail was rejected/timed out: send_alert()'s
    # return value gates the advance, so undelivered news stays NEW next run.
    held: list = []
    if alerting:
        state = next_alert_state(prev_state, RESULTS, NOW, delivered=delivered)
        if not delivered:
            if state.get("undelivered_forced_advance_at") == iso(NOW):
                log_undelivered(
                    f"CHANNEL PRESUMED DEAD after {MAX_UNDELIVERED_HOLDS} undelivered runs "
                    f"— alert state force-advanced",
                    "The same undelivered news was re-alerted on "
                    f"{MAX_UNDELIVERED_HOLDS} consecutive runs and never reached the "
                    "owner. To bound the re-alert loop, alert_state.json now advances; "
                    "these checks will read as STANDING from the next run on. FIX THE "
                    "CHANNEL (~/.config/alphaforge/resend.env) — the full alert bodies "
                    f"are logged above.\nundelivered ids: "
                    f"{','.join(undelivered_ids(prev_state, RESULTS)) or 'none'}")
            else:
                held = undelivered_ids(prev_state, RESULTS)
        save_alert_state(state)
    print(f"OVERALL={status['overall']} {status['counts']} "
          f"new={len(transitions['new_fails'])} standing={len(transitions['standing_fails'])} "
          f"recovered={len(transitions['recovered'])}"
          + (f" delivered={delivered} held_as_new={len(held)}" if alerting and not delivered else ""))
    sys.exit(0 if status["overall"] != "FAIL" else 2)


if __name__ == "__main__":
    main()
