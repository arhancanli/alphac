"""Local paper-account evidence capture; no valuation or operating clearance."""

import asyncio
import hashlib
import json
import os
import time
from decimal import Decimal
from pathlib import Path

from alphaforge.execution.spot_paper import PaperReader, account_digest


def _encode(value):
    if isinstance(value, Decimal) and value.is_finite():
        return {"decimal_json_number": str(value)}
    raise ValueError("unsupported evidence value")


def canonical(value):
    return json.dumps(value, default=_encode, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


class ObservationReader(PaperReader):
    """Retain parsed response bodies, not wire bytes or authentication headers.

    Receipt timing includes body decoding. Wall time is uncalibrated; monotonic
    values measure local durations only. Endpoint responses remain sequential.
    """

    def __init__(self, credentials, *, transport=None, wall=time.time_ns,
                 monotonic=time.monotonic_ns):
        super().__init__(credentials, transport=transport)
        self.wall, self.monotonic = wall, monotonic
        self.receipts = []

    async def get(self, path, *, params=None):
        receipt = {"path": path, "params": dict(params or {}),
                   "request_start_wall_ns": self.wall(),
                   "request_start_monotonic_ns": self.monotonic()}
        try:
            response = await super().get(path, params=params)
            # Round trip into a detached JSON-safe copy without binary-float loss.
            receipt["parsed_response"] = json.loads(canonical(response))
            receipt["status"] = "RECEIVED"
            return response
        except (Exception, asyncio.CancelledError):
            receipt["status"] = "READ_FAILED"
            # Exception bodies can contain credentials or server payloads.
            raise
        finally:
            receipt["receipt_monotonic_ns"] = self.monotonic()
            receipt["receipt_wall_ns"] = self.wall()
            receipt["elapsed_ns"] = (receipt["receipt_monotonic_ns"]
                                      - receipt["request_start_monotonic_ns"])
            self.receipts.append(receipt)


async def collect(reader: ObservationReader, *, expected_binding: str,
                  after: str, until: str):
    """One bounded capture; incomplete scans retain receipts and fail closed."""
    if (not isinstance(expected_binding, str) or len(expected_binding) != 64
            or any(c not in "0123456789abcdef" for c in expected_binding)):
        raise ValueError("explicit SHA256 account binding required")
    if reader.receipts:
        raise ValueError("fresh observation reader required")
    gaps = {"NO_ATOMIC_SOURCE_CUT", "UNCALIBRATED_LOCAL_WALL_CLOCK",
            "NO_PER_POSITION_PRICE_RECEIPT", "FLOW_SETTLEMENT_NOT_PROVEN",
            "ACCOUNT_PARTITION_DEDICATION_NOT_PROVEN"}
    scan = None
    stable = False
    try:
        async with asyncio.timeout(60):
            first = await reader.get("/v2/account")
            if account_digest(first) != expected_binding:
                raise ValueError("account mismatch")
            positions = await reader.get("/v2/positions")
            if not isinstance(positions, list) or len(positions) > 10000:
                raise ValueError("invalid positions")
            scan = await reader.read_activities(
                after=after, until=until, expected_account_binding=expected_binding)
            last_positions = await reader.get("/v2/positions")
            if not isinstance(last_positions, list) or len(last_positions) > 10000:
                raise ValueError("invalid positions")
            last = await reader.get("/v2/account")
            if account_digest(last) != expected_binding:
                raise ValueError("account mismatch")
            # Strict equality is diagnostic: price updates may change either body.
            stable = first == last and positions == last_positions
            if not stable:
                gaps.add("ACCOUNT_OR_POSITION_RESPONSES_CHANGED")
    except Exception:
        gaps.add("INCOMPLETE_OR_INVALID_CAPTURE")
    previous = None
    for r in reader.receipts:
        if (r["elapsed_ns"] < 0 or r["receipt_wall_ns"] < r["request_start_wall_ns"]
                or (previous is not None and (
                    r["request_start_wall_ns"] < previous["receipt_wall_ns"]
                    or r["request_start_monotonic_ns"] < previous["receipt_monotonic_ns"]))):
            gaps.add("LOCAL_CLOCK_ORDERING_FAILURE")
        previous = r
    packet = {"schema": "canli.portfolio-observation.v1",
              "status": "OBSERVATION_ONLY_NOT_VALUATION",
              "expected_account_binding": expected_binding,
              "requested_activity_window": {"after": after, "until": until},
              "receipts": reader.receipts, "activity_scan": scan,
              "repeated_response_agreement": stable,
              "blocking_reasons": sorted(gaps), "valuation_snapshot": None,
              "source_authentication_verified": False, "runtime_clearance": False,
              "targets_verified": False,
              "body_encoding": "parsed JSON; decimal numbers tagged; not original wire bytes"}
    detached = json.loads(canonical(packet))
    detached["content_sha256"] = hashlib.sha256(canonical(detached)).hexdigest()
    return detached


def save_capture(path: Path, packet: dict):
    """Exclusive private file creation; never overwrite earlier evidence."""
    body = canonical(packet) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
