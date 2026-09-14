#!/usr/bin/env python3
"""Flip drawdown control v1 live, as one declared, re-pinned, tested change.

WHY A SCRIPT. Activation touches six files that must agree byte for byte: the contract's
``activation.live``, the sleeves' read source in ``configs/base.yaml``, a change_log entry in
``config/live_change_contract.json`` with ``contaminates_forward_record`` true (that entry's date
starts the new forward-evidence epoch), the re-pinned fingerprint in the same file and in
``config/forward_evidence_contract.json``, the current-book drawdown study's pin, and the
pre-registration draft's pin. Done by hand, one of them gets forgotten and the live-change gate
blocks the next publish, or worse, does not. The script does all six in one pass, re-measures
the fingerprint the same way the gate does, and prints what still has to happen on Frankfurt.

It changes nothing without ``--decision`` (the owner's recorded words) and ``--activated-on``
(the UTC date the first sleeve applies the multiplier). ``--dry-run`` prints the plan.

The one thing it cannot do is make the crypto host read the flipped contract: that is a
companion-file rollout of ``config/drawdown_control_contract.json`` and ``configs/base.yaml``
through ``scripts/deploy_crypto_position_attribution_vps.py`` (owner-run). Until it lands, the
equity sleeves apply the brake and the crypto sleeve does not; the change_log entry says so.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CONTROL = REPO / "config" / "drawdown_control_contract.json"
BASE_YAML = REPO / "configs" / "base.yaml"
LIVE_CHANGE = REPO / "config" / "live_change_contract.json"
FORWARD_EVIDENCE = REPO / "config" / "forward_evidence_contract.json"
STUDY_PIN = REPO / "scripts" / "analyze_current_book_drawdown.py"
PREREG_DRAFT = REPO / "docs" / "design" / "FORWARD_PREREGISTRATION_DRAFT.md"
FINGERPRINTER = REPO / "scripts" / "export_live_config_fingerprint.py"


def _load_fingerprinter() -> Any:
    spec = importlib.util.spec_from_file_location("live_config_fingerprinter", FINGERPRINTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_source_https(text: str) -> str:
    """Add ``book_ladder.source: https`` under ``risk:`` (idempotent, comment-preserving)."""
    if re.search(r"^\s+book_ladder:\s*(#.*)?$", text, re.M):
        return re.sub(
            r"(^\s+book_ladder:[^\n]*\n(?:\s+\w+:[^\n]*\n)*?\s+source:\s*)\S+",
            r"\1https",
            text,
            flags=re.M,
        )
    block = (
        "  book_ladder:                 # BOOK-level drawdown brake (drawdown control v1)\n"
        "    source: https              # every sleeve reads the public artifact; activated "
        "by the contract\n"
    )
    return re.sub(r"^risk:\s*\n", "risk:\n" + block, text, count=1, flags=re.M)


def plan(*, decision: str, activated_on: str, now: dt.datetime | None = None) -> dict[str, Any]:
    """Compute every edit without writing; the caller applies them atomically."""
    dt.date.fromisoformat(activated_on)
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    if control["activation"].get("live") is True:
        raise SystemExit("already live; nothing to do")
    live_change = json.loads(LIVE_CHANGE.read_text(encoding="utf-8"))
    forward = json.loads(FORWARD_EVIDENCE.read_text(encoding="utf-8"))
    old_fp = live_change["declared_fingerprint"]
    if forward["required_live_config_fingerprint"] != old_fp:
        raise SystemExit("forward-evidence contract and live-change contract disagree already")
    study = STUDY_PIN.read_text(encoding="utf-8")
    draft = PREREG_DRAFT.read_text(encoding="utf-8")
    if study.count(old_fp) != 1 or draft.count(old_fp) != 1:
        raise SystemExit("the study or the draft does not carry exactly one copy of the old pin")

    control["activation"] = {
        **control["activation"],
        "live": True,
        "activated_on": activated_on,
        "decision": {
            "recorded_at": (now or dt.datetime.now(dt.UTC)).isoformat(),
            "by": "Arhan Canli (owner)",
            "words": decision,
            "how": "scripts/activate_book_drawdown_brake.py",
        },
    }
    control["status"] = control["activation"].get("status_after_activation", "MECHANISM_LIVE")
    ladder = control["ladder"]
    entry = {
        "date": activated_on,
        "change": (
            "drawdown control v1 ACTIVATED: config/drawdown_control_contract.json activation.live "
            "is true and configs/base.yaml risk.book_ladder.source is https. From this date every "
            "sleeve multiplies its target gross by the BOOK-level multiplier the publisher derives "
            f"from the combined book's published marks: half gross at {ladder['dd_half_frac']:.1%} "
            f"below the high-water mark, flat at {ladder['dd_flat_frac']:.1%}, absorbing until an "
            "owner rearm in config/book_ladder_rearms.json. The equity sleeves apply it from the "
            "next cycle after this commit; the crypto sleeve applies it from the companion-file "
            "rollout of the contract and base.yaml to Frankfurt, whose receipt is recorded in the "
            "operator log."
        ),
        "reason": (
            "The owner's 11 percent maximum-drawdown bound is a bound on the combined book. The "
            "declared ladder was measured on the current-composition paths and accepted "
            "(artifacts/analysis/drawdown_control_v1: regime p95 0.1645 to 0.1102, p99 0.2065 to "
            "0.1116, halt probability 0.064, drift cost 0.0074 over two years), the consumers were "
            "wired default-off and tested (PR #32), and the owner decided to activate: "
            f"{decision!r}."
        ),
        "evidence": (
            "artifacts/engineering/live_config_fingerprint.json; "
            "artifacts/engineering/book_drawdown_ladder.json; "
            "config/drawdown_control_contract.json activation.decision; "
            "docs/design/DRAWDOWN_CONTROL_V1_PROTOCOL.md; docs/design/OPERATOR_LOG_2026-09.md"
        ),
        "contaminates_forward_record": True,
        "note": (
            "A trading change: the book is sized differently from this date whenever the book "
            "ladder is below 1. The forward-evidence epoch restarts on this date; returns before "
            "it are published as a prior epoch and never pooled (forward_evidence_contract "
            "rules.configuration_change)."
        ),
    }
    return {
        "old_fingerprint": old_fp,
        "control": control,
        "base_yaml": _set_source_https(BASE_YAML.read_text(encoding="utf-8")),
        "live_change": live_change,
        "forward": forward,
        "entry": entry,
        "study": study,
        "draft": draft,
    }


def apply(p: dict[str, Any]) -> str:
    """Write the six files, re-measure, and return the new fingerprint."""
    CONTROL.write_text(json.dumps(p["control"], indent=2, ensure_ascii=False) + "\n", "utf-8")
    BASE_YAML.write_text(p["base_yaml"], encoding="utf-8")
    fingerprinter = _load_fingerprinter()
    fp = fingerprinter.build_fingerprint()
    new_fp = str(fp["fingerprint"])
    old_fp = p["old_fingerprint"]
    if new_fp == old_fp:
        raise SystemExit("the fingerprint did not move; activation is not on the hashed surface")
    live_change = p["live_change"]
    live_change["declared_fingerprint"] = new_fp
    live_change["declared_surface"] = fp["surface"]
    live_change["declared_at"] = p["entry"]["date"]
    live_change["change_log"].append(p["entry"])
    LIVE_CHANGE.write_text(json.dumps(live_change, indent=2, ensure_ascii=False) + "\n", "utf-8")
    forward = p["forward"]
    forward["required_live_config_fingerprint"] = new_fp
    FORWARD_EVIDENCE.write_text(json.dumps(forward, indent=2, ensure_ascii=False) + "\n", "utf-8")
    STUDY_PIN.write_text(p["study"].replace(old_fp, new_fp), encoding="utf-8")
    short_old, short_new = old_fp[7:15], new_fp[7:15]
    draft = p["draft"].replace(old_fp, new_fp)
    draft = re.sub(rf"sha256:{short_old}…[0-9a-f]{{7}}", f"sha256:{short_new}…{new_fp[-7:]}", draft)
    PREREG_DRAFT.write_text(draft, encoding="utf-8")
    fingerprinter.main()
    return new_fp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--decision", required=True, help="the owner's recorded words")
    ap.add_argument("--activated-on", required=True, help="UTC date, YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    p = plan(decision=args.decision, activated_on=args.activated_on)
    if args.dry_run:
        print(json.dumps({"entry": p["entry"], "old_fingerprint": p["old_fingerprint"]}, indent=2))
        return 0
    new_fp = apply(p)
    print(f"ACTIVATED on {args.activated_on}: fingerprint {p['old_fingerprint']} -> {new_fp}")
    print("next: uv run python scripts/check_live_change_declared.py; then roll out")
    print("      config/drawdown_control_contract.json and configs/base.yaml to Frankfurt as")
    print("      companion files (scripts/deploy_crypto_position_attribution_vps.py --apply).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
