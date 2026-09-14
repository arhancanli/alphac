"""Read-only dedicated paper account probe; emits sanitized evidence, never orders."""

import asyncio
import json
from pathlib import Path

from alphaforge.execution.spot_paper import PaperCredentials, PaperReader, PaperReadError


async def preflight() -> dict:
    path = Path.home() / ".config/alphaforge/alpaca_spot.env"
    try:
        credentials = PaperCredentials.from_file(path)
    except PaperReadError as error:
        return {
            "status": "ACCOUNT_NOT_VERIFIED",
            "reason": str(error),
            "requests_sent": 0,
            "orders_submitted": 0,
            "runtime_clearance": False,
        }
    reader = PaperReader(credentials)
    try:
        # Empty exclusions cannot prove dedication; this observation never binds an epoch.
        return await reader.fresh_account_preflight(excluded_account_bindings=set())
    except PaperReadError as error:
        return {
            "status": "ACCOUNT_NOT_VERIFIED",
            "reason": str(error),
            "orders_submitted": 0,
            "runtime_clearance": False,
        }
    finally:
        await reader.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(preflight()), indent=2))
