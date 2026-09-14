"""Read-only host clock gate for this macOS paper deployment; never adjusts time."""

import asyncio
import re
from contextlib import suppress
from decimal import Decimal


class ClockBlocked(ValueError):
    pass


def assess_sntp(output: str) -> dict:
    lines = output.strip().splitlines()
    if len(lines) != 1:
        raise ClockBlocked("one unambiguous clock observation required")
    match = re.fullmatch(r"([+-]\d+(?:\.\d+)?) \+/- (\d+(?:\.\d+)?) time\.apple\.com \S+", lines[0])
    if match is None:
        raise ClockBlocked("unrecognized clock observation")
    offset, uncertainty = (Decimal(v) * 1000 for v in match.groups())
    if abs(offset) > Decimal(50) or uncertainty > Decimal(100):
        raise ClockBlocked("clock offset or uncertainty exceeds paper limits")
    return {
        "status": "HOST_CLOCK_SAMPLE_WITHIN_LIMITS",
        "offset_ms": str(offset),
        "uncertainty_ms": str(uncertainty),
        "clock_adjusted": False,
        "source": "time.apple.com",
        "authenticated_time_protocol": False,
    }


async def check_host_clock() -> dict:
    """Take a fresh bounded SNTP sample. Missing command or failed read blocks.

    This verifies the configured operational offset/uncertainty limits. SNTP is
    not authenticated time and is not a certificate of exchange clock accuracy.
    The caller's wall/monotonic deadline also detects clock steps during trading.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/sntp",
            "-t",
            "3",
            "-n",
            "1",
            "time.apple.com",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        raise ClockBlocked("read-only clock probe unavailable") from None
    try:
        async with asyncio.timeout(4):
            output, _ = await proc.communicate()
        if proc.returncode != 0 or len(output) > 4096:
            raise ClockBlocked("clock probe failed or exceeded output limit")
        return assess_sntp(output.decode("ascii"))
    except (TimeoutError, UnicodeError):
        raise ClockBlocked("clock probe timed out or returned invalid data") from None
    finally:
        if proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
