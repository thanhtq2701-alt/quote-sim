from decimal import Decimal

import pytest

from quote_sim.models import PricingPolicy, Product
from quote_sim.pricing import (
    ValidationError,
    calculate_line_total,
    calculate_quote_totals,
    create_line_item,
)

TEST_MAX_DISCOUNT = Decimal("0.30")
TEST_VAT_RATE = Decimal("0.10")
TEST_POLICY = PricingPolicy(
    max_discount=TEST_MAX_DISCOUNT,
    vat_rate=TEST_VAT_RATE,
)


def test_create_line_item_accepts_positive_integer_quantity() -> None:
    catalog = {"widget": Product("widget", Decimal("10.00"))}

    line_item = create_line_item(
        "widget", 1, Decimal("0.00"), catalog, TEST_POLICY
    )

    assert line_item.quantity == 1


def test_create_line_item_rejects_zero_quantity() -> None:
    catalog = {"widget": Product("widget", Decimal("10.00"))}

    with pytest.raises(ValidationError, match="positive integer"):
        create_line_item("widget", 0, Decimal("0.00"), catalog, TEST_POLICY)


def test_create_line_item_rejects_negative_quantity() -> None:
    catalog = {"widget": Product("widget", Decimal("10.00"))}

    with pytest.raises(ValidationError, match="positive integer"):
        create_line_item("widget", -1, Decimal("0.00"), catalog, TEST_POLICY)


def test_create_line_item_rejects_non_integer_quantity() -> None:
    catalog = {"widget": Product("widget", Decimal("10.00"))}

    with pytest.raises(ValidationError, match="positive integer"):
        create_line_item("widget", 1.5, Decimal("0.00"), catalog, TEST_POLICY)


def test_create_line_item_snapshots_price_from_catalog() -> None:
    catalog = {"widget": Product("widget", Decimal("10.00"))}

    line_item = create_line_item(
        "widget", 1, Decimal("0.00"), catalog, TEST_POLICY
    )
    catalog["widget"] = Product("widget", Decimal("12.00"))

    assert line_item.unit_price == Decimal("10.00")
    assert calculate_line_total(line_item, catalog, TEST_POLICY) == Decimal("10.00")


def test_create_line_item_rejects_unknown_product() -> None:
    with pytest.raises(ValidationError, match="unknown product"):
        create_line_item(
            "unknown", 1, Decimal("0.00"), {}, TEST_POLICY
        )


def test_create_line_item_accepts_zero_discount() -> None:
    catalog = {"widget": Product("widget", Decimal("10.00"))}

    line_item = create_line_item(
        "widget", 1, Decimal("0.00"), catalog, TEST_POLICY
    )

    assert line_item.discount == Decimal("0.00")


def test_create_line_item_accepts_discount_at_maximum() -> None:
    catalog = {"widget": Product("widget", Decimal("10.00"))}

    line_item = create_line_item(
        "widget", 1, TEST_MAX_DISCOUNT, catalog, TEST_POLICY
    )

    assert line_item.discount == TEST_MAX_DISCOUNT


def test_create_line_item_rejects_negative_discount() -> None:
    catalog = {"widget": Product("widget", Decimal("10.00"))}

    with pytest.raises(ValidationError, match="discount must be between"):
        create_line_item("widget", 1, Decimal("-0.01"), catalog, TEST_POLICY)


def test_create_line_item_rejects_discount_above_maximum() -> None:
    catalog = {"widget": Product("widget", Decimal("10.00"))}

    with pytest.raises(ValidationError, match="discount must be between"):
        create_line_item("widget", 1, Decimal("0.31"), catalog, TEST_POLICY)


def test_calculate_line_total_uses_decimal_arithmetic_and_rounds_half_up() -> None:
    catalog = {"widget": Product("widget", Decimal("1.10"))}
    line_item = create_line_item(
        "widget", 3, Decimal("0.25"), catalog, TEST_POLICY
    )

    total = calculate_line_total(line_item, catalog, TEST_POLICY)

    assert total == Decimal("2.48")


def test_calculate_quote_totals_rounds_subtotal_and_vat() -> None:
    catalog = {
        "first": Product("first", Decimal("0.025")),
        "second": Product("second", Decimal("0.025")),
    }
    line_items = (
        create_line_item("first", 1, Decimal("0.00"), catalog, TEST_POLICY),
        create_line_item("second", 1, Decimal("0.00"), catalog, TEST_POLICY),
    )

    totals = calculate_quote_totals(line_items, catalog, TEST_POLICY)

    assert totals.line_totals == (Decimal("0.03"), Decimal("0.03"))
    assert totals.subtotal == Decimal("0.06")
    assert totals.vat == Decimal("0.01")
    assert totals.total == Decimal("0.07")


def test_create_line_item_rejects_float_unit_price() -> None:
    catalog = {"widget": Product("widget", 10.0)}

    with pytest.raises(ValidationError, match="unit_price must be a finite Decimal"):
        create_line_item("widget", 1, Decimal("0.00"), catalog, TEST_POLICY)


def test_create_line_item_rejects_float_discount() -> None:
    catalog = {"widget": Product("widget", Decimal("10.00"))}

    with pytest.raises(ValidationError, match="discount must be a finite Decimal"):
        create_line_item("widget", 1, 0.1, catalog, TEST_POLICY)
