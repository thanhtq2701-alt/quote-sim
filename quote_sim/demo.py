"""Run a fake quote through evidence, approval, and sending for CLI or web display."""

from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from quote_sim.access import Action, Role
from quote_sim.approval import ApprovalPolicy, ApprovalWorkflow
from quote_sim.audit import AuditEntry, AuditLog
from quote_sim.evidence import PriceListCatalog, attach_evidence, product_catalog
from quote_sim.models import PricingPolicy, Quote, QuoteState, QuoteTotals
from quote_sim.pricing import ValidationError, calculate_quote_totals, create_line_item

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_PRICE_LIST_PATHS: Mapping[str, Path] = MappingProxyType(
    {
        "v1": PROJECT_ROOT / "data" / "price_list_v1.json",
        "v2": PROJECT_ROOT / "data" / "price_list_v2.json",
    }
)

DEMO_AGENT_ID = "agent-demo"
DEMO_SALES_ID = "sales-demo"
DEMO_MANAGER_ID = "manager-demo"
DEMO_QUOTE_ID = "quote-demo-001"

DEMO_MAX_DISCOUNT = Decimal("0.30")
DEMO_VAT_RATE = Decimal("0.10")
DEMO_AUTO_APPROVE_THRESHOLD = Decimal("0.10")
DEMO_DISCOUNT = Decimal("0.20")
DEMO_QUANTITY = 2
DEMO_DISCOUNT_RULE_ID = "demo-standard-discount"
DEMO_AUTO_APPROVE_RULE_ID = "demo-low-discount-policy"


@dataclass(frozen=True)
class DemoResult:
    quote: Quote
    totals: QuoteTotals
    audit_entries: tuple[AuditEntry, ...]
    price_list_version: str


def run_scenario(
    quantity: int = DEMO_QUANTITY,
    discount: Decimal = DEMO_DISCOUNT,
    price_list_version: str = "v1",
) -> DemoResult:
    """Run the same validated scenario for both the terminal demo and browser form."""
    try:
        price_list_path = DEMO_PRICE_LIST_PATHS[price_list_version]
    except KeyError as error:
        raise ValidationError("choose a published price-list version") from error

    price_lists = PriceListCatalog()
    price_list = price_lists.publish_file(price_list_path)
    catalog = product_catalog(price_list)
    pricing_policy = PricingPolicy(
        max_discount=DEMO_MAX_DISCOUNT,
        vat_rate=DEMO_VAT_RATE,
    )
    approval_policy = ApprovalPolicy(
        auto_approve_threshold=DEMO_AUTO_APPROVE_THRESHOLD,
        rule_id=DEMO_AUTO_APPROVE_RULE_ID,
    )
    audit_log = AuditLog()
    workflow = ApprovalWorkflow(
        approval_policy,
        audit_log,
        price_lists,
        pricing_policy,
    )

    quote = Quote(quote_id=DEMO_QUOTE_ID, creator_id=DEMO_AGENT_ID)
    audit_log.record(
        actor_id=DEMO_AGENT_ID,
        role=Role.AGENT.value,
        action=Action.CREATE_QUOTE.value,
        quote_id=quote.quote_id,
        from_state=None,
        to_state=quote.state,
        details={},
    )

    line_item = create_line_item(
        product_id="sample-widget",
        quantity=quantity,
        discount=discount,
        catalog=catalog,
        policy=pricing_policy,
    )
    line_item = attach_evidence(
        line_item,
        price_list,
        discount_rule_id=DEMO_DISCOUNT_RULE_ID,
    )
    quote = replace(quote, line_items=(line_item,))
    audit_log.record(
        actor_id=DEMO_AGENT_ID,
        role=Role.AGENT.value,
        action=Action.EDIT_DRAFT.value,
        quote_id=quote.quote_id,
        from_state=QuoteState.DRAFT,
        to_state=QuoteState.DRAFT,
        details={
            "product_id": line_item.product_id,
            "quantity": line_item.quantity,
            "price_list_version": price_list.version,
            "discount_rule_id": DEMO_DISCOUNT_RULE_ID,
        },
    )

    quote = workflow.submit(quote, DEMO_SALES_ID, Role.SALES)
    if quote.state is QuoteState.PENDING_APPROVAL:
        quote = workflow.approve(quote, DEMO_MANAGER_ID, Role.MANAGER)
    quote = workflow.send(quote, DEMO_SALES_ID, Role.SALES)

    totals = calculate_quote_totals(quote.line_items, catalog, pricing_policy)
    return DemoResult(
        quote=quote,
        totals=totals,
        audit_entries=audit_log.entries,
        price_list_version=price_list.version,
    )


def main() -> None:
    result = run_scenario()
    print("Quote workflow demo (fake data)")
    for step, entry in enumerate(result.audit_entries, start=1):
        state_change = (
            f"{entry.from_state.value if entry.from_state else 'none'} -> "
            f"{entry.to_state.value if entry.to_state else 'none'}"
        )
        print(
            f"{step}. {entry.role.upper()} {entry.action}: {state_change}"
        )

    print("Totals (USD):")
    for line_number, line_total in enumerate(result.totals.line_totals, start=1):
        print(f"  Line {line_number}: {line_total}")
    print(f"  Subtotal: {result.totals.subtotal}")
    print(f"  VAT: {result.totals.vat}")
    print(f"  Total: {result.totals.total}")

    print("Audit log:")
    for entry in result.audit_entries:
        from_state = entry.from_state.value if entry.from_state else "none"
        to_state = entry.to_state.value if entry.to_state else "none"
        details = ", ".join(
            f"{key}={value}" for key, value in entry.details.items()
        )
        print(
            f"  {entry.timestamp.isoformat()} | {entry.actor_id} ({entry.role}) | "
            f"{entry.action} | {from_state} -> {to_state} | {details}"
        )


if __name__ == "__main__":
    main()
