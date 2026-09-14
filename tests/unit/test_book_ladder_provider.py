"""The book multiplier provider must apply the published number only when the contract says the
brake is live, keep the last good reading across a failed refresh, flag staleness without
dropping the reading, and never raise into a trading cycle."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from alphaforge.risk.book_ladder import BookLadderProvider

TODAY = dt.date(2026, 9, 14)


def _contract(tmp_path: Path, live: bool) -> Path:
    p = tmp_path / "config" / "drawdown_control_contract.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"activation": {"live": live}}))
    return p


def _current(tmp_path: Path, mult: float, state: str, as_of: str = "2026-09-14") -> Path:
    p = tmp_path / "var" / "book_ladder" / "current.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "gross_multiplier": mult,
                "state": state,
                "as_of": as_of,
                "generated_at": "2026-09-14T12:00:00+00:00",
            }
        )
    )
    return p


def _file_provider(tmp_path: Path, *, live: bool) -> BookLadderProvider:
    return BookLadderProvider(
        contract_path=_contract(tmp_path, live),
        source="file",
        path=tmp_path / "var" / "book_ladder" / "current.json",
        today=lambda: TODAY,
    )


def test_a_live_contract_applies_the_published_multiplier(tmp_path: Path) -> None:
    _current(tmp_path, 0.5, "HALF_GROSS")
    r = _file_provider(tmp_path, live=True).read()
    assert (r.multiplier, r.applied, r.state, r.stale, r.error) == (
        0.5,
        True,
        "HALF_GROSS",
        False,
        None,
    )


def test_an_inactive_contract_never_applies_even_a_halt(tmp_path: Path) -> None:
    _current(tmp_path, 0.0, "FLAT_HALTED")
    r = _file_provider(tmp_path, live=False).read()
    assert (r.multiplier, r.applied, r.state) == (1.0, False, None)


def test_a_missing_contract_is_off(tmp_path: Path) -> None:
    _current(tmp_path, 0.0, "FLAT_HALTED")
    p = BookLadderProvider(
        contract_path=tmp_path / "nope.json",
        source="file",
        path=tmp_path / "var" / "book_ladder" / "current.json",
    )
    assert p.multiplier() == 1.0 and p.last_reading is not None and not p.last_reading.applied


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[1, 2]",
        json.dumps({"gross_multiplier": 1.5, "state": "NORMAL", "as_of": "2026-09-14"}).encode(),
        json.dumps({"gross_multiplier": 0.5, "state": "WEIRD", "as_of": "2026-09-14"}).encode(),
        json.dumps({"gross_multiplier": 0.5, "state": "HALF_GROSS", "as_of": "yesterday"}).encode(),
        json.dumps({"state": "HALF_GROSS", "as_of": "2026-09-14"}).encode(),
    ],
)
def test_a_bad_source_fails_open_with_an_error_and_no_exception(
    tmp_path: Path, body: bytes
) -> None:
    path = tmp_path / "var" / "book_ladder" / "current.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(body)
    r = _file_provider(tmp_path, live=True).read()
    assert r.multiplier == 1.0 and r.applied is True and r.error


def test_a_missing_file_fails_open_loudly(tmp_path: Path) -> None:
    r = _file_provider(tmp_path, live=True).read()
    assert r.multiplier == 1.0 and r.applied and "FileNotFoundError" in str(r.error)


def test_a_failed_refresh_keeps_the_last_good_reading(tmp_path: Path) -> None:
    path = _current(tmp_path, 0.5, "HALF_GROSS")
    p = _file_provider(tmp_path, live=True)
    assert p.multiplier() == 0.5
    path.write_text("garbage")
    r = p.read()
    assert r.multiplier == 0.5 and r.state == "HALF_GROSS" and r.error


def test_an_old_reading_is_applied_and_flagged_stale(tmp_path: Path) -> None:
    _current(tmp_path, 0.5, "HALF_GROSS", as_of="2026-09-01")
    r = _file_provider(tmp_path, live=True).read()
    assert r.multiplier == 0.5 and r.stale is True and r.error is None


def test_the_https_source_uses_the_injected_fetch_and_keeps_last_good_on_failure(tmp_path) -> None:
    calls: list[tuple[str, float]] = []
    bodies = [
        json.dumps(
            {"gross_multiplier": 0.0, "state": "FLAT_HALTED", "as_of": "2026-09-14"}
        ).encode(),
        None,
    ]

    def fetch(url: str, timeout_s: float) -> bytes:
        calls.append((url, timeout_s))
        body = bodies.pop(0)
        if body is None:
            raise TimeoutError("timed out")
        return body

    p = BookLadderProvider(
        contract_path=_contract(tmp_path, True),
        source="https",
        url="https://canlicapital.com/glassbox/book_drawdown_ladder.json",
        timeout_s=2.5,
        fetch=fetch,
        today=lambda: TODAY,
    )
    assert p.multiplier() == 0.0
    assert calls == [("https://canlicapital.com/glassbox/book_drawdown_ladder.json", 2.5)]
    r = p.read()
    assert r.multiplier == 0.0 and r.state == "FLAT_HALTED" and "TimeoutError" in str(r.error)


def test_an_https_source_must_be_https() -> None:
    with pytest.raises(ValueError, match="https://"):
        BookLadderProvider(contract_path=Path("c.json"), source="https", url="http://x/y.json")


def test_from_settings_resolves_the_default_file_beside_var(tmp_path: Path) -> None:
    from alphaforge.config.settings import Settings

    settings = Settings().model_copy(
        update={"paths": Settings().paths.model_copy(update={"var_dir": tmp_path / "var"})}
    )
    p = BookLadderProvider.from_settings(settings)
    assert p.source_description == str(tmp_path / "var" / "book_ladder" / "current.json")
    assert p._contract_path == tmp_path / "config" / "drawdown_control_contract.json"
    assert p.multiplier() == 1.0  # no contract there: off, not an exception
