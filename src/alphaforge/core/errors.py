"""AlphaForge exception hierarchy.

Every error raised by alphaforge code derives from :class:`AlphaForgeError` so callers
can catch the whole family with one clause while letting genuine programming errors
(``TypeError``, ``KeyError``, ...) propagate unchanged.
"""

from __future__ import annotations

__all__ = [
    "AlphaForgeError",
    "ConfigError",
    "DataGapError",
    "LockHeldError",
    "LookaheadError",
    "NaiveDatetimeError",
    "ReconciliationError",
    "RiskLimitError",
    "SchemaError",
]


class AlphaForgeError(Exception):
    """Base class for all AlphaForge errors; never raised directly."""


class NaiveDatetimeError(AlphaForgeError):
    """Raised when a naive or non-UTC datetime crosses an API boundary that requires UTC."""


class LookaheadError(AlphaForgeError):
    """Raised when data with ``available_at`` later than the decision timestamp is requested."""


class SchemaError(AlphaForgeError):
    """Raised when a table/record fails validation against its declared pyarrow schema."""


class ConfigError(AlphaForgeError):
    """Raised when settings are missing, malformed, or mutually inconsistent at load time."""


class DataGapError(AlphaForgeError):
    """Raised when expected bars are absent from the lake and the caller declared no fill policy."""


class LockHeldError(AlphaForgeError):
    """Raised when another process holds the exclusive lock on a single-writer resource.

    Single-writer jobs (ingestion today; any future state-mutating job) take an OS-level
    ``flock`` before touching shared state, making concurrent writers mechanically
    impossible rather than merely discouraged. The holder's pid is recorded in the lock
    file and included in the message.
    """


class ReconciliationError(AlphaForgeError):
    """Raised when local order/position/balance state disagrees with the broker beyond tolerance."""


class RiskLimitError(AlphaForgeError):
    """Raised when a pre-trade check or portfolio monitor breaches a configured risk limit."""
