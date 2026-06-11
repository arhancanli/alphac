"""Symbol mapping: canonical instrument_id ↔ exchange symbol ↔ ccxt unified symbol.

Canonical instrument identity (dataDesign.md §2.3, buildabilityCritique.md ruling 3.2):

    "<EXCHANGE>:<MARKET>:<EXCHANGE_SYMBOL>"   e.g. "BINANCE:PERP:BTCUSDT"

- ``EXCHANGE`` and ``EXCHANGE_SYMBOL`` are uppercase, ``MARKET`` ∈ {``PERP``, ``SPOT``}
  (the :class:`~alphaforge.core.types.MarketType` member name).
- ccxt unified symbols: spot ``"BTC/USDT"``; linear perp ``"BTC/USDT:USDT"`` (settle
  currency equals the quote — inverse contracts are out of scope and rejected).
- Exchange symbols concatenate base+quote with no separator; the quote is recovered by
  longest-suffix match against :data:`KNOWN_QUOTES`, which handles multi-character
  quotes (``FDUSD`` vs ``USD``) and oddball bases (``1000SHIB``, ``BTCDOM``).

All functions are pure; malformed input raises :class:`~alphaforge.core.errors.SchemaError`.
"""

from __future__ import annotations

from typing import Final

from alphaforge.core.errors import SchemaError
from alphaforge.core.types import MarketType

__all__ = [
    "KNOWN_QUOTES",
    "SymbolMapper",
]

#: Quote currencies recognized when splitting concatenated exchange symbols, ordered
#: longest-first so that e.g. ``BTCFDUSD`` splits as ``BTC``/``FDUSD``, never ``BTCFD``/``USD``.
KNOWN_QUOTES: Final[tuple[str, ...]] = (
    "FDUSD",
    "BUSD",
    "TUSD",
    "USDC",
    "USDT",
    "DAI",
    "BNB",
    "BTC",
    "ETH",
    "EUR",
    "TRY",
    "USD",
)

_MARKET_LABELS: Final[dict[str, MarketType]] = {m.name: m for m in MarketType}


class SymbolMapper:
    """Pure, stateless conversions between the three symbol vocabularies.

    All methods are static; the class is a namespace, never instantiated with state.
    """

    @staticmethod
    def to_instrument_id(exchange: str, market_type: MarketType, exchange_symbol: str) -> str:
        """Build a canonical instrument_id; normalizes ``exchange``/``exchange_symbol`` to upper.

        Raises :class:`SchemaError` if either string is empty or contains ``":"``.
        """
        for name, value in (("exchange", exchange), ("exchange_symbol", exchange_symbol)):
            if not value or ":" in value:
                raise SchemaError(f"{name} must be a non-empty string without ':', got {value!r}")
        return f"{exchange.upper()}:{market_type.name}:{exchange_symbol.upper()}"

    @staticmethod
    def parse_instrument_id(instrument_id: str) -> tuple[str, MarketType, str]:
        """Split a canonical instrument_id into ``(exchange, market_type, exchange_symbol)``.

        Strict: exactly three non-empty colon-separated segments, exchange and symbol
        uppercase, market segment a :class:`MarketType` member name. Raises
        :class:`SchemaError` otherwise (never silently normalizes).
        """
        parts = instrument_id.split(":")
        if len(parts) != 3 or not all(parts):
            raise SchemaError(
                f"instrument_id must be 'EXCHANGE:MARKET:SYMBOL', got {instrument_id!r}"
            )
        exchange, market_label, symbol = parts
        if exchange != exchange.upper() or symbol != symbol.upper():
            raise SchemaError(f"instrument_id segments must be uppercase, got {instrument_id!r}")
        market_type = _MARKET_LABELS.get(market_label)
        if market_type is None:
            raise SchemaError(
                f"unknown market type {market_label!r} in {instrument_id!r}; "
                f"expected one of {sorted(_MARKET_LABELS)}"
            )
        return exchange, market_type, symbol

    @staticmethod
    def split_exchange_symbol(exchange_symbol: str) -> tuple[str, str]:
        """Split a concatenated exchange symbol into ``(base, quote)``.

        Longest-suffix match against :data:`KNOWN_QUOTES`; the base must be non-empty.
        Raises :class:`SchemaError` if no known quote matches or the base is empty.
        """
        for quote in KNOWN_QUOTES:
            if exchange_symbol.endswith(quote):
                base = exchange_symbol[: -len(quote)]
                if not base:
                    raise SchemaError(
                        f"exchange symbol {exchange_symbol!r} has empty base after "
                        f"stripping quote {quote!r}"
                    )
                return base, quote
        raise SchemaError(
            f"exchange symbol {exchange_symbol!r} ends with no known quote (known: {KNOWN_QUOTES})"
        )

    @staticmethod
    def to_ccxt(instrument_id: str) -> str:
        """Canonical instrument_id → ccxt unified symbol.

        ``"BINANCE:PERP:BTCUSDT"`` → ``"BTC/USDT:USDT"`` (linear perp, settle = quote);
        ``"BINANCE:SPOT:BTCUSDT"`` → ``"BTC/USDT"``. Raises :class:`SchemaError` on a
        malformed id or an unrecognized quote suffix.
        """
        _, market_type, symbol = SymbolMapper.parse_instrument_id(instrument_id)
        base, quote = SymbolMapper.split_exchange_symbol(symbol)
        if market_type is MarketType.PERP:
            return f"{base}/{quote}:{quote}"
        return f"{base}/{quote}"

    @staticmethod
    def from_ccxt(exchange: str, ccxt_symbol: str) -> str:
        """ccxt unified symbol → canonical instrument_id.

        ``"BTC/USDT:USDT"`` → perp, ``"BTC/USDT"`` → spot. The settle suffix (if any)
        must equal the quote (linear contracts only) and the quote must be in
        :data:`KNOWN_QUOTES` so the resulting id round-trips through :meth:`to_ccxt`.
        Raises :class:`SchemaError` on malformed/inverse/unknown-quote symbols.
        """
        head, sep, settle = ccxt_symbol.partition(":")
        base, slash, quote = head.partition("/")
        if not slash or not base or not quote or "/" in quote:
            raise SchemaError(f"ccxt symbol must be 'BASE/QUOTE[:SETTLE]', got {ccxt_symbol!r}")
        if sep:
            if ":" in settle or not settle:
                raise SchemaError(f"malformed settle suffix in ccxt symbol {ccxt_symbol!r}")
            if settle != quote:
                raise SchemaError(
                    f"inverse/non-linear contract {ccxt_symbol!r} unsupported: "
                    f"settle {settle!r} != quote {quote!r}"
                )
            market_type = MarketType.PERP
        else:
            market_type = MarketType.SPOT
        if quote.upper() not in KNOWN_QUOTES:
            raise SchemaError(
                f"quote {quote!r} of {ccxt_symbol!r} not in KNOWN_QUOTES; "
                "the id would not round-trip through to_ccxt"
            )
        return SymbolMapper.to_instrument_id(exchange, market_type, f"{base}{quote}")
