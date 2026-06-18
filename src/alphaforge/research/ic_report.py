"""Per-factor Rank-IC evidence over full history — THE Phase-4 go/no-go report.

For every registered DIRECTIONAL factor (``FeatureSpec.direction != 0``) and every
requested holding horizon ``h``, this module produces the §7.2 evidence row::

    RankIC_t = SpearmanCorr_i( direction_k · z_{k,i,t},  y_{i,t,h} )      over U_t
    summary  = (n, mean, std, t_NW, hit_rate, IC-IR, by-year means)

where

- ``z_{k,i,t}`` is the cross-sectionally processed factor value (CSPipeline
  winsorize_mad → cs_zscore under the PIT universe mask for ``cross_sectional``
  factors; the raw engine output for time-series factors),
- ``y_{i,t,h} = ln( O(τ+Δ) → O(τ+(1+h)Δ) )`` is the execution-aware forward log
  return of :func:`alphaforge.labeling.forward_returns` (§5.1) — signal at bar
  close, entry next open, exit ``h`` bars later,
- ``U_t`` is the point-in-time universe (``UniverseStore`` membership intervals;
  fail-closed — instruments without an interval covering ``t`` are non-members),
- inference runs on the NON-OVERLAPPING ``h``-bar grid
  (:func:`alphaforge.validation.non_overlapping`) with a Newey-West HAC t-stat at
  ``lags = NW_LAGS`` (residual serial correlation in factor exposures survives
  de-overlapping the labels, so plain i.i.d. lags=0 would still be optimistic).

PIT discipline: factor values come from :meth:`FeatureEngine.compute_history`
(every value at ``t`` is a pure function of data available at ``t + Δ``); the
universe mask is applied BEFORE any cross-sectional statistic (selection-bias
guard); only the *labels* look into the future — they are evaluation targets and
never feed back into features.

Direction adjustment makes the report uniformly readable: a healthy alpha shows a
POSITIVE mean IC regardless of its raw sign convention, because the processed
value is multiplied by ``FeatureSpec.direction`` before correlating.

Memory discipline: one batch ``compute_history`` pass shares a single PIT context
across all specs (float64 only); forward returns are built once per horizon and
deleted after use; per-factor processing walks columns, never copies the panel.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

import numpy as np
import pandas as pd
import pyarrow as pa

from alphaforge.config.sleeve import sleeve_for
from alphaforge.core.time import Ms, from_ms, now_ms
from alphaforge.core.types import AssetClass
from alphaforge.data.schemas import ohlcv_dataset
from alphaforge.features.cross_section import CSPipeline
from alphaforge.labeling import forward_returns
from alphaforge.validation import ICSummary, ic_summary, non_overlapping, rank_ic

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import FeatureRegistry
    from alphaforge.features.spec import FeatureSpec

__all__ = [
    "BARS_PER_YEAR",
    "DEFAULT_HORIZONS",
    "JSON_FILENAME",
    "NW_LAGS",
    "TEXT_FILENAME",
    "ICReport",
    "ICReportRunner",
    "ICRow",
]

NW_LAGS: Final[int] = 6
"""Newey-West lag depth for IC inference on the non-overlapping grid."""

DEFAULT_HORIZONS: Final[tuple[int, ...]] = (24, 72)
"""Default forward-return horizons in 1h bars (1d and 3d; §7.2 default h = 72)."""

JSON_FILENAME: Final[str] = "ic_report.json"
"""Filename of the persisted machine-readable report inside ``out_dir``."""

TEXT_FILENAME: Final[str] = "ic_report.txt"
"""Filename of the persisted human-readable table inside ``out_dir``."""

BARS_PER_YEAR: Final[float] = 8760.0
"""1h bars per 365d year (24/7 crypto) — used for the annualized IC-IR column."""

_NAN_TEXT: Final[str] = "-"


def _json_float(value: float) -> float | None:
    """NaN/inf → ``None`` (JSON has no NaN literal); finite floats pass through."""
    return float(value) if math.isfinite(value) else None


def _load_float(value: object) -> float:
    """Inverse of :func:`_json_float`: ``None`` → NaN."""
    return float("nan") if value is None else float(cast(float, value))


def _fmt(value: float, spec: str) -> str:
    """Format a float for the text table; NaN renders as ``-``."""
    return format(value, spec) if math.isfinite(value) else _NAN_TEXT


def _fmt_ts(ms: Ms) -> str:
    """Epoch ms UTC → compact ISO-8601 with a ``Z`` suffix."""
    return from_ms(ms).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True, kw_only=True)
class ICRow:
    """One (factor, horizon) evidence row of the report.

    - ``factor`` / ``family``: registry identity (``family`` is the StrEnum value).
    - ``horizon``: forward-return horizon ``h`` in 1h bars.
    - ``n_obs``: finite Rank-IC observations on the non-overlapping ``h``-grid.
    - ``mean_ic`` / ``t_nw`` / ``hit_rate`` / ``ic_ir``: the
      :class:`~alphaforge.validation.ICSummary` statistics (``t_nw`` at
      ``lags = NW_LAGS``); NaN when the factor produced no usable cross-sections
      (e.g. lookback exceeds the available history).
    - ``by_year``: UTC calendar year → mean IC, for stability inspection.
    """

    factor: str
    family: str
    horizon: int
    n_obs: int
    mean_ic: float
    t_nw: float
    hit_rate: float
    ic_ir: float
    by_year: Mapping[int, float]

    @property
    def ic_ir_ann(self) -> float:
        """Annualized IC-IR: ``ic_ir · sqrt(8760 / h)`` (§7.2; non-overlapping grid)."""
        return self.ic_ir * math.sqrt(BARS_PER_YEAR / self.horizon)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe mapping (NaN → null; ``by_year`` keys stringified)."""
        return {
            "factor": self.factor,
            "family": self.family,
            "horizon": self.horizon,
            "n_obs": self.n_obs,
            "mean_ic": _json_float(self.mean_ic),
            "t_nw": _json_float(self.t_nw),
            "hit_rate": _json_float(self.hit_rate),
            "ic_ir": _json_float(self.ic_ir),
            "by_year": {str(year): _json_float(v) for year, v in sorted(self.by_year.items())},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ICRow:
        """Inverse of :meth:`to_dict` (null → NaN; year keys back to int)."""
        by_year_raw = cast("Mapping[str, object]", data["by_year"])
        return cls(
            factor=str(data["factor"]),
            family=str(data["family"]),
            horizon=int(data["horizon"]),
            n_obs=int(data["n_obs"]),
            mean_ic=_load_float(data["mean_ic"]),
            t_nw=_load_float(data["t_nw"]),
            hit_rate=_load_float(data["hit_rate"]),
            ic_ir=_load_float(data["ic_ir"]),
            by_year={int(year): _load_float(v) for year, v in by_year_raw.items()},
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ICReport:
    """The full go/no-go report: one :class:`ICRow` per (directional factor, horizon).

    ``start``/``end`` bound the decision-bar span ``[start, end)`` (epoch ms UTC);
    ``generated_at`` is the wall clock at generation; ``universe_note`` documents
    the PIT mask provenance. Rows are stored in computation order (horizon-major,
    registry order within); :meth:`render_text` sorts by evidence strength.
    """

    rows: tuple[ICRow, ...]
    generated_at: Ms
    start: Ms
    end: Ms
    horizons: tuple[int, ...]
    n_instruments: int
    universe_note: str

    def to_json(self) -> str:
        """Serialize to deterministic, NaN-free JSON (round-trips via :meth:`from_json`)."""
        payload: dict[str, Any] = {
            "generated_at": self.generated_at,
            "start": self.start,
            "end": self.end,
            "horizons": list(self.horizons),
            "n_instruments": self.n_instruments,
            "nw_lags": NW_LAGS,
            "universe_note": self.universe_note,
            "rows": [row.to_dict() for row in self.rows],
        }
        return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)

    @classmethod
    def from_json(cls, text: str) -> ICReport:
        """Reconstruct a report from :meth:`to_json` output."""
        data = cast("Mapping[str, Any]", json.loads(text))
        return cls(
            rows=tuple(
                ICRow.from_dict(cast("Mapping[str, Any]", row))
                for row in cast("Sequence[object]", data["rows"])
            ),
            generated_at=int(data["generated_at"]),
            start=int(data["start"]),
            end=int(data["end"]),
            horizons=tuple(int(h) for h in cast("Sequence[int]", data["horizons"])),
            n_instruments=int(data["n_instruments"]),
            universe_note=str(data["universe_note"]),
        )

    def render_text(self) -> str:
        """Aligned evidence table, strongest |t_NW| first (NaN evidence last).

        Columns: factor, family, h, n, mean_ic, t_nw, hit, ic_ir, icir_ann
        (annualized IC-IR = ``ic_ir · sqrt(8760/h)``, §7.2). A ``-`` cell means
        the statistic is undefined (no usable cross-sections at that horizon).
        """

        def sort_key(row: ICRow) -> tuple[bool, float, str, int]:
            nan = not math.isfinite(row.t_nw)
            return (nan, -abs(row.t_nw) if not nan else 0.0, row.factor, row.horizon)

        ordered = sorted(self.rows, key=sort_key)
        name_w = max([len("factor"), *(len(r.factor) for r in ordered)])
        family_w = max([len("family"), *(len(r.family) for r in ordered)])
        header = (
            f"{'factor':<{name_w}}  {'family':<{family_w}}  {'h':>5}  {'n':>6}  "
            f"{'mean_ic':>8}  {'t_nw':>7}  {'hit':>5}  {'ic_ir':>7}  {'icir_ann':>8}"
        )
        lines = [
            "AlphaForge — factor Rank-IC report (alphaDesign.md §7.2)",
            f"span: [{_fmt_ts(self.start)}, {_fmt_ts(self.end)}) | "
            f"generated: {_fmt_ts(self.generated_at)}",
            f"horizons (1h bars): {', '.join(str(h) for h in self.horizons)} | "
            f"instruments: {self.n_instruments} | "
            f"inference: non-overlapping h-grid, Newey-West lags={NW_LAGS}",
            f"universe: {self.universe_note}",
            "",
            header,
            "-" * len(header),
        ]
        lines.extend(
            f"{row.factor:<{name_w}}  {row.family:<{family_w}}  {row.horizon:>5}  "
            f"{row.n_obs:>6}  {_fmt(row.mean_ic, '+8.4f'):>8}  {_fmt(row.t_nw, '+7.2f'):>7}  "
            f"{_fmt(row.hit_rate, '5.2f'):>5}  {_fmt(row.ic_ir, '+7.3f'):>7}  "
            f"{_fmt(row.ic_ir_ann, '+8.2f'):>8}"
            for row in ordered
        )
        return "\n".join(lines)


class ICReportRunner:
    """Computes the report end-to-end from the lake (see module docstring).

    Construction wires the already-built Phase-4 surfaces: the
    :class:`FeatureEngine` (PIT factor values), the :class:`PITDataReader` (bars
    for forward returns), the :class:`UniverseStore` (PIT membership mask), the
    :class:`FeatureRegistry` holding the factor library (import
    ``alphaforge.features.library`` before constructing the registry argument),
    and ``paths`` for instrument discovery — the report covers every instrument
    *physically present* in the OHLCV lake (``LakePaths.instrument_ids``), so
    delisted names participate for exactly their historical spans.
    """

    def __init__(
        self,
        engine: FeatureEngine,
        reader: PITDataReader,
        universe: UniverseStore,
        registry: FeatureRegistry,
        *,
        paths: LakePaths,
        asset_class: AssetClass = AssetClass.CRYPTO_PERP,
    ) -> None:
        self._engine = engine
        self._reader = reader
        self._universe = universe
        self._registry = registry
        self._paths = paths
        # Sleeve resolves the anchor TF (H1 crypto / D1 equity), the trading calendar
        # (24/7 / XNYS) for the forward-return session hops, and the OHLCV dataset
        # (OHLCV / OHLCV_1D). Default CRYPTO_PERP keeps the crypto path byte-identical.
        self._asset_class = asset_class
        sleeve = sleeve_for(asset_class)
        self._tf = sleeve.anchor_tf
        self._calendar = sleeve.calendar
        self._dataset = ohlcv_dataset(self._tf)

    def run(
        self,
        *,
        start: Ms,
        end: Ms,
        horizons: Sequence[int] = DEFAULT_HORIZONS,
        out_dir: Path,
    ) -> ICReport:
        """Build, persist (JSON + text under ``out_dir``), and return the report.

        Pipeline per the module docstring:

        1. ``compute_history`` for ALL directional registry specs over
           ``[start, end)`` x every instrument with OHLCV data in the lake.
        2. PIT universe mask, vectorized over the stored membership intervals.
        3. CSPipeline (winsorize_mad → cs_zscore) under the mask for
           ``cross_sectional`` factors; raw values for time-series factors.
        4. Direction-adjust: ``adjusted = direction · processed``.
        5. Per horizon ``h``: execution-aware forward log returns, Rank-IC per
           timestamp over members, subsampled to the non-overlapping ``h``-grid.
        6. :func:`ic_summary` with ``lags = NW_LAGS`` → one :class:`ICRow`.

        Raises ``ValueError`` on an invalid span/horizons, an empty lake, or a
        registry without directional specs. Factors whose lookback exceeds the
        available history simply report ``n_obs = 0`` with NaN statistics — they
        still appear (an invisible factor is how a broken one ships).
        """
        if end <= start:
            raise ValueError(f"run requires end > start, got [{start}, {end})")
        hs = tuple(int(h) for h in horizons)
        if not hs:
            raise ValueError("at least one horizon is required")
        if any(h <= 0 for h in hs):
            raise ValueError(f"horizons must all be > 0; got {hs}")
        if len(set(hs)) != len(hs):
            raise ValueError(f"horizons must be unique; got {hs}")

        directional = [s for s in self._registry.all_specs() if s.direction != 0]
        # Scope factors to the SLEEVE: the eq_* library for EQUITY, everything else (the
        # crypto library, incl. funding/carry factors that have no equity analogue) for
        # crypto. Running a crypto carry factor on equity data errors (no funding metadata).
        is_equity = self._asset_class is AssetClass.EQUITY
        specs = [s for s in directional if s.name.startswith("eq_") == is_equity]
        if not specs:
            raise ValueError(
                f"no directional specs for the {self._asset_class.value} sleeve; "
                "import alphaforge.features.library before building the registry"
            )
        # Scope instruments to the candidate set. EQUITY: the liquid universe's members
        # (ever) that have bars — NOT every one of the ~10k tickers in the lake (many are
        # not even in the SCD2 store, e.g. non-common types). Crypto: the full lake (its
        # ~tens of names ARE the candidate set), unchanged so the crypto IC is byte-identical.
        if is_equity:
            universe_members = set(
                self._universe.read_intervals().column("instrument_id").to_pylist()
            )
            in_lake = set(self._paths.instrument_ids(self._dataset))
            instrument_ids = sorted(universe_members & in_lake)
        else:
            instrument_ids = self._paths.instrument_ids(self._dataset)
        if not instrument_ids:
            raise ValueError(
                "no instruments with OHLCV data for the candidate set; ingest bars "
                "(and, for equities, build the universe via 'af universe rebuild') first"
            )

        adjusted = self._adjusted_factors(specs, instrument_ids, start=start, end=end)
        mask = _membership_mask(self._universe, adjusted)
        bars = self._bars_frame(instrument_ids, start=start, end=end, h_max=max(hs))

        rows: list[ICRow] = []
        for h in hs:
            fwd = forward_returns(bars, h, timeframe=self._tf, calendar=self._calendar)
            for spec in specs:
                ic_dense = rank_ic(adjusted[spec.name], fwd, mask)
                summary: ICSummary = ic_summary(non_overlapping(ic_dense, h), lags=NW_LAGS)
                rows.append(
                    ICRow(
                        factor=spec.name,
                        family=spec.family.value,
                        horizon=h,
                        n_obs=summary.n,
                        mean_ic=summary.mean,
                        t_nw=summary.t_nw,
                        hit_rate=summary.hit_rate,
                        ic_ir=summary.ic_ir,
                        by_year=dict(summary.by_year),
                    )
                )
                del ic_dense
            del fwd
        del bars, adjusted

        intervals = self._universe.read_intervals()
        members = len(set(intervals.column("instrument_id").to_pylist()))
        report = ICReport(
            rows=tuple(rows),
            generated_at=now_ms(),
            start=start,
            end=end,
            horizons=hs,
            n_instruments=len(instrument_ids),
            universe_note=(
                f"PIT membership intervals from UniverseStore "
                f"({intervals.num_rows} interval(s), {members} distinct member(s)); "
                "non-members masked before all cross-sectional statistics"
            ),
        )
        _persist(report, out_dir)
        return report

    def _adjusted_factors(
        self,
        specs: Sequence[FeatureSpec],
        instrument_ids: Sequence[str],
        *,
        start: Ms,
        end: Ms,
    ) -> pd.DataFrame:
        """Steps 1, 3, 4: engine batch pass → CS processing under the mask → x direction.

        Returns the direction-adjusted factor frame (columns = spec names, index =
        the engine's complete ``(ts_open, instrument_id)`` grid). Cross-sectional
        columns are winsorized and z-scored over PIT members only (the mask is
        applied *inside* :meth:`CSPipeline.apply`, before any statistic — the
        selection-bias guard); time-series columns pass through raw.
        """
        raw = self._engine.compute_history(specs, instrument_ids, start=start, end=end)
        assert isinstance(raw.index, pd.MultiIndex)  # engine contract; mypy aid
        mask = _membership_mask(self._universe, raw)
        cs_names = [s.name for s in specs if s.cross_sectional]
        processed = (
            CSPipeline().apply(raw[cs_names], mask) if cs_names else pd.DataFrame(index=raw.index)
        )
        adjusted = {
            spec.name: (processed[spec.name] if spec.cross_sectional else raw[spec.name])
            * float(spec.direction)
            for spec in specs
        }
        return pd.DataFrame(adjusted, index=raw.index)

    def _bars_frame(
        self, instrument_ids: Sequence[str], *, start: Ms, end: Ms, h_max: int
    ) -> pd.DataFrame:
        """Long bar frame for :func:`forward_returns` (instrument_id, ts_open, open).

        The read extends ``(h_max + 1)`` bars past ``end`` so the label of the last
        decision bar (exit at ``τ + (1 + h)·Δ``) exists when the lake has the data;
        ``as_of`` equals the read horizon — labels are evaluation-only and may see
        the future by construction (they never re-enter the feature path).
        ``ts_open`` is cast to int64 epoch ms (the labeler's contract).
        """
        delta = self._tf.ms
        read_end = end + (h_max + 1) * delta
        tbl = self._reader.ohlcv(
            instrument_ids, start=start, end=read_end, as_of=read_end, tf=self._tf
        )
        ts = tbl.column("ts_open").cast(pa.int64()).combine_chunks().to_numpy(zero_copy_only=False)
        return pd.DataFrame(
            {
                "instrument_id": tbl.column("instrument_id").to_pylist(),
                "ts_open": np.asarray(ts, dtype=np.int64),
                "open": tbl.column("open").combine_chunks().to_numpy(zero_copy_only=False),
            }
        )


def _membership_mask(universe: UniverseStore, panel: pd.DataFrame) -> pd.Series:
    """Boolean membership Series over ``panel``'s ``(ts_open, instrument_id)`` grid.

    Vectorized over the stored membership intervals (one ``read_intervals`` call,
    one ``searchsorted`` pair per interval — NEVER a per-row ``membership_asof``
    sweep): ``(t, i)`` is True iff some interval of ``i`` satisfies
    ``effective_from <= t`` and (``effective_to`` is null or ``> t``) — the same
    half-open semantics as ``UniverseStore.membership_asof``. Instruments without
    any interval are False everywhere (fail-closed). Consumers align by reindex
    with ``fill_value=False``, so coverage gaps stay non-member.
    """
    index = panel.index
    assert isinstance(index, pd.MultiIndex)  # engine contract; mypy aid
    ts_grid = np.unique(index.get_level_values("ts_open").to_numpy(dtype=np.int64))
    ids: list[str] = list(dict.fromkeys(index.get_level_values("instrument_id")))
    id_pos = {iid: j for j, iid in enumerate(ids)}

    member = np.zeros((ts_grid.size, len(ids)), dtype=bool)
    intervals = universe.read_intervals()
    iids: list[str] = intervals.column("instrument_id").to_pylist()
    froms: list[int] = intervals.column("effective_from").cast(pa.int64()).to_pylist()
    tos: list[int | None] = intervals.column("effective_to").cast(pa.int64()).to_pylist()
    for iid, eff_from, eff_to in zip(iids, froms, tos, strict=True):
        j = id_pos.get(iid)
        if j is None:
            continue
        lo = int(np.searchsorted(ts_grid, eff_from, side="left"))
        hi = ts_grid.size if eff_to is None else int(np.searchsorted(ts_grid, eff_to, side="left"))
        if lo < hi:
            member[lo:hi, j] = True

    grid_index = pd.MultiIndex.from_product([ts_grid, ids], names=("ts_open", "instrument_id"))
    return pd.Series(member.ravel(), index=grid_index, name="is_member")


def _persist(report: ICReport, out_dir: Path) -> None:
    """Write ``ic_report.json`` and ``ic_report.txt`` under ``out_dir`` (mkdir -p)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / JSON_FILENAME).write_text(report.to_json() + "\n", encoding="utf-8")
    (out_dir / TEXT_FILENAME).write_text(report.render_text() + "\n", encoding="utf-8")
