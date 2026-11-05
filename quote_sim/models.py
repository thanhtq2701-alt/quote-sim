from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True)
class Product:
    """Keep catalog prices immutable while a quote line is being created."""

    product_id: str
    unit_price: Decimal


@dataclass(frozen=True)
class LineEvidence:
    """Keep the source and rule beside the price copied into a quote line."""

    product_id: str
    price_list_version: str
    unit_price_snapshot: Decimal
    discount_rule_id: str


@dataclass(frozen=True)
class LineItem:
    """Keep the original price snapshot so later catalog changes cannot reprice a quote."""

    product_id: str
    quantity: int
    unit_price: Decimal
    discount: Decimal
    evidence: LineEvidence | None = None


@dataclass(frozen=True)
class PricingPolicy:
    """Make discount and VAT rules explicit instead of embedding business values in calculations."""

    max_discount: Decimal
    vat_rate: Decimal


@dataclass(frozen=True)
class QuoteTotals:
    """Return rounded line and quote amounts together under one pricing policy."""

    line_totals: tuple[Decimal, ...]
    subtotal: Decimal
    vat: Decimal
    total: Decimal


class QuoteState(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"


@dataclass(frozen=True)
class Quote:
    """Keep each workflow step as a new value so state changes can be audited."""

    quote_id: str
    creator_id: str
    line_items: tuple[LineItem, ...] = ()
    state: QuoteState = QuoteState.DRAFT
    submitted_by: str | None = None
    approved_by: str | None = None
