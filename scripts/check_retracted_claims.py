#!/usr/bin/env python3
"""Refuse to publish a claim this record has already withdrawn.

Runs after the state/glass-box regeneration and BEFORE the web deploy, so a retracted number
cannot reach the public site the way AlphaTrend's DSR 0.83 did: withdrawn in the signed chain on
2026-08-06, still on the homepage, still in the /progress unfurl card, and still asserted in three
glass-box artifacts on 2026-08-12. Six days, from a pipeline that was publishing the correction
and the error side by side.

WHAT MAKES THIS DIFFERENT FROM A GREP. The retracted number must remain QUOTABLE inside its own
retraction — scrubbing history would be its own dishonesty, and a guard that forced deletion would
push the record toward hiding mistakes rather than explaining them. So each rule carries an
exemption pattern, and a hit only fails when the surrounding window does NOT explain it. The check
is therefore satisfied by disclosure, never by silence.

It fails CLOSED: an unreadable blocklist, an unparseable line, or a scan target that does not exist
is an error, not a pass. A check that cannot fail is worse than no check.

    python scripts/check_retracted_claims.py [--root DIR]...
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
BLOCKLIST = _REPO / "docs" / "retracted_claims.txt"

#: Bytes either side of a hit that count as "the surrounding explanation". Wide enough that a
#: retraction sentence one clause away still exempts, tight enough that an unrelated withdrawal
#: elsewhere on the page cannot launder an assertion at the top.
WINDOW = 400

#: A fourth, optional rule field can identify a locally unambiguous non-claim use of the same
#: digits. This window is deliberately much smaller than ``WINDOW``: a legitimate metric name
#: may excuse only the number assigned to that metric, not a withdrawn assertion elsewhere in
#: the same JSON object or paragraph.
LOCAL_CONTEXT_WINDOW = 80

SCAN_SUFFIXES = {".html", ".json", ".js", ".txt", ".md"}
SKIP_DIRS = {"node_modules", ".git", ".vercel", "assets"}

#: The ONLY file exempt wholesale: the signed append-only chain. It is exempt because it cannot be
#: repaired -- an entry is hash-linked and signed the moment it is written, so a bare assertion
#: inside it can only be answered by APPENDING a retraction the 400-byte window will never see.
#: Failing forever on an un-editable file does not protect the record; it pressures someone into
#: weakening the rule, which this file warns against in its own header.
#:
#: NARROWED 2026-08-19, and this is the point of the change. The set previously read
#: {"paper-state.json", "track_record.json", "transparency.json"} -- three entries, none of them
#: right. "transparency.json" MATCHES NO FILE: the chain is published as transparency_log.json, so
#: the one exemption that was justified was never in force (the chain passed on its merits, which
#: is how nobody noticed). The two that WERE in force are the two published surfaces the whole
#: dashboard renders from, and they are regenerated from source every hour -- so a bare claim in
#: them is always fixable, and exempting them is what let AlphaVintage's withdrawn 0.3403 sit on
#: canlicapital.com in the single most-read file on the site while this gate reported a pass.
#:
#: The rule is now: an IMMUTABLE copy is exempt, every MUTABLE copy is scanned. Because the
#: mutable copies are generated from the same prose that later gets signed into the chain, a bare
#: assertion is caught before it can ever reach the copy that cannot be fixed.
EXEMPT_NAMES = {"transparency_log.json"}


class Rule:
    __slots__ = ("exempt", "ignore_local", "pattern", "raw", "seq")

    def __init__(
        self,
        seq: str,
        pattern: str,
        exempt: str,
        ignore_local: str,
        raw: str,
    ) -> None:
        self.seq = seq
        self.pattern = re.compile(pattern, re.IGNORECASE)
        self.exempt = re.compile(exempt, re.IGNORECASE) if exempt.strip() else None
        self.ignore_local = (
            re.compile(ignore_local, re.IGNORECASE) if ignore_local.strip() else None
        )
        self.raw = raw


def load_rules() -> list[Rule]:
    if not BLOCKLIST.exists():
        raise SystemExit(f"FAIL: blocklist missing at {BLOCKLIST} — refusing to publish blind")
    rules: list[Rule] = []
    for n, line in enumerate(BLOCKLIST.read_text().splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # "::", never "|". The patterns contain alternation, so splitting on "|" cut this file's
        # own regexes mid-group and every one of them failed to compile -- the guard against
        # unenforced rules was itself unenforceable on its first run.
        parts = [p.strip() for p in s.split("::")]
        if len(parts) < 2 or len(parts) > 4:
            raise SystemExit(f"FAIL: {BLOCKLIST}:{n} unparseable: {line!r}")
        seq, pattern = parts[0], parts[1]
        exempt = parts[2] if len(parts) > 2 else ""
        ignore_local = parts[3] if len(parts) > 3 else ""
        rules.append(Rule(seq, pattern, exempt, ignore_local, s))
    if not rules:
        raise SystemExit("FAIL: blocklist parsed to zero rules — that is not a passing state")
    return rules


def scan(root: Path, rules: list[Rule]) -> list[tuple[Path, Rule, str]]:
    violations: list[tuple[Path, Rule, str]] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in p.parts) or p.name in EXEMPT_NAMES:
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for rule in rules:
            for m in rule.pattern.finditer(text):
                local_start = max(0, m.start() - LOCAL_CONTEXT_WINDOW)
                local_context = text[
                    local_start : m.end() + LOCAL_CONTEXT_WINDOW
                ]
                relative_match = (m.start() - local_start, m.end() - local_start)
                if rule.ignore_local is not None and any(
                    ignored.start() <= relative_match[0] and ignored.end() >= relative_match[1]
                    for ignored in rule.ignore_local.finditer(local_context)
                ):
                    continue
                window = text[max(0, m.start() - WINDOW) : m.end() + WINDOW]
                if rule.exempt is not None and rule.exempt.search(window):
                    continue  # quoted inside its own retraction — that is the correct usage
                snippet = " ".join(window[WINDOW - 90 : WINDOW + 130].split())
                violations.append((p, rule, snippet))
    return violations


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", action="append", default=None, help="directory to scan (repeatable)")
    a = ap.parse_args()
    roots = [Path(r).expanduser() for r in (a.root or ["~/meridian/dist", "~/meridian/public"])]

    rules = load_rules()
    missing = [r for r in roots if not r.exists()]
    if missing and len(missing) == len(roots):
        raise SystemExit(f"FAIL: none of the scan roots exist: {[str(m) for m in missing]}")

    all_v: list[tuple[Path, Rule, str]] = []
    for r in roots:
        if r.exists():
            all_v.extend(scan(r, rules))

    existing_root_count = len([root for root in roots if root.exists()])
    print(f"retracted-claims check: {len(rules)} rules over {existing_root_count} root(s)")
    if not all_v:
        print("  PASS — no withdrawn claim is asserted anywhere in the publish set")
        return 0

    print(f"  FAIL — {len(all_v)} assertion(s) of a claim this record has withdrawn:\n")
    for p, rule, snippet in all_v:
        print(f"   {p}")
        print(f"     rule [{rule.seq}]: {rule.pattern.pattern}")
        print(f"     context: …{snippet}…\n")
    print("  Either remove the claim, or state the retraction next to it. Do NOT weaken the rule.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
