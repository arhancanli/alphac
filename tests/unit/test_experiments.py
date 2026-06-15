"""Unit tests for the anti-overfit experiment ledger + walk-forward DSR wiring.

Covers (alphaDesign.md section 7.4):

* :class:`~alphaforge.validation.experiments.ExperimentLog` round-trip through a
  tmp JSONL file, idempotency on the config hash (a re-run never inflates N),
  ``n_trials`` counting DISTINCT configs, and ``trial_sharpe_variance`` matching
  a hand-computed ddof=1 sample variance (and the <2-trial documented default).
* :func:`config_hash` stability under key reordering and equivalent spellings.
* The walk-forward DSR wiring: :func:`~alphaforge.analytics.walkforward.compute_validation`
  on a synthetic equity curve records exactly one trial and produces a
  ValidationReport whose fields match the (stubbed-deterministic) DSR report;
  the runner attaches the ``validation`` block to the saved walkforward.json.
* CLI smoke: ``af research evaluate`` over a saved run dir prints PSR/DSR and the
  honest verdict.

Offline, tmp_path only, deterministic (every now_ms is passed in, never read).
"""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from alphaforge.analytics.walkforward import (
    ValidationReport,
    compute_validation,
)
from alphaforge.validation.dsr import DSRReport
from alphaforge.validation.experiments import (
    DEFAULT_SR_TRIALS_VARIANCE,
    ExperimentLog,
    ExperimentRecord,
    config_hash,
)

if TYPE_CHECKING:
    from pathlib import Path

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z


# ---------------------------------------------------------------------------
# config_hash
# ---------------------------------------------------------------------------


class TestConfigHash:
    def test_stable_under_key_reordering(self) -> None:
        # Canonicalization sorts keys -> order does not change the hash.
        assert config_hash({"a": 1, "b": [2, 3]}) == config_hash({"b": [2, 3], "a": 1})

    def test_distinct_configs_distinct_hashes(self) -> None:
        assert config_hash({"a": 1}) != config_hash({"a": 2})

    def test_hash_is_16_hex_chars(self) -> None:
        h = config_hash({"allocator": "rank", "rebalance_bars": 24})
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_non_serializable_raises(self) -> None:
        with pytest.raises(TypeError):
            config_hash({"bad": object()})


# ---------------------------------------------------------------------------
# ExperimentLog
# ---------------------------------------------------------------------------


def _record(log: ExperimentLog, config: dict[str, object], sr_pp: float, now_ms: int) -> None:
    log.record(
        config,
        sharpe_ann=sr_pp * math.sqrt(365.0),
        sharpe_per_period=sr_pp,
        n_obs=200,
        skew=-0.3,
        kurtosis=4.0,
        now_ms=now_ms,
    )


class TestExperimentLog:
    def test_missing_file_reads_empty(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "absent.jsonl")
        assert log.all() == []
        assert log.n_trials() == 0
        # No finite trial Sharpes -> documented default V[SR].
        assert log.trial_sharpe_variance() == DEFAULT_SR_TRIALS_VARIANCE

    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "e.jsonl"
        log = ExperimentLog(path)
        rec = log.record(
            {"allocator": "rank", "rebalance_bars": 24},
            sharpe_ann=1.5,
            sharpe_per_period=0.0786,
            n_obs=250,
            skew=-0.4,
            kurtosis=5.2,
            now_ms=T0,
        )
        # Returned record matches what was passed.
        assert rec.now_ms == T0
        assert rec.sharpe_per_period == pytest.approx(0.0786)
        assert rec.config == {"allocator": "rank", "rebalance_bars": 24}
        # Persisted and re-read byte-faithfully.
        reread = ExperimentLog(path).all()
        assert len(reread) == 1
        got = reread[0]
        assert got.config_hash == rec.config_hash
        assert got.config == rec.config
        assert got.now_ms == T0
        assert got.sharpe_ann == pytest.approx(1.5)
        assert got.skew == pytest.approx(-0.4)
        assert got.kurtosis == pytest.approx(5.2)
        assert got.n_obs == 250

    def test_idempotent_on_config_hash(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "e.jsonl")
        _record(log, {"a": 1, "b": 2}, 0.10, 1_000)
        # Same config (reordered) with DIFFERENT metrics: must NOT add a line and
        # must return the ORIGINAL record (a re-run cannot inflate N or overwrite).
        again = log.record(
            {"b": 2, "a": 1},
            sharpe_ann=99.0,
            sharpe_per_period=9.0,
            n_obs=1,
            skew=0.0,
            kurtosis=3.0,
            now_ms=2_000,
        )
        assert log.n_trials() == 1
        assert again.now_ms == 1_000  # original, not the re-run
        assert again.sharpe_per_period == pytest.approx(0.10)
        assert len(log.all()) == 1

    def test_n_trials_counts_distinct(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "e.jsonl")
        _record(log, {"allocator": "rank"}, 0.10, 1)
        _record(log, {"allocator": "mvo"}, 0.20, 2)
        _record(log, {"allocator": "rank"}, 0.99, 3)  # dup of first -> no-op
        assert log.n_trials() == 2
        assert len(log.all()) == 2

    def test_trial_sharpe_variance_hand_computed(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "e.jsonl")
        # Per-period Sharpes 0.1, 0.3, 0.5: mean 0.3, ddof=1 var = ((0.2^2)+0+(0.2^2))/2 = 0.04.
        _record(log, {"c": 1}, 0.1, 1)
        _record(log, {"c": 2}, 0.3, 2)
        _record(log, {"c": 3}, 0.5, 3)
        assert log.trial_sharpe_variance() == pytest.approx(0.04, abs=1e-12)

    def test_variance_default_when_single_trial(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "e.jsonl")
        _record(log, {"c": 1}, 0.1, 1)
        assert log.trial_sharpe_variance() == DEFAULT_SR_TRIALS_VARIANCE

    def test_variance_ignores_non_finite_sharpes(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "e.jsonl")
        _record(log, {"c": 1}, 0.2, 1)
        _record(log, {"c": 2}, 0.4, 2)
        # A degenerate trial with a nan Sharpe round-trips as null and is excluded.
        log.record(
            {"c": 3},
            sharpe_ann=math.nan,
            sharpe_per_period=math.nan,
            n_obs=1,
            skew=math.nan,
            kurtosis=math.nan,
            now_ms=3,
        )
        assert log.n_trials() == 3
        # Variance over only [0.2, 0.4]: ddof=1 = 0.02.
        assert log.trial_sharpe_variance() == pytest.approx(0.02, abs=1e-12)

    def test_nan_round_trips_as_null(self, tmp_path: Path) -> None:
        path = tmp_path / "e.jsonl"
        log = ExperimentLog(path)
        log.record(
            {"c": 1},
            sharpe_ann=math.nan,
            sharpe_per_period=math.nan,
            n_obs=1,
            skew=math.nan,
            kurtosis=math.nan,
            now_ms=5,
        )
        raw = json.loads(path.read_text(encoding="utf-8").strip())
        assert raw["sharpe_ann"] is None
        assert raw["skew"] is None
        back = log.all()[0]
        assert math.isnan(back.sharpe_ann)
        assert math.isnan(back.skew)

    def test_corrupt_ledger_raises_with_line_number(self, tmp_path: Path) -> None:
        path = tmp_path / "e.jsonl"
        path.write_text('{"not": "a record"}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="line 1"):
            ExperimentLog(path).all()

    def test_blank_lines_tolerated(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "e.jsonl")
        _record(log, {"c": 1}, 0.1, 1)
        # Append a blank line manually; all() must skip it without error.
        with (tmp_path / "e.jsonl").open("a", encoding="utf-8") as fh:
            fh.write("\n")
        assert log.n_trials() == 1

    def test_record_json_obj_inverse(self) -> None:
        rec = ExperimentRecord(
            config_hash="abc",
            config={"a": 1},
            now_ms=7,
            sharpe_ann=1.0,
            sharpe_per_period=0.05,
            n_obs=10,
            skew=0.1,
            kurtosis=3.0,
        )
        back = ExperimentRecord.from_json_obj(rec.to_json_obj())
        assert back == rec


# ---------------------------------------------------------------------------
# walk-forward DSR wiring (compute_validation)
# ---------------------------------------------------------------------------


def _synthetic_equity(seed: int, n_days: int = 120, mu: float = 0.0004) -> pd.Series:
    """A deterministic hourly equity curve spanning ``n_days`` UTC days."""
    rng = np.random.default_rng(seed)
    n = n_days * 24
    rets = rng.normal(mu, 0.008, n)
    vals = 100_000.0 * np.exp(np.cumsum(rets))
    idx = np.array([T0 + k * HOUR for k in range(n)], dtype=np.int64)
    return pd.Series(vals, index=pd.Index(idx, name="ts"), name="equity")


class _StubDSR:
    """A deterministic DSR stub recording the exact arguments it was called with.

    Returns a REAL :class:`DSRReport` (not a duck) so the wiring is exercised
    against the production type, with fixed fields for assertion.
    """

    def __init__(self, dsr: float = 0.97) -> None:
        self.calls: list[tuple[int, int, float, float]] = []
        self._dsr = dsr

    def __call__(
        self,
        daily_returns: pd.Series,
        n_trials: int,
        sr_trials_variance: float,
        periods_per_year: float,
    ) -> DSRReport:
        self.calls.append((len(daily_returns), n_trials, sr_trials_variance, periods_per_year))
        return DSRReport(
            psr=0.80,
            dsr=self._dsr,
            sr_ann=1.23,
            sr_per_period=0.064,
            skew=-0.2,
            kurtosis=4.1,
            n_obs=len(daily_returns),
            expected_max_sr=0.11,
        )


class TestComputeValidation:
    def test_records_one_trial_and_builds_report(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "e.jsonl")
        equity = _synthetic_equity(1)
        stub = _StubDSR()
        report = compute_validation(
            equity, {"allocator": "rank", "rebalance_bars": 24}, log, now_ms=999, dsr_fn=stub
        )
        assert isinstance(report, ValidationReport)
        # Exactly one trial recorded with the passed-in timestamp.
        assert log.n_trials() == 1
        assert log.all()[0].now_ms == 999
        # Single trial -> n_trials reported honestly, but maths fed max(2, 1) = 2.
        assert report.n_trials == 1
        assert report.n_trials_used == 2
        assert stub.calls[0][1] == 2  # n_trials passed to DSR
        assert stub.calls[0][2] == DEFAULT_SR_TRIALS_VARIANCE  # V[SR] default for <2 trials
        assert stub.calls[0][3] == pytest.approx(365.0)  # periods_per_year
        # Report fields mirror the (stubbed) DSR result + the gate.
        assert report.psr == pytest.approx(0.80)
        assert report.dsr == pytest.approx(0.97)
        assert report.sr_ann == pytest.approx(1.23)
        assert report.expected_max_sr == pytest.approx(0.11)
        assert report.clears_dsr_gate is True  # 0.97 >= 0.95

    def test_gate_fails_below_threshold(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "e.jsonl")
        # 0.94 is just below the 0.95 deployment gate.
        report = compute_validation(
            _synthetic_equity(2), {"x": 1}, log, now_ms=1, dsr_fn=_StubDSR(dsr=0.94)
        )
        assert report is not None
        assert report.clears_dsr_gate is False

    def test_short_curve_returns_none_and_records_nothing(self, tmp_path: Path) -> None:
        log = ExperimentLog(tmp_path / "e.jsonl")
        equity = _synthetic_equity(3).iloc[:5]  # < 2 UTC days
        assert compute_validation(equity, {"x": 1}, log, now_ms=1, dsr_fn=_StubDSR()) is None
        assert log.n_trials() == 0  # nothing recorded

    def test_real_dsr_path_is_deterministic(self, tmp_path: Path) -> None:
        # No stub: exercises the real dsr_from_returns import + maths.
        log = ExperimentLog(tmp_path / "e.jsonl")
        equity = _synthetic_equity(4)
        a = compute_validation(equity, {"x": 1}, log, now_ms=10)
        assert a is not None
        assert 0.0 <= a.psr <= 1.0
        assert 0.0 <= a.dsr <= 1.0
        assert a.n_obs >= 2
        # Re-running the identical config is idempotent: still one trial, and the
        # DSR is reproducible bit-for-bit.
        b = compute_validation(equity, {"x": 1}, log, now_ms=20)
        assert b is not None
        assert log.n_trials() == 1
        assert b.dsr == pytest.approx(a.dsr, abs=1e-12)

    def test_distinct_configs_inflate_n_and_deflate(self, tmp_path: Path) -> None:
        # Two distinct trials -> N = 2 and a measured V[SR]; DSR uses both.
        log = ExperimentLog(tmp_path / "e.jsonl")
        compute_validation(_synthetic_equity(5), {"cfg": "a"}, log, now_ms=1)
        report = compute_validation(_synthetic_equity(6), {"cfg": "b"}, log, now_ms=2)
        assert report is not None
        assert report.n_trials == 2
        assert report.n_trials_used == 2
        # V[SR] is now the measured ledger variance, not the default 1.0.
        assert report.sr_trials_variance != DEFAULT_SR_TRIALS_VARIANCE


# ---------------------------------------------------------------------------
# runner wiring: the saved walkforward.json carries a validation block
# ---------------------------------------------------------------------------

_LAKE_IDS = tuple(f"BINANCE:PERP:{b}USDT" for b in ("BTC", "ETH", "SOL", "ADA"))


def _build_world(tmp: Path) -> object:
    """A minimal synthetic lake + stores driving the real WalkForwardRunner."""
    import pyarrow as pa

    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import Instrument, InstrumentStore
    from alphaforge.core.types import AssetClass, MarketType
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.schemas import Dataset
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.store.writer import LakeWriter
    from alphaforge.data.universe.store import UniverseStore

    def closes(seed: int, n: int, level: float) -> np.ndarray:
        rng = np.random.default_rng(seed)
        return np.asarray(level * np.exp(np.cumsum(rng.normal(0.0, 0.004, n))))

    n_bars = 1_200
    per_inst = {iid: closes(3 + k, n_bars, 30.0 * (k + 1)) for k, iid in enumerate(_LAKE_IDS)}
    iids: list[str] = []
    ts: list[int] = []
    opens: list[float] = []
    cl: list[float] = []
    for iid, close in per_inst.items():
        n = len(close)
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        opens.append(float(close[0]))
        opens.extend(float(v) for v in close[:-1])
        cl.extend(float(v) for v in close)
    n_rows = len(iids)
    table = pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(opens, type=pa.float64()),
            "high": pa.array([v * 1.002 for v in cl], type=pa.float64()),
            "low": pa.array([v * 0.998 for v in cl], type=pa.float64()),
            "close": pa.array(cl, type=pa.float64()),
            "volume": pa.array([10.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([1.0e6] * n_rows, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )
    paths = LakePaths(tmp / "lake")
    LakeWriter(paths).write(Dataset.OHLCV, table)
    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array(list(_LAKE_IDS), type=pa.string()),
                "effective_from": pa.array(
                    [T0] * len(_LAKE_IDS), type=pa.timestamp("ms", tz="UTC")
                ),
                "effective_to": pa.array(
                    [None] * len(_LAKE_IDS), type=pa.timestamp("ms", tz="UTC")
                ),
                "rank": pa.array([1] * len(_LAKE_IDS), type=pa.int32()),
                "reason": pa.array(["enter_top40"] * len(_LAKE_IDS), type=pa.string()),
            }
        )
    )
    store = InstrumentStore(tmp / "ops.sqlite")
    for iid in _LAKE_IDS:
        store.upsert(
            Instrument(
                instrument_id=iid,
                asset_class=AssetClass.CRYPTO_PERP,
                market_type=MarketType.PERP,
                base=iid.split(":")[2].removesuffix("USDT"),
                quote="USDT",
                tick_size=0.01,
                lot_size=0.0001,
                min_qty=0.0001,
                min_notional=5.0,
                can_short=True,
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                funding_interval_hours=8,
                listed_ts=T0 - 365 * 24 * HOUR,
                delisted_ts=None,
            ),
            as_of=T0 - 365 * 24 * HOUR,
        )
    from alphaforge.backtest import StaticCostInputs

    return {
        "reader": PITDataReader(paths),
        "store": store,
        "universe": universe,
        "cost_model": TransactionCostModel.from_settings(Settings()),
        "cost_inputs": StaticCostInputs(adv_quote=1.0e8, sigma_daily=0.05),
        "settings": Settings(),
    }


class _ConstMuSource:
    """Constant-mu_ann signal frame (the test_walkforward orchestration stub)."""

    def compute_research(self, start: int, end: int) -> pd.DataFrame:
        opens = list(range(start, end, HOUR))
        rows: list[dict[str, object]] = []
        for k, iid in enumerate(_LAKE_IDS):
            for ts_open in opens:
                rows.append(
                    {
                        "ts_open": ts_open,
                        "instrument_id": iid,
                        "alpha_blend": float(k - 1.5),
                        "mu_ann": 0.04 * float(k - 1.5),
                    }
                )
        return pd.DataFrame(rows).set_index(["ts_open", "instrument_id"]).sort_index()


def test_runner_attaches_validation_block(tmp_path: Path) -> None:
    """The runner records its trial and writes a validation block into walkforward.json."""
    from alphaforge.analytics.walkforward import WalkForwardRunner

    world = _build_world(tmp_path)
    runner = WalkForwardRunner(
        world["reader"],  # type: ignore[index]
        world["store"],  # type: ignore[index]
        world["universe"],  # type: ignore[index]
        world["cost_model"],  # type: ignore[index]
        _ConstMuSource(),
        world["settings"],  # type: ignore[index]
        cost_inputs=world["cost_inputs"],  # type: ignore[index]
    )
    log = ExperimentLog(tmp_path / "experiments.jsonl")
    out = tmp_path / "wf_out"
    result = runner.run(
        T0,
        T0 + 900 * HOUR,
        train_bars=300,
        test_bars=200,
        rebalance_bars=24,
        cov_min_periods=120,
        out_dir=out,
        now_ms=T0 + 1_000_000,
        alpha_names=["carry_fund_21", "mr_res_72"],
        experiment_log=log,
    )
    world["store"].close()  # type: ignore[index]

    # The in-memory result carries the validation report.
    assert result.validation is not None
    v = result.validation
    assert 0.0 <= v.psr <= 1.0
    assert 0.0 <= v.dsr <= 1.0
    assert v.n_trials == 1
    assert v.n_trials_used == 2
    assert isinstance(v.clears_dsr_gate, bool)

    # Exactly one trial logged at the PASSED-IN timestamp (no clock read).
    assert log.n_trials() == 1
    assert log.all()[0].now_ms == T0 + 1_000_000

    # The saved walkforward.json has a validation block with the documented keys.
    meta = json.loads((out / "walkforward.json").read_text(encoding="utf-8"))
    block = meta["validation"]
    assert set(block) == {
        "psr",
        "dsr",
        "sr_ann",
        "n_trials",
        "n_trials_used",
        "expected_max_sr",
        "sr_trials_variance",
        "n_obs",
        "clears_dsr_gate",
    }
    assert block["n_trials"] == 1
    assert block["n_obs"] >= 2


def test_runner_without_now_ms_skips_validation(tmp_path: Path) -> None:
    """now_ms=None (default) -> no clock read, no ledger write, validation None."""
    from alphaforge.analytics.walkforward import WalkForwardRunner

    world = _build_world(tmp_path)
    runner = WalkForwardRunner(
        world["reader"],  # type: ignore[index]
        world["store"],  # type: ignore[index]
        world["universe"],  # type: ignore[index]
        world["cost_model"],  # type: ignore[index]
        _ConstMuSource(),
        world["settings"],  # type: ignore[index]
        cost_inputs=world["cost_inputs"],  # type: ignore[index]
    )
    result = runner.run(
        T0,
        T0 + 900 * HOUR,
        train_bars=300,
        test_bars=200,
        rebalance_bars=24,
        cov_min_periods=120,
    )
    world["store"].close()  # type: ignore[index]
    assert result.validation is None
    # The default ledger under settings.paths.var_dir was never touched.
    assert not (world["settings"].paths.var_dir / "experiments.jsonl").exists()  # type: ignore[index]


# ---------------------------------------------------------------------------
# CLI smoke: af research evaluate
# ---------------------------------------------------------------------------


def test_cli_research_evaluate_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from alphaforge.cli.research_cmds import research_app

    # Isolate var_dir so setup_logging / the default ledger never touch ./var.
    var_dir = tmp_path / "var"
    var_dir.mkdir()
    monkeypatch.setenv("AF_PATHS__VAR_DIR", str(var_dir))

    # A run dir with a saved equity.parquet spanning >= 2 UTC days.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    equity = _synthetic_equity(11)
    pd.DataFrame(
        {
            "ts": equity.index.to_numpy(dtype="int64"),
            "equity": equity.to_numpy(dtype="float64"),
        }
    ).to_parquet(run_dir / "equity.parquet", index=False)

    # A ledger with two distinct trials so N >= 2.
    ledger = ExperimentLog(tmp_path / "experiments.jsonl")
    _record(ledger, {"cfg": "a"}, 0.05, 1)
    _record(ledger, {"cfg": "b"}, 0.09, 2)

    runner = CliRunner()
    res = runner.invoke(
        research_app,
        ["evaluate", str(run_dir), "--log", str(ledger.path)],
    )
    assert res.exit_code == 0, res.output
    assert "PSR(0)" in res.output
    assert "DSR" in res.output
    assert "verdict:" in res.output
    assert "DSR gate (>=0.95)" in res.output
    assert "PBO" in res.output  # the not-available line


def test_cli_research_evaluate_missing_equity_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from alphaforge.cli.research_cmds import research_app

    var_dir = tmp_path / "var"
    var_dir.mkdir()
    monkeypatch.setenv("AF_PATHS__VAR_DIR", str(var_dir))

    empty = tmp_path / "empty"
    empty.mkdir()
    res = CliRunner().invoke(research_app, ["evaluate", str(empty)])
    assert res.exit_code == 1
    assert "no equity.parquet" in res.output
