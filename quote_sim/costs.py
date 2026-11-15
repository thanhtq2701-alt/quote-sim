"""Fake internal costs, kept apart from price lists because only managers may see them."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType

from quote_sim.pricing import ValidationError


@dataclass(frozen=True)
class CostSheet:
    """Freeze costs so a margin shown to a manager cannot be changed by a later reader."""

    version: str
    costs: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValidationError("cost-sheet version must be a non-empty string")
        if not isinstance(self.costs, Mapping):
            raise ValidationError("cost-sheet costs must be a mapping")
        validated: dict[str, Decimal] = {}
        for product_id, unit_cost in self.costs.items():
            if not isinstance(product_id, str) or not product_id.strip():
                raise ValidationError("product ids must be non-empty strings")
            if (
                not isinstance(unit_cost, Decimal)
                or not unit_cost.is_finite()
                or unit_cost < 0
            ):
                raise ValidationError("unit costs must be finite non-negative Decimals")
            validated[product_id] = unit_cost
        object.__setattr__(self, "costs", MappingProxyType(validated))

    def unit_cost(self, product_id: str) -> Decimal | None:
        """Return None for an unknown cost so a view can say "unknown" instead of zero margin."""
        return self.costs.get(product_id)


def load_cost_sheet(path: str | Path) -> CostSheet:
    """Parse costs from strings, like price lists, so no binary float enters money values."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ValidationError(f"cannot read cost sheet: {path}") from error
    except json.JSONDecodeError as error:
        raise ValidationError(f"invalid cost-sheet JSON: {path}") from error

    if not isinstance(document, dict):
        raise ValidationError("cost-sheet JSON must be an object")
    version = document.get("version")
    costs = document.get("costs")
    if not isinstance(version, str) or not isinstance(costs, dict):
        raise ValidationError("cost sheet must contain a version and costs object")

    decimal_costs: dict[str, Decimal] = {}
    for product_id, raw_cost in costs.items():
        if not isinstance(raw_cost, str):
            raise ValidationError(f"cost for {product_id} must be a decimal string")
        try:
            decimal_costs[product_id] = Decimal(raw_cost)
        except InvalidOperation as error:
            raise ValidationError(f"invalid cost for {product_id}") from error
    return CostSheet(version=version, costs=decimal_costs)
