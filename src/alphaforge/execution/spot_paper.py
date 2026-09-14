"""Bounded read-only Alpaca paper preflight and order recovery.

This module has no POST/DELETE method. Preflight establishes a fresh account
candidate, not research admission, clock accuracy, or runtime trade clearance.
"""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

PAPER_ORIGIN = "https://paper-api.alpaca.markets"


class PaperReadError(ValueError):
    """Sanitized error; never include credentials or response bodies."""


@dataclass(frozen=True)
class PaperCredentials:
    key: str = field(repr=False)
    secret: str = field(repr=False)

    @classmethod
    def from_file(cls, path: Path) -> "PaperCredentials":
        # No shell evaluation, environment fallback, or implicit equity account.
        try:
            raw = path.read_bytes()
        except OSError:
            raise PaperReadError("dedicated paper credential file unavailable") from None
        if len(raw) > 16_384:
            raise PaperReadError("credential file exceeds size budget")
        values = {}
        try:
            for line in raw.decode().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key in values:
                    raise ValueError()
                value = value.strip()
                if value[:1] in ("'", '"'):
                    if len(value) < 2 or value[-1] != value[0]:
                        raise ValueError()
                    value = value[1:-1]
                values[key] = value
            if values.get("APCA_API_BASE_URL") != PAPER_ORIGIN:
                raise ValueError()
            key, secret = values["APCA_API_KEY_ID"], values["APCA_API_SECRET_KEY"]
            if any(not v or len(v) > 256 or any(c.isspace() for c in v) for v in (key, secret)):
                raise ValueError()
        except (ValueError, KeyError, UnicodeError):
            raise PaperReadError("invalid dedicated paper credentials or origin") from None
        return cls(key, secret)


class PaperReader:
    def __init__(self, credentials: PaperCredentials, *, transport=None):
        self.client = httpx.AsyncClient(
            headers={"APCA-API-KEY-ID": credentials.key, "APCA-API-SECRET-KEY": credentials.secret},
            timeout=4,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def close(self):
        await self.client.aclose()

    async def get(self, path: str, *, params=None):
        if path not in {
            "/v2/account",
            "/v2/positions",
            "/v2/orders",
            "/v2/assets",
            "/v2/account/activities",
            "/v2/orders:by_client_order_id",
        }:
            raise PaperReadError("unapproved read endpoint")
        return await self._read(PAPER_ORIGIN + path, params=params)

    async def read_activities(self, *, after: str, until: str, expected_account_binding: str):
        """Bounded all-type activity scan, pinned to creation-time UTC interval.

        Dates filter creation time, which can differ from fee settlement dates.
        Exhausted pagination does not prove that delayed fees have been posted.
        Fetch all types so cash transfers and corrections cannot be filtered out.
        """
        try:
            first = datetime.fromisoformat(after.replace("Z", "+00:00"))
            last = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if (
                first.tzinfo is None
                or last.tzinfo is None
                or first.utcoffset() != timedelta(0)
                or last.utcoffset() != timedelta(0)
                or not timedelta(0) < last - first <= timedelta(days=7)
                or last > datetime.now(UTC)
            ):
                raise ValueError()
        except (TypeError, ValueError, AttributeError):
            raise PaperReadError("fixed UTC activity window up to seven days required") from None
        if not isinstance(expected_account_binding, str) or not expected_account_binding:
            raise PaperReadError("expected account binding required")
        params = {
            "after": first.isoformat(),
            "until": last.isoformat(),
            "direction": "asc",
            "page_size": 100,
        }
        records = []
        seen = set()
        try:
            async with asyncio.timeout(45):
                before = account_digest(await self.get("/v2/account"))
                if before != expected_account_binding:
                    raise PaperReadError("activity account binding mismatch")
                for _page_index in range(21):
                    page = await self.get("/v2/account/activities", params=params)
                    if not isinstance(page, list) or len(page) > 100:
                        raise PaperReadError("invalid activity page")
                    if not page:
                        break
                    if len(records) + len(page) > 2000:
                        raise PaperReadError("activity count budget exhausted")
                    for record in page:
                        if not isinstance(record, dict):
                            raise PaperReadError("invalid activity record")
                        identity = record.get("id")
                        if (
                            not isinstance(identity, str)
                            or not 1 <= len(identity) <= 256
                            or identity in seen
                        ):
                            raise PaperReadError("duplicate or missing activity identity")
                        if (
                            not isinstance(record.get("activity_type"), str)
                            or not record["activity_type"]
                        ):
                            raise PaperReadError("missing activity classification")
                        # When supplied, check creation time, never substitute the
                        # settlement-date field or infer timezone from the opaque ID.
                        if record.get("created_at") is not None:
                            try:
                                created = datetime.fromisoformat(
                                    record["created_at"].replace("Z", "+00:00")
                                )
                                if created.tzinfo is None or not first <= created <= last:
                                    raise ValueError()
                            except (ValueError, TypeError, AttributeError):
                                raise PaperReadError(
                                    "activity creation time outside interval"
                                ) from None
                        seen.add(identity)
                        records.append(record)
                    params = {**params, "page_token": page[-1]["id"]}
                else:
                    raise PaperReadError("activity pagination budget exhausted")
                after_binding = account_digest(await self.get("/v2/account"))
                if after_binding != before:
                    raise PaperReadError("account binding changed during activity scan")
        except TimeoutError:
            raise PaperReadError("activity scan time budget exhausted") from None
        return {
            "account_binding": before,
            "after": first.isoformat(),
            "until": last.isoformat(),
            "records": tuple(records),
            "pages_read": _page_index + 1,
            "pagination_exhausted": True,
            "settlement_complete": False,
            "late_posting_excluded_from_completeness_claim": True,
            "journal_clearance": False,
        }

    async def read_books(self):
        """Read full Alpaca US books; account routing must be verified separately."""
        from alphaforge.execution.spot_book import parse_rest_books

        raw = await self._read(
            "https://data.alpaca.markets/v1beta3/crypto/us/latest/orderbooks",
            params={"symbols": "BTC/USD,ETH/USD"},
        )
        received_ns = time.time_ns()
        try:
            return parse_rest_books(raw, received_ns=received_ns)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise PaperReadError("invalid book snapshot or clock ordering") from None

    async def _read(self, url, *, params):
        try:
            async with asyncio.timeout(5):
                async with self.client.stream("GET", url, params=params) as response:
                    if response.status_code != 200:
                        raise PaperReadError(f"paper read HTTP {response.status_code}")
                    buf = bytearray()
                    async for chunk in response.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > 1_048_576:
                            raise PaperReadError("paper response exceeds size budget")
                    return json.loads(buf, parse_float=Decimal)
        except (TimeoutError, httpx.HTTPError, json.JSONDecodeError, UnicodeError):
            raise PaperReadError("paper read unavailable or malformed") from None

    async def fresh_account_preflight(self, *, excluded_account_bindings: set[str]) -> dict:
        """Account must be empty; exclusions must come from verified other sleeve accounts.

        This report never automatically binds or initializes an epoch. Account
        ownership/dedication remains unverified if no exclusion bindings exist.
        """
        account = await self.get("/v2/account")
        binding = account_digest(account)
        if binding in excluded_account_bindings:
            raise PaperReadError("account already belongs to another sleeve")
        validate_account(account)
        positions = await self.get("/v2/positions")
        orders = await self.get("/v2/orders", params={"status": "open", "limit": 500})
        if not isinstance(positions, list) or not isinstance(orders, list):
            raise PaperReadError("malformed position or order list")
        if positions or orders:
            raise PaperReadError("new epoch requires an empty dedicated account")
        assets = await self.get("/v2/assets", params={"asset_class": "crypto", "status": "active"})
        if not isinstance(assets, list):
            raise PaperReadError("malformed asset list")
        found = {}
        for asset in assets:
            if not isinstance(asset, dict):
                raise PaperReadError("malformed asset entry")
            symbol = asset.get("symbol")
            if symbol not in ("BTC/USD", "ETH/USD"):
                continue
            if (
                symbol in found
                or asset.get("class") != "crypto"
                or asset.get("tradable") is not True
            ):
                raise PaperReadError("missing or ambiguous crypto capability")
            if asset.get("status") != "active":
                raise PaperReadError("inactive spot asset")
            found[symbol] = {
                k: str(number(asset.get(k), positive=True))
                for k in ("min_order_size", "min_trade_increment", "price_increment")
            }
        if set(found) != {"BTC/USD", "ETH/USD"}:
            raise PaperReadError("required spot assets unavailable")
        return {
            "status": "FRESH_PAPER_ACCOUNT_OBSERVED",
            "account_binding": binding,
            "other_sleeve_bindings_checked": len(excluded_account_bindings),
            "dedication_verified": False,
            "assets": found,
            "orders_submitted": 0,
            "runtime_clearance": False,
        }

    async def recover_order(self, intent: dict[str, str]) -> dict:
        raw = await self.get(
            "/v2/orders:by_client_order_id", params={"client_order_id": intent["client_order_id"]}
        )
        return assess_order(intent, raw)


def account_digest(raw: object) -> str:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
        raise PaperReadError("missing account identity")
    return hashlib.sha256((PAPER_ORIGIN + ":" + raw["id"]).encode()).hexdigest()


def number(raw, *, positive=False) -> Decimal:
    if not isinstance(raw, str):
        raise PaperReadError("numeric API string required")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise PaperReadError("invalid numeric API value") from None
    if not value.is_finite() or value < 0 or (positive and value == 0):
        raise PaperReadError("invalid numeric API range")
    return value


def validate_account(raw: dict, *, require_funding: bool = True) -> None:
    if raw.get("status") != "ACTIVE" or raw.get("currency") != "USD":
        raise PaperReadError("active USD account required")
    for key in ("trading_blocked", "account_blocked", "trade_suspended_by_user"):
        if raw.get(key) is not False:
            raise PaperReadError("account restriction unknown or active")
    if raw.get("crypto_status") != "ACTIVE":
        raise PaperReadError("crypto eligibility unverified")
    number(raw.get("equity"), positive=True)
    number(raw.get("cash"), positive=require_funding)
    number(raw.get("non_marginable_buying_power"), positive=require_funding)


def assess_order(intent: dict[str, str], raw: object) -> dict:
    """Distinguish terminal execution from completed balance/fee reconciliation."""
    if not isinstance(raw, dict):
        raise PaperReadError("missing order recovery")
    for key in ("client_order_id", "symbol", "side", "type", "time_in_force"):
        if raw.get(key) != intent.get(key) or intent.get(key) is None:
            raise PaperReadError("broker order does not match reserved intent")
    for key in ("qty", "limit_price"):
        if number(raw.get(key), positive=True) != number(intent.get(key), positive=True):
            raise PaperReadError("broker order sizing differs from reservation")
    if raw.get("asset_class") != "crypto" or not isinstance(raw.get("id"), str) or not raw["id"]:
        raise PaperReadError("unverified crypto order identity")
    filled = number(raw.get("filled_qty"))
    qty = number(intent["qty"], positive=True)
    if filled > qty:
        raise PaperReadError("overfilled order")
    status = raw.get("status")
    terminal = status in {"filled", "canceled", "expired", "rejected"}
    if (status == "filled" and filled != qty) or (status == "rejected" and filled != 0):
        raise PaperReadError("inconsistent terminal order")
    if filled:
        price = number(raw.get("filled_avg_price"), positive=True)
        limit = number(intent["limit_price"], positive=True)
        if (intent["side"] == "buy" and price > limit) or (
            intent["side"] == "sell" and price < limit
        ):
            raise PaperReadError("fill violates limit price")
    return {
        "client_order_id": intent["client_order_id"],
        "execution_terminal": terminal,
        "filled_qty": str(filled),
        "fee_and_balance_reconciliation_required": filled > 0,
        "resubmission_allowed": False,
        "journal_clearance": False,
    }
