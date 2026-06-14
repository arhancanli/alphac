"""Modeled-vs-realized slippage report (leakageCritique.md finding 8, Phase 8 gate).

The validation problem this solves
----------------------------------
In a naive paper loop the broker fills orders AT the cost model's predicted
price, so "realized vs modeled slippage" compares the model with itself and shows
perfect agreement for the entire paper phase -- the half-spread and impact
coefficients reach real money UNTESTED (leakageCritique.md finding 8). AlphaForge's
PaperBroker breaks the circularity: it WALKS a real order-book snapshot to get the
realized ``walked_price`` and ALSO computes the ``modeled_price`` the
:class:`~alphaforge.costs.model.TransactionCostModel` would have charged, storing
their adverse-signed difference as ``slippage_bps`` on every fill. That column is
the one genuine modeled-vs-realized signal paper mode produces.

This module reads those persisted audit columns and turns them into the operator
report the Phase-8 gate demands ("modeled-vs-realized slippage reviewed"). It does
NOT recompute slippage -- the PaperBroker already side-normalized it so that
"realized worse than model" is POSITIVE for both buys and sells; this report
aggregates and presents that stored figure, so the report's sign convention is
inherited from and consistent with the broker's.

Reading is READ-ONLY and tolerant: a young store with zero audited fills yields a
zeroed summary rather than an error, so the report is safe to run on day one of a
soak.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "InstrumentSlippage",
    "SlippageReport",
    "SlippageSummary",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentSlippage:
    """Per-instrument slippage roll-up (one row of the report breakdown).

    ``mean_bps`` / ``median_bps`` / ``p90_bps`` / ``p99_bps`` are adverse-signed
    (positive => realized worse than modeled), in basis points of the modeled
    price. ``n_book_exhausted`` counts fills whose order-book snapshot ran out of
    depth before the order filled.
    """

    instrument_id: str
    n_fills: int
    mean_bps: float
    median_bps: float
    p90_bps: float
    p99_bps: float
    n_book_exhausted: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SlippageSummary:
    """Aggregate modeled-vs-realized slippage over all audited fills.

    All ``*_bps`` figures are adverse-signed (positive => realized walk worse than
    the model predicted), in basis points of the modeled price, exactly as the
    PaperBroker stored them. ``per_instrument`` is sorted by ``instrument_id``.
    An empty/young store yields ``n_fills == 0`` with every statistic ``0.0`` and
    an empty breakdown.
    """

    n_fills: int
    mean_bps: float
    median_bps: float
    p90_bps: float
    p99_bps: float
    n_book_exhausted: int
    per_instrument: tuple[InstrumentSlippage, ...]


def _percentile(sorted_values: list[float], q: float) -> float:
    """Return the ``q``-quantile (0..1) of an ascending ``sorted_values`` list.

    Linear interpolation between order statistics (the "inclusive" / numpy-default
    convention): index ``q*(n-1)``. ``sorted_values`` must be non-empty and
    ascending. A single value returns itself for any ``q``.
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _stats(values: list[float]) -> tuple[float, float, float, float]:
    """Return ``(mean, median, p90, p99)`` of ``values`` (``(0,0,0,0)`` when empty)."""
    if not values:
        return 0.0, 0.0, 0.0, 0.0
    ordered = sorted(values)
    mean = statistics.fmean(ordered)
    median = _percentile(ordered, 0.5)
    p90 = _percentile(ordered, 0.90)
    p99 = _percentile(ordered, 0.99)
    return mean, median, p90, p99


@dataclass(frozen=True, slots=True)
class _AuditRow:
    """One read of the fills audit columns (only rows WITH walked-book provenance)."""

    instrument_id: str
    slippage_bps: float
    book_exhausted: bool


class SlippageReport:
    """The modeled-vs-realized slippage report, built from a TradingStore's fills.

    Construct via :meth:`from_store`. Holds only the audited slippage rows in
    memory (the report is tiny -- a few bytes per fill). :meth:`summary` computes
    the aggregate and per-instrument statistics; :meth:`render_text` formats an
    aligned operator table.
    """

    __slots__ = ("_rows",)

    def __init__(self, rows: list[_AuditRow]) -> None:
        """Internal: use :meth:`from_store`. ``rows`` are pre-filtered audit reads."""
        self._rows = rows

    @classmethod
    def from_store(cls, store_path: Path) -> SlippageReport:
        """Read the audited fills from the TradingStore at ``store_path`` (read-only).

        Opens ``store_path`` in SQLite read-only mode (``mode=ro`` URI) so the
        report can run safely alongside the live loop's writer, and selects only
        fills that carry walked-book provenance (``walked_price IS NOT NULL`` and a
        non-null ``slippage_bps`` -- recovered broker fills without an audit are
        excluded, since they have no modeled-vs-realized signal). A store with no
        ``fills`` table yet (a brand-new file) reads as zero rows.

        Args:
            store_path: path to ``var/trading.sqlite``.

        Returns:
            A :class:`SlippageReport` over the audited fills (possibly empty).
        """
        uri = f"file:{store_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            if not _has_fills_table(conn):
                return cls([])
            cur = conn.execute(
                "SELECT instrument_id, slippage_bps, book_exhausted FROM fills "
                "WHERE walked_price IS NOT NULL AND slippage_bps IS NOT NULL "
                "ORDER BY fill_id"
            )
            rows = [
                _AuditRow(
                    instrument_id=str(r["instrument_id"]),
                    slippage_bps=float(r["slippage_bps"]),
                    book_exhausted=bool(r["book_exhausted"]),
                )
                for r in cur.fetchall()
            ]
        finally:
            conn.close()
        return cls(rows)

    def summary(self) -> SlippageSummary:
        """Compute aggregate and per-instrument slippage statistics.

        Counts, mean/median/p90/p99 of the stored adverse-signed ``slippage_bps``,
        and the number of book-exhausted fills, overall and broken down by
        instrument (sorted by ``instrument_id``). An empty report returns a fully
        zeroed summary with no per-instrument rows.
        """
        n_fills = len(self._rows)
        n_exhausted = sum(1 for r in self._rows if r.book_exhausted)
        mean, median, p90, p99 = _stats([r.slippage_bps for r in self._rows])

        by_instrument: dict[str, list[_AuditRow]] = {}
        for row in self._rows:
            by_instrument.setdefault(row.instrument_id, []).append(row)

        per_instrument = tuple(
            self._instrument_summary(instrument_id, rows)
            for instrument_id, rows in sorted(by_instrument.items())
        )
        return SlippageSummary(
            n_fills=n_fills,
            mean_bps=mean,
            median_bps=median,
            p90_bps=p90,
            p99_bps=p99,
            n_book_exhausted=n_exhausted,
            per_instrument=per_instrument,
        )

    @staticmethod
    def _instrument_summary(instrument_id: str, rows: list[_AuditRow]) -> InstrumentSlippage:
        """Roll up one instrument's audited fills into an :class:`InstrumentSlippage`."""
        mean, median, p90, p99 = _stats([r.slippage_bps for r in rows])
        return InstrumentSlippage(
            instrument_id=instrument_id,
            n_fills=len(rows),
            mean_bps=mean,
            median_bps=median,
            p90_bps=p90,
            p99_bps=p99,
            n_book_exhausted=sum(1 for r in rows if r.book_exhausted),
        )

    def render_text(self) -> str:
        """Render an aligned plain-text report (ASCII only) for the operator/tearsheet.

        Shows the overall line then a per-instrument table. A zero-fill store
        renders a clear 'no audited fills yet' notice rather than an empty table,
        so an early-soak report is unambiguous rather than blank.
        """
        s = self.summary()
        lines = ["modeled-vs-realized slippage (adverse bps, positive = worse than model)"]
        if s.n_fills == 0:
            lines.append("  no audited fills yet (0 walked-book fills recorded)")
            return "\n".join(lines)

        lines.append(
            f"  overall: n={s.n_fills}  mean={s.mean_bps:+.3f}  median={s.median_bps:+.3f}  "
            f"p90={s.p90_bps:+.3f}  p99={s.p99_bps:+.3f}  book_exhausted={s.n_book_exhausted}"
        )
        name_w = max(len(r.instrument_id) for r in s.per_instrument)
        name_w = max(name_w, len("instrument"))
        header = (
            f"  {'instrument':<{name_w}}  {'n':>5}  {'mean':>9}  {'median':>9}  "
            f"{'p90':>9}  {'p99':>9}  {'exhaust':>7}"
        )
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for r in s.per_instrument:
            lines.append(
                f"  {r.instrument_id:<{name_w}}  {r.n_fills:>5}  {r.mean_bps:>+9.3f}  "
                f"{r.median_bps:>+9.3f}  {r.p90_bps:>+9.3f}  {r.p99_bps:>+9.3f}  "
                f"{r.n_book_exhausted:>7}"
            )
        return "\n".join(lines)


def _has_fills_table(conn: sqlite3.Connection) -> bool:
    """True iff the connected database has a ``fills`` table (a fresh file has none)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'fills'"
    ).fetchone()
    return row is not None
