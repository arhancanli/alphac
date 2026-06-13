"""Validation: IC metrics and overlap-honest inference (alphaDesign.md §7).

Curated public surface — downstream modules import from
:mod:`alphaforge.validation`, not its submodules.
"""

from alphaforge.validation.metrics import (
    ICSummary,
    ic_summary,
    newey_west_tstat,
    non_overlapping,
    rank_ic,
)
from alphaforge.validation.splits import PurgedWalkForward

__all__ = [
    "ICSummary",
    "PurgedWalkForward",
    "ic_summary",
    "newey_west_tstat",
    "non_overlapping",
    "rank_ic",
]
