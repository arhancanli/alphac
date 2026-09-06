"""Block the publish if the live trading configuration has changed without being declared.

Exit 0 = the configuration in force matches `config/live_change_contract.json`.
Exit 1 = it does not, and the deploy must not proceed.

WHAT THIS CAN AND CANNOT DO, stated honestly because the distinction decides the design.

By the time this runs, an undeclared configuration change has ALREADY reached the trading loop —
the tick trades before it publishes. So this cannot prevent contamination of the forward record;
`tests/unit/test_live_change_is_declared.py` is the defense that does, by failing before the
change is ever committed. What this buys is that the contamination stops being INVISIBLE: the
published bundle freezes and its `generated_at` goes stale, which is a symptom somebody notices,
instead of a silent drift in how the book sizes itself.

It deliberately does NOT halt trading. Halting would open a gap in the forward record, and a gap
is the same harm this exists to prevent — the record's value is its continuity. A marked
discontinuity is recoverable; a hole is not, and neither is a silent change.

Same shape and the same reasoning as `scripts/check_retracted_claims.py`, which for 41 ticks
printed a warning and published anyway. A check that cannot stop the thing it checks is not a
gate, it is a log line.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "config" / "live_change_contract.json"

sys.path.insert(0, str(REPO / "scripts"))

from export_live_config_fingerprint import build_fingerprint  # noqa: E402


def main() -> int:
    if not CONTRACT.exists():
        print(f"BLOCKED: no live-change contract at {CONTRACT.relative_to(REPO)}")
        return 1

    declared = json.loads(CONTRACT.read_text())
    measured = build_fingerprint()

    if measured["fingerprint"] == declared["declared_fingerprint"]:
        print(f"live config declared OK  {measured['fingerprint']}")
        return 0

    print("BLOCKED: THE LIVE TRADING CONFIGURATION CHANGED WITHOUT BEING DECLARED.")
    print(f"  declared: {declared['declared_fingerprint']}")
    print(f"  measured: {measured['fingerprint']}")

    declared_surface = declared.get("declared_surface", {})
    for section, measured_values in measured["surface"].items():
        declared_values = declared_surface.get(section, {})
        keys = sorted(set(declared_values) | set(measured_values))
        for key in keys:
            before, after = declared_values.get(key), measured_values.get(key)
            if before != after:
                print(f"    {section}.{key}: {before!r} -> {after!r}")

    print()
    print("  The book has ALREADY traded under the new configuration — this blocks the publish,")
    print("  not the trade. The forward record now contains a discontinuity, and the forward")
    print("  record is the only evidence that can defeat deflation. Record the change in")
    print("  change_log in config/live_change_contract.json with its reason and evidence, mark")
    print("  the record at this date, and re-run scripts/export_live_config_fingerprint.py.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
