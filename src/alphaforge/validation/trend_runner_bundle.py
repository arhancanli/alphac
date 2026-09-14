"""Isolated research runner wiring; never edits an existing lake or activates paper."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa

import alphaforge.features.library  # noqa: F401
from alphaforge.backtest.fills import BarView, ParticipationCappedFill
from alphaforge.backtest.payable_engine import PayableEquityBacktester
from alphaforge.backtest.quality_fill import QualityGatedFill, ReviewedBar
from alphaforge.config.sleeve import sleeve_for
from alphaforge.core.types import AssetClass
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import CORPORATE_ACTIONS_SCHEMA, OHLCV_SCHEMA, UNIVERSE_SCHEMA, Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.execution.corporate_actions import CorporateAction, CorporateActionType
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import default_registry
from alphaforge.portfolio.paired_price_strategy import PairedPriceBlendStrategy
from alphaforge.research.zoo import register_mf_trend_grid
from alphaforge.signals.raw_label_trend import RawLabelTrendSignalService
from alphaforge.validation.trend_dividend_settlement import DividendSettlementBook
from alphaforge.validation.trend_input_routes_v2 import TrendInputRoutesV2
from alphaforge.validation.trend_observation import ObservationError, fingerprint
from alphaforge.validation.trend_raw_label_provider import RawHoldingLabelProvider


class TrendRunnerBundle:
    def __init__(
        self,
        paired,
        *,
        instrument_symbols,
        snapshots,
        payments,
        mode,
        retrospective_vintage_ms=None,
    ):
        if mode != "DIAGNOSTIC_CURRENT_VINTAGE":
            raise ObservationError(
                "Runner bundle is diagnostic only; price receipt timing unverified"
            )
        routes = TrendInputRoutesV2(paired)
        last = int(paired.session_ms.max())
        # Full feature history must pass; execution-only quarantine is insufficient
        # because disputed prices must not enter covariance, marks or forced exits.
        self._features = routes.feature_bars(through_session=last)
        self._raw = routes.execution_bars(through_session=last)
        self._mapping = dict(instrument_symbols)
        if set(self._mapping.values()) != set(paired.symbol):
            raise ObservationError("Instrument mapping must cover exactly the panel symbols")
        self._retrospective_vintage_ms = retrospective_vintage_ms
        DividendSettlementBook(Decimal(0), retrospective_vintage_ms=retrospective_vintage_ms)
        self._snapshots = dict(snapshots)
        if retrospective_vintage_ms is not None and any(
            snap.observed_ms > retrospective_vintage_ms for snap in self._snapshots.values()
        ):
            raise ObservationError("Action snapshot exceeds retrospective vintage")
        self._payments = tuple(payments)
        inverse = {s: iid for iid, s in self._mapping.items()}
        required = {}
        for symbol, snapshot in self._snapshots.items():
            if symbol not in inverse or snapshot.symbol != symbol or snapshot.complete is not True:
                raise ObservationError("Unknown snapshot symbol")
            for event in snapshot.actions:
                if event.kind == "dividend":
                    key = (inverse[symbol], event.session_ms)
                    if key in required:
                        raise ObservationError("Duplicate dividend in action snapshot")
                    required[key] = Decimal(str(event.value))
        paid = {}
        for payment in self._payments:
            key = (payment.symbol, payment.ex_ms)
            if key in paid:
                raise ObservationError("Duplicate payment event")
            DividendSettlementBook(
                Decimal(0), retrospective_vintage_ms=retrospective_vintage_ms
            ).accrue(payment, Decimal(0), as_of_ms=payment.ex_ms)
            paid[key] = payment.cash_per_share
        if paid != required:
            raise ObservationError("Exact complete dividend payment schedule required")
        self.provider = RawHoldingLabelProvider(
            paired, instrument_symbols=self._mapping, snapshots=snapshots, mode=mode
        )
        self.binding = {
            **self.provider.binding,
            "paired_input_sha256": fingerprint(
                {
                    "raw": self._raw.to_dict("records"),
                    "signal": self._features.to_dict("records"),
                    "payments": [
                        {**asdict(e), "cash_per_share": str(e.cash_per_share)}
                        for e in self._payments
                    ],
                }
            ),
            "risk_prices": "synthetic_returns_raw_position_marks_v1",
            "quote_volume": "raw_close_times_raw_volume_proxy",
            "mode": mode,
        }
        if retrospective_vintage_ms is not None:
            self.binding["retrospective_vintage_ms"] = retrospective_vintage_ms
            self.binding["execution_mode"] = "RETROSPECTIVE_CURRENT_VINTAGE"
            self.binding["point_in_time_proven"] = False
        self._prepared = False
        self._settings_digest = None
        self._signals_digest = None

    def prepare(self, directory):
        if self._prepared:
            raise ObservationError("Bundle is already prepared")
        directory = Path(directory)
        directory.mkdir(exist_ok=False)
        inverse = {s: iid for iid, s in self._mapping.items()}
        raw_quote = dict(
            zip(
                zip(self._raw.symbol, self._raw.session_ms, strict=True),
                self._raw.close * self._raw.volume,
                strict=True,
            )
        )
        self._reviewed = []
        for name, data in [("signal", self._features), ("execution", self._raw)]:
            paths = LakePaths(directory / name)
            writer = LakeWriter(paths)
            rows = []
            for row in data.itertuples():
                record = {
                    "instrument_id": inverse[row.symbol],
                    "ts_open": int(row.session_ms),
                    **{
                        f: float(getattr(row, f))
                        for f in ["open", "high", "low", "close", "volume"]
                    },
                    "quote_volume": float(raw_quote[(row.symbol, row.session_ms)]),
                    "n_trades": None,
                    "quality_flags": 0,
                    "ingested_at": int(pd.Timestamp.now(tz="UTC").timestamp() * 1000),
                }
                rows.append(record)
                if name == "execution":
                    self._reviewed.append(
                        ReviewedBar(
                            record["instrument_id"],
                            BarView(
                                **{
                                    f: record[f]
                                    for f in [
                                        "ts_open",
                                        "open",
                                        "high",
                                        "low",
                                        "close",
                                        "volume",
                                        "quote_volume",
                                    ]
                                }
                            ),
                            bool(row.execution_eligible),
                        )
                    )
            writer.write(Dataset.OHLCV_1D, pa.Table.from_pylist(rows, schema=OHLCV_SCHEMA))
            memberships = [
                {
                    "instrument_id": inverse[s],
                    "effective_from": int(g.session_ms.min()),
                    "effective_to": None,
                    "rank": i + 1,
                    "reason": "paired research fixture/input",
                }
                for i, (s, g) in enumerate(data.groupby("symbol"))
            ]
            writer.write(
                Dataset.UNIVERSE_MEMBERSHIP,
                pa.Table.from_pylist(memberships, schema=UNIVERSE_SCHEMA),
            )
            if name == "execution":
                events = [
                    {
                        "instrument_id": inverse[s],
                        "action_type": a.kind,
                        "ex_date": a.session_ms,
                        "available_at": snap.observed_ms,
                        "ratio": a.value if a.kind == "split" else 1.0,
                        "cash_amount": a.value if a.kind == "dividend" else None,
                        "ingested_at": snap.observed_ms,
                    }
                    for s, snap in self._snapshots.items()
                    for a in snap.actions
                ]
                if events:
                    writer.write(
                        Dataset.CORPORATE_ACTIONS,
                        pa.Table.from_pylist(events, schema=CORPORATE_ACTIONS_SCHEMA),
                    )
        self.signal_paths = LakePaths(directory / "signal")
        self.execution_paths = LakePaths(directory / "execution")
        self._directory = directory
        self._staged_hashes = {
            str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*.parquet")
        }
        self._prepared = True

    def verify(self):
        if not self._prepared:
            raise ObservationError("Prepare isolated inputs first")
        actual = {
            str(p.relative_to(self._directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self._directory.rglob("*.parquet")
        }
        if actual != self._staged_hashes:
            raise ObservationError("Staged input files changed")

    def _bind_settings(self, settings):
        if settings.data.asset_class is not AssetClass.EQUITY:
            raise ObservationError("Equity settings required")
        digest = fingerprint(settings.model_dump(mode="json"))
        if self._settings_digest is not None and digest != self._settings_digest:
            raise ObservationError("Signal, allocator and engine settings differ")
        self._settings_digest = digest
        self.binding["settings_sha256"] = digest

    @staticmethod
    def _frame_digest(frame):
        data = pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
        return hashlib.sha256(data + repr(tuple(frame.columns)).encode()).hexdigest()

    def compute_signals(self, store, settings, *, history_anchor, start, end):
        service = self.signal_service(store, settings, history_anchor=history_anchor)
        frame = service.compute_research(start, end)
        self._signals_digest = self._frame_digest(frame)
        self.binding.update(service.trial_binding)
        self.binding["signals_sha256"] = self._signals_digest
        self.binding["signal_window"] = [start, end]
        return frame

    def signal_service(self, store, settings, *, history_anchor):
        if not self._prepared:
            raise ObservationError("Prepare isolated inputs first")
        self.verify()
        self._bind_settings(settings)
        registry = default_registry()
        register_mf_trend_grid(registry)
        universe = UniverseStore(self.signal_paths)
        return RawLabelTrendSignalService(
            FeatureEngine(
                PITDataReader(self.signal_paths), store, universe, asset_class=AssetClass.EQUITY
            ),
            universe,
            registry,
            settings.signals,
            alpha_names=["mf_trend_63", "mf_trend_126", "mf_trend_252"],
            sleeve=sleeve_for(AssetClass.EQUITY),
            history_anchor=history_anchor,
            raw_label_provider=self.provider,
            blend_normalization="directional_rms",
        )

    def strategy(self, settings, signal_frame, **kwargs):
        self.verify()
        self._bind_settings(settings)
        if self._signals_digest is None or self._frame_digest(signal_frame) != self._signals_digest:
            raise ObservationError("Signal frame is not the bound runner output")
        return PairedPriceBlendStrategy(
            settings,
            signal_frame=signal_frame,
            allocator="trend",
            signal_reader=PITDataReader(self.signal_paths),
            input_digest=self.binding["paired_input_sha256"],
            **kwargs,
        )

    def engine(self, store, settings, **kwargs):
        self.verify()
        self._bind_settings(settings)
        cost = TransactionCostModel.from_settings(settings)
        fill = QualityGatedFill(ParticipationCappedFill(cost), self._reviewed)
        sleeve = sleeve_for(AssetClass.EQUITY)
        retrospective = {}
        if self._retrospective_vintage_ms is not None:
            inverse = {s: iid for iid, s in self._mapping.items()}
            retrospective = {
                "retrospective_vintage_ms": self._retrospective_vintage_ms,
                "retrospective_actions": tuple(
                    CorporateAction(
                        instrument_id=inverse[s],
                        action_type=CorporateActionType(a.kind),
                        ex_date=a.session_ms,
                        available_at=snap.observed_ms,
                        ratio=a.value if a.kind == "split" else 1.0,
                        cash_amount=a.value if a.kind == "dividend" else None,
                    )
                    for s, snap in self._snapshots.items()
                    for a in snap.actions
                ),
            }
        return PayableEquityBacktester(
            PITDataReader(self.execution_paths),
            store,
            cost,
            payments=self._payments,
            **retrospective,
            tf=sleeve.anchor_tf,
            asset_class=AssetClass.EQUITY,
            fill_model=fill,
            config_echo={"paired_runner_binding": self.binding},
            **kwargs,
        )
