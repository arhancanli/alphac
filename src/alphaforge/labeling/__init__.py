"""Labeling: execution-aware targets for model training and factor evaluation.

Curated public surface — downstream modules import from :mod:`alphaforge.labeling`,
not its submodules. Labels look into the future by construction; they are
training/evaluation targets ONLY and must never re-enter the feature path.
"""

from alphaforge.labeling.forward_returns import forward_returns

__all__ = ["forward_returns"]
