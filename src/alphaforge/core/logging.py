"""Structured logging for AlphaForge (structlog over stdlib logging).

Two sinks on the root logger, so both structlog-native and foreign stdlib
records (ccxt, urllib3, ...) flow through identical processors:

- console: human-readable dev renderer on stderr
- JSONL file: ``<log_dir>/alphaforge.jsonl``, rotated daily at UTC midnight,
  30 rotated files retained (ruling: structlog JSONL is the only unbounded
  growth in the system — rotation + retention are mandatory from Phase 1).
  Lines are one JSON object each, queryable with DuckDB's read_json_auto.

Every line carries ``ts`` (ISO-8601 UTC), ``level``, ``logger``, ``event``
plus whatever key-values the caller bound. ``setup_logging`` is idempotent:
handlers are tagged by name and replaced, never duplicated, so re-running it
(tests, notebook re-execution) is safe.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import structlog
from structlog.typing import Processor

from alphaforge.core.errors import ConfigError

__all__ = ["LOG_FILE_NAME", "get_logger", "setup_logging"]

LOG_FILE_NAME = "alphaforge.jsonl"
_CONSOLE_HANDLER_NAME = "alphaforge.console"
_FILE_HANDLER_NAME = "alphaforge.file"
_RETENTION_DAYS = 30

# Shared by the structlog-native pipeline and the foreign_pre_chain so stdlib
# records get the same ts/level/logger keys. format_exc_info renders
# exceptions to a string "exception" key (identical in console and JSONL).
_SHARED_PROCESSORS: tuple[Processor, ...] = (
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
)


def setup_logging(log_dir: Path, level: str = "INFO", json_file: bool = True) -> None:
    """Configure structlog + stdlib root handlers. Call once at process start.

    ``log_dir`` is created if missing. ``level`` is a stdlib level name
    (case-insensitive: DEBUG/INFO/WARNING/ERROR/CRITICAL) applied to the root
    logger; unknown names raise ConfigError. ``json_file=False`` skips the
    JSONL sink (console only — e.g. throwaway CLI invocations).

    Idempotent: previously installed AlphaForge handlers (identified by
    handler name) are closed and replaced; foreign handlers are untouched.
    """
    level_no = logging.getLevelNamesMapping().get(level.upper())
    if level_no is None or level_no == logging.NOTSET:
        raise ConfigError(f"unknown log level: {level!r}")

    structlog.configure(
        processors=[*_SHARED_PROCESSORS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,  # safe re-configuration (tests, level changes)
    )

    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() in (_CONSOLE_HANDLER_NAME, _FILE_HANDLER_NAME):
            root.removeHandler(handler)
            handler.close()

    console = logging.StreamHandler(sys.stderr)
    console.set_name(_CONSOLE_HANDLER_NAME)
    console.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
            ],
            foreign_pre_chain=list(_SHARED_PROCESSORS),
        )
    )
    root.addHandler(console)

    if json_file:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            log_dir / LOG_FILE_NAME,
            when="midnight",
            utc=True,
            backupCount=_RETENTION_DAYS,
            encoding="utf-8",
        )
        file_handler.set_name(_FILE_HANDLER_NAME)
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer(sort_keys=True),
                ],
                foreign_pre_chain=list(_SHARED_PROCESSORS),
            )
        )
        root.addHandler(file_handler)

    root.setLevel(level_no)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return the structlog stdlib BoundLogger for ``name`` (dotted-path
    convention: ``alphaforge.data.ingest``). Lazy: safe to call at import
    time, before :func:`setup_logging` has run — configuration binds on first
    log call."""
    return structlog.stdlib.get_logger(name)
