from decimal import Decimal

import pytest

from quote_sim.interpret import (
    AmbiguousDiscount,
    DiscountUnit,
    NeedsClarification,
    interpret_discount,
)


@pytest.mark.parametrize(("text", "expected"), [("30%", "0.30"), ("12.5 percent", "0.125")])
def test_percent_sign_means_percent(text: str, expected: str) -> None:
    assert interpret_discount(text) == Decimal(expected)


def test_number_above_one_is_read_as_percent() -> None:
    assert interpret_discount("30") == Decimal("0.30")


def test_zero_needs_no_question() -> None:
    assert interpret_discount("0") == Decimal("0")


def test_exactly_one_is_ambiguous_and_just_above_is_percent() -> None:
    with pytest.raises(AmbiguousDiscount) as question:
        interpret_discount("1")

    assert question.value.value == Decimal("1")
    assert interpret_discount("1.01") == Decimal("0.0101")


def test_explicit_unit_resolves_ambiguity() -> None:
    assert interpret_discount("0.3", DiscountUnit.FRACTION) == Decimal("0.3")
    assert interpret_discount("0.3", DiscountUnit.PERCENT) == Decimal("0.003")


def test_percent_text_marked_as_fraction_is_rejected() -> None:
    with pytest.raises(NeedsClarification, match="written as a percentage"):
        interpret_discount("30%", DiscountUnit.FRACTION)


@pytest.mark.parametrize("text", ["abc", "-5"])
def test_non_number_or_negative_discount_needs_clarification(text: str) -> None:
    with pytest.raises(NeedsClarification):
        interpret_discount(text)
