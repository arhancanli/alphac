"""Task 4 of the plan: monthly cohorts and the residual-stability signal.

Transcribed from the pre-registration's *Signal* section, clause by clause:

1. A pair is eligible when both Item 1A sections hold at least 500 words (the pair builder
   already requires the immediately prior unamended 10-K for the same CIK).
2. Raw stability is the five-token-shingle Jaccard similarity the pair builder computed;
   higher means less narrative change. Nothing is stemmed, weighted or length-adjusted here.
3. Cohorts are formed by SEC acceptance calendar month. Eligibility at the entry date requires
   an unadjusted close of at least $5 and a median trailing 21-session dollar volume of at
   least $5 million, both known at the entry open (the prior session's close and the 21
   sessions ending there).
4. The filing-reaction control is the adjusted close from the latest session close before
   acceptance to the first session whose open is later than acceptance, less SPY.
5. Momentum is the adjusted close at session -21 over session -252 minus one, both relative
   to the cohort month's last session.
6. Within a cohort, stability, reaction and momentum are percentile-ranked; ranked stability
   is regressed on an intercept, ranked reaction, ranked momentum and one-hot accession-time
   two-digit SIC; the signal is the OLS residual. No coefficient crosses a cohort.
7. A cohort needs at least 20 eligible issuers, at least five names in each tail, at least 10
   residual degrees of freedom and at least 10 distinct finite residuals; otherwise it is flat.
   Long the top residual quintile, short the bottom; ties break by CIK.

The locked direction is long stable, short changed. Nothing here can invert it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from alphaforge.research.narrative_change.inputs import (
    DailyPanel,
    IssuerTickerHistory,
    SessionCalendar,
    instrument_id_for,
)

MIN_SECTION_WORDS = 500
MIN_ENTRY_CLOSE = 5.0
MIN_MEDIAN_DOLLAR_VOLUME = 5_000_000.0
DOLLAR_VOLUME_WINDOW = 21
MIN_COHORT_ISSUERS = 20
MIN_TAIL_NAMES = 5
MIN_RESIDUAL_DOF = 10
MIN_DISTINCT_RESIDUALS = 10
MOMENTUM_SKIP = 21
MOMENTUM_LOOKBACK = 252


@dataclass(frozen=True)
class CohortResult:
    """One acceptance-month cohort: its names with sides, or the reason it is flat."""

    year: int
    month: int
    entry_session: dt.date | None
    status: str
    rows: pd.DataFrame
    attrition: dict[str, int] = field(default_factory=dict)

    @property
    def is_flat(self) -> bool:
        return self.status != "RANKED"

    def weights(self) -> dict[str, float]:
        """Equal-notional 50 percent long, 50 percent short over the cohort's names."""
        if self.is_flat:
            return {}
        longs = self.rows[self.rows["side"] == "LONG"]["instrument_id"].to_list()
        shorts = self.rows[self.rows["side"] == "SHORT"]["instrument_id"].to_list()
        weights: dict[str, float] = {}
        for iid in longs:
            weights[str(iid)] = 0.5 / len(longs)
        for iid in shorts:
            weights[str(iid)] = -0.5 / len(shorts)
        return weights


def eligible_pairs(pairs: pd.DataFrame) -> pd.DataFrame:
    """Clause 1: both sections at least 500 words, acceptance timestamps parsed and ordered."""
    frame = pairs.copy()
    frame["current_acceptance"] = pd.to_datetime(frame["current_acceptance"], utc=True)
    frame["previous_acceptance"] = pd.to_datetime(frame["previous_acceptance"], utc=True)
    ok = (
        (frame["previous_section_words"] >= MIN_SECTION_WORDS)
        & (frame["current_section_words"] >= MIN_SECTION_WORDS)
        & (frame["current_acceptance"] > frame["previous_acceptance"])
        & frame["fivegram_jaccard"].between(0.0, 1.0)
    )
    frame = frame[ok].copy()
    frame["cohort_year"] = frame["current_acceptance"].dt.year
    frame["cohort_month"] = frame["current_acceptance"].dt.month
    frame["acceptance_ms"] = (
        (frame["current_acceptance"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)
    ).astype("int64")
    return frame


def _adjusted_at(
    panel: DailyPanel, iid: str, session: dt.date | None, calendar: SessionCalendar
) -> float:
    if session is None:
        return float("nan")
    ts = int(calendar.opens[calendar.position(session)])
    if ts not in panel.adjusted_close.index or iid not in panel.adjusted_close.columns:
        return float("nan")
    grid = panel.adjusted_close.index.to_numpy(dtype="int64")
    pos = int(np.searchsorted(grid, ts))
    if pos >= grid.size or int(grid[pos]) != ts:
        return float("nan")
    return float(panel.adjusted_close[iid].to_numpy(dtype="float64")[pos])


def filing_reaction(
    panel: DailyPanel,
    spy_adjusted: pd.Series,
    calendar: SessionCalendar,
    iid: str,
    acceptance_ms: int,
) -> float:
    """Clause 4: the issuer's adjusted-close move across acceptance, less SPY, same interval."""
    start = calendar.last_session_before(acceptance_ms)
    end = calendar.first_session_open_after(acceptance_ms)
    if start is None or end is None:
        return float("nan")
    p0, p1 = _adjusted_at(panel, iid, start, calendar), _adjusted_at(panel, iid, end, calendar)
    s0 = spy_adjusted.get(int(calendar.opens[calendar.position(start)]), np.nan)
    s1 = spy_adjusted.get(int(calendar.opens[calendar.position(end)]), np.nan)
    if not all(np.isfinite(x) and x > 0 for x in (p0, p1, s0, s1)):
        return float("nan")
    return float(p1 / p0 - s1 / s0)


def momentum_12_1(
    panel: DailyPanel, calendar: SessionCalendar, iid: str, month_end: dt.date
) -> float:
    """Clause 5: adjusted close at session -21 over session -252, from the month-end session."""
    near = calendar.offset(month_end, -MOMENTUM_SKIP)
    far = calendar.offset(month_end, -MOMENTUM_LOOKBACK)
    p_near, p_far = (
        _adjusted_at(panel, iid, near, calendar),
        _adjusted_at(panel, iid, far, calendar),
    )
    if not (np.isfinite(p_near) and np.isfinite(p_far) and p_far > 0):
        return float("nan")
    return float(p_near / p_far - 1.0)


def entry_eligibility(
    panel: DailyPanel, calendar: SessionCalendar, iid: str, entry_session: dt.date
) -> tuple[bool, str]:
    """Clause 3: last known close at least $5, median trailing 21-session dollar volume at least
    $5 million, both ending at the session before entry (known at the entry open)."""
    prior = calendar.offset(entry_session, -1)
    if prior is None or iid not in panel.close.columns:
        return False, "no_prior_session"
    pos = calendar.position(prior)
    window = calendar.opens[max(0, pos - DOLLAR_VOLUME_WINDOW + 1) : pos + 1]
    closes = panel.close[iid].reindex(window)
    volumes = panel.volume[iid].reindex(window)
    last_close = float(closes.iloc[-1]) if len(closes) else float("nan")
    if not np.isfinite(last_close):
        return False, "no_close_before_entry"
    if last_close < MIN_ENTRY_CLOSE:
        return False, "close_below_5"
    dollar = (closes * volumes).dropna()
    if len(window) < DOLLAR_VOLUME_WINDOW or dollar.empty:
        return False, "dollar_volume_window_short"
    if float(dollar.median()) < MIN_MEDIAN_DOLLAR_VOLUME:
        return False, "median_dollar_volume_below_5m"
    return True, "eligible"


def _percentile_rank(values: pd.Series) -> pd.Series:
    return values.rank(method="average", pct=True)


def residual_signal(cohort: pd.DataFrame) -> tuple[pd.Series | None, str]:
    """Clause 6 and the regression half of clause 7: OLS residual of ranked stability."""
    ranked = pd.DataFrame(
        {
            "stability": _percentile_rank(cohort["stability"]),
            "reaction": _percentile_rank(cohort["reaction"]),
            "momentum": _percentile_rank(cohort["momentum"]),
        },
        index=cohort.index,
    )
    sic = cohort["sic"].astype(str)
    dummies = pd.get_dummies(sic, prefix="sic", dtype=float)
    design = pd.concat(
        [
            pd.Series(1.0, index=cohort.index, name="intercept"),
            ranked[["reaction", "momentum"]],
            dummies,
        ],
        axis=1,
    )
    x = design.to_numpy(dtype="float64")
    y = ranked["stability"].to_numpy(dtype="float64")
    rank = int(np.linalg.matrix_rank(x))
    dof = len(cohort) - rank
    if dof < MIN_RESIDUAL_DOF:
        return None, "residual_dof_below_10"
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    residual = pd.Series(y - x @ beta, index=cohort.index, name="residual")
    finite = residual[np.isfinite(residual)]
    if finite.round(12).nunique() < MIN_DISTINCT_RESIDUALS:
        return None, "fewer_than_10_distinct_residuals"
    return residual, "RANKED"


def rank_cohort(cohort: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Clause 7: quintile tails with ties broken by CIK, or the flat reason."""
    if len(cohort) < MIN_COHORT_ISSUERS:
        return cohort.assign(side="FLAT", residual=np.nan), "fewer_than_20_eligible"
    residual, status = residual_signal(cohort)
    if residual is None:
        return cohort.assign(side="FLAT", residual=np.nan), status
    ordered = cohort.assign(residual=residual).sort_values(
        ["residual", "cik"], ascending=[False, True], kind="mergesort"
    )
    n_tail = len(ordered) // 5
    if n_tail < MIN_TAIL_NAMES:
        return ordered.assign(side="FLAT"), "fewer_than_5_per_tail"
    side = pd.Series("NONE", index=ordered.index)
    side.iloc[:n_tail] = "LONG"
    side.iloc[-n_tail:] = "SHORT"
    return ordered.assign(side=side), "RANKED"


def build_cohort(
    *,
    year: int,
    month: int,
    pairs: pd.DataFrame,
    history: IssuerTickerHistory,
    panel: DailyPanel,
    spy_adjusted: pd.Series,
    calendar: SessionCalendar,
) -> CohortResult:
    """Everything from eligible pairs to sides for one acceptance month."""
    entry = calendar.second_session_open_after_month_end(year, month)
    month_end_session = calendar.last_session_before(
        int(
            dt.datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=dt.UTC).timestamp() * 1000
        )
    )
    members = pairs[(pairs["cohort_year"] == year) & (pairs["cohort_month"] == month)]
    attrition: dict[str, int] = {"pairs_in_month": len(members)}
    if entry is None or month_end_session is None:
        return CohortResult(
            year, month, entry, "no_entry_session_on_calendar", pd.DataFrame(), attrition
        )
    rows: list[dict[str, Any]] = []
    ciks = members["cik"].to_numpy(dtype="int64").tolist()
    accessions = members["current_accession"].astype(str).to_list()
    sics = members["sic"].astype(object).to_list()
    stabilities = members["fivegram_jaccard"].to_numpy(dtype="float64").tolist()
    acceptances = members["acceptance_ms"].to_numpy(dtype="int64").tolist()
    for k in range(len(members)):
        cik = ciks[k]
        mapping = history.map(cik, entry)
        if mapping.status != "MAPPED" or mapping.ticker is None:
            attrition[f"mapping_{mapping.status.lower()}"] = (
                attrition.get(f"mapping_{mapping.status.lower()}", 0) + 1
            )
            continue
        iid = instrument_id_for(mapping.ticker)
        ok, reason = entry_eligibility(panel, calendar, iid, entry)
        if not ok:
            attrition[reason] = attrition.get(reason, 0) + 1
            continue
        sic_value = sics[k]
        if sic_value is None or (isinstance(sic_value, float) and np.isnan(sic_value)):
            attrition["sic_missing"] = attrition.get("sic_missing", 0) + 1
            continue
        reaction = filing_reaction(panel, spy_adjusted, calendar, iid, acceptances[k])
        momentum = momentum_12_1(panel, calendar, iid, month_end_session)
        if not (np.isfinite(reaction) and np.isfinite(momentum)):
            attrition["control_unavailable"] = attrition.get("control_unavailable", 0) + 1
            continue
        rows.append(
            {
                "cik": cik,
                "ticker": mapping.ticker,
                "instrument_id": iid,
                "accession": accessions[k],
                "sic": str(sic_value)[:2],
                "stability": stabilities[k],
                "reaction": reaction,
                "momentum": momentum,
            }
        )
    if not rows:
        return CohortResult(year, month, entry, "fewer_than_20_eligible", pd.DataFrame(), attrition)
    cohort = pd.DataFrame(rows).drop_duplicates(subset=["cik"], keep="last")
    attrition["eligible"] = len(cohort)
    ranked, status = rank_cohort(cohort)
    return CohortResult(year, month, entry, status, ranked.reset_index(drop=True), attrition)
