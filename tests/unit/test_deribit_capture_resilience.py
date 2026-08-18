"""Deribit research capture must retry transiently and fail closed without partial output."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "deribit_capture_under_test", _ROOT / "scripts" / "deribit_capture.py"
)
assert _SPEC and _SPEC.loader
CAPTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(CAPTURE)


class _Exchange:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def load_markets(self) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError("synthetic timeout")


def test_load_markets_retries_then_succeeds() -> None:
    exchange = _Exchange(failures=2)
    sleeps: list[float] = []
    assert CAPTURE._load_markets_with_retry(exchange, sleep=sleeps.append)
    assert exchange.calls == 3
    assert sleeps == list(CAPTURE.LOAD_BACKOFF_SECONDS)


def test_load_markets_exhaustion_returns_false_instead_of_raising() -> None:
    exchange = _Exchange(failures=99)
    sleeps: list[float] = []
    assert not CAPTURE._load_markets_with_retry(exchange, sleep=sleeps.append)
    assert exchange.calls == CAPTURE.LOAD_ATTEMPTS
    assert sleeps == list(CAPTURE.LOAD_BACKOFF_SECONDS)


def test_default_lake_is_repo_relative_not_home_relative() -> None:
    assert CAPTURE.ROOT == _ROOT / "data" / "deribit"
