"""Unit tests for alphaforge.research.ic_report (+ the ``af research ic`` CLI).

World construction: six universe members with cross-sectionally spread constant
drifts plus small i.i.d. noise — a PERFECT momentum world (past relative strength
predicts future relative strength), so direction-adjusted ``mom_xs_*`` factors must
show strongly positive Rank-IC with NW t > 2. Funding rates are ranked WITH drift
(high carry cost on the future winners), i.e. an ANTI-carry world: the
``carry_fund_*`` factors (direction +1 on ``-f̄``) must show strongly negative IC.

Leakage/selection guards under test: a non-member instrument with a deliberately
adversarial price path (momentum up, future down) sits in the lake but NOT in the
universe — every reported statistic must be bit-identical to a lake without it.
Inference honesty: ``n_obs`` must equal the non-overlapping ``ceil(span/h)`` grid
size, factors whose lookback exceeds available history must still appear (as NaN
rows), and the JSON artifact must round-trip exactly.

All tests run against deterministic synthetic tmp lakes (offline).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pytest

from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library import __all__ as _library_all  # registers the library
from alphaforge.features.registry import FeatureRegistry, default_registry
from alphaforge.research.ic_report import (
    JSON_FILENAME,
    NW_LAGS,
    TEXT_FILENAME,
    ICReport,
    ICReportRunner,
    ICRow,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

assert _library_all  # the import side effect (registration) is the point

HOUR = 3_600_000
MIN5 = 300_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z (1h- and 8h-aligned)
N_BARS = 2000
START = T0 + 760 * HOUR  # past carry_fund_90 (729) and mom_xs_504_48 (553) warmups
END = T0 + 1900 * HOUR  # leaves 100 bars for the h=72 exit legs
N_TS = (END - START) // HOUR  # 1140 decision bars
HORIZONS = (24, 72)

MEMBERS = [
    "BINANCE:PERP:ALPUSDT",
    "BINANCE:PERP:BETUSDT",
    "BINANCE:PERP:CHIUSDT",
    "BINANCE:PERP:DELUSDT",
    "BINANCE:PERP:EPSUSDT",
    "BINANCE:PERP:FOXUSDT",
]
EVIL = "BINANCE:PERP:EVLUSDT"  # in the lake, never in the universe

# Constant per-bar drifts, cross-sectionally spread: rank(mu) == rank(fwd return).
DRIFTS = {iid: (k - 2.5) * 0.0012 for k, iid in enumerate(MEMBERS)}
NOISE_SIGMA = 0.004
# Funding ranked WITH drift => carry (= -f̄·ann) anti-ranked with fwd returns.
FUNDING = {iid: 0.0001 * (k + 1) for k, iid in enumerate(MEMBERS)}

DIRECTIONAL = (
    "mom_xs_168_24",
    "mom_xs_504_48",
    "mom_xs_2160_168",
    "mom_ts_168",
    "mom_ts_504",
    "mom_ts_2160",
    "mr_res_24",
    "mr_res_72",
    "carry_fund_21",
    "carry_fund_90",
)
# Factors whose window reaches past the lake's first bar for EVERY decision ts in
# [START, END): C_{t-2160} never exists (END is bar 1900) => all-NaN rows.
COLD = ("mom_xs_2160_168", "mom_ts_2160")


# --------------------------------------------------------------------------- builders


def _close_path(seed: int, mu: float, n: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(mu + NOISE_SIGMA * rng.normal(0.0, 1.0, n)))


def _evil_path(n: int) -> np.ndarray:
    """Adversarial non-member: strong momentum into a strong reversal (IC poison)."""
    drift = np.where(np.arange(n) < n // 2, 0.004, -0.004)
    rng = np.random.default_rng(666)
    return 100.0 * np.exp(np.cumsum(drift + 0.001 * rng.normal(0.0, 1.0, n)))


def _ohlcv_table(closes: dict[str, np.ndarray]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    opens: list[float] = []
    close_col: list[float] = []
    for iid, close in closes.items():
        n = len(close)
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        opens.append(float(close[0]))
        opens.extend(float(v) for v in close[:-1])  # open = previous close
        close_col.extend(float(v) for v in close)
    n_rows = len(iids)
    high = [max(o, c) * 1.001 for o, c in zip(opens, close_col, strict=True)]
    low = [min(o, c) * 0.999 for o, c in zip(opens, close_col, strict=True)]
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(opens, type=pa.float64()),
            "high": pa.array(high, type=pa.float64()),
            "low": pa.array(low, type=pa.float64()),
            "close": pa.array(close_col, type=pa.float64()),
            "volume": pa.array([10.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([1000.0] * n_rows, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _funding_table(instrument_ids: list[str]) -> pa.Table:
    rows: list[tuple[str, int, float, int]] = []
    for iid in instrument_ids:
        rate = FUNDING.get(iid, 0.001)
        for j in range(N_BARS // 8):
            settle = T0 + j * 8 * HOUR
            rows.append((iid, settle, rate, settle + MIN5))
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "ts_funding": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "rate": pa.array([r[2] for r in rows], type=pa.float64()),
            "available_at": pa.array([r[3] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "ingested_at": pa.array([r[3] + 1000 for r in rows], type=pa.timestamp("ms", tz="UTC")),
        }
    )


def _universe_table(instrument_ids: list[str]) -> pa.Table:
    n = len(instrument_ids)
    return pa.table(
        {
            "instrument_id": pa.array(instrument_ids, type=pa.string()),
            "effective_from": pa.array([T0] * n, type=pa.timestamp("ms", tz="UTC")),
            "effective_to": pa.array([None] * n, type=pa.timestamp("ms", tz="UTC")),
            "rank": pa.array(list(range(1, n + 1)), type=pa.int32()),
            "reason": pa.array(["test_member"] * n, type=pa.string()),
        }
    )


def _instrument(instrument_id: str) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=instrument_id.split(":")[2].removesuffix("USDT"),
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


def _seed_instruments(db_path: Path, instrument_ids: list[str]) -> None:
    with InstrumentStore(db_path) as store:
        for iid in instrument_ids:
            store.upsert(_instrument(iid), as_of=T0 - 1000)


def _build_lake(root: Path, *, with_evil: bool) -> LakePaths:
    paths = LakePaths(root / "lake")
    writer = LakeWriter(paths)
    closes = {iid: _close_path(100 + k, DRIFTS[iid], N_BARS) for k, iid in enumerate(MEMBERS)}
    instrument_ids = list(MEMBERS)
    if with_evil:
        closes[EVIL] = _evil_path(N_BARS)
        instrument_ids.append(EVIL)
    writer.write(Dataset.OHLCV, _ohlcv_table(closes))
    writer.write(Dataset.FUNDING, _funding_table(instrument_ids))
    UniverseStore(paths).write_intervals(_universe_table(MEMBERS))  # EVIL never a member
    return paths


@dataclass(frozen=True)
class Env:
    paths: LakePaths
    engine: FeatureEngine
    reader: PITDataReader
    universe: UniverseStore
    runner: ICReportRunner
    report: ICReport
    out_dir: Path


def _library_registry() -> FeatureRegistry:
    """Exactly the library's directional specs, copied out of the global registry.

    The process-global ``default_registry()`` is shared suite-wide and other test
    modules legitimately register throwaway specs into it (e.g. the ``@feature``
    decorator tests); pinning the spec set keeps this module deterministic under
    any test ordering.
    """
    registry = FeatureRegistry()
    source = default_registry()
    for name in DIRECTIONAL:
        spec = source.get(name)
        registry.register(lambda s=spec: s)
    return registry


def _make_env(tmp: Path, *, with_evil: bool) -> Iterator[Env]:
    paths = _build_lake(tmp, with_evil=with_evil)
    ids = [*MEMBERS, EVIL] if with_evil else list(MEMBERS)
    _seed_instruments(tmp / "instruments.db", ids)
    instruments = InstrumentStore(tmp / "instruments.db")
    reader = PITDataReader(paths)
    universe = UniverseStore(paths)
    engine = FeatureEngine(reader, instruments, universe)
    runner = ICReportRunner(engine, reader, universe, _library_registry(), paths=paths)
    out_dir = tmp / "out" / "nested"  # exercises mkdir(parents=True)
    report = runner.run(start=START, end=END, horizons=HORIZONS, out_dir=out_dir)
    yield Env(
        paths=paths,
        engine=engine,
        reader=reader,
        universe=universe,
        runner=runner,
        report=report,
        out_dir=out_dir,
    )
    instruments.close()


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    """Six members, no adversary — the reference world."""
    yield from _make_env(tmp_path_factory.mktemp("ic_report_clean"), with_evil=False)


@pytest.fixture(scope="module")
def env_evil(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    """Same six members + an adversarial NON-member in the lake."""
    yield from _make_env(tmp_path_factory.mktemp("ic_report_evil"), with_evil=True)


def _row(report: ICReport, factor: str, horizon: int) -> ICRow:
    matches = [r for r in report.rows if r.factor == factor and r.horizon == horizon]
    assert len(matches) == 1, f"expected exactly one row for ({factor}, {horizon})"
    return matches[0]


# ----------------------------------------------------------------------- report shape


class TestReportShape:
    def test_rows_cover_directional_specs_times_horizons(self, env: Env) -> None:
        got = {(r.factor, r.horizon) for r in env.report.rows}
        expected = {(name, h) for name in DIRECTIONAL for h in HORIZONS}
        assert got == expected
        assert len(env.report.rows) == len(expected)  # no duplicates

    def test_families_match_registry(self, env: Env) -> None:
        registry = default_registry()
        for row in env.report.rows:
            assert row.family == registry.get(row.factor).family.value

    def test_no_nondirectional_factors(self, env: Env) -> None:
        factors = {r.factor for r in env.report.rows}
        for name in ("vol_yz_168", "liq_amihud_720", "adv_quote_30d", "reg_rvp_720", "close_px"):
            assert name not in factors

    def test_n_obs_equals_non_overlapping_grid(self, env: Env) -> None:
        # The dense grid has N_TS timestamps; keeping every h-th gives ceil(N_TS/h).
        for h in HORIZONS:
            row = _row(env.report, "mom_xs_168_24", h)
            assert row.n_obs == math.ceil(N_TS / h)

    def test_subsampling_actually_thins_the_grid(self, env: Env) -> None:
        row24 = _row(env.report, "mom_xs_168_24", 24)
        row72 = _row(env.report, "mom_xs_168_24", 72)
        assert row24.n_obs < N_TS  # not the dense grid
        assert row72.n_obs < row24.n_obs  # longer horizon => fewer obs

    def test_insufficient_history_factors_emit_nan_rows(self, env: Env) -> None:
        for name in COLD:
            for h in HORIZONS:
                row = _row(env.report, name, h)
                assert row.n_obs == 0
                assert math.isnan(row.mean_ic)
                assert math.isnan(row.t_nw)
                assert row.by_year == {}

    def test_by_year_buckets(self, env: Env) -> None:
        row = _row(env.report, "mom_xs_168_24", 24)
        assert set(row.by_year) == {2024}  # the whole span is inside 2024
        assert row.by_year[2024] == pytest.approx(row.mean_ic)

    def test_report_metadata(self, env: Env) -> None:
        assert env.report.start == START
        assert env.report.end == END
        assert env.report.horizons == HORIZONS
        assert env.report.n_instruments == len(MEMBERS)
        assert "interval" in env.report.universe_note


# -------------------------------------------------------------------- planted alphas


class TestPlantedEvidence:
    def test_momentum_world_positive_ic(self, env: Env) -> None:
        for name in ("mom_xs_168_24", "mom_xs_504_48"):
            for h in HORIZONS:
                row = _row(env.report, name, h)
                assert row.mean_ic > 0.3, f"{name}@{h}: mean_ic={row.mean_ic}"
                assert row.t_nw > 2.0, f"{name}@{h}: t_nw={row.t_nw}"
                assert row.hit_rate > 0.8

    def test_anti_carry_world_negative_ic(self, env: Env) -> None:
        for name in ("carry_fund_21", "carry_fund_90"):
            for h in HORIZONS:
                row = _row(env.report, name, h)
                assert row.mean_ic < -0.3, f"{name}@{h}: mean_ic={row.mean_ic}"
                assert row.t_nw < -2.0, f"{name}@{h}: t_nw={row.t_nw}"

    def test_ic_ir_annualization(self, env: Env) -> None:
        row = _row(env.report, "mom_xs_168_24", 24)
        assert row.ic_ir_ann == pytest.approx(row.ic_ir * math.sqrt(8760.0 / 24.0))


# -------------------------------------------------------------------- universe mask


class TestUniverseMask:
    def test_non_member_with_insane_values_does_not_move_ic(self, env: Env, env_evil: Env) -> None:
        """EVIL trends up then crashes (max momentum, negative fwd) but is NOT a
        member: every reported statistic must match the EVIL-free lake exactly."""
        assert env_evil.report.n_instruments == len(MEMBERS) + 1  # it IS in the lake
        for clean in env.report.rows:
            evil = _row(env_evil.report, clean.factor, clean.horizon)
            assert evil.n_obs == clean.n_obs
            for a, b in (
                (evil.mean_ic, clean.mean_ic),
                (evil.t_nw, clean.t_nw),
                (evil.hit_rate, clean.hit_rate),
                (evil.ic_ir, clean.ic_ir),
            ):
                assert (math.isnan(a) and math.isnan(b)) or a == pytest.approx(b, rel=1e-12)


# ---------------------------------------------------------------------- persistence


class TestPersistence:
    def test_out_dir_created_with_both_artifacts(self, env: Env) -> None:
        assert (env.out_dir / JSON_FILENAME).is_file()
        assert (env.out_dir / TEXT_FILENAME).is_file()

    def test_json_roundtrip_in_memory(self, env: Env) -> None:
        clone = ICReport.from_json(env.report.to_json())
        assert clone.generated_at == env.report.generated_at
        assert clone.start == env.report.start
        assert clone.end == env.report.end
        assert clone.horizons == env.report.horizons
        assert clone.n_instruments == env.report.n_instruments
        assert clone.universe_note == env.report.universe_note
        # to_dict maps NaN -> None, so row comparison is NaN-safe and exact.
        assert [r.to_dict() for r in clone.rows] == [r.to_dict() for r in env.report.rows]

    def test_persisted_json_matches_report(self, env: Env) -> None:
        text = (env.out_dir / JSON_FILENAME).read_text(encoding="utf-8")
        parsed = json.loads(text)  # valid JSON (no NaN literals)
        assert parsed["nw_lags"] == NW_LAGS
        clone = ICReport.from_json(text)
        assert [r.to_dict() for r in clone.rows] == [r.to_dict() for r in env.report.rows]

    def test_persisted_text_matches_render(self, env: Env) -> None:
        text = (env.out_dir / TEXT_FILENAME).read_text(encoding="utf-8")
        assert text == env.report.render_text() + "\n"


# --------------------------------------------------------------------------- render


class TestRenderText:
    def test_contains_every_directional_factor(self, env: Env) -> None:
        text = env.report.render_text()
        for name in DIRECTIONAL:
            assert name in text

    def test_sorted_by_abs_tnw_desc_nan_last(self, env: Env) -> None:
        text = env.report.render_text()
        data_lines = [line for line in text.splitlines() if re.match(r"^(mom_|mr_|carry_)", line)]
        assert len(data_lines) == len(env.report.rows)
        rendered_keys = [(line.split()[0], line.split()[2]) for line in data_lines]
        t_by_key = {(r.factor, str(r.horizon)): r.t_nw for r in env.report.rows}
        t_values = [t_by_key[(factor, h)] for factor, h in rendered_keys]
        finite = [abs(t) for t in t_values if math.isfinite(t)]
        assert finite == sorted(finite, reverse=True)
        first_nan = next((i for i, t in enumerate(t_values) if math.isnan(t)), len(t_values))
        assert all(math.isnan(t) for t in t_values[first_nan:])  # NaN block is a suffix

    def test_nan_statistics_render_as_dash(self, env: Env) -> None:
        text = env.report.render_text()
        cold_line = next(line for line in text.splitlines() if line.startswith(COLD[0] + " "))
        assert " - " in f"{cold_line} "  # NaN cells render as '-'

    def test_header_mentions_span_and_inference(self, env: Env) -> None:
        text = env.report.render_text()
        assert "2024-" in text
        assert f"Newey-West lags={NW_LAGS}" in text
        assert "non-overlapping" in text


# ----------------------------------------------------------------------- validation


class TestValidation:
    def test_end_not_after_start_raises(self, env: Env, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="end > start"):
            env.runner.run(start=END, end=START, horizons=(24,), out_dir=tmp_path)

    def test_empty_horizons_raises(self, env: Env, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="at least one horizon"):
            env.runner.run(start=START, end=END, horizons=(), out_dir=tmp_path)

    def test_nonpositive_horizon_raises(self, env: Env, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="> 0"):
            env.runner.run(start=START, end=END, horizons=(24, 0), out_dir=tmp_path)

    def test_duplicate_horizons_raise(self, env: Env, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unique"):
            env.runner.run(start=START, end=END, horizons=(24, 24), out_dir=tmp_path)

    def test_registry_without_directional_specs_raises(self, env: Env, tmp_path: Path) -> None:
        runner = ICReportRunner(
            env.engine,
            env.reader,
            env.universe,
            FeatureRegistry(),  # empty: nothing directional registered
            paths=env.paths,
        )
        with pytest.raises(ValueError, match="no directional specs"):
            runner.run(start=START, end=END, horizons=(24,), out_dir=tmp_path)

    def test_empty_lake_raises(self, env: Env, tmp_path: Path) -> None:
        runner = ICReportRunner(
            env.engine,
            env.reader,
            env.universe,
            _library_registry(),
            paths=LakePaths(tmp_path / "empty_lake"),
        )
        with pytest.raises(ValueError, match="no instruments"):
            runner.run(start=START, end=END, horizons=(24,), out_dir=tmp_path)

    def test_validation_failures_write_nothing(self, env: Env, tmp_path: Path) -> None:
        out = tmp_path / "never_created"
        with pytest.raises(ValueError, match="unique"):
            env.runner.run(start=START, end=END, horizons=(24, 24), out_dir=out)
        assert not out.exists()


# ------------------------------------------------------------------------------ CLI


class TestCli:
    def test_af_research_ic_smoke(
        self,
        env: Env,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """End-to-end through the typer app against the module fixture's lake."""
        from typer.testing import CliRunner

        from alphaforge.cli.research_cmds import research_app

        var_dir = tmp_path / "var"
        var_dir.mkdir()
        _seed_instruments(var_dir / "ops.sqlite", list(MEMBERS))
        out_dir = tmp_path / "research_out"
        monkeypatch.setenv("AF_PATHS__LAKE_DIR", str(env.paths.root))
        monkeypatch.setenv("AF_PATHS__VAR_DIR", str(var_dir))
        # Shield the CLI from suite-wide pollution of the process-global registry
        # (other modules register throwaway specs via the @feature decorator).
        monkeypatch.setattr("alphaforge.features.registry.default_registry", _library_registry)

        result = CliRunner().invoke(
            research_app,
            [
                "ic",
                "--start",
                "2024-02-01",
                "--end",
                "2024-03-20",
                "--horizons",
                "24",
                "--out",
                str(out_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "mom_xs_168_24" in result.output
        assert str(out_dir / JSON_FILENAME) in result.output
        assert (out_dir / JSON_FILENAME).is_file()
        report = ICReport.from_json((out_dir / JSON_FILENAME).read_text(encoding="utf-8"))
        assert report.horizons == (24,)
        assert {r.factor for r in report.rows} == set(DIRECTIONAL)

    def test_bad_horizons_rejected(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from alphaforge.cli.research_cmds import research_app

        result = CliRunner().invoke(
            research_app, ["ic", "--horizons", "24,zebra", "--out", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "horizons" in result.output
