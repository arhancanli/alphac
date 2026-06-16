"""The headline D7 guarantee: OFF == identity, byte-for-byte (``12_FINAL.md`` test 1).

With ``ml=False`` and ``regime=False`` the Phase-12 gate machinery is completely
inert — the runner takes its pre-Phase-12 ``full_frame``-slice path, the gating
functions multiply by 1.0, and ``trial_config`` gains NO gate keys — so the run
output (the stitched OOS ``equity`` and the :class:`ValidationReport`) is identical
to today's HEAD. This module pins that guarantee at two seams against ONE tiny
synthetic ``tmp_path`` lake (a few instruments, ~44 days, two purged legs — well
under the fast-test budget), reusing the synthetic-lake fixture idiom from
``test_cli_gated_flags.py`` / ``test_walkforward_equivalence.py``:

1. THE GATE-FUNCTION IDENTITY (the seam the runner's OFF path relies on):
   :func:`~alphaforge.signals.gating.gate_signal_frame` with an
   :class:`~alphaforge.ml.model.IdentityMeta` (``feature_frame=None`` ⇒ ``|size|≡1``)
   and an EMPTY daily ``G`` series (every hour cold-starts to ``G=1.0``, the runner's
   own :meth:`WalkForwardRunner._build_leg_regime` inactive series) returns a frame
   ``.equals`` the ungated :meth:`SignalService.compute_research` frame — EXACTLY,
   on BOTH ``alpha_blend`` AND ``mu_ann`` (no last-ULP perturbation; the OFF path
   multiplies the already-computed blend ``mu_ann`` by 1.0, never recomputes it).

2. THE RUN IDENTITY (the headline): ``WalkForwardRunner.run(..., ml=False,
   regime=False)`` on a runner WITH the Phase-12 gate collaborators present (a
   ``daily_btc_reader``) produces an ``equity`` Series, a ``ValidationReport``
   ``to_json_obj()``, and an experiment-ledger ``config_hash`` byte-identical to the
   same run on a runner WITHOUT any gate collaborators — i.e. the mere PRESENCE of
   the gate machinery does not perturb the OFF output. The OFF ``validation`` block
   carries NONE of the Phase-12 gate keys (``variant`` / ``baseline`` /
   ``clears_baseline_gate`` / ``gate_inactive_frac``), exactly as today.

Offline, ``tmp_path`` lake only, deterministic (seeded rng), no network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

import alphaforge.features.library  # noqa: F401  (registers the factor library)
from alphaforge.analytics.walkforward import WalkForwardRunner
from alphaforge.backtest import StaticCostInputs
from alphaforge.config.settings import Settings
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import default_registry
from alphaforge.ml.model import IdentityMeta
from alphaforge.signals.blending import ALPHA_BLEND_COLUMN
from alphaforge.signals.gating import gate_signal_frame
from alphaforge.signals.service import SignalService
from alphaforge.signals.sizing import MU_ANN_COLUMN
from alphaforge.validation.experiments import ExperimentLog, config_hash

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from alphaforge.core.time import Ms

HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z (1h-aligned)

# 44 days of 1h bars: a 31-day train warms the three real gates the OOS curve needs
# (LakeCostInputs 30d-median ADV, the 240-bar covariance window, the 169-bar momentum
# lookback); train=744/test=96 tiles two purged OOS legs. Same shape as the CLI test.
N_BARS = 1056
_TRAIN_DAYS = 31
_TEST_DAYS = 4
_TRAIN_BARS = _TRAIN_DAYS * 24
_TEST_BARS = _TEST_DAYS * 24

BTC = "BINANCE:PERP:BTCUSDT"
MEMBERS = (BTC, *(f"BINANCE:PERP:{b}USDT" for b in ("ETH", "SOL", "ADA", "DOGE")))
ALL_IDS = list(MEMBERS)
# Per-instrument constant drifts so the cross-section is persistently RANKED (a stable
# XS momentum the rank allocator takes real, non-flat positions on -> a non-degenerate
# OOS curve whose Sharpe/DSR validation is defined).
_DRIFTS = (0.002, -0.002, 0.0015, -0.0015, 0.001)
_ALPHA = "mom_xs_168_24"  # lookback 169 bars < 744-bar train -> warms inside the window
_INITIAL_CASH = 100_000.0


def _closes(seed: int, n: int, level: float, drift: float) -> np.ndarray:
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


class _DailyBtcStub:
    """A :class:`~alphaforge.analytics.walkforward.DailyBtcReader` (presence-only).

    The OFF path (``regime=False``) never calls ``read_daily_btc`` — the runner only
    reads daily BTC when ``regime`` is on. This stub exists only to prove that simply
    HAVING a gate collaborator on the runner does not perturb the OFF output (D7);
    it returns an empty daily frame so a stray read would be harmless.
    """

    def read_daily_btc(self, start: Ms, end: Ms) -> pd.DataFrame:  # pragma: no cover
        del start, end
        return pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": []},
            index=pd.Index([], dtype="int64", name="ts_open"),
        )


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A tmp lake: synthetic OHLCV + SCD2 instruments + PIT universe (module-scoped)."""
    tmp = tmp_path_factory.mktemp("gates_off_identity")
    paths = LakePaths(tmp / "lake")
    closes = {
        iid: _closes(101 + k, N_BARS, 50.0 * (k + 1), _DRIFTS[k])
        for k, iid in enumerate(ALL_IDS)
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

    store = InstrumentStore(tmp / "ops.sqlite")
    for iid in ALL_IDS:
        store.upsert(_instrument(iid), as_of=T0 - 365 * 24 * HOUR)
    store.close()
    yield tmp


def _service(lake: Path) -> SignalService:
    paths = LakePaths(lake / "lake")
    reader = PITDataReader(paths)
    store = InstrumentStore(lake / "ops.sqlite")
    universe = UniverseStore(paths)
    return SignalService(
        FeatureEngine(reader, store, universe),
        universe,
        default_registry(),
        Settings().signals,
        alpha_names=[_ALPHA],
    )


def _runner(
    lake: Path, *, with_gate_collaborators: bool
) -> tuple[WalkForwardRunner, InstrumentStore]:
    paths = LakePaths(lake / "lake")
    reader = PITDataReader(paths)
    store = InstrumentStore(lake / "ops.sqlite")
    universe = UniverseStore(paths)
    service = SignalService(
        FeatureEngine(reader, store, universe),
        universe,
        default_registry(),
        Settings().signals,
        alpha_names=[_ALPHA],
    )
    runner = WalkForwardRunner(
        reader,
        store,
        universe,
        TransactionCostModel.from_settings(Settings()),
        service,
        Settings(),
        cost_inputs=StaticCostInputs(adv_quote=1.0e8, sigma_daily=0.05),
        # The headline: the OFF output must be identical whether or not the runner
        # carries the Phase-12 gate collaborators. WITH = a daily_btc_reader present.
        daily_btc_reader=_DailyBtcStub() if with_gate_collaborators else None,
    )
    return runner, store


def _run_off(
    lake: Path, *, with_gate_collaborators: bool, log: ExperimentLog
) -> tuple[pd.Series, dict[str, object] | None]:
    """``run(ml=False, regime=False)`` -> (equity, validation.to_json_obj() or None)."""
    runner, store = _runner(lake, with_gate_collaborators=with_gate_collaborators)
    try:
        result = runner.run(
            T0,
            T0 + N_BARS * HOUR,
            train_bars=_TRAIN_BARS,
            test_bars=_TEST_BARS,
            allocator="rank",
            initial_cash=_INITIAL_CASH,
            alpha_names=[_ALPHA],
            now_ms=T0 + N_BARS * HOUR,
            experiment_log=log,
            ml=False,
            regime=False,
        )
    finally:
        store.close()
    validation = None if result.validation is None else result.validation.to_json_obj()
    return result.equity, validation


# --------------------------------------------------------------------------- the test


class TestGateFunctionIdentity:
    """Seam 1: the gating math is a byte-exact identity under IdentityMeta + empty G."""

    def test_gate_signal_frame_identity_equals_ungated_compute_research(
        self, lake: Path
    ) -> None:
        """``gate_signal_frame`` with identity meta + empty G == the ungated frame.

        This is the function-level D7 guarantee the runner's OFF path inherits: an
        :class:`IdentityMeta` (``feature_frame=None`` ⇒ ``|size|≡1``) and an EMPTY daily
        ``G`` series (the runner's own inactive series — every hour ``fillna(1.0)``s to
        ``G=1.0``) leave BOTH the ungated ``alpha_blend`` and the blend ``mu_ann``
        UNCHANGED, exactly. ``mu_ann`` is multiplied by 1.0, never recomputed, so there
        is no last-ULP drift.
        """
        service = _service(lake)
        frame = service.compute_research(T0, T0 + N_BARS * HOUR)
        assert not frame.empty, "the synthetic OOS frame must be non-degenerate"

        # The runner's inactive regime series: an EMPTY daily G keyed by int64 ts_open.
        # apply_regime_gate fillna(1.0)s every hour -> a byte-exact identity broadcast.
        empty_g = pd.Series([], index=pd.Index([], dtype="int64", name="ts_open"), dtype="float64")
        gated = gate_signal_frame(
            frame,
            None,  # no feature frame -> IdentityMeta path, |size| == 1
            IdentityMeta(),
            empty_g,
            frame[ALPHA_BLEND_COLUMN],  # sigma arg unused on the multiply (linearity) path
        )

        # Both columns are byte-identical; the gate's whole effect is a multiply by 1.0.
        pd.testing.assert_series_equal(
            gated[ALPHA_BLEND_COLUMN], frame[ALPHA_BLEND_COLUMN], check_exact=True
        )
        pd.testing.assert_series_equal(
            gated[MU_ANN_COLUMN], frame[MU_ANN_COLUMN], check_exact=True
        )
        assert frame.equals(gated[[ALPHA_BLEND_COLUMN, MU_ANN_COLUMN]])

    def test_identity_frame_is_non_vacuous(self, lake: Path) -> None:
        """Guard the fixture: the OOS frame carries FINITE, non-zero ``mu_ann`` so the
        identity is a real (non-vacuous) μ-ann frame, not an all-NaN one a trivial
        multiply would preserve regardless of the gate."""
        service = _service(lake)
        frame = service.compute_research(T0, T0 + N_BARS * HOUR)
        mu = frame[MU_ANN_COLUMN].to_numpy(dtype=float)
        finite = mu[np.isfinite(mu)]
        assert finite.size > 0, "the OOS frame has no finite mu_ann -> the identity is vacuous"
        assert bool(np.any(finite != 0.0)), "all mu_ann are 0 -> the identity is vacuous"


class TestRunOffIdentity:
    """Seam 2: ``run(ml=False, regime=False)`` is identical with vs without gate wiring."""

    def test_equity_and_validation_byte_identical_with_and_without_gate_collaborators(
        self, lake: Path, tmp_path: Path
    ) -> None:
        """The headline: the OFF run output does not depend on the gate machinery's
        presence (D7). Equity ``.equals``, ``validation.to_json_obj()`` identical, and the
        ledger ``config_hash`` identical — the same trial, same number, byte for byte."""
        log_a = ExperimentLog(tmp_path / "ledger_a.jsonl")
        log_b = ExperimentLog(tmp_path / "ledger_b.jsonl")

        eq_no_gate, val_no_gate = _run_off(lake, with_gate_collaborators=False, log=log_a)
        eq_gate, val_gate = _run_off(lake, with_gate_collaborators=True, log=log_b)

        # Equity is byte-identical (the OFF path never touches the gate machinery).
        assert eq_no_gate.equals(eq_gate)

        # The validation block is byte-identical AND carries NONE of the Phase-12 gate
        # keys (those are emitted only for a gated variant; OFF == today's HEAD).
        assert val_no_gate == val_gate
        assert val_no_gate is not None
        for gate_key in ("variant", "baseline", "clears_baseline_gate", "gate_inactive_frac"):
            assert gate_key not in val_no_gate, f"OFF validation must not carry {gate_key!r}"

        # The same trial recorded the same config_hash on each ledger (N unchanged, D7).
        assert log_a.n_trials() == 1
        assert log_b.n_trials() == 1
        hashes_a = {rec.config_hash for rec in log_a.all()}
        hashes_b = {rec.config_hash for rec in log_b.all()}
        assert hashes_a == hashes_b

    def test_off_trial_config_hash_omits_gate_keys(self, lake: Path, tmp_path: Path) -> None:
        """The OFF ``trial_config`` hashes to the SAME value as the pre-Phase-12 config
        (no ``ml``/``regime``/``ml_*``/``regime_*`` keys) — so OFF==identity holds on the
        ledger and ``N`` is byte-identical to today (D6/D7)."""
        log = ExperimentLog(tmp_path / "ledger_c.jsonl")
        _run_off(lake, with_gate_collaborators=True, log=log)
        recorded = next(iter(log.all())).config_hash

        # The exact trial_config the runner builds on the OFF path (no gate keys) — see
        # WalkForwardRunner.run's base_trial_config; gate keys are absent when both off.
        from alphaforge.validation.splits import PurgedWalkForward

        band = Settings().portfolio.no_trade_band
        splitter = PurgedWalkForward.from_settings(
            Settings(), train_bars=_TRAIN_BARS, test_bars=_TEST_BARS, embargo_bars=168
        )
        del splitter  # only built to mirror the runner's construction; purge is implicit
        expected = config_hash(
            {
                "start": T0,
                "end": T0 + N_BARS * HOUR,
                "train_bars": _TRAIN_BARS,
                "test_bars": _TEST_BARS,
                "allocator": "rank",
                "rebalance_bars": 24,
                "no_trade_band": band,
                "instrument_ids": sorted(dict.fromkeys(ALL_IDS)),
                "alpha_names": [_ALPHA],
            }
        )
        assert recorded == expected, (
            "OFF trial_config hash drifted from the pre-Phase-12 config -> N would change"
        )
