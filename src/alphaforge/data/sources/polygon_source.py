"""``PolygonEquitiesSource`` — US cash equities (daily bars + corporate actions) via Polygon.io.

Scope (EQUITIES_SLEEVE.md §1): **US common-equity daily bars only.** Polygon.io is the
provider because it is survivorship-free (its reference endpoints expose *delisted*
tickers, not just the live listing) and requires no KYC. ETFs, warrants, units, and
non-common types are skipped at listing time, exactly as the crypto source serves
USDT-margined perps only.

Why this differs from the crypto (ccxt) source, and how the difference is handled:

* **No funding leg.** A perpetual settles funding; an equity has **corporate actions**
  (splits + dividends). :meth:`fetch_funding` therefore raises ``NotImplementedError``
  and the settlement leg is :meth:`fetch_corporate_actions`, which conforms to
  :data:`CORPORATE_ACTIONS_SCHEMA` (one row per split/dividend, with an explicit
  point-in-time ``available_at`` — the §3.2 funding-finding-18 discipline applied to
  actions).
* **Raw-in-lake, adjust-at-read.** OHLCV is fetched with ``adjusted=false`` so the lake
  stores **as-traded** prices/volume (immutable; never silently rewritten when a new
  split lands). Split/dividend adjustment is reconstructed point-in-time at *feature*
  time from the separately-stored corporate-actions dataset — this module only fetches
  the two raw legs (dataDesign.md §0.5; EQUITIES_SLEEVE.md §1.3 rationale).
* **Session calendar, daily bars.** Daily (:data:`~alphaforge.core.time.Timeframe.D1`)
  is the v1 native timeframe; an intraday request raises ``NotImplementedError`` so an
  accidental mis-aligned fetch fails loud rather than returning bad bars.
* **Survivorship-free identity.** Equity ids are collision-free
  (``"XNAS:CASH:AAPLUSD"`` via :meth:`SymbolMapper.equity_instrument_id`); a ticker that
  itself ends in a crypto quote token (``BTC``, ``ETH``) round-trips intact, never
  mis-split by the crypto ``KNOWN_QUOTES`` matcher (EQUITIES_CRITIQUE.md B4).

The concrete REST shape is Polygon's documented API (aggregates/bars, reference tickers
+ delisted tickers, splits, dividends), reached through :class:`PolygonClientProtocol`
so tests inject a fake returning canned dict payloads (no network, ever — mirrors
``test_ccxt_source.py``). Construction performs no I/O; a missing API key with no
injected client raises :class:`ConfigError` rather than issuing a silent unauthenticated
call. The live validation fires the moment a ``POLYGON_API_KEY`` lands.

All public methods take/return integer epoch milliseconds UTC (:data:`Ms`); ISO dates
from Polygon's reference endpoints are converted at the edge via
:func:`~alphaforge.core.time.parse_utc`.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from enum import StrEnum
from typing import Any, Final, Protocol

import httpx
import pyarrow as pa

from alphaforge.core.errors import ConfigError, SchemaError
from alphaforge.core.instruments import Instrument
from alphaforge.core.symbols import SymbolMapper
from alphaforge.core.time import Ms, Timeframe, from_ms, now_ms, parse_utc
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.ingest.retry import RateBudget, transient_retry
from alphaforge.data.schemas import (
    CORPORATE_ACTIONS_SCHEMA,
    OHLCV_SCHEMA,
    Dataset,
    validate_table,
)
from alphaforge.data.sources.base import DataSource

__all__ = [
    "CA_PUBLICATION_LAG_MS",
    "CORPORATE_ACTIONS_SCHEMA",
    "Adjustment",
    "PolygonClientProtocol",
    "PolygonEquitiesSource",
]

CA_PUBLICATION_LAG_MS: Final[int] = 86_400_000
"""Corporate-action publication lag δ_ca: 1 day, in milliseconds.

A split/dividend is *knowable* on its declaration date (or, absent one, its
ex/effective date), but is only reliably queryable on Polygon's reference API within a
day of becoming public. One day is the conservative point-in-time lag — the analogue of
:data:`~alphaforge.data.sources.ccxt_source.FUNDING_PUBLICATION_LAG_MS`. Every action
row's ``available_at`` is ``knowable_date + CA_PUBLICATION_LAG_MS``; the adjustment join
at read time uses ``available_at`` only, never the ex/effective date (leakage finding
18). It costs nothing at daily decision frequency and guarantees a backtest never folds
in a split before live trading could have known it.
"""

_AGGS_PAGE_LIMIT: Final[int] = 50_000
"""Max rows per ``/v2/aggs/.../range`` request (Polygon hard cap)."""

_REFERENCE_PAGE_LIMIT: Final[int] = 1000
"""Max rows per ``/v3/reference/*`` request (Polygon hard cap)."""

_REQUEST_WEIGHT: Final[int] = 1
"""Budget weight charged per Polygon REST request (Polygon meters req/min, not weight)."""

_COMMON_EQUITY_TYPES: Final[frozenset[str]] = frozenset({"CS", "ADRC"})
"""Polygon ticker ``type`` codes kept in v1: common stock (``CS``) and American
Depositary Receipt common (``ADRC``). ETFs, ETNs, warrants, units, preferred shares,
funds, and indices are excluded — the equity analogue of the crypto USDT-perp-only
filter. Documented so widening the universe is a one-line, reviewable change."""

_PRIMARY_EXCHANGE_TO_MIC: Final[dict[str, str]] = {
    "XNAS": "XNAS",
    "XNYS": "XNYS",
    "ARCX": "ARCX",
    "BATS": "BATS",
    "XASE": "XASE",
}
"""Polygon ``primary_exchange`` MIC → canonical id exchange segment. Polygon already
reports MICs, so this is largely identity; unlisted MICs fall back to the raw value
uppercased (a new venue must not silently drop instruments)."""

_DEFAULT_TICK_SIZE: Final[float] = 0.01
"""Penny tick — the US equity default (sub-dollar names trade in 0.0001 increments;
Polygon exposes no per-symbol tick, so this is a documented default like the crypto fee
defaults). EQUITIES_SLEEVE.md §1.1."""

_DEFAULT_LOT_SIZE: Final[float] = 1.0
_DEFAULT_MIN_QTY: Final[float] = 1.0
_DEFAULT_MIN_NOTIONAL: Final[float] = 0.0
_DEFAULT_FEE_BPS: Final[float] = 0.0
"""Whole-share lot/min-qty and zero commission (per-trade SEC/TAF charges live in the
cost model, not the instrument fee fields). EQUITIES_SLEEVE.md §1.1."""

_TRANSIENT_STATUS: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
"""HTTP statuses Polygon returns under transient pressure (rate limit + 5xx). 401/403
(auth), 404 (bad ticker), and other 4xx are permanent and propagate immediately."""


class Adjustment(StrEnum):
    """Price-adjustment policy requested from Polygon's aggregates endpoint.

    The lake stores **raw** (``SPLIT_NONE``) bars only — adjustment is reconstructed
    point-in-time at feature time from the corporate-actions dataset, so a backtest at
    decision ``T`` sees only the adjustment factors knowable by ``T`` (EQUITIES_SLEEVE.md
    §1.3). ``SPLIT_ONLY`` exists for the live/diagnostic path that wants Polygon's
    split-adjusted (but NOT dividend-adjusted) series; it must never feed the lake.
    """

    SPLIT_NONE = "none"
    SPLIT_ONLY = "split_only"


class PolygonClientProtocol(Protocol):
    """The exact Polygon REST surface :class:`PolygonEquitiesSource` calls.

    A structural :class:`typing.Protocol` so the test fake is mypy-strict without
    subclassing. Each method returns Polygon's documented JSON body as a
    :class:`~collections.abc.Mapping` (the adapter reads ``"results"``/``"next_url"`` and
    never assumes a concrete client class). The real implementation
    (:class:`_HttpxPolygonClient`) is a thin ``httpx`` wrapper.
    """

    def get_aggs(
        self,
        ticker: str,
        *,
        multiplier: int,
        timespan: str,
        from_ms: Ms,
        to_ms: Ms,
        adjusted: bool,
        limit: int,
    ) -> Mapping[str, Any]:
        """``GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}``."""
        ...

    def list_tickers(
        self,
        *,
        market: str,
        active: bool,
        date: str | None,
        limit: int,
        cursor: str | None,
    ) -> Mapping[str, Any]:
        """``GET /v3/reference/tickers`` (one page; pagination via ``next_url`` cursor)."""
        ...

    def get_ticker_details(self, ticker: str, *, date: str | None) -> Mapping[str, Any]:
        """``GET /v3/reference/tickers/{ticker}`` — lifecycle + listing enrichment."""
        ...

    def list_splits(
        self,
        *,
        ticker: str | None,
        execution_date_lte: str | None,
        limit: int,
        cursor: str | None,
    ) -> Mapping[str, Any]:
        """``GET /v3/reference/splits`` (one page)."""
        ...

    def list_dividends(
        self,
        *,
        ticker: str | None,
        ex_date_lte: str | None,
        limit: int,
        cursor: str | None,
    ) -> Mapping[str, Any]:
        """``GET /v3/reference/dividends`` (one page)."""
        ...


def _opt_float(value: Any) -> float | None:
    """Parse a Polygon-payload number (str/int/float) to float; None/'' → None."""
    if value is None or value == "":
        return None
    return float(value)


def _date_to_ms(value: str) -> Ms:
    """Polygon reference date → epoch ms at 00:00 UTC.

    Polygon emits dates as ``YYYY-MM-DD`` (ex/execution/list dates) or full RFC-3339
    instants (``delisted_utc``). A bare date is pinned to UTC midnight; an instant is
    parsed as-is. Raises :class:`SchemaError` on an unparseable value (a malformed
    reference payload must fail loud, not be silently dropped).
    """
    try:
        if len(value) == 10 and value[4] == "-" and value[7] == "-":
            return parse_utc(f"{value}T00:00:00+00:00")
        return parse_utc(value)
    except (ValueError, IndexError) as exc:
        raise SchemaError(f"unparseable Polygon date {value!r}: {exc}") from exc


class PolygonEquitiesSource(DataSource):
    """US cash-equity market data (daily bars + corporate actions) from Polygon.io.

    Construction performs no I/O; every network call happens inside the fetch methods,
    each metered by the optional rate budget and retried on transient errors. A missing
    ``api_key`` with no injected ``client`` raises :class:`ConfigError` — there is no
    silent unauthenticated call.

    Args:
        api_key: Polygon API key. Required when ``client`` is not injected; ``None`` +
            ``client=None`` raises :class:`ConfigError`.
        rate_budget: Optional client-side request budget; when present, ``acquire(1)`` is
            charged before *every* REST request (Polygon's free tier is 5 req/min — the
            budget is the throttle). ``None`` issues requests unthrottled.
        client: Injectable Polygon-shaped client (tests pass a fake returning canned dict
            payloads). ``None`` constructs the real :class:`_HttpxPolygonClient` from
            ``api_key``.
        adjustment: Aggregates adjustment policy. **Must stay** :attr:`Adjustment.SPLIT_NONE`
            for the lake path (raw-in-lake, adjust-at-read); other values are for
            diagnostics only and must never feed the writer (EQUITIES_SLEEVE.md §1.3).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        rate_budget: RateBudget | None = None,
        client: PolygonClientProtocol | None = None,
        adjustment: Adjustment = Adjustment.SPLIT_NONE,
    ) -> None:
        if client is None:
            if not api_key:
                raise ConfigError(
                    "PolygonEquitiesSource requires an api_key (or an injected client); "
                    "refusing to issue unauthenticated Polygon requests"
                )
            client = _HttpxPolygonClient(api_key)
        self._client = client
        self._budget = rate_budget
        self._adjustment = adjustment
        self.name = "polygon.equities"
        self._retry = transient_retry((PolygonTransientError, httpx.TransportError))
        #: instrument_id -> raw vendor ticker (e.g. "BRK.B"), built in list_instruments
        #: and owned here so the fetch round-trip never re-derives the dotted ticker from
        #: the (separator-free) canonical id.
        self._vendor_ticker: dict[str, str] = {}

    # ------------------------------------------------------------------ helpers

    def _acquire(self) -> None:
        """Charge one request against the rate budget (no-op when budget is None)."""
        if self._budget is not None:
            self._budget.acquire(_REQUEST_WEIGHT)

    @staticmethod
    def _canonical_ticker(vendor_ticker: str) -> str:
        """Vendor ticker → separator-free canonical form (``"BRK.B"`` → ``"BRKB"``).

        Dots (class shares) and slashes are removed; the result is uppercased. The raw
        vendor ticker is preserved separately for the fetch round-trip — this is only the
        id-canonicalization step (EQUITIES_SLEEVE.md §1.1).
        """
        return vendor_ticker.replace(".", "").replace("/", "").upper()

    def _resolve_ticker(self, instrument_id: str) -> str:
        """Canonical id → raw vendor ticker for the aggregates/splits/dividends calls.

        Prefers the ``instrument_id → vendor_ticker`` map built by
        :meth:`list_instruments` (so dotted tickers round-trip); falls back to the
        canonical ticker parsed straight from the id when the map has no entry (e.g. a
        fetch issued before listing in the same process — correct for non-dotted names).

        Raises:
            SchemaError: malformed id (propagated from the mapper).
            ValueError: a well-formed non-``CASH`` id this source does not serve.
        """
        _, market_type, _ = SymbolMapper.parse_instrument_id(instrument_id)
        if market_type is not MarketType.CASH:
            raise ValueError(
                f"PolygonEquitiesSource serves CASH equities only; got {instrument_id!r} "
                f"with market type {market_type.value!r}"
            )
        cached = self._vendor_ticker.get(instrument_id)
        if cached is not None:
            return cached
        _, ticker = SymbolMapper.parse_equity_id(instrument_id)
        return ticker

    def _paginate(
        self,
        fetch: Any,
        **kwargs: Any,
    ) -> Iterator[Mapping[str, Any]]:
        """Walk a cursor-paginated Polygon reference endpoint, yielding every result row.

        ``fetch`` is one of the client's ``list_*`` methods; ``kwargs`` are its
        per-call arguments minus ``cursor``. Each page is metered and transient-retried;
        the ``next_url`` cursor is extracted and threaded until exhausted. Deterministic:
        same canned pages in, same row stream out.
        """
        cursor: str | None = None
        while True:
            self._acquire()
            body: Mapping[str, Any] = self._retry(fetch, cursor=cursor, **kwargs)
            results = body.get("results") or []
            yield from results
            cursor = _next_cursor(body)
            if cursor is None:
                break

    def _instrument_from_ticker(
        self,
        listing: Mapping[str, Any],
        details: Mapping[str, Any],
        as_of: Ms,
    ) -> Instrument:
        """Map a Polygon ticker (listing row + details) to a populated :class:`Instrument`.

        Identity: ``primary_exchange`` (MIC) + the canonicalized ticker build the
        collision-free id via :meth:`SymbolMapper.equity_instrument_id`; the raw vendor
        ticker is recorded in ``self._vendor_ticker`` for the fetch round-trip. Lifecycle
        is the **survivorship spine**: ``list_date`` → ``listed_ts`` (0 when absent),
        ``delisted_utc`` → ``delisted_ts`` (``None`` while active). Filters/fees are
        documented US-equity defaults (Polygon exposes no per-symbol tick).

        Raises:
            SchemaError: a ticker row with no usable ``ticker`` field.
        """
        vendor_ticker = listing.get("ticker") or details.get("ticker")
        if not isinstance(vendor_ticker, str) or not vendor_ticker:
            raise SchemaError(f"Polygon ticker row missing 'ticker': {listing!r}")
        raw_mic = str(
            listing.get("primary_exchange") or details.get("primary_exchange") or ""
        ).upper()
        mic = _PRIMARY_EXCHANGE_TO_MIC.get(raw_mic, raw_mic or "XNAS")
        canonical = self._canonical_ticker(vendor_ticker)
        instrument_id = SymbolMapper.equity_instrument_id(mic, canonical)
        self._vendor_ticker[instrument_id] = vendor_ticker

        list_date = listing.get("list_date") or details.get("list_date")
        listed_ts: Ms = _date_to_ms(str(list_date)) if list_date else 0

        delisted_raw = listing.get("delisted_utc") or details.get("delisted_utc")
        if delisted_raw:
            delisted_ms = _date_to_ms(str(delisted_raw))
            # Clamp to keep the Instrument invariant delisted_ts > listed_ts; a venue
            # reporting an implausible (<= listed) delist falls back to the observation.
            delisted_ts: Ms | None = (
                delisted_ms if delisted_ms > listed_ts else max(as_of, listed_ts + 1)
            )
        else:
            delisted_ts = None

        return Instrument(
            instrument_id=instrument_id,
            asset_class=AssetClass.EQUITY,
            market_type=MarketType.CASH,
            base=canonical,
            quote="USD",
            tick_size=_DEFAULT_TICK_SIZE,
            lot_size=_DEFAULT_LOT_SIZE,
            min_qty=_DEFAULT_MIN_QTY,
            min_notional=_DEFAULT_MIN_NOTIONAL,
            contract_multiplier=1.0,
            can_short=True,
            maker_fee_bps=_DEFAULT_FEE_BPS,
            taker_fee_bps=_DEFAULT_FEE_BPS,
            funding_interval_hours=None,
            listed_ts=listed_ts,
            delisted_ts=delisted_ts,
        )

    # ----------------------------------------------------------- DataSource API

    def list_instruments(self, *, as_of: Ms) -> list[Instrument]:
        """Return US common equities — **including delisted tickers** — from Polygon.

        .. warning:: **Survivorship-free ONLY because the delisted set is included.** The
           live ``active=true`` listing alone is survivorship-biased (a name fully purged
           before this system first ran never appears); pulling ``active=false`` too is
           what makes the historical universe whole (leakageCritique.md finding 1, the
           equity analogue of the crypto Binance-Vision archive). A known pre-period
           delisting (e.g. Lehman) therefore appears here with ``delisted_ts`` set, so the
           SCD2 store ranks it while it lived and the universe builder closes its interval
           at ``delisted_ts``.

        Both the active and inactive ``/v3/reference/tickers`` pages are walked
        (cursor-paginated) and filtered to the common-equity ``type`` set
        (:data:`_COMMON_EQUITY_TYPES`); ETFs/warrants/units are excluded. Each ticker is
        enriched via ``/v3/reference/tickers/{ticker}`` for ``list_date`` / ``delisted_utc``
        / ``primary_exchange``, building the ``instrument_id ↔ vendor_ticker`` map. The
        result is de-duplicated on ``instrument_id`` (a name can appear on both pages
        across a re-list) keeping the most-recently-observed record, and sorted by
        ``instrument_id`` (the :class:`DataSource` contract).

        Args:
            as_of: Observation timestamp (epoch ms UTC); stamps SCD2 versioning upstream
                and is the fallback ``delisted_ts`` for a dead ticker whose venue
                timestamp is missing/implausible.

        Returns:
            Instruments sorted by ``instrument_id``.
        """
        by_id: dict[str, Instrument] = {}
        date_str = _ms_to_date(as_of)
        for active in (True, False):
            for listing in self._paginate(
                self._client.list_tickers,
                market="stocks",
                active=active,
                date=date_str,
                limit=_REFERENCE_PAGE_LIMIT,
            ):
                ticker_type = str(listing.get("type") or "")
                if ticker_type not in _COMMON_EQUITY_TYPES:
                    continue
                vendor_ticker = listing.get("ticker")
                details: Mapping[str, Any] = (
                    self._ticker_details(str(vendor_ticker), date_str) if vendor_ticker else {}
                )
                inst = self._instrument_from_ticker(listing, details, as_of)
                by_id[inst.instrument_id] = inst
        return sorted(by_id.values(), key=lambda inst: inst.instrument_id)

    def _ticker_details(self, vendor_ticker: str, date_str: str) -> Mapping[str, Any]:
        """Fetch one ticker's reference details (metered + retried); ``{}`` if absent."""
        self._acquire()
        body: Mapping[str, Any] = self._retry(
            self._client.get_ticker_details, vendor_ticker, date=date_str
        )
        results = body.get("results")
        return results if isinstance(results, Mapping) else {}

    def fetch_ohlcv(
        self,
        instrument_id: str,
        *,
        tf: Timeframe,
        since: Ms,
        until: Ms,
        now: Ms | None = None,
    ) -> pa.Table:
        """Fetch closed **raw** daily bars with ``ts_open`` in ``[since, until)``.

        Uses ``/v2/aggs/.../range`` with ``adjusted=false`` so the stored bars are
        **as-traded** (raw): split/dividend adjustment is reconstructed point-in-time at
        feature time from the corporate-actions dataset, never baked into the lake
        (EQUITIES_SLEEVE.md §1.3). Daily (:attr:`Timeframe.D1`) only —
        ``multiplier=1, timespan="day"``; any other timeframe raises
        ``NotImplementedError`` (intraday equities are post-v1, and an accidental
        intraday fetch must fail loud rather than return mis-aligned bars).

        Polygon agg mapping: ``t`` (window-open epoch ms, the session date at 00:00 UTC) →
        ``ts_open``; ``o/h/l/c`` → OHLC; ``v`` (shares) → ``volume``; dollar volume → the
        canonical ``quote_volume`` (``vw * v`` when ``vw`` present, else ``c * v``,
        documented — this is what the equity universe ranks ADV on); ``n`` → ``n_trades``.
        ``quality_flags`` is 0 (a natively-fetched equity bar carries no resampler-derived
        flag semantics) and ``ingested_at`` is the wall clock at fetch.

        Pagination walks ``from_ms`` in pages of 50 000 until the page is empty/short or
        ``until`` is reached. Open times must be strictly increasing — a non-monotonic
        payload raises :class:`SchemaError`. **No partial bars, ever:** any row with
        ``ts_open + tf.ms > (now or wall clock)`` is dropped here, before the writer.

        Args:
            instrument_id: Canonical CASH-equity id, e.g. ``"XNAS:CASH:AAPLUSD"``.
            tf: Bar timeframe; must be :attr:`Timeframe.D1` in v1.
            since: Inclusive lower bound on ``ts_open`` (epoch ms UTC).
            until: Exclusive upper bound on ``ts_open`` (epoch ms UTC).
            now: Injectable closed-bar cutoff (epoch ms UTC); ``None`` reads the wall
                clock once via :func:`now_ms`.

        Returns:
            Table conforming to :data:`~alphaforge.data.schemas.OHLCV_SCHEMA`, sorted and
            unique on ``ts_open`` (possibly empty; ``until == since`` is an empty no-op).

        Raises:
            NotImplementedError: ``tf`` is not :attr:`Timeframe.D1`.
            ValueError: ``until < since``, or a non-``CASH`` id this source does not serve.
            SchemaError: malformed id or a non-monotonic exchange payload.
        """
        if tf is not Timeframe.D1:
            raise NotImplementedError(
                f"PolygonEquitiesSource fetches daily (D1) bars only in v1; got {tf.value!r} "
                "(intraday equities are post-v1)"
            )
        ticker = self._resolve_ticker(instrument_id)
        if until < since:
            raise ValueError(f"until ({until}) must be >= since ({since})")
        now_eff: Ms = now_ms() if now is None else now
        ingested_at: Ms = now_ms()
        adjusted = self._adjustment is Adjustment.SPLIT_ONLY

        rows: list[Mapping[str, Any]] = []
        prev_ts: int | None = None
        cursor = since
        while cursor < until:
            self._acquire()
            body: Mapping[str, Any] = self._retry(
                self._client.get_aggs,
                ticker,
                multiplier=1,
                timespan="day",
                from_ms=cursor,
                to_ms=until - 1,
                adjusted=adjusted,
                limit=_AGGS_PAGE_LIMIT,
            )
            page = body.get("results") or []
            if not page:
                break
            for agg in page:
                ts = int(agg["t"])
                if prev_ts is not None and ts <= prev_ts:
                    raise SchemaError(
                        f"aggs for {ticker!r} not strictly increasing: open_time {ts} "
                        f"after {prev_ts}"
                    )
                prev_ts = ts
                if ts < since or ts >= until:
                    continue
                if ts + tf.ms > now_eff:
                    continue  # in-progress bar: close is in the future — never serve it
                rows.append(agg)
            cursor = int(page[-1]["t"]) + tf.ms
            if len(page) < _AGGS_PAGE_LIMIT:
                break

        table = pa.Table.from_pydict(
            {
                "instrument_id": [instrument_id] * len(rows),
                "ts_open": [int(a["t"]) for a in rows],
                "open": [float(a["o"]) for a in rows],
                "high": [float(a["h"]) for a in rows],
                "low": [float(a["l"]) for a in rows],
                "close": [float(a["c"]) for a in rows],
                "volume": [float(a["v"]) for a in rows],
                "quote_volume": [_dollar_volume(a) for a in rows],
                "n_trades": [None if a.get("n") is None else int(a["n"]) for a in rows],
                "quality_flags": [0] * len(rows),
                "ingested_at": [ingested_at] * len(rows),
            },
            schema=OHLCV_SCHEMA,
        )
        validate_table(table, Dataset.OHLCV)
        return table

    def fetch_funding(self, instrument_id: str, *, since: Ms, until: Ms) -> pa.Table:
        """Not applicable to equities — raises ``NotImplementedError``.

        An equity has no funding leg; its settlement is corporate actions. The
        :class:`DataSource` ABC requires the three methods, so this one is honest about
        the mismatch and points at :meth:`fetch_corporate_actions` (EQUITIES_SLEEVE.md
        §1.3). It is never reached on a correct equity path; reaching it is a routing bug,
        which this surfaces immediately rather than returning a silent empty table.
        """
        raise NotImplementedError(
            "equities have no funding leg; use fetch_corporate_actions "
            f"(instrument {instrument_id!r})"
        )

    def fetch_corporate_actions(
        self, instrument_id: str, *, since: Ms, until: Ms
    ) -> pa.Table:
        """Fetch splits + dividends with ``ex_date`` in ``[since, until)`` (the settlement leg).

        Splits come from ``/v3/reference/splits`` (``execution_date`` is the ex/effective
        date; ``split_to/split_from`` is the adjustment ``ratio``). Dividends come from
        ``/v3/reference/dividends`` (``ex_dividend_date``, ``cash_amount``). Both are
        cursor-paginated and merged into one table sorted by ``(ex_date, action_type)``.

        **Point-in-time stamping (the corporate-actions analogue of funding finding 18):**
        each row's ``available_at`` is ``knowable_date + CA_PUBLICATION_LAG_MS`` where
        ``knowable_date`` is the ``declaration_date`` when Polygon provides one, else the
        ex/effective date. The adjustment join at read time uses ``available_at`` only,
        never ``ex_date`` — a split announced after a decision must not touch that
        decision's prices.

        Args:
            instrument_id: Canonical CASH-equity id, e.g. ``"XNAS:CASH:AAPLUSD"``.
            since: Inclusive lower bound on ``ex_date`` (epoch ms UTC).
            until: Exclusive upper bound on ``ex_date`` (epoch ms UTC).

        Returns:
            Table conforming to :data:`CORPORATE_ACTIONS_SCHEMA`, sorted by
            ``(ex_date, action_type)`` (possibly empty; ``until == since`` is an empty
            no-op).

        Raises:
            ValueError: ``until < since``, or a non-``CASH`` id this source does not serve.
            SchemaError: malformed id or an unparseable reference date.
        """
        ticker = self._resolve_ticker(instrument_id)
        if until < since:
            raise ValueError(f"until ({until}) must be >= since ({since})")
        if until == since:
            return _empty_corporate_actions()
        ingested_at: Ms = now_ms()
        until_date = _ms_to_date(until - 1)

        events: list[tuple[Ms, str, Ms, float, float | None]] = []
        for split in self._paginate(
            self._client.list_splits,
            ticker=ticker,
            execution_date_lte=until_date,
            limit=_REFERENCE_PAGE_LIMIT,
        ):
            ex_raw = split.get("execution_date")
            if not ex_raw:
                continue
            ex_date = _date_to_ms(str(ex_raw))
            if not since <= ex_date < until:
                continue
            ratio = _split_ratio(split)
            knowable = split.get("declaration_date") or ex_raw
            available_at = _date_to_ms(str(knowable)) + CA_PUBLICATION_LAG_MS
            events.append((ex_date, "split", available_at, ratio, None))

        for div in self._paginate(
            self._client.list_dividends,
            ticker=ticker,
            ex_date_lte=until_date,
            limit=_REFERENCE_PAGE_LIMIT,
        ):
            ex_raw = div.get("ex_dividend_date")
            if not ex_raw:
                continue
            ex_date = _date_to_ms(str(ex_raw))
            if not since <= ex_date < until:
                continue
            cash = _opt_float(div.get("cash_amount"))
            knowable = div.get("declaration_date") or ex_raw
            available_at = _date_to_ms(str(knowable)) + CA_PUBLICATION_LAG_MS
            events.append((ex_date, "dividend", available_at, 1.0, cash))

        events.sort(key=lambda e: (e[0], e[1]))
        table = pa.Table.from_pydict(
            {
                "instrument_id": [instrument_id] * len(events),
                "action_type": [e[1] for e in events],
                "ex_date": [e[0] for e in events],
                "available_at": [e[2] for e in events],
                "ratio": [e[3] for e in events],
                "cash_amount": [e[4] for e in events],
                "ingested_at": [ingested_at] * len(events),
            },
            schema=CORPORATE_ACTIONS_SCHEMA,
        )
        validate_table(table, Dataset.CORPORATE_ACTIONS)
        return table


def _dollar_volume(agg: Mapping[str, Any]) -> float | None:
    """Dollar (quote) volume for one aggregate: ``vw * v`` when ``vw`` present, else ``c * v``.

    Polygon's ``vw`` is the volume-weighted average price for the bar; ``vw * v`` is exact
    dollar volume. When ``vw`` is absent (some thin names) the close-times-volume fallback
    is documented and used. ``None`` only if both volume and price are unparseable.
    """
    volume = _opt_float(agg.get("v"))
    if volume is None:
        return None
    vwap = _opt_float(agg.get("vw"))
    if vwap is not None:
        return vwap * volume
    close = _opt_float(agg.get("c"))
    return None if close is None else close * volume


def _split_ratio(split: Mapping[str, Any]) -> float:
    """Split adjustment ratio ``split_to / split_from`` (2-for-1 → 2.0, 1-for-10 → 0.1).

    Raises :class:`SchemaError` on a missing/zero ``split_from`` (a degenerate split would
    silently poison every adjusted price).
    """
    split_to = _opt_float(split.get("split_to"))
    split_from = _opt_float(split.get("split_from"))
    if split_to is None or split_from is None or split_from == 0.0:
        raise SchemaError(f"split row missing usable split_to/split_from: {split!r}")
    return split_to / split_from


def _next_cursor(body: Mapping[str, Any]) -> str | None:
    """Extract the pagination cursor from a Polygon reference response, or ``None``.

    Polygon paginates with a full ``next_url`` carrying a ``cursor`` query parameter; the
    client honours either a raw ``cursor`` field or the ``cursor`` embedded in ``next_url``.
    An absent/empty value ends pagination.
    """
    cursor = body.get("next_cursor") or body.get("cursor")
    if cursor:
        return str(cursor)
    next_url = body.get("next_url")
    if not next_url:
        return None
    _, _, query = str(next_url).partition("cursor=")
    token = query.split("&", 1)[0]
    return token or None


def _ms_to_date(ms: Ms) -> str:
    """Epoch ms → ``YYYY-MM-DD`` (UTC) for Polygon reference ``date`` / ``*_lte`` params."""
    return from_ms(ms).strftime("%Y-%m-%d")


def _empty_corporate_actions() -> pa.Table:
    """Zero-row table conforming to :data:`CORPORATE_ACTIONS_SCHEMA`."""
    return CORPORATE_ACTIONS_SCHEMA.empty_table()


class PolygonTransientError(Exception):
    """A transient Polygon HTTP failure (429 + 5xx) — retried by :func:`transient_retry`.

    Raised by :class:`_HttpxPolygonClient` (and matched by the adapter's retry policy)
    when Polygon returns a :data:`_TRANSIENT_STATUS`. Permanent failures (401/403 auth,
    404 bad ticker, other 4xx) raise :class:`~httpx.HTTPStatusError` and propagate
    immediately, unretried.
    """


class _HttpxPolygonClient:
    """Thin ``httpx`` implementation of :class:`PolygonClientProtocol` (the live path).

    Holds the API key, issues GETs against ``https://api.polygon.io``, raises
    :class:`PolygonTransientError` on :data:`_TRANSIENT_STATUS` (so the adapter retries)
    and ``raise_for_status`` on other 4xx (permanent). It is exercised ONLY when a real
    ``POLYGON_API_KEY`` is configured — every unit test injects a fake client instead, so
    this class never touches the network in CI.
    """

    _BASE_URL: Final[str] = "https://api.polygon.io"

    def __init__(self, api_key: str, *, timeout_s: float = 30.0) -> None:
        self._api_key = api_key
        self._http = httpx.Client(base_url=self._BASE_URL, timeout=timeout_s)

    def _get(self, path: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        query = {k: v for k, v in params.items() if v is not None}
        query["apiKey"] = self._api_key
        response = self._http.get(path, params=query)
        if response.status_code in _TRANSIENT_STATUS:
            raise PolygonTransientError(f"Polygon {response.status_code} on {path}")
        response.raise_for_status()
        body: Mapping[str, Any] = response.json()
        return body

    def get_aggs(
        self,
        ticker: str,
        *,
        multiplier: int,
        timespan: str,
        from_ms: Ms,
        to_ms: Ms,
        adjusted: bool,
        limit: int,
    ) -> Mapping[str, Any]:
        path = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_ms}/{to_ms}"
        return self._get(
            path,
            {"adjusted": "true" if adjusted else "false", "sort": "asc", "limit": limit},
        )

    def list_tickers(
        self,
        *,
        market: str,
        active: bool,
        date: str | None,
        limit: int,
        cursor: str | None,
    ) -> Mapping[str, Any]:
        return self._get(
            "/v3/reference/tickers",
            {
                "market": market,
                "active": "true" if active else "false",
                "date": date,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def get_ticker_details(self, ticker: str, *, date: str | None) -> Mapping[str, Any]:
        return self._get(f"/v3/reference/tickers/{ticker}", {"date": date})

    def list_splits(
        self,
        *,
        ticker: str | None,
        execution_date_lte: str | None,
        limit: int,
        cursor: str | None,
    ) -> Mapping[str, Any]:
        return self._get(
            "/v3/reference/splits",
            {
                "ticker": ticker,
                "execution_date.lte": execution_date_lte,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def list_dividends(
        self,
        *,
        ticker: str | None,
        ex_date_lte: str | None,
        limit: int,
        cursor: str | None,
    ) -> Mapping[str, Any]:
        return self._get(
            "/v3/reference/dividends",
            {
                "ticker": ticker,
                "ex_dividend_date.lte": ex_date_lte,
                "limit": limit,
                "cursor": cursor,
            },
        )
