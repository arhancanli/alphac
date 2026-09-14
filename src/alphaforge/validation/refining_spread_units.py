"""Research arithmetic for standard 3:2:1 contracts; no signal or execution model.

Explicit dollar quotes only. These mark differences are not a return on margin,
not physical refinery profit, and not a license to net unmatched maturities.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RefiningQuotes:
    wti_usd_per_barrel: Decimal
    rbob_usd_per_gallon: Decimal
    ulsd_usd_per_gallon: Decimal

    def __post_init__(self):
        for value in (self.wti_usd_per_barrel, self.rbob_usd_per_gallon, self.ulsd_usd_per_gallon):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError("Finite Decimal dollar quotes required")

    @property
    def crack_usd_per_input_barrel(self):
        return (
            Decimal(42) * (2 * self.rbob_usd_per_gallon + self.ulsd_usd_per_gallon)
            - 3 * self.wti_usd_per_barrel
        ) / 3

    @property
    def standard_recipe_mark_usd(self):
        # -3 CL (1,000 barrels), +2 RB and +1 HO (42,000 gallons each).
        return (
            -3000 * self.wti_usd_per_barrel
            + 84000 * self.rbob_usd_per_gallon
            + 42000 * self.ulsd_usd_per_gallon
        )


def recipe_mark_change(start: RefiningQuotes, end: RefiningQuotes, *, recipes: int = 1):
    if type(recipes) is not int:
        raise ValueError("Integer signed recipe count required")
    return recipes * (end.standard_recipe_mark_usd - start.standard_recipe_mark_usd)
