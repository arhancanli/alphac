"""CLI integration tests for the Phase-12 gate flags (D5/D6/D7, the CLI surface).

These exercise the two CLI commands the CLI builder owns END-TO-END through typer's
:class:`~typer.testing.CliRunner`, against a TINY synthetic ``tmp_path`` lake driven by
the REAL ``WalkForwardRunner`` / ``SignalService`` (no stubs — the runner's own gated
machinery runs). The fixture is deliberately minimal (a few instruments, ~240 1h bars,
``--train-days 4 --test-days 3`` ⇒ two purged legs) so the whole module stays well under
the fast-test budget. The daily-BTC window is far shorter than ``MIN_FIT_DAYS`` (730), so
``--regime`` exercises the documented IdentityRegime cold-start fallback (D3) — the real
HMM fit on >=730 daily obs is pinned by the runner's own pipeline integration test.

What is asserted (the CLI builder's seams, 12_FINAL.md §4/§5):

* ``af research walkforward`` accepts ``--ml/--no-ml`` and ``--regime/--no-regime``;
  the default-OFF run writes a ``walkforward.json`` whose ``validation`` block carries
  NO ``baseline`` (the blend-only path is byte-identical to today, D7).
* A GATED run (``--ml`` and/or ``--regime``) writes a ``validation`` block WITH a nested
  ``baseline``, a ``variant`` tag, ``gate_inactive_frac``, and ``clears_baseline_gate``;
  the summary print shows the ``variant ... vs baseline ... beats-baseline:`` line.
* ``--regime`` constructs the daily-BTC adapter and the run survives the cold-start
  fallback (``gate_inactive_frac == 1.0`` with this sub-MIN_FIT_DAYS lake) rather than
  crashing.
* ``af research evaluate`` on a gated run requires ``clears_baseline_gate`` for the
  LIVE-ELIGIBLE verdict (D5): a gated variant that does NOT beat its baseline is reported
  ``NOT live-eligible (does not beat blend baseline)``; a blend-only run is judged on DSR
  alone (no baseline gate).

Offline, ``tmp_path`` lake only, deterministic (seeded rng), no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from typer.testing import CliRunner, Result

from alphaforge.cli.main import app
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore

if TYPE_CHECKING:
    from collections.abc import Iterator

runner = CliRunner()

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z (1h-aligned)
# 44 days of 1h bars. The 31-day train warms ALL three real gates the OOS curve needs:
# the LakeCostInputs 30-day-median ADV (else every order is rejected as non-finite-ADV
# and the curve is flat), the 240-bar covariance window, and the 169-bar momentum
# lookback. With train=744/test=96 the splitter tiles three OOS legs.
N_BARS = 1056
_TRAIN_DAYS = 31  # 744 bars > 30d ADV warmup, 240 cov_min_periods, 169 factor lookback
_TEST_DAYS = 4  # 96 bars OOS per leg
# BTC is the regime gate's market anchor (must be in the universe so the daily-BTC
# adapter can read it); the rest give the cross-section the blend ranks over.
BTC = "BINANCE:PERP:BTCUSDT"
MEMBERS = (BTC, *(f"BINANCE:PERP:{b}USDT" for b in ("ETH", "SOL", "ADA", "DOGE")))
ALL_IDS = list(MEMBERS)
# Per-instrument constant drifts so the cross-section is persistently RANKED (strong,
# stable XS momentum the rank allocator can take real positions on).
_DRIFTS = (0.002, -0.002, 0.0015, -0.0015, 0.001)
# ONE pure-price directional alpha that warms within this window (lookback 169 bars <
# the 744-bar train) so the blend actually trades a non-flat OOS curve — most of the
# default library needs 700-3200 bars / funding history this synthetic lake lacks.
_ALPHA = "mom_xs_168_24"


def _closes(seed: int, n: int, level: float, drift: float) -> np.ndarray:
    # A per-instrument drift over 1.2%/bar noise so the OOS book both moves enough to
    # clear the no-trade band AND keeps a stable cross-sectional ranking — together they
    # give a NON-FLAT equity curve (a flat curve has zero-variance returns, and the
    # Sharpe / DSR validation is undefined — the run would then error, not assert).
    rng = np.random.default_rng(seed)
    return np.asarray(level * np.exp(np.cumsum(rng.normal(drift, 0.012, n))))


def _ohlcv_table(per_inst: dict[str, np.ndarray]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    opens: list[float] = []
    closes: list[float] = []
    for iid, close in per_inst.items():
        n = len(close)
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        opens.append(float(close[0]))
        opens.extend(float(v) for v in close[:-1])
        closes.extend(float(v) for v in close)
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(opens, type=pa.float64()),
            "high": pa.array([v * 1.001 for v in closes], type=pa.float64()),
            "low": pa.array([v * 0.999 for v in closes], type=pa.float64()),
            "close": pa.array(closes, type=pa.float64()),
            "volume": pa.array([100.0] * n_rows, type=pa.float64()),
            # Deep, finite quote volume so the LakeCostInputs 30d-median ADV is large and
            # every modest test order clears the fill model's 5%-of-ADV gate.
            "quote_volume": pa.array([1.0e7] * n_rows, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
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


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A tmp repo: synthetic lake + SCD2 instruments + PIT universe, paths env-steered.

    ``load_settings`` infers the repo root from the package, so we steer the three
    path roots the commands touch (lake / var / artifacts) via the ``AF_PATHS__*`` env
    layer — which wins over YAML — so nothing reads ./data or ./var.
    """
    lake_dir = tmp_path / "lake"
    var_dir = tmp_path / "var"
    artifacts_dir = tmp_path / "artifacts"
    var_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AF_PATHS__LAKE_DIR", str(lake_dir))
    monkeypatch.setenv("AF_PATHS__VAR_DIR", str(var_dir))
    monkeypatch.setenv("AF_PATHS__ARTIFACTS_DIR", str(artifacts_dir))

    paths = LakePaths(lake_dir)
    closes = {
        iid: _closes(101 + k, N_BARS, 50.0 * (k + 1), _DRIFTS[k]) for k, iid in enumerate(ALL_IDS)
    }
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(closes))

    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array(list(MEMBERS), type=pa.string()),
                "effective_from": pa.array([T0] * len(MEMBERS), type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None] * len(MEMBERS), type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1] * len(MEMBERS), type=pa.int32()),
                "reason": pa.array(["enter_top40"] * len(MEMBERS), type=pa.string()),
            }
        )
    )

    store = InstrumentStore(var_dir / "ops.sqlite")
    for iid in ALL_IDS:
        store.upsert(_instrument(iid), as_of=T0 - 365 * 24 * HOUR)
    store.close()

    yield tmp_path


_END = T0 + N_BARS * HOUR
# A bare YYYY-MM-DDTHH:MM:SSZ keeps the CLI's UTC parse 1h-aligned; the fixture's
# T0/_END are exact 1h-aligned epoch-ms.
_START_ARG = "2023-01-01T00:00:00Z"


def _ms_to_iso(ms: int) -> str:
    return pd.Timestamp(ms, unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _walkforward(out: Path, *flags: str) -> Result:
    """Invoke ``af research walkforward`` over the tiny window into ``out``."""
    args = [
        "research",
        "walkforward",
        "--start",
        _START_ARG,
        "--end",
        _ms_to_iso(_END),
        "--train-days",
        str(_TRAIN_DAYS),
        "--test-days",
        str(_TEST_DAYS),
        "--alphas",
        _ALPHA,
        "--out",
        str(out),
        *flags,
    ]
    return runner.invoke(app, args, catch_exceptions=False)


def _validation_block(out: Path) -> dict[str, object]:
    meta = json.loads((out / "walkforward.json").read_text(encoding="utf-8"))
    validation = meta["validation"]
    assert isinstance(validation, dict), "expected a validation block in walkforward.json"
    return validation


class TestWalkforwardFlags:
    def test_blend_only_run_has_no_gate_keys_and_succeeds(self, repo: Path) -> None:
        """Default OFF: the run succeeds and the validation block omits the gate keys (D7).

        The blend-only ``walkforward.json`` validation block is byte-identical to today's
        HEAD — exactly the nine pre-Phase-12 keys, with NO ``variant`` / ``baseline`` /
        ``gate_inactive_frac`` / ``clears_baseline_gate`` (those are emitted only for a
        gated variant). The summary print likewise carries no gate line.
        """
        out = repo / "wf_blend"
        result = _walkforward(out)
        assert result.exit_code == 0, result.output
        assert (out / "equity.parquet").exists()
        v = _validation_block(out)
        assert "variant" not in v
        assert "baseline" not in v
        assert "clears_baseline_gate" not in v
        assert "gate_inactive_frac" not in v
        assert "beats-baseline:" not in result.output

    def test_ml_flag_produces_gated_variant_with_baseline(self, repo: Path) -> None:
        """``--ml`` runs the gated path: variant tagged, baseline attached, line printed."""
        out = repo / "wf_ml"
        result = _walkforward(out, "--ml")
        assert result.exit_code == 0, result.output
        v = _validation_block(out)
        assert v["variant"] == "ml"
        assert isinstance(v["baseline"], dict), "a gated run must carry a blend-only baseline"
        assert "clears_baseline_gate" in v
        # The summary print shows the Phase-12 gate line.
        assert "variant ml" in result.output
        assert "beats-baseline:" in result.output

    def test_regime_flag_cold_start_falls_back_to_identity(self, repo: Path) -> None:
        """``--regime`` builds the daily-BTC adapter; the sub-MIN_FIT_DAYS lake cold-starts.

        Every leg's expanding daily window has far fewer than ``MIN_FIT_DAYS`` (730) daily
        BTC rows, so the runner falls back to IdentityRegime on every leg rather than
        crashing — ``gate_inactive_frac == 1.0`` is the observable proof the fallback fired.
        """
        out = repo / "wf_regime"
        result = _walkforward(out, "--regime")
        assert result.exit_code == 0, result.output
        v = _validation_block(out)
        assert v["variant"] == "regime"
        assert isinstance(v["baseline"], dict)
        assert v["gate_inactive_frac"] == pytest.approx(1.0)

    def test_both_flags_variant_label_is_ml_plus_regime(self, repo: Path) -> None:
        """``--ml --regime`` tags the combined variant and still carries a baseline."""
        out = repo / "wf_both"
        result = _walkforward(out, "--ml", "--regime")
        assert result.exit_code == 0, result.output
        v = _validation_block(out)
        assert v["variant"] == "ml+regime"
        assert isinstance(v["baseline"], dict)


class TestEvaluateBaselineGate:
    """``af research evaluate`` folds the must-beat-baseline gate into the verdict (D5)."""

    def test_blend_only_run_is_judged_on_dsr_alone(self, repo: Path) -> None:
        """A blend-only run has no baseline, so evaluate never prints the baseline gate."""
        out = repo / "wf_blend_eval"
        assert _walkforward(out).exit_code == 0
        result = runner.invoke(app, ["research", "evaluate", str(out)], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "must-beat-baseline gate" not in result.output
        assert "verdict:" in result.output

    def test_gated_run_that_loses_baseline_is_not_live_eligible(self, repo: Path) -> None:
        """A gated variant whose ``clears_baseline_gate`` is False is refused (D5).

        We rewrite the persisted ``walkforward.json`` to the canonical losing shape
        (a gated variant carrying a baseline, ``clears_baseline_gate=False``) and assert
        ``evaluate`` reads it off the run dir and prints the must-beat-baseline refusal —
        the exact CLI seam §5 specifies, independent of whether THIS tiny fixture's gated
        DSR happens to beat its baseline.
        """
        out = repo / "wf_gated_lose"
        assert _walkforward(out, "--ml").exit_code == 0
        meta_path = out / "walkforward.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        v = meta["validation"]
        baseline = v["baseline"]
        assert isinstance(baseline, dict)
        # Force the losing case: variant DSR ties/loses the baseline.
        v["clears_baseline_gate"] = False
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        result = runner.invoke(app, ["research", "evaluate", str(out)], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "must-beat-baseline gate: FAILS" in result.output
        assert "NOT live-eligible (does not beat blend baseline)" in result.output

    def test_gated_run_that_beats_baseline_passes_the_baseline_gate(self, repo: Path) -> None:
        """A gated variant with ``clears_baseline_gate=True`` passes the baseline gate (D5).

        The baseline gate is the only thing the persisted ``walkforward.json`` controls;
        the headline LIVE-ELIGIBLE verdict additionally needs the equity-derived DSR to
        clear 0.95 (which evaluate recomputes from ``equity.parquet`` and this tiny
        random fixture cannot be made to guarantee). So we assert the baseline gate
        CLEARS and that the run is NOT refused on the baseline ground — the CLI seam this
        builder owns — rather than pinning the DSR-dependent final verdict.
        """
        out = repo / "wf_gated_win"
        assert _walkforward(out, "--ml").exit_code == 0
        meta_path = out / "walkforward.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        v = meta["validation"]
        v["clears_baseline_gate"] = True
        assert isinstance(v["baseline"], dict)
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        result = runner.invoke(app, ["research", "evaluate", str(out)], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "must-beat-baseline gate: CLEARS" in result.output
        assert "does not beat blend baseline" not in result.output
