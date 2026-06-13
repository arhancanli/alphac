"""Risk engine (execDesign §7): hard limits, pre-trade checks, portfolio
monitors, and the kill-switch.

Layering: :class:`RiskLimits` is the one frozen statement of the risk
posture; :class:`PreTradeChecker` gates every order (backtest AND live, same
code path); :mod:`~alphaforge.risk.monitors` watches the book between trades
(historical daily VaR/CVaR, the drawdown ladder, the staleness breaker); and
:class:`KillSwitch` is the file-based human brake under all of it.
"""

from alphaforge.risk.killswitch import KillSwitch
from alphaforge.risk.limits import RiskLimits
from alphaforge.risk.monitors import (
    DDState,
    DrawdownLadder,
    StalenessBreaker,
    VarReport,
    historical_var_cvar,
)
from alphaforge.risk.pretrade import CheckReport, OrderVerdict, PreTradeChecker

__all__ = [
    "CheckReport",
    "DDState",
    "DrawdownLadder",
    "KillSwitch",
    "OrderVerdict",
    "PreTradeChecker",
    "RiskLimits",
    "StalenessBreaker",
    "VarReport",
    "historical_var_cvar",
]
