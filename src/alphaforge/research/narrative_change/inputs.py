"""Task 3 of the plan: market inputs, the session calendar, issuer mapping, the input manifest.

Every rule here is transcribed from the pre-registration and named after its clause:

- **Issuer mapping.** CIK maps to the Sharadar ticker row whose first/last-price interval
  contains the entry date. No row, or more than one issuer history claiming the ticker on that
  date, excludes the filing; the runner never guesses from the current ticker.
- **Session calendar.** XNYS sessions are the days SPY traded; the ``first session whose opening
  timestamp is later than SEC acceptance`` is the filing-reaction end, and the ``latest session
  close before acceptance`` is its start (timing clarification).
- **Prices.** Daily bars from the survivorship-inclusive Sharadar lake; adjusted closes come from
  the shared PIT engine (``alphaforge.features.library.equity_price.adjusted_close``), so this
  sleeve prices splits and dividends exactly as every other equity sleeve does. Unadjusted close
  and volume feed the $5 close and $5 million median dollar-volume filters.
- **Input manifest.** One canonical manifest binds the ticker-history snapshot, every loaded
  symbol's exact values and missingness, the SPY-derived calendar and the corporate-action rows
  consumed by the adjustment engine. The result binds its SHA-256, so unrelated lake partitions
  are excluded without weakening reproducibility (market-input lineage clarification).

No return is computed here: a return is a ratio of two closes, and this module stops at closes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from alphaforge.core.time import Ms, Timeframe
from alphaforge.data.store.reader import PITDataReader
from alphaforge.features.library.equity_price import adjusted_close

SPY_INSTRUMENT_ID = "XUSE:CASH:SPYUSD"
"""The repository's pinned SPY research series (the managed-futures lake, Yahoo total return)."""

DAY_MS: int = Timeframe.D1.ms
MappingStatus = Literal["MAPPED", "NO_ROW", "AMBIGUOUS"]


def instrument_id_for(ticker: str) -> str:
    """The Sharadar lake's instrument id for a ticker (``XUSE:CASH:<TICKER>USD``)."""
    if not ticker or not ticker.isascii():
        raise ValueError(f"not a Sharadar ticker: {ticker!r}")
    return f"XUSE:CASH:{ticker.upper()}USD"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _to_ms(values: pd.Series) -> pd.Series:
    """Epoch milliseconds from a lake timestamp column (or pass integers through)."""
    if pd.api.types.is_integer_dtype(values):
        return values.astype("int64")
    stamps = pd.to_datetime(values, utc=True)
    # Unit-agnostic: pandas keeps the lake's millisecond unit, so a bare astype("int64") would
    # already be milliseconds while a nanosecond column would be a thousand times larger.
    epoch = pd.Timestamp(0, tz="UTC")
    return ((stamps - epoch) // pd.Timedelta(milliseconds=1)).astype("int64")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


# ------------------------------------------------------------------------- issuer mapping


@dataclass(frozen=True)
class IssuerMapping:
    cik: int
    entry_date: dt.date
    status: MappingStatus
    ticker: str | None
    permaticker: int | None
    candidates: int


class IssuerTickerHistory:
    """The Sharadar TICKERS snapshot the ingest froze (``issuer_ticker_history.parquet``)."""

    REQUIRED = ("permaticker", "ticker", "cik", "firstpricedate", "lastpricedate")

    def __init__(self, frame: pd.DataFrame, *, source_sha256: str) -> None:
        missing = [c for c in self.REQUIRED if c not in frame.columns]
        if missing:
            raise ValueError(f"ticker history is missing columns {missing}")
        rows = frame.loc[:, list(self.REQUIRED)].copy()
        rows = rows.dropna(subset=["cik", "ticker"])
        rows["cik"] = rows["cik"].astype("int64")
        rows["permaticker"] = rows["permaticker"].astype("int64")
        rows["ticker"] = rows["ticker"].astype(str)
        rows["first"] = pd.to_datetime(rows["firstpricedate"], errors="coerce").dt.date
        rows["last"] = pd.to_datetime(rows["lastpricedate"], errors="coerce").dt.date
        self._rows = rows
        ciks = rows["cik"].to_numpy(dtype="int64")
        self._by_cik: dict[int, pd.DataFrame] = {
            int(cik): rows[ciks == cik] for cik in np.unique(ciks)
        }
        self.source_sha256 = source_sha256

    @classmethod
    def load(cls, path: Path) -> IssuerTickerHistory:
        return cls(pd.read_parquet(path), source_sha256=_sha256_path(path))

    def map(self, cik: int, entry_date: dt.date) -> IssuerMapping:
        """The one ticker row whose price interval contains ``entry_date``; else exclude."""
        group = self._by_cik.get(int(cik))
        if group is None:
            return IssuerMapping(int(cik), entry_date, "NO_ROW", None, None, 0)
        inside = group[
            (group["first"].notna())
            & (group["last"].notna())
            & (group["first"] <= entry_date)
            & (group["last"] >= entry_date)
        ]
        if inside.empty:
            return IssuerMapping(int(cik), entry_date, "NO_ROW", None, None, 0)
        if len(inside) != 1:
            return IssuerMapping(int(cik), entry_date, "AMBIGUOUS", None, None, len(inside))
        ticker = str(inside["ticker"].to_numpy(dtype=object)[0])
        permaticker = int(inside["permaticker"].to_numpy(dtype="int64")[0])
        # A second issuer history claiming the same ticker on that date is the same ambiguity
        # seen from the other side; the filing is excluded either way.
        claimants = self._rows[
            (self._rows["ticker"] == ticker)
            & (self._rows["first"].notna())
            & (self._rows["last"].notna())
            & (self._rows["first"] <= entry_date)
            & (self._rows["last"] >= entry_date)
        ]
        if claimants["cik"].nunique() != 1:
            return IssuerMapping(
                int(cik), entry_date, "AMBIGUOUS", None, None, int(claimants["cik"].nunique())
            )
        return IssuerMapping(int(cik), entry_date, "MAPPED", ticker, permaticker, 1)


# ----------------------------------------------------------------------- session calendar


class SessionCalendar:
    """XNYS sessions derived from SPY's daily bars; ``ts_open`` epoch ms per session."""

    def __init__(self, session_opens_ms: Sequence[int]) -> None:
        opens = np.asarray(sorted({int(x) for x in session_opens_ms}), dtype="int64")
        if opens.size < 2:
            raise ValueError("a session calendar needs at least two sessions")
        self.opens = opens
        self.dates = [dt.datetime.fromtimestamp(x / 1000, tz=dt.UTC).date() for x in opens]
        self._index = {d: i for i, d in enumerate(self.dates)}

    @classmethod
    def from_spy_bars(cls, bars: pd.DataFrame) -> SessionCalendar:
        if bars.empty:
            raise ValueError("no SPY bars: the session calendar cannot be derived")
        return cls(_to_ms(bars["ts_open"]).to_list())

    def __len__(self) -> int:
        return int(self.opens.size)

    def position(self, session: dt.date) -> int:
        try:
            return self._index[session]
        except KeyError as error:
            raise ValueError(f"{session} is not an XNYS session") from error

    def offset(self, session: dt.date, k: int) -> dt.date | None:
        """The session ``k`` sessions after (negative: before) ``session``; None off the grid."""
        pos = self.position(session) + k
        if pos < 0 or pos >= len(self.dates):
            return None
        return self.dates[pos]

    def first_session_open_after(self, instant_ms: int) -> dt.date | None:
        """Timing clarification: the first session whose opening timestamp is later than
        ``instant_ms`` (the SEC acceptance instant). Session opens are the bar's ``ts_open``,
        which the daily lake labels at 00:00 UTC of the session date; a filing accepted at
        16:09 UTC on a session day therefore ends on the NEXT session, never the same one."""
        pos = int(np.searchsorted(self.opens, instant_ms, side="right"))
        return self.dates[pos] if pos < len(self.dates) else None

    def last_session_before(self, instant_ms: int) -> dt.date | None:
        """The latest session whose close (``ts_open + 1 day``) is before ``instant_ms``."""
        closes = self.opens + DAY_MS
        pos = int(np.searchsorted(closes, instant_ms, side="left")) - 1
        return self.dates[pos] if pos >= 0 else None

    def second_session_open_after_month_end(self, year: int, month: int) -> dt.date | None:
        """Entry rule: the second XNYS session open after calendar month-end."""
        last_day = dt.date(year + (month == 12), (month % 12) + 1, 1) - dt.timedelta(days=1)
        month_end_ms = int(
            dt.datetime(
                last_day.year, last_day.month, last_day.day, 23, 59, 59, tzinfo=dt.UTC
            ).timestamp()
            * 1000
        )
        first = self.first_session_open_after(month_end_ms)
        return None if first is None else self.offset(first, 1)


# ------------------------------------------------------------------------- price panel


@dataclass(frozen=True)
class DailyPanel:
    """Wide daily frames on the session grid (index ``ts_open`` ms, columns instrument ids)."""

    open: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    adjusted_close: pd.DataFrame
    actions: pd.DataFrame

    @property
    def instrument_ids(self) -> list[str]:
        return [str(c) for c in self.close.columns]

    def dollar_volume(self) -> pd.DataFrame:
        return self.close * self.volume


def load_daily_panel(
    reader: PITDataReader,
    instrument_ids: Iterable[str],
    *,
    start_ms: Ms,
    end_ms: Ms,
    calendar: SessionCalendar,
) -> DailyPanel:
    """Daily bars for ``instrument_ids`` on the calendar's grid, PIT as of ``end_ms``.

    Rows are the calendar's sessions inside ``[start_ms, end_ms)``; a session without a bar
    for an instrument is NaN (the prereg's missing-open rule reads that NaN; nothing is
    forward-filled). Adjusted closes fold every split and knowable dividend through the shared
    engine.
    """
    ids = sorted({str(i) for i in instrument_ids})
    grid = calendar.opens[(calendar.opens >= int(start_ms)) & (calendar.opens < int(end_ms))]
    index = pd.Index(grid.astype("int64"), name="ts_open")
    empty = pd.DataFrame(np.nan, index=index, columns=ids, dtype="float64")
    if not ids or grid.size == 0:
        return DailyPanel(empty, empty.copy(), empty.copy(), empty.copy(), pd.DataFrame())
    bars = reader.ohlcv(ids, start=start_ms, end=end_ms, as_of=end_ms, tf=Timeframe.D1)
    frame = bars.to_pandas()
    if not frame.empty:
        # The lake labels bars with a UTC timestamp; the grid is epoch milliseconds.
        frame = frame.assign(ts_open=_to_ms(frame["ts_open"]))
    wide: dict[str, pd.DataFrame] = {}
    for column in ("open", "close", "volume"):
        if frame.empty:
            wide[column] = empty.copy()
            continue
        pivot = frame.pivot(index="ts_open", columns="instrument_id", values=column)
        wide[column] = pivot.reindex(index=index, columns=ids).astype("float64")
    actions_table = reader.corporate_actions(ids, start=start_ms, end=end_ms, as_of=end_ms)
    actions = actions_table.to_pandas()
    if not actions.empty:
        actions = actions.assign(
            ex_date=_to_ms(actions["ex_date"]), available_at=_to_ms(actions["available_at"])
        )
        actions = actions.loc[
            :, ["instrument_id", "action_type", "ex_date", "available_at", "ratio", "cash_amount"]
        ]
    adjusted = adjusted_close(wide["close"], actions, tf_ms=DAY_MS, include_dividends=True)
    return DailyPanel(wide["open"], wide["close"], wide["volume"], adjusted, actions)


# ------------------------------------------------------------------------ input manifest


def _frame_digest(frame: pd.DataFrame, column: str) -> str:
    """Hash exact values and missingness of one instrument's column, index included."""
    values = frame[column].to_numpy(dtype="float64")
    index = frame.index.to_numpy(dtype="int64")
    mask = np.isnan(values)
    return _sha256_bytes(index.tobytes() + np.where(mask, 0.0, values).tobytes() + mask.tobytes())


def build_input_manifest(
    *,
    panel: DailyPanel,
    calendar: SessionCalendar,
    ticker_history_sha256: str,
    spy_source: str,
    lake_dir: Path,
) -> dict[str, Any]:
    """The one canonical manifest the result binds (market-input lineage clarification)."""
    symbols: dict[str, dict[str, Any]] = {}
    for iid in panel.instrument_ids:
        per = {
            column: _frame_digest(
                getattr(panel, column)[[iid]].rename(columns={iid: column}), column
            )
            for column in ("open", "close", "volume", "adjusted_close")
        }
        observed = int(panel.close[iid].notna().sum())
        symbols[iid] = {**per, "sessions_observed": observed, "sessions_on_grid": len(panel.close)}
    if panel.actions.empty:
        actions_digest = _sha256_bytes(b"")
        actions_rows = 0
    else:
        rows = panel.actions.sort_values(["instrument_id", "ex_date", "action_type"])
        iids = rows["instrument_id"].astype(str).to_list()
        kinds = rows["action_type"].astype(str).to_list()
        ex_dates = rows["ex_date"].to_numpy(dtype="int64").tolist()
        availables = rows["available_at"].to_numpy(dtype="int64").tolist()
        ratios = rows["ratio"].to_numpy(dtype="float64").tolist()
        cashes = rows["cash_amount"].to_numpy(dtype="float64").tolist()
        actions_digest = _sha256_bytes(
            _canonical(
                [
                    [
                        iids[k],
                        kinds[k],
                        ex_dates[k],
                        availables[k],
                        None if np.isnan(ratios[k]) else ratios[k],
                        None if np.isnan(cashes[k]) else cashes[k],
                    ]
                    for k in range(len(rows))
                ]
            )
        )
        actions_rows = len(rows)
    manifest: dict[str, Any] = {
        "schema": "canli.alphac-narrative-change-input-manifest.v1",
        "preregistration": "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "lake_dir": str(lake_dir),
        "ticker_history_sha256": ticker_history_sha256,
        "spy": {"instrument_id": SPY_INSTRUMENT_ID, "source": spy_source},
        "session_calendar": {
            "sessions": len(calendar),
            "first": calendar.dates[0].isoformat(),
            "last": calendar.dates[-1].isoformat(),
            "sha256": _sha256_bytes(calendar.opens.tobytes()),
        },
        "symbols": symbols,
        "corporate_actions": {"rows": actions_rows, "sha256": actions_digest},
        "adjustment_engine": "alphaforge.features.library.equity_price.adjusted_close",
    }
    manifest["content_hash"] = "sha256:" + _sha256_bytes(_canonical(manifest))
    return manifest
