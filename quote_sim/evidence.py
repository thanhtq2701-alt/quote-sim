import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType

from quote_sim.models import LineEvidence, LineItem, Quote, Product
from quote_sim.pricing import ValidationError


class MissingEvidence(ValueError):
    """Identify a quote line that cannot be traced to an available price-list record."""


@dataclass(frozen=True)
class PriceList:
    """Freeze each published product-price mapping so later versions cannot rewrite it."""

    version: str
    products: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValidationError("price-list version must be a non-empty string")
        if not isinstance(self.products, Mapping):
            raise ValidationError("price-list products must be a mapping")
        validated_products: dict[str, Decimal] = {}
        for product_id, unit_price in self.products.items():
            if not isinstance(product_id, str) or not product_id.strip():
                raise ValidationError("product ids must be non-empty strings")
            if (
                not isinstance(unit_price, Decimal)
                or not unit_price.is_finite()
                or unit_price < 0
            ):
                raise ValidationError("price-list prices must be finite non-negative Decimals")
            validated_products[product_id] = unit_price
        object.__setattr__(self, "products", MappingProxyType(validated_products))


class PriceListCatalog:
    """Keep published versions addressable without allowing a duplicate to replace one."""

    def __init__(self, price_lists: Iterable[PriceList] = ()) -> None:
        self._versions: dict[str, PriceList] = {}
        for price_list in price_lists:
            self.publish(price_list)

    @property
    def versions(self) -> tuple[str, ...]:
        return tuple(self._versions)

    @property
    def latest_version(self) -> str:
        """Use publication order, not string sorting, so "v10" cannot sort before "v9"."""
        if not self._versions:
            raise MissingEvidence("no price-list version has been published")
        return next(reversed(self._versions))

    def publish(self, price_list: PriceList) -> None:
        if not isinstance(price_list, PriceList):
            raise TypeError("price_list must be a PriceList")
        if price_list.version in self._versions:
            raise ValidationError(f"price-list version already published: {price_list.version}")
        self._versions[price_list.version] = price_list

    def publish_file(self, path: str | Path) -> PriceList:
        price_list = load_price_list(path)
        self.publish(price_list)
        return price_list

    def get(self, version: str) -> PriceList:
        try:
            return self._versions[version]
        except KeyError as error:
            raise MissingEvidence(f"unknown price-list version: {version}") from error


def load_price_list(path: str | Path) -> PriceList:
    """Load fake prices as Decimals so JSON parsing never introduces binary floats."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ValidationError(f"cannot read price list: {path}") from error
    except json.JSONDecodeError as error:
        raise ValidationError(f"invalid price-list JSON: {path}") from error

    if not isinstance(document, dict):
        raise ValidationError("price-list JSON must be an object")
    version = document.get("version")
    products = document.get("products")
    if not isinstance(version, str) or not isinstance(products, dict):
        raise ValidationError("price list must contain a version and products object")

    decimal_prices: dict[str, Decimal] = {}
    for product_id, raw_price in products.items():
        if not isinstance(raw_price, str):
            raise ValidationError(f"price for {product_id} must be a decimal string")
        try:
            decimal_prices[product_id] = Decimal(raw_price)
        except InvalidOperation as error:
            raise ValidationError(f"invalid price for {product_id}") from error
    return PriceList(version=version, products=decimal_prices)


def product_catalog(price_list: PriceList) -> Mapping[str, Product]:
    """Adapt an immutable price list for pricing without losing its versioned source."""
    if not isinstance(price_list, PriceList):
        raise TypeError("price_list must be a PriceList")
    return MappingProxyType(
        {
            product_id: Product(product_id, unit_price)
            for product_id, unit_price in price_list.products.items()
        }
    )


def attach_evidence(
    line_item: LineItem,
    price_list: PriceList,
    discount_rule_id: str,
) -> LineItem:
    """Copy the matching versioned price and rule onto a draft line."""
    if not isinstance(line_item, LineItem):
        raise TypeError("line_item must be a LineItem")
    if not isinstance(price_list, PriceList):
        raise TypeError("price_list must be a PriceList")
    if not isinstance(discount_rule_id, str) or not discount_rule_id.strip():
        raise ValidationError("discount_rule_id must be a non-empty string")
    if (
        not isinstance(line_item.unit_price, Decimal)
        or not line_item.unit_price.is_finite()
    ):
        raise ValidationError("line unit_price must be a finite Decimal")
    unit_price = price_list.products.get(line_item.product_id)
    if unit_price is None:
        raise MissingEvidence(
            f"product {line_item.product_id} is absent from price list {price_list.version}"
        )
    if line_item.unit_price != unit_price:
        raise ValidationError("line unit price does not match the selected price-list version")
    return replace(
        line_item,
        evidence=LineEvidence(
            product_id=line_item.product_id,
            price_list_version=price_list.version,
            unit_price_snapshot=unit_price,
            discount_rule_id=discount_rule_id,
        ),
    )


def validate_line_evidence(
    line_item: LineItem,
    price_lists: PriceListCatalog,
) -> None:
    """Check that the line's evidence still matches its immutable source version."""
    evidence = line_item.evidence
    if evidence is None:
        raise MissingEvidence(f"line for {line_item.product_id} has no evidence")
    if not isinstance(evidence, LineEvidence):
        raise ValidationError("line evidence must be a LineEvidence record")
    if evidence.product_id != line_item.product_id:
        raise ValidationError("evidence product does not match the quote line")
    if (
        not isinstance(evidence.discount_rule_id, str)
        or not evidence.discount_rule_id.strip()
    ):
        raise ValidationError("evidence discount_rule_id must be a non-empty string")
    if (
        not isinstance(evidence.unit_price_snapshot, Decimal)
        or not evidence.unit_price_snapshot.is_finite()
    ):
        raise ValidationError("evidence unit_price_snapshot must be a finite Decimal")
    price_list = price_lists.get(evidence.price_list_version)
    source_price = price_list.products.get(evidence.product_id)
    if source_price is None:
        raise MissingEvidence(
            f"product {evidence.product_id} is absent from price list {price_list.version}"
        )
    if (
        evidence.unit_price_snapshot != source_price
        or line_item.unit_price != evidence.unit_price_snapshot
    ):
        raise ValidationError("evidence price does not match the quote line and source version")


def validate_quote_evidence(
    quote: Quote,
    price_lists: PriceListCatalog,
) -> None:
    if not quote.line_items:
        raise MissingEvidence("quote has no line items")
    for line_item in quote.line_items:
        validate_line_evidence(line_item, price_lists)
