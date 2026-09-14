"""Inspect a spot journal or explicitly reconcile one decision. Never submits orders."""

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path

from alphaforge.execution.spot_ops import inspect_journal, recover_decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="read existing journal without credentials or network")
    status.add_argument("--journal", type=Path, required=True)
    recover = sub.add_parser(
        "recover", help="GET broker evidence and reconcile one sealed decision"
    )
    recover.add_argument("--journal", type=Path, required=True)
    recover.add_argument("--account-binding", required=True)
    recover.add_argument("--epoch", required=True)
    recover.add_argument("--decision-ms", type=int, required=True)
    recover.add_argument(
        "--until", required=True, help="fixed UTC activity cutoff, not a moving window"
    )
    args = parser.parse_args()
    try:
        if args.command == "status":
            report = inspect_journal(args.journal)
        else:
            report = asyncio.run(
                recover_decision(
                    args.journal,
                    account_binding=args.account_binding,
                    epoch=args.epoch,
                    decision_ms=args.decision_ms,
                    until=args.until,
                    credentials_path=Path.home() / ".config/alphaforge/alpaca_spot.env",
                )
            )
    except (OSError, ValueError, sqlite3.Error):
        # Do not print exception strings that may contain broker payloads or paths.
        report = {
            "status": "OPERATION_BLOCKED",
            "command": args.command,
            "submission_authorized": False,
            "decision_clearance": False,
        }
        print(json.dumps(report, indent=2))
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
