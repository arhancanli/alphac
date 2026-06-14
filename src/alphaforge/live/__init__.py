"""Live PAPER-trading persistence, recovery, and outbound alerting (Phase 7).

This package holds the durable spine of the 24/7 loop: :class:`TradingStore` (the
SQLite source of truth for cycles/orders/fills/snapshots), the boot crash-recovery
algorithm (:meth:`LiveLoop.recover_on_boot` -- the SOLE live recovery path), and
the outbound :class:`Alerter` family. The loop itself (``loop.py``) and the
broker/order-manager (``execution/``) compose against these surfaces.
"""

from __future__ import annotations

from alphaforge.live.alerts import (
    Alerter,
    AlertLevel,
    LogAlerter,
    MultiAlerter,
    TelegramAlerter,
    build_alerter,
)
from alphaforge.live.loop import (
    CostInputSource,
    CycleReport,
    DataUpdater,
    DecisionStrategy,
    LiveLoop,
    MuProvider,
    UniverseRefresher,
    WatermarkSource,
    decode_paper_state,
    encode_paper_state,
)
from alphaforge.live.store import (
    CycleRecord,
    CycleStatus,
    FillAudit,
    FillRecord,
    OrderRecord,
    TradingStore,
)

__all__ = [
    "AlertLevel",
    "Alerter",
    "CostInputSource",
    "CycleRecord",
    "CycleReport",
    "CycleStatus",
    "DataUpdater",
    "DecisionStrategy",
    "FillAudit",
    "FillRecord",
    "LiveLoop",
    "LogAlerter",
    "MuProvider",
    "MultiAlerter",
    "OrderRecord",
    "TelegramAlerter",
    "TradingStore",
    "UniverseRefresher",
    "WatermarkSource",
    "build_alerter",
    "decode_paper_state",
    "encode_paper_state",
]
