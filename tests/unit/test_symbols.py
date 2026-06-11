"""Unit tests for alphaforge.core.symbols — canonical id ↔ exchange ↔ ccxt mapping."""

from __future__ import annotations

import pytest

from alphaforge.core.errors import SchemaError
from alphaforge.core.symbols import KNOWN_QUOTES, SymbolMapper
from alphaforge.core.types import MarketType

# (market_type, exchange_symbol, instrument_id, ccxt_symbol) — incl. multi-char quote
# and oddball-base cases (1000SHIBUSDT, BTCDOMUSDT) that break naive 3/4-char splits.
CORPUS: list[tuple[MarketType, str, str, str]] = [
    (MarketType.PERP, "BTCUSDT", "BINANCE:PERP:BTCUSDT", "BTC/USDT:USDT"),
    (MarketType.SPOT, "BTCUSDT", "BINANCE:SPOT:BTCUSDT", "BTC/USDT"),
    (MarketType.PERP, "ETHUSDT", "BINANCE:PERP:ETHUSDT", "ETH/USDT:USDT"),
    (MarketType.PERP, "1000SHIBUSDT", "BINANCE:PERP:1000SHIBUSDT", "1000SHIB/USDT:USDT"),
    (MarketType.PERP, "1000PEPEUSDT", "BINANCE:PERP:1000PEPEUSDT", "1000PEPE/USDT:USDT"),
    (MarketType.PERP, "BTCDOMUSDT", "BINANCE:PERP:BTCDOMUSDT", "BTCDOM/USDT:USDT"),
    (MarketType.PERP, "ETHUSDC", "BINANCE:PERP:ETHUSDC", "ETH/USDC:USDC"),
    (MarketType.SPOT, "BTCFDUSD", "BINANCE:SPOT:BTCFDUSD", "BTC/FDUSD"),
    (MarketType.SPOT, "BNBBUSD", "BINANCE:SPOT:BNBBUSD", "BNB/BUSD"),
    (MarketType.SPOT, "ETHBTC", "BINANCE:SPOT:ETHBTC", "ETH/BTC"),
    (MarketType.SPOT, "USDCUSDT", "BINANCE:SPOT:USDCUSDT", "USDC/USDT"),
    (MarketType.PERP, "DOGEUSDT", "BINANCE:PERP:DOGEUSDT", "DOGE/USDT:USDT"),
]


class TestToInstrumentId:
    def test_basic_perp(self) -> None:
        iid = SymbolMapper.to_instrument_id("BINANCE", MarketType.PERP, "BTCUSDT")
        assert iid == "BINANCE:PERP:BTCUSDT"

    def test_normalizes_case(self) -> None:
        iid = SymbolMapper.to_instrument_id("binance", MarketType.SPOT, "btcusdt")
        assert iid == "BINANCE:SPOT:BTCUSDT"

    @pytest.mark.parametrize(
        ("exchange", "symbol"),
        [("", "BTCUSDT"), ("BINANCE", ""), ("BIN:ANCE", "BTCUSDT"), ("BINANCE", "BTC:USDT")],
    )
    def test_rejects_empty_or_colon(self, exchange: str, symbol: str) -> None:
        with pytest.raises(SchemaError):
            SymbolMapper.to_instrument_id(exchange, MarketType.PERP, symbol)


class TestParseInstrumentId:
    def test_round_trips_to_instrument_id(self) -> None:
        for market_type, symbol, iid, _ in CORPUS:
            assert SymbolMapper.parse_instrument_id(iid) == ("BINANCE", market_type, symbol)
            assert SymbolMapper.to_instrument_id("BINANCE", market_type, symbol) == iid

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "BTCUSDT",
            "BINANCE:BTCUSDT",
            "BINANCE:PERP:BTC:USDT",
            "BINANCE:FUTURES:BTCUSDT",
            "BINANCE:perp:BTCUSDT",
            "binance:PERP:BTCUSDT",
            "BINANCE:PERP:btcusdt",
            "BINANCE:PERP:",
            ":PERP:BTCUSDT",
            "BINANCE::BTCUSDT",
        ],
    )
    def test_malformed_raises_schema_error(self, bad: str) -> None:
        with pytest.raises(SchemaError):
            SymbolMapper.parse_instrument_id(bad)


class TestSplitExchangeSymbol:
    def test_longest_quote_wins(self) -> None:
        # FDUSD must beat the shorter USD suffix.
        assert SymbolMapper.split_exchange_symbol("BTCFDUSD") == ("BTC", "FDUSD")
        assert SymbolMapper.split_exchange_symbol("BNBBUSD") == ("BNB", "BUSD")

    def test_oddball_bases(self) -> None:
        assert SymbolMapper.split_exchange_symbol("1000SHIBUSDT") == ("1000SHIB", "USDT")
        assert SymbolMapper.split_exchange_symbol("BTCDOMUSDT") == ("BTCDOM", "USDT")

    def test_unknown_quote_raises(self) -> None:
        with pytest.raises(SchemaError):
            SymbolMapper.split_exchange_symbol("BTCXYZ")

    def test_empty_base_raises(self) -> None:
        with pytest.raises(SchemaError):
            SymbolMapper.split_exchange_symbol("USDT")

    def test_known_quotes_ordered_longest_first(self) -> None:
        lengths = [len(q) for q in KNOWN_QUOTES]
        assert lengths == sorted(lengths, reverse=True)


class TestToCcxt:
    @pytest.mark.parametrize(("_mt", "_sym", "iid", "ccxt"), CORPUS)
    def test_corpus(self, _mt: MarketType, _sym: str, iid: str, ccxt: str) -> None:
        assert SymbolMapper.to_ccxt(iid) == ccxt

    def test_unknown_quote_raises(self) -> None:
        with pytest.raises(SchemaError):
            SymbolMapper.to_ccxt("BINANCE:PERP:BTCXYZ")

    def test_malformed_id_raises(self) -> None:
        with pytest.raises(SchemaError):
            SymbolMapper.to_ccxt("BTC/USDT:USDT")


class TestFromCcxt:
    @pytest.mark.parametrize(("_mt", "_sym", "iid", "ccxt"), CORPUS)
    def test_corpus(self, _mt: MarketType, _sym: str, iid: str, ccxt: str) -> None:
        assert SymbolMapper.from_ccxt("BINANCE", ccxt) == iid

    def test_lowercase_exchange_normalized(self) -> None:
        assert SymbolMapper.from_ccxt("binance", "BTC/USDT:USDT") == "BINANCE:PERP:BTCUSDT"

    def test_inverse_contract_rejected(self) -> None:
        with pytest.raises(SchemaError):
            SymbolMapper.from_ccxt("BINANCE", "BTC/USD:BTC")

    @pytest.mark.parametrize(
        "bad",
        ["BTCUSDT", "BTC/", "/USDT", "BTC/USDT:", "BTC/USDT:USDT:USDT", "BTC//USDT", ""],
    )
    def test_malformed_raises(self, bad: str) -> None:
        with pytest.raises(SchemaError):
            SymbolMapper.from_ccxt("BINANCE", bad)

    def test_unknown_quote_rejected_early(self) -> None:
        # Would not round-trip through to_ccxt, so it must fail at ingestion.
        with pytest.raises(SchemaError):
            SymbolMapper.from_ccxt("BINANCE", "BTC/XYZ")


class TestRoundTrip:
    """to_ccxt ∘ from_ccxt = id and from_ccxt ∘ to_ccxt = id over the corpus."""

    @pytest.mark.parametrize(("_mt", "_sym", "iid", "ccxt"), CORPUS)
    def test_ccxt_fixed_point(self, _mt: MarketType, _sym: str, iid: str, ccxt: str) -> None:
        assert SymbolMapper.to_ccxt(SymbolMapper.from_ccxt("BINANCE", ccxt)) == ccxt

    @pytest.mark.parametrize(("_mt", "_sym", "iid", "ccxt"), CORPUS)
    def test_instrument_id_fixed_point(
        self, _mt: MarketType, _sym: str, iid: str, ccxt: str
    ) -> None:
        assert SymbolMapper.from_ccxt("BINANCE", SymbolMapper.to_ccxt(iid)) == iid
