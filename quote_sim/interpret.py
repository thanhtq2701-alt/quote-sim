"""Interpret what a human typed, and ask instead of guessing when it could mean two things.

A discount typed as "0.3" might mean 30% (a fraction) or 0.3% (a percentage). Picking one silently
could put a 100x wrong discount on a quote, so ambiguous input raises AmbiguousDiscount and the
caller asks the person which they meant.
"""

from decimal import Decimal, InvalidOperation
from enum import Enum

from quote_sim.pricing import ValidationError

PERCENT = Decimal("100")
PERCENT_SUFFIXES = ("%", "percent")


class NeedsClarification(ValidationError):
    """The input was not understood well enough to act on; a person must rephrase or choose.

    Nothing has been attempted on a quote yet when this is raised, so there is nothing to audit.
    """


class DiscountUnit(str, Enum):
    PERCENT = "percent"
    FRACTION = "fraction"


class AmbiguousDiscount(NeedsClarification):
    """Carry the typed number so a caller can offer both readings back to the person."""

    def __init__(self, value: Decimal) -> None:
        self.value = value
        super().__init__(
            f"is {value} meant as {value}% or as the fraction {value} "
            f"(= {format((value * PERCENT).normalize(), 'f')}%)?"
        )


def interpret_discount(text: str, unit: DiscountUnit | None = None) -> Decimal:
    """Return the discount as a fraction (0.15 means 15%).

    Rules: a "%" or "percent" suffix means percent; an explicit unit is obeyed; 0 is 0 either way;
    a number above 1 can only be a percentage, because a fraction above 1 is a >100% discount;
    anything from 0 (exclusive) to 1 (inclusive) is ambiguous and must be clarified.
    """
    if not isinstance(text, str):
        raise NeedsClarification("discount must be text")
    if unit is not None and not isinstance(unit, DiscountUnit):
        raise ValidationError("discount unit must be percent or fraction")

    raw = text.strip().lower()
    written_as_percent = raw.endswith(PERCENT_SUFFIXES)
    for suffix in PERCENT_SUFFIXES:
        raw = raw.removesuffix(suffix)
    try:
        number = Decimal(raw.strip())
    except InvalidOperation as error:
        raise NeedsClarification(f"discount {text.strip()!r} is not a number") from error
    if not number.is_finite() or number < 0:
        raise NeedsClarification("discount must be a non-negative number")

    if written_as_percent:
        if unit is DiscountUnit.FRACTION:
            raise NeedsClarification(f"{text.strip()!r} is written as a percentage, not a fraction")
        return number / PERCENT
    if unit is DiscountUnit.PERCENT:
        return number / PERCENT
    if unit is DiscountUnit.FRACTION:
        return number
    if number == 0:
        return number
    if number > 1:
        return number / PERCENT
    raise AmbiguousDiscount(number)
