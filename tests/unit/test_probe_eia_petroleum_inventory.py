from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from probe_eia_petroleum_inventory import build_scores, next_session


def _weekly_events(years: int = 8) -> pd.DataFrame:
    dates = pd.date_range("2011-01-07", periods=52 * years, freq="7D")
    rows: list[dict[str, object]] = []
    for proxy, offset in (("USO", 0.0), ("UGA", 0.5)):
        for number, period_end in enumerate(dates):
            rows.append(
                {
                    "release_date": period_end + pd.Timedelta(days=5),
                    "period_end": period_end,
                    "proxy": proxy,
                    "change_million_barrels": float(np.sin(number / 8.0) + offset),
                }
            )
    return pd.DataFrame(rows)


def test_scores_require_only_prior_seasonal_and_scale_history() -> None:
    events = _weekly_events()
    baseline = build_scores(events)
    altered = events.copy()
    altered.loc[
        altered["release_date"] == altered["release_date"].max(),
        "change_million_barrels",
    ] = 999
    rerun = build_scores(altered)
    before_last = baseline["release_date"] < baseline["release_date"].max()
    pd.testing.assert_series_equal(
        baseline.loc[before_last, "score"].reset_index(drop=True),
        rerun.loc[before_last, "score"].reset_index(drop=True),
    )
    assert baseline["score"].notna().any()


def test_next_session_is_strictly_after_release_date() -> None:
    calendar = pd.date_range("2026-01-05", periods=5, freq="B")
    assert next_session(calendar, pd.Timestamp("2026-01-05")) == 1
    assert next_session(calendar, pd.Timestamp("2026-01-08")) == 4
    assert next_session(calendar, pd.Timestamp("2026-01-10")) is None
