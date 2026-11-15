from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal

from quote_sim.models import LineItem, PricingPolicy, Product, QuoteTotals

USD_CENT = Decimal("0.01")
USD_ZERO = Decimal("0.00")
DISCOUNT_MIN = Decimal("0")
DISCOUNT_MAX = Decimal("1")


class ValidationError(ValueError):
    """Report invalid pricing input explicitly so callers cannot mistake it for a valid quote."""


def create_line_item(
    product_id: str,
    quantity: int,
    discount: Decimal,
    catalog: Mapping[str, Product],
    policy: PricingPolicy,
) -> LineItem:
    """Snapshot a catalog price; discount is a fraction, so 0.10 represents 10%."""
    _validate_policy(policy)
    _validate_product_id(product_id)
    _validate_quantity(quantity)
    validate_discount(discount, policy)

    product = _get_catalog_product(product_id, catalog)
    _validate_decimal(product.unit_price, "unit_price")
    if product.unit_price < 0:
        raise ValidationError("unit_price cannot be negative")

    return LineItem(
        product_id=product_id,
        quantity=quantity,
        unit_price=product.unit_price,
        discount=discount,
    )


def calculate_line_total(
    line_item: LineItem,
    catalog: Mapping[str, Product],
    policy: PricingPolicy,
) -> Decimal:
    """Calculate from the line's snapshot, not a possibly newer catalog price."""
    validate_line_item(line_item, catalog, policy)

    discount_factor = DISCOUNT_MAX - line_item.discount
    amount = Decimal(line_item.quantity) * line_item.unit_price * discount_factor
    return amount.quantize(USD_CENT, rounding=ROUND_HALF_UP)


def validate_line_item(
    line_item: LineItem,
    catalog: Mapping[str, Product],
    policy: PricingPolicy,
) -> None:
    """Recheck stored lines at workflow boundaries, not only when first constructed."""
    _validate_policy(policy)
    if not isinstance(line_item, LineItem):
        raise ValidationError("line_item must be a LineItem")
    _validate_product_id(line_item.product_id)
    _get_catalog_product(line_item.product_id, catalog)
    _validate_quantity(line_item.quantity)
    _validate_decimal(line_item.unit_price, "unit_price")
    if line_item.unit_price < 0:
        raise ValidationError("unit_price cannot be negative")
    validate_discount(line_item.discount, policy)


def calculate_quote_totals(
    line_items: Sequence[LineItem],
    catalog: Mapping[str, Product],
    policy: PricingPolicy,
) -> QuoteTotals:
    """Sum rounded line amounts before calculating VAT to keep displayed totals consistent."""
    line_totals = tuple(
        calculate_line_total(line_item, catalog, policy) for line_item in line_items
    )
    return summarize_line_totals(line_totals, policy)


def summarize_line_totals(
    line_totals: Sequence[Decimal],
    policy: PricingPolicy,
) -> QuoteTotals:
    """Share one VAT rule for callers whose lines come from different price-list versions."""
    totals = tuple(line_totals)
    for line_total in totals:
        _validate_decimal(line_total, "line_total")
    subtotal = sum(totals, USD_ZERO)
    vat = (subtotal * _validate_policy(policy)).quantize(USD_CENT, rounding=ROUND_HALF_UP)
    return QuoteTotals(
        line_totals=totals,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
    )


def _validate_policy(policy: PricingPolicy) -> Decimal:
    if not isinstance(policy, PricingPolicy):
        raise ValidationError("policy must be a PricingPolicy")
    _validate_decimal(policy.max_discount, "max_discount")
    _validate_decimal(policy.vat_rate, "vat_rate")
    if not DISCOUNT_MIN <= policy.max_discount <= DISCOUNT_MAX:
        raise ValidationError("max_discount must be between 0 and 1")
    if policy.vat_rate < DISCOUNT_MIN:
        raise ValidationError("vat_rate cannot be negative")
    return policy.vat_rate


def validate_discount(discount: Decimal, policy: PricingPolicy) -> None:
    """Apply the same maximum-discount rule to new and already-created quote lines."""
    _validate_policy(policy)
    _validate_decimal(discount, "discount")
    if discount < DISCOUNT_MIN or discount > policy.max_discount:
        max_percent = format((policy.max_discount * 100).normalize(), "f")
        raise ValidationError(
            f"discount must be between 0 and {policy.max_discount} (= {max_percent}%)"
        )


def _validate_product_id(product_id: str) -> None:
    if not isinstance(product_id, str) or not product_id.strip():
        raise ValidationError("product_id must be a non-empty string")


def _validate_quantity(quantity: int) -> None:
    if type(quantity) is not int or quantity <= 0:
        raise ValidationError("quantity must be a positive integer")


def _get_catalog_product(
    product_id: str,
    catalog: Mapping[str, Product],
) -> Product:
    product = catalog.get(product_id)
    if not isinstance(product, Product) or product.product_id != product_id:
        raise ValidationError(f"unknown product: {product_id}")
    return product


def _validate_decimal(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValidationError(f"{field_name} must be a finite Decimal")
