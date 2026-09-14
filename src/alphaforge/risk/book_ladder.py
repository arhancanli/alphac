"""Book-level drawdown multiplier, read side (drawdown control v1, 2026-09-14).

WHY. The owner's 11 percent maximum-drawdown bound is a bound on the COMBINED book, and
``config/drawdown_control_contract.json`` declares the brake that enforces it: half gross when the
book is 5.5 percent below its high-water mark, flat at 11 percent, absorbing until an owner rearm.
``scripts/book_drawdown_ladder.py`` replays the published combined marks through that ladder every
publish and writes the multiplier in force (1.0 / 0.5 / 0.0). Every sleeve multiplies its own
target gross by that number, so the whole book de-grosses together when the BOOK is in drawdown,
whatever the sleeve's own curve says. The sleeve-level :class:`~alphaforge.risk.DrawdownLadder`
is untouched; this is an outer factor applied after it.

TRANSPORT. The producer runs on the publishing machine; the crypto loop runs in Frankfurt. A local
consumer reads ``var/book_ladder/current.json``; a remote one reads the public artifact
``/glassbox/book_drawdown_ladder.json`` on canlicapital.com (same fields, hash-bound to the same
computation). Both are files written by a process that is not this one, so this module treats
every read as untrusted input and never lets a bad read into a trading cycle as an exception.

ONE SWITCH. The contract's ``activation.live`` flag is read here, from the same file the site
publishes, so the public contract and the trading path cannot disagree about whether the brake is
on. When it is off the provider reports 1.0 and ``applied=False`` whatever the source says.

FAIL-OPEN, LOUDLY. A missing, unreadable, malformed or out-of-range source yields 1.0 and an
``error`` in the reading (the caller logs it; the nightly health board's C12-book-ladder check fails
independently). A reading older than ``max_age_days`` is still applied and flagged ``stale``: the
ladder is derived from marks, so a stale file means the publisher has not run, not that the state
moved. The last good reading is kept across failed refreshes inside one process. The choice of
fail-open mirrors the equity cycle's calendar gate: a plumbing failure must not put a hole in the
forward record; the health board, not the cycle, is where plumbing failures become alerts.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from alphaforge.config.settings import Settings

FetchFn = Callable[[str, float], bytes]
TodayFn = Callable[[], dt.date]

_VALID_STATES = frozenset({"NORMAL", "HALF_GROSS", "FLAT_HALTED"})


@dataclass(frozen=True)
class BookLadderReading:
    """What the provider saw, for the cycle log and the operator's confession."""

    multiplier: float
    """The multiplier the caller must apply: 1.0 unless activated and the source says less."""
    applied: bool
    """False when the contract's ``activation.live`` is off (multiplier is then always 1.0)."""
    state: str | None
    as_of: str | None
    generated_at: str | None
    source: str
    stale: bool
    error: str | None
    """A read failure. The multiplier is then the last good reading, or 1.0 if there is none."""

    def as_log_fields(self) -> dict[str, Any]:
        return {
            "book_multiplier": self.multiplier,
            "book_applied": self.applied,
            "book_state": self.state,
            "book_as_of": self.as_of,
            "book_source": self.source,
            "book_stale": self.stale,
            "book_error": self.error,
        }


def _https_fetch(url: str, timeout_s: float) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        return bytes(resp.read())


class BookLadderProvider:
    """Read the book multiplier from a file or the public artifact; never raise into a cycle."""

    def __init__(
        self,
        *,
        contract_path: Path,
        source: Literal["file", "https"],
        path: Path | None = None,
        url: str | None = None,
        max_age_days: int = 4,
        timeout_s: float = 5.0,
        fetch: FetchFn | None = None,
        today: TodayFn | None = None,
    ) -> None:
        if source == "file" and path is None:
            raise ValueError("a file source needs a path")
        if source == "https" and (not url or not url.startswith("https://")):
            raise ValueError("an https source needs an https:// url")
        self._contract_path = Path(contract_path)
        self._source = source
        self._path = Path(path) if path is not None else None
        self._url = url
        self._max_age_days = int(max_age_days)
        self._timeout_s = float(timeout_s)
        self._fetch = fetch if fetch is not None else _https_fetch
        self._today = today if today is not None else (lambda: dt.datetime.now(dt.UTC).date())
        self._last_good: BookLadderReading | None = None
        self._last: BookLadderReading | None = None

    @classmethod
    def from_settings(cls, settings: Settings, *, root: Path | None = None) -> BookLadderProvider:
        """Build from ``settings.risk.book_ladder``; relative paths resolve against ``root``.

        ``root`` defaults to the parent of the resolved ``paths.var_dir`` (the repository root in
        every shipped profile), so the contract and the consumer file are found beside the state
        the rest of the loop already writes there.
        """
        cfg = settings.risk.book_ladder
        base = root if root is not None else Path(settings.paths.var_dir).parent
        contract = Path(cfg.contract_path)
        if not contract.is_absolute():
            contract = base / contract
        path = Path(settings.paths.var_dir) / "book_ladder" / "current.json"
        if cfg.path is not None:
            path = Path(cfg.path)
            if not path.is_absolute():
                path = base / path
        return cls(
            contract_path=contract,
            source=cfg.source,
            path=path,
            url=cfg.url,
            max_age_days=cfg.max_age_days,
            timeout_s=cfg.timeout_s,
        )

    @property
    def source_description(self) -> str:
        return str(self._path) if self._source == "file" else str(self._url)

    @property
    def last_reading(self) -> BookLadderReading | None:
        return self._last

    def activated(self) -> bool:
        """The contract's ``activation.live``; a missing or unreadable contract is OFF."""
        try:
            contract = json.loads(self._contract_path.read_text(encoding="utf-8"))
            return bool(contract.get("activation", {}).get("live", False))
        except Exception:
            return False

    def _raw(self) -> bytes:
        if self._source == "file":
            assert self._path is not None
            return self._path.read_bytes()
        assert self._url is not None
        return self._fetch(self._url, self._timeout_s)

    def _parse(self, raw: bytes) -> tuple[float, str, str, str | None]:
        doc = json.loads(raw.decode("utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("source is not a JSON object")
        mult = float(doc["gross_multiplier"])
        state = str(doc["state"])
        as_of = str(doc["as_of"])
        if not math.isfinite(mult) or not 0.0 <= mult <= 1.0:
            raise ValueError(f"gross_multiplier {mult!r} out of [0, 1]")
        if state not in _VALID_STATES:
            raise ValueError(f"state {state!r} is not a ladder state")
        dt.date.fromisoformat(as_of)
        generated = doc.get("generated_at")
        return mult, state, as_of, (str(generated) if generated is not None else None)

    def read(self) -> BookLadderReading:
        """One read of the source; fail-open to the last good reading or 1.0, never raising."""
        source = self.source_description
        if not self.activated():
            self._last = BookLadderReading(
                multiplier=1.0,
                applied=False,
                state=None,
                as_of=None,
                generated_at=None,
                source=source,
                stale=False,
                error=None,
            )
            return self._last
        try:
            mult, state, as_of, generated = self._parse(self._raw())
        except Exception as exc:  # any failure is a reading, not an exception
            prior = self._last_good
            self._last = BookLadderReading(
                multiplier=prior.multiplier if prior is not None else 1.0,
                applied=True,
                state=prior.state if prior is not None else None,
                as_of=prior.as_of if prior is not None else None,
                generated_at=prior.generated_at if prior is not None else None,
                source=source,
                stale=prior.stale if prior is not None else False,
                error=f"{type(exc).__name__}: {exc}"[:200],
            )
            return self._last
        age_days = (self._today() - dt.date.fromisoformat(as_of)).days
        reading = BookLadderReading(
            multiplier=mult,
            applied=True,
            state=state,
            as_of=as_of,
            generated_at=generated,
            source=source,
            stale=age_days > self._max_age_days,
            error=None,
        )
        self._last_good = reading
        self._last = reading
        return reading

    def multiplier(self) -> float:
        """The number a strategy multiplies its target gross by. Never raises."""
        return self.read().multiplier
