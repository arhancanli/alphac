#!/usr/bin/env python3
"""Validate a frozen pre-result reservation against its exact trial config."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Final

from alphaforge.validation.trial_reservation import (
    ReservationError,
    validate_reservation,
)

REPO: Final[Path] = Path(__file__).resolve().parent.parent

__all__ = ["ReservationError", "validate_reservation"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reservation", type=Path)
    parser.add_argument("trial_config", type=Path)
    args = parser.parse_args()
    reservation = json.loads(args.reservation.read_text(encoding="utf-8"))
    trial_config = json.loads(args.trial_config.read_text(encoding="utf-8"))
    result = validate_reservation(reservation, trial_config=trial_config, repo=REPO)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
