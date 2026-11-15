"""Role-filtered read models: the single place that decides whether cost and margin appear."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from quote_sim.access import Action, Role, is_allowed
from quote_sim.costs import CostSheet
from quote_sim.models import LineItem, PricingPolicy, Product, Quote, QuoteState
from quote_sim.pricing import (
    USD_CENT,
    USD_ZERO,
    calculate_line_total,
    summarize_line_totals,
)


@dataclass(frozen=True)
class LineView:
    """Show one line with its evidence; cost fields stay None unless the reader may see them."""

    product_id: str
    quantity: int
    unit_price: Decimal
    discount: Decimal
    line_total: Decimal
    price_list_version: str | None
    discount_rule_id: str | None
    unit_cost: Decimal | None = None
    margin: Decimal | None = None


@dataclass(frozen=True)
class QuoteView:
    """A read-only snapshot shaped for one role, so callers cannot leak hidden fields by accident."""

    quote_id: str
    state: QuoteState
    creator_id: str
    submitted_by: str | None
    approved_by: str | None
    lines: tuple[LineView, ...]
    subtotal: Decimal
    vat: Decimal
    total: Decimal
    cost_visible: bool
    total_margin: Decimal | None = None


def build_quote_view(
    quote: Quote,
    role: Role,
    pricing_policy: PricingPolicy,
    cost_sheet: CostSheet | None,
) -> QuoteView:
    """Price each line from its own snapshot, so a newer price list never changes the view."""
    cost_visible = is_allowed(role, Action.VIEW_COST_MARGIN) and cost_sheet is not None
    lines = tuple(
        _build_line_view(line, pricing_policy, cost_sheet if cost_visible else None)
        for line in quote.line_items
    )
    totals = summarize_line_totals([line.line_total for line in lines], pricing_policy)

    total_margin: Decimal | None = None
    if cost_visible and all(line.margin is not None for line in lines):
        total_margin = sum((line.margin for line in lines if line.margin is not None), USD_ZERO)

    return QuoteView(
        quote_id=quote.quote_id,
        state=quote.state,
        creator_id=quote.creator_id,
        submitted_by=quote.submitted_by,
        approved_by=quote.approved_by,
        lines=lines,
        subtotal=totals.subtotal,
        vat=totals.vat,
        total=totals.total,
        cost_visible=cost_visible,
        total_margin=total_margin,
    )


def _build_line_view(
    line: LineItem,
    pricing_policy: PricingPolicy,
    cost_sheet: CostSheet | None,
) -> LineView:
    # The snapshot itself is the price source here; evidence validity is checked on submit.
    own_catalog = {line.product_id: Product(line.product_id, line.unit_price)}
    line_total = calculate_line_total(line, own_catalog, pricing_policy)

    unit_cost = cost_sheet.unit_cost(line.product_id) if cost_sheet is not None else None
    margin = (
        (line_total - Decimal(line.quantity) * unit_cost).quantize(
            USD_CENT, rounding=ROUND_HALF_UP
        )
        if unit_cost is not None
        else None
    )
    evidence = line.evidence
    return LineView(
        product_id=line.product_id,
        quantity=line.quantity,
        unit_price=line.unit_price,
        discount=line.discount,
        line_total=line_total,
        price_list_version=evidence.price_list_version if evidence else None,
        discount_rule_id=evidence.discount_rule_id if evidence else None,
        unit_cost=unit_cost,
        margin=margin,
    )
