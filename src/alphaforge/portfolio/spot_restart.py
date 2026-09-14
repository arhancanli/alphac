"""Unadmitted spot baseline: closed daily bars only; no network or return evaluation."""

from dataclasses import dataclass
from decimal import Decimal

DAY_MS = 86_400_000
SYMBOLS = ("BTC/USD", "ETH/USD")
STRATEGY_ID = "alphaforge_spot_trend_v1"


@dataclass(frozen=True)
class DailyClose:
    # UTC boundary ending the daily interval, not the vendor's bar-start timestamp.
    end_ms: int
    close: Decimal


def target_weights(
    histories: dict[str, tuple[DailyClose, ...]], *, decision_ms: int
) -> dict[str, Decimal]:
    """45% per coin above its 200-day mean; unused allocation stays in cash.

    Missing, stale, unfinished or malformed data raises rather than impersonating
    an intentional cash signal. The caller must record a blocked decision.
    """
    if type(decision_ms) is not int or decision_ms < DAY_MS:
        raise ValueError("invalid decision timestamp")
    if set(histories) != set(SYMBOLS):
        raise ValueError("exact BTC/USD and ETH/USD histories required")
    last_end = decision_ms // DAY_MS * DAY_MS
    targets = {}
    for symbol in SYMBOLS:
        bars = histories[symbol]
        if len(bars) != 200:
            raise ValueError("exactly 200 completed daily observations required")
        expected = range(last_end - 199 * DAY_MS, last_end + 1, DAY_MS)
        for bar, end in zip(bars, expected, strict=True):
            if (
                type(bar.end_ms) is not int
                or bar.end_ms != end
                or not isinstance(bar.close, Decimal)
                or not bar.close.is_finite()
                or bar.close <= 0
            ):
                raise ValueError("invalid or non-contiguous closed daily bars")
        mean = sum((bar.close for bar in bars), Decimal(0)) / 200
        targets[symbol] = Decimal("0.45") if bars[-1].close > mean else Decimal(0)
    return targets
