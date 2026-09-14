"""Disabled-by-default, paper-only transport using durable pre-I/O claims.

The application must supply a verified runtime readiness check. No production
readiness provider or activation is installed by this module. Tests inject a
mock transport and readiness checker; those are not evidence of live readiness.
"""

import asyncio
import json
import time
from decimal import Decimal

import httpx

from alphaforge.execution.spot_clock import check_host_clock
from alphaforge.execution.spot_evidence import verify_preparation
from alphaforge.execution.spot_intents import SpotIntentJournal
from alphaforge.execution.spot_paper import (
    PAPER_ORIGIN,
    PaperCredentials,
    PaperReader,
    account_digest,
    number,
    validate_account,
)
from alphaforge.execution.spot_risk import check_current_risk
from alphaforge.portfolio.spot_restart import SYMBOLS


class SubmissionBlocked(ValueError):
    pass


class PaperSubmitter:
    def __init__(
        self,
        credentials: PaperCredentials,
        *,
        account_binding: str,
        epoch: str,
        readiness_check=None,
        enabled=False,
        transport=None,
    ):
        self.reader = PaperReader(credentials, transport=transport)
        self.account_binding = account_binding
        self.epoch = epoch
        self.readiness_check = readiness_check
        self.enabled = enabled

    async def close(self):
        await self.reader.close()

    async def submit(
        self, journal: SpotIntentJournal, order: dict[str, str], *, valid_until_ms: int
    ) -> dict:
        """Make at most one POST attempt; all ambiguous outcomes remain reserved.

        The readiness callback must verify current data, clock, risk, strategy,
        account/epoch and source bindings. Callback success is a trusted application
        boundary, not independently proved by this transport. Activation is off
        unless the application explicitly configures both the callback and enable.
        """
        if self.enabled is not True or self.readiness_check is None:
            raise SubmissionBlocked("paper activation or readiness provider unavailable")
        started_wall_ns, started_mono_ns = time.time_ns(), time.monotonic_ns()
        now_ms = started_wall_ns // 1_000_000
        if type(valid_until_ms) is not int or not now_ms < valid_until_ms <= now_ms + 5_000:
            raise SubmissionBlocked("short-lived submission deadline required")
        deadline_mono_ns = started_mono_ns + valid_until_ms * 1_000_000 - started_wall_ns

        def check_deadline():
            wall, mono = time.time_ns(), time.monotonic_ns()
            if abs((wall - started_wall_ns) - (mono - started_mono_ns)) > 10_000_000:
                raise SubmissionBlocked("clock discontinuity during submission preparation")
            if wall // 1_000_000 >= valid_until_ms or mono >= deadline_mono_ns:
                raise SubmissionBlocked("submission deadline expired")
            return wall // 1_000_000

        fields = {
            "client_order_id",
            "symbol",
            "side",
            "qty",
            "type",
            "time_in_force",
            "limit_price",
        }
        if (
            set(order) != fields
            or order.get("symbol") not in SYMBOLS
            or order.get("side") not in {"buy", "sell"}
            or order.get("type") != "limit"
            or order.get("time_in_force") != "ioc"
        ):
            raise SubmissionBlocked("exact spot IOC limit intent required")
        client_id = order["client_order_id"]
        if not isinstance(client_id, str) or not 1 <= len(client_id) <= 48:
            raise SubmissionBlocked("invalid client order identity")
        qty, price = (
            number(order["qty"], positive=True),
            number(order["limit_price"], positive=True),
        )
        if qty * price > Decimal(200_000):
            raise SubmissionBlocked("order notional cap exceeded")
        binding = journal.conn.execute("SELECT account,epoch FROM binding").fetchone()
        if binding != (self.account_binding, self.epoch):
            raise SubmissionBlocked("journal does not bind this account and epoch")
        reserved = journal.conn.execute(
            "SELECT decision_ms FROM order_ids WHERE client_order_id=?", (client_id,)
        ).fetchone()
        if reserved is None:
            raise SubmissionBlocked("order has no durable decision")
        verify_preparation(journal, decision_ms=reserved[0])
        baseline = journal.baseline_for_order(client_id)
        if baseline["account_binding"] != self.account_binding:
            raise SubmissionBlocked("sealed baseline account mismatch")
        frozen = json.dumps(order, sort_keys=True, separators=(",", ":"))
        order = json.loads(frozen)
        account = await self.reader.get("/v2/account")
        if account_digest(account) != self.account_binding:
            raise SubmissionBlocked("authenticated account differs from binding")
        validate_account(account, require_funding=False)
        if order["side"] == "buy":
            available = min(number(account["cash"]), number(account["non_marginable_buying_power"]))
            if qty * price * Decimal("1.0025") > available:
                raise SubmissionBlocked("current cash cannot cover order and fee reserve")
        else:
            positions = await self.reader.get("/v2/positions")
            if not isinstance(positions, list):
                raise SubmissionBlocked("unverified positions")
            matching = [
                p
                for p in positions
                if p.get("symbol") in {order["symbol"], order["symbol"].replace("/", "")}
            ]
            if (
                len(matching) != 1
                or matching[0].get("asset_class") != "crypto"
                or matching[0].get("side") != "long"
                or number(matching[0].get("qty_available")) < qty
            ):
                raise SubmissionBlocked("current available spot position cannot cover sale")
        check_deadline()
        check_input = json.loads(frozen)
        try:
            async with asyncio.timeout((deadline_mono_ns - time.monotonic_ns()) / 1e9):
                await self.readiness_check(check_input)
                await check_host_clock()
                await check_current_risk(self.reader, journal, json.loads(frozen))
        except TimeoutError:
            raise SubmissionBlocked("readiness verification exceeded submission deadline") from None
        if json.dumps(check_input, sort_keys=True, separators=(",", ":")) != frozen:
            raise SubmissionBlocked("readiness check altered the reserved order")
        now_ms = check_deadline()
        intent = json.loads(frozen)
        claim = journal.claim_submission(intent, now_ms=now_ms)
        if claim != "CLAIMED_NOT_RUNTIME_CLEARANCE":
            return {"status": "ALREADY_ATTEMPTED_RECONCILE", "post_attempted": False}
        # No retry, redirect, or automatic journal release, including HTTP 4xx.
        post_attempted = False
        try:
            check_deadline()
            async with asyncio.timeout(5):
                post_attempted = True
                async with self.reader.client.stream(
                    "POST", PAPER_ORIGIN + "/v2/orders", json=intent
                ) as response:
                    if response.status_code not in (200, 201):
                        return {
                            "status": "HTTP_RESPONSE_REQUIRES_RECONCILIATION",
                            "http_status": response.status_code,
                            "post_attempted": True,
                        }
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 65_536:
                            raise ValueError("order response size budget")
                    result = json.loads(raw)
                    journal.record_acknowledgement(client_id, result)
            return {
                "status": "ACKNOWLEDGED_NOT_SETTLED",
                "post_attempted": post_attempted,
                "journal_clearance": False,
            }
        except (TimeoutError, httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            return {
                "status": "SUBMISSION_UNCERTAIN_RECONCILE",
                "post_attempted": post_attempted,
                "journal_clearance": False,
            }
