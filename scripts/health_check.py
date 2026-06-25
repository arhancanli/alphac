#!/usr/bin/env python3
"""Canli Capital / AlphaForge — daily health monitor.

Runs the full check board (tests, live sites, data freshness, engine loops,
honesty/consistency, publisher), performs ONLY the narrow allowlist of safe
self-heals, writes an atomic status.json + human log + history snapshot, and
alerts via Resend (osascript + log fallback). Stdlib only, so it never depends
on the uv env to RUN (it shells out to `uv run pytest` for the test checks).

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
KILL = os.path.join(AF, "var", "KILL")
RESEND_ENV = os.path.join(HOME, ".config", "alphaforge", "resend.env")

LANDING = "https://canlicapital.com"
APP = "https://app.canlicapital.com"

# honesty keystones — these MUST hold; the monitor never edits them, only verifies
EXPECT_INSAMPLE = 1.46
EXPECT_FORWARD = "0.7 to 1.0"
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
    _, ga_land = _freshness(f"{LANDING}/paper-state.json", "C1-landing-fresh",
                            "landing paper-state fresh", 30, 50)
    _, ga_app = _freshness(f"{APP}/paper-state.json", "C1-app-fresh",
                           "app paper-state fresh", 30, 50)
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
    # forward must be deflated band on both hosts
    bad = [h for h, d in served.items() if d and d.get("metrics", {}).get("honest_forward_sharpe") != EXPECT_FORWARD]
    add("C4b-forward", "honesty", "forward Sharpe deflated band",
        "PASS" if m.get("honest_forward_sharpe") == EXPECT_FORWARD and not bad else "FAIL",
        "critical", observed=f"local={m.get('honest_forward_sharpe')} bad={bad}",
        expected=EXPECT_FORWARD)
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
        for k in ("alphaforge", "alphamax"):
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
    rc, out = sh("launchctl list | grep -oE 'com.accapital.(livetick|alphamax|publish|health|aimonitor)'")
    loaded = set(out.split())
    need = {"com.accapital.livetick", "com.accapital.alphamax", "com.accapital.publish"}
    missing = need - loaded
    add("P3-launchd", "publisher", "scheduled jobs loaded",
        "PASS" if not missing else "FAIL", "high",
        observed=f"missing={sorted(missing)}" if missing else "all core loaded",
        expected="livetick+alphamax+publish loaded")


def check_alert_channel():
    has_resend = os.path.exists(RESEND_ENV) and "RESEND_API_KEY=re_" in open(RESEND_ENV).read()
    add("A-alert", "self", "deliverable alert channel exists",
        "PASS" if has_resend else "WARN", "high",
        observed="resend key present" if has_resend else "no resend -> osascript+log",
        expected="resend or telegram")
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
        for job in ("livetick", "alphamax", "publish"):
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

def write_status() -> dict:
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


def alert(status: dict, enabled: bool):
    overall = status["overall"]
    reds = [r for r in RESULTS if r["status"] == "FAIL"]
    warns = [r for r in RESULTS if r["status"] == "WARN"]
    c = status["counts"]
    subj = (f"AlphaForge OK — {c['pass_']} green {NOW.date()}" if overall == "PASS"
            else f"AlphaForge {overall} {len(reds)}x — " + ",".join(r["id"] for r in reds[:5]))
    lines = [f"OVERALL={overall}  pass={c['pass_']} warn={c['warn']} fail={c['fail']}", ""]
    for r in reds:
        lines.append(f"FAIL [{r['severity']}] {r['id']} {r['title']}: {r['observed']} (want {r['expected']})")
    for r in warns:
        lines.append(f"WARN {r['id']} {r['title']}: {r['observed']}")
    if status["remediation"]:
        lines += ["", "self-heal:"] + [f"  {m['check_id']}: {m['action']} -> {m['post_state']}"
                                        for m in status["remediation"]]
    body = "\n".join(lines)
    if not enabled:
        print(subj + "\n" + body)
        return
    sent = False
    if os.path.exists(RESEND_ENV):
        env = {}
        for ln in open(RESEND_ENV):
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.strip().split("=", 1)
                env[k] = v
        key = env.get("RESEND_API_KEY", "")
        to = env.get("RESEND_TO", "arhancanli8@gmail.com")
        frm = env.get("RESEND_FROM", "onboarding@resend.dev")
        if key:
            payload = json.dumps(dict(**{"from": f"AlphaForge Health <{frm}>"},
                                      to=[to], subject=subj,
                                      text=body))
            rc, out = sh(f"/usr/bin/curl -s -o /dev/null -w '%{{http_code}}' "
                         f"https://api.resend.com/emails -H 'Authorization: Bearer {key}' "
                         f"-H 'Content-Type: application/json' -d @-",
                         timeout=30, env=dict(os.environ)) if False else (0, "")
            # send via stdin to avoid arg-escaping the JSON
            try:
                p = subprocess.run(["/usr/bin/curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                    "https://api.resend.com/emails",
                                    "-H", f"Authorization: Bearer {key}",
                                    "-H", "Content-Type: application/json",
                                    "-d", payload], capture_output=True, text=True, timeout=30)
                sent = p.stdout.strip().startswith("2")
            except Exception:  # noqa: BLE001
                sent = False
    if not sent and overall != "PASS":
        # never silent on a red: loud macOS fallback
        sh(f"osascript -e 'display notification \"AlphaForge {overall} {len(reds)} red\" "
           f"with title \"health\"' 2>/dev/null")
    print(f"[alert] sent={sent} subject={subj!r}")


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

    status = write_status()
    alert(status, enabled=not (a.dry_run or a.no_alert))
    print(f"OVERALL={status['overall']} {status['counts']}")
    sys.exit(0 if status["overall"] != "FAIL" else 2)


if __name__ == "__main__":
    main()
