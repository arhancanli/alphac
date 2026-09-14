"""Task 3 of the narrative-change plan: the pre-registration's mapping, timing and lineage rules,
each pinned on synthetic data before any real return is loaded."""

from __future__ import annotations

import datetime as dt
import hashlib

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.research.narrative_change.inputs import (
    DAY_MS,
    DailyPanel,
    IssuerTickerHistory,
    SessionCalendar,
    build_input_manifest,
    instrument_id_for,
)


def _ms(day: dt.date, hour: int = 0, minute: int = 0) -> int:
    return int(
        dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC).timestamp() * 1000
    )


def _history() -> IssuerTickerHistory:
    frame = pd.DataFrame(
        {
            "permaticker": [1, 2, 3, 4],
            "ticker": ["AAA", "AAA", "BBB", "CCC"],
            "cik": [100, 200, 300, 300],
            "firstpricedate": ["2010-01-01", "2018-01-01", "2010-01-01", "2015-01-01"],
            "lastpricedate": ["2017-12-31", "2026-06-18", "2026-06-18", "2026-06-18"],
        }
    )
    return IssuerTickerHistory(frame, source_sha256="deadbeef")


def test_cik_maps_to_the_one_row_whose_price_interval_contains_the_entry_date() -> None:
    history = _history()
    mapped = history.map(100, dt.date(2015, 6, 1))
    assert (mapped.status, mapped.ticker, mapped.permaticker) == ("MAPPED", "AAA", 1)
    later = history.map(200, dt.date(2020, 6, 1))
    assert (later.status, later.ticker) == ("MAPPED", "AAA")  # the ticker was reused, cleanly


def test_no_row_and_ambiguous_histories_exclude_the_filing() -> None:
    history = _history()
    assert history.map(100, dt.date(2020, 1, 1)).status == "NO_ROW"  # after AAA's first life
    assert history.map(999, dt.date(2020, 1, 1)).status == "NO_ROW"
    ambiguous = history.map(300, dt.date(2020, 1, 1))  # one CIK, two live rows (BBB and CCC)
    assert ambiguous.status == "AMBIGUOUS" and ambiguous.candidates == 2


def test_instrument_ids_follow_the_sharadar_lake_convention() -> None:
    assert instrument_id_for("aapl") == "XUSE:CASH:AAPLUSD"
    with pytest.raises(ValueError):
        instrument_id_for("")


def _calendar() -> SessionCalendar:
    # Mon 2026-08-31 .. Fri 2026-09-04, then Tue 2026-09-08 (Labor Day skipped), Wed 09-09
    days = [dt.date(2026, 8, d) for d in (27, 28, 31)] + [
        dt.date(2026, 9, d) for d in (1, 2, 3, 4, 8, 9, 10)
    ]
    return SessionCalendar([_ms(d) for d in days])


def test_filing_reaction_window_follows_the_timing_clarification() -> None:
    cal = _calendar()
    # accepted Tuesday 2026-09-01 at 16:09 UTC (after the open): ends on the NEXT session
    accepted = _ms(dt.date(2026, 9, 1), 16, 9)
    assert cal.first_session_open_after(accepted) == dt.date(2026, 9, 2)
    assert cal.last_session_before(accepted) == dt.date(2026, 8, 31)
    # accepted Friday evening: the first session whose open is later is Tuesday (holiday skipped)
    friday_evening = _ms(dt.date(2026, 9, 4), 21, 0)
    assert cal.first_session_open_after(friday_evening) == dt.date(2026, 9, 8)
    assert cal.last_session_before(friday_evening) == dt.date(2026, 9, 3)
    # accepted after the calendar ends: no end session yet
    assert cal.first_session_open_after(_ms(dt.date(2026, 9, 10), 18)) is None


def test_entry_is_the_second_session_open_after_month_end() -> None:
    cal = _calendar()
    assert cal.second_session_open_after_month_end(2026, 8) == dt.date(2026, 9, 2)
    assert cal.offset(dt.date(2026, 9, 4), 1) == dt.date(2026, 9, 8)
    assert cal.offset(dt.date(2026, 8, 27), -1) is None
    with pytest.raises(ValueError, match="not an XNYS session"):
        cal.position(dt.date(2026, 9, 7))


def _panel(cal: SessionCalendar) -> DailyPanel:
    index = pd.Index(cal.opens, name="ts_open")
    ids = ["XUSE:CASH:AAAUSD", "XUSE:CASH:BBBUSD"]
    close = pd.DataFrame(
        np.array([[10.0 + k, 20.0 + k] for k in range(len(index))]), index=index, columns=ids
    )
    close.iloc[3, 1] = np.nan  # an internal halt for BBB
    frame = lambda x: close * x  # noqa: E731
    return DailyPanel(frame(0.99), close, frame(1000.0), close, pd.DataFrame())


def test_the_input_manifest_binds_values_missingness_calendar_and_actions() -> None:
    cal = _calendar()
    panel = _panel(cal)
    manifest = build_input_manifest(
        panel=panel,
        calendar=cal,
        ticker_history_sha256="deadbeef",
        spy_source="data/lake_mf/ohlcv_1d",
        lake_dir=__import__("pathlib").Path("/lake"),
    )
    assert manifest["session_calendar"]["sessions"] == 10
    assert manifest["symbols"]["XUSE:CASH:BBBUSD"]["sessions_observed"] == 9
    assert manifest["symbols"]["XUSE:CASH:AAAUSD"]["sessions_observed"] == 10
    assert manifest["corporate_actions"] == {"rows": 0, "sha256": hashlib.sha256(b"").hexdigest()}
    again = build_input_manifest(
        panel=panel,
        calendar=cal,
        ticker_history_sha256="deadbeef",
        spy_source="data/lake_mf/ohlcv_1d",
        lake_dir=__import__("pathlib").Path("/lake"),
    )
    assert again["content_hash"] == manifest["content_hash"]
    # one changed close moves the hash; a NaN moved to another day moves it too
    moved = panel.close.copy()
    moved.iloc[5, 0] += 0.01
    changed = build_input_manifest(
        panel=DailyPanel(panel.open, moved, panel.volume, moved, panel.actions),
        calendar=cal,
        ticker_history_sha256="deadbeef",
        spy_source="data/lake_mf/ohlcv_1d",
        lake_dir=__import__("pathlib").Path("/lake"),
    )
    assert changed["content_hash"] != manifest["content_hash"]
    assert DAY_MS == 86_400_000


# ------------------------------------------------------------- the lake-backed daily panel


def _bars_table(per_inst: dict[str, list[float]], opens_ms: list[int]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    closes: list[float] = []
    for iid, series in per_inst.items():
        for t, c in zip(opens_ms, series, strict=True):
            if np.isnan(c):
                continue  # a missing session is simply absent from the lake
            iids.append(iid)
            ts.append(t)
            closes.append(float(c))
    n = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array([c * 0.99 for c in closes], type=pa.float64()),
            "high": pa.array([c * 1.01 for c in closes], type=pa.float64()),
            "low": pa.array([c * 0.98 for c in closes], type=pa.float64()),
            "close": pa.array(closes, type=pa.float64()),
            "volume": pa.array([1000.0] * n, type=pa.float64()),
            "quote_volume": pa.array([1.0e6] * n, type=pa.float64()),
            "n_trades": pa.array([7] * n, type=pa.int64()),
            "quality_flags": pa.array([0] * n, type=pa.int32()),
            "ingested_at": pa.array(
                [t + DAY_MS + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def test_the_daily_panel_reads_the_lake_pit_and_folds_a_split(tmp_path) -> None:
    from alphaforge.data.schemas import Dataset
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.store.writer import LakeWriter
    from alphaforge.research.narrative_change.inputs import SPY_INSTRUMENT_ID, load_daily_panel

    cal = _calendar()
    opens = [int(x) for x in cal.opens]
    aaa, bbb = "XUSE:CASH:AAAUSD", "XUSE:CASH:BBBUSD"
    aaa_close = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 53.0, 54.0, 55.0, 56.0]  # 2:1 split
    bbb_close = [20.0, 21.0, 22.0, np.nan, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0]  # a halt
    spy_close = [float(400 + k) for k in range(10)]
    paths = LakePaths(tmp_path / "lake")
    writer = LakeWriter(paths)
    writer.write(
        Dataset.OHLCV_1D,
        _bars_table({aaa: aaa_close, bbb: bbb_close, SPY_INSTRUMENT_ID: spy_close}, opens),
    )
    split_ex = opens[6]  # the split takes effect on the seventh session
    writer.write(
        Dataset.CORPORATE_ACTIONS,
        pa.table(
            {
                "instrument_id": pa.array([aaa], type=pa.string()),
                "action_type": pa.array(["split"], type=pa.string()),
                "ex_date": pa.array([split_ex], type=pa.timestamp("ms", tz="UTC")),
                "available_at": pa.array([opens[4]], type=pa.timestamp("ms", tz="UTC")),
                "ratio": pa.array([0.5], type=pa.float64()),
                "cash_amount": pa.array([None], type=pa.float64()),
                "ingested_at": pa.array([opens[4] + 1000], type=pa.timestamp("ms", tz="UTC")),
            }
        ),
    )
    reader = PITDataReader(paths)
    spy = reader.ohlcv(
        [SPY_INSTRUMENT_ID],
        start=opens[0],
        end=opens[-1] + DAY_MS,
        as_of=opens[-1] + DAY_MS,
        tf=__import__("alphaforge.core.time", fromlist=["Timeframe"]).Timeframe.D1,
    ).to_pandas()
    derived = SessionCalendar.from_spy_bars(spy)
    assert derived.dates == cal.dates
    panel = load_daily_panel(
        reader, [aaa, bbb], start_ms=opens[0], end_ms=opens[-1] + DAY_MS, calendar=derived
    )
    assert list(panel.close.index) == opens
    assert np.isnan(panel.close.loc[opens[3], bbb]) and panel.close.loc[opens[4], bbb] == 24.0
    assert panel.close.loc[opens[5], aaa] == 105.0  # raw close is never rewritten
    assert panel.adjusted_close.loc[opens[5], aaa] == pytest.approx(52.5)  # pre-ex bar folded
    assert panel.adjusted_close.loc[opens[6], aaa] == pytest.approx(53.0)  # post-ex untouched
    assert (
        panel.actions.iloc[0]["ratio"] == 0.5 and int(panel.actions.iloc[0]["ex_date"]) == split_ex
    )
    manifest = build_input_manifest(
        panel=panel,
        calendar=derived,
        ticker_history_sha256="x",
        spy_source=str(paths.root),
        lake_dir=paths.root,
    )
    assert manifest["corporate_actions"]["rows"] == 1
    assert manifest["symbols"][bbb]["sessions_observed"] == 9
