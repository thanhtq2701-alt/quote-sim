import json
from decimal import Decimal
from pathlib import Path

import pytest

from quote_sim.access import Role
from quote_sim.costs import CostSheet, load_cost_sheet
from quote_sim.evidence import PriceList, attach_evidence
from quote_sim.models import LineItem, PricingPolicy, Quote
from quote_sim.pricing import ValidationError
from quote_sim.service import QuoteDesk
from quote_sim.views import build_quote_view

TEST_PRICING_POLICY = PricingPolicy(max_discount=Decimal("0.30"), vat_rate=Decimal("0.10"))
TEST_COSTS = CostSheet("test-costs", {"widget": Decimal("6.00")})
TEST_PRICE_LIST = PriceList("test-v1", {"widget": Decimal("10.00"), "cable": Decimal("2.00")})


def make_quote(*product_ids: str) -> Quote:
    lines = tuple(
        attach_evidence(
            LineItem(
                product_id=product_id,
                quantity=2,
                unit_price=TEST_PRICE_LIST.products[product_id],
                discount=Decimal("0.10"),
            ),
            TEST_PRICE_LIST,
            "test-rule",
        )
        for product_id in product_ids
    )
    return Quote(quote_id="quote-1", creator_id="agent-1", line_items=lines)


def test_manager_view_shows_unit_cost_and_margin() -> None:
    view = build_quote_view(make_quote("widget"), Role.MANAGER, TEST_PRICING_POLICY, TEST_COSTS)

    # 2 x 10.00 x 0.90 = 18.00 revenue; 2 x 6.00 = 12.00 cost.
    assert view.cost_visible is True
    assert view.lines[0].unit_cost == Decimal("6.00")
    assert view.lines[0].margin == Decimal("6.00")
    assert view.total_margin == Decimal("6.00")


@pytest.mark.parametrize("role", [Role.AGENT, Role.SALES, Role.VIEWER])
def test_non_manager_roles_do_not_see_cost_or_margin(role: Role) -> None:
    view = build_quote_view(make_quote("widget"), role, TEST_PRICING_POLICY, TEST_COSTS)

    assert view.cost_visible is False
    assert view.lines[0].unit_cost is None
    assert view.lines[0].margin is None
    assert view.total_margin is None


def test_total_margin_is_unknown_when_a_product_has_no_cost() -> None:
    view = build_quote_view(
        make_quote("widget", "cable"), Role.MANAGER, TEST_PRICING_POLICY, TEST_COSTS
    )

    assert view.lines[0].margin == Decimal("6.00")
    assert view.lines[1].margin is None
    assert view.total_margin is None


def test_view_total_uses_line_snapshot_not_newer_price_list(desk: QuoteDesk) -> None:
    quote = desk.create_quote("agent-1")
    desk.add_line(
        "agent-1",
        quote.quote_id,
        product_id="widget",
        quantity=2,
        discount=Decimal("0.10"),
        discount_rule_id="test-rule",
        price_list_version="test-v1",
    )
    before = desk.view("viewer-1", quote.quote_id)

    desk.price_lists.publish(PriceList("test-v9", {"widget": Decimal("99.00")}))
    after = desk.view("viewer-1", quote.quote_id)

    assert before.total == after.total == Decimal("19.80")
    assert after.lines[0].unit_price == Decimal("10.00")
    assert after.lines[0].price_list_version == "test-v1"


def test_cost_sheet_rejects_negative_cost() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        CostSheet("test-costs", {"widget": Decimal("-1.00")})


def test_cost_written_as_json_number_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "costs.json"
    path.write_text(
        json.dumps({"version": "test-costs", "costs": {"widget": 6.0}}),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="decimal string"):
        load_cost_sheet(path)
