"""Shared test setup for desk-level tests; values are named test inputs, not business rules."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quote_sim.access import Role
from quote_sim.approval import ApprovalPolicy
from quote_sim.audit import AuditLog
from quote_sim.costs import CostSheet
from quote_sim.evidence import PriceList, PriceListCatalog
from quote_sim.models import PricingPolicy
from quote_sim.service import QuoteDesk
from quote_sim.users import User, UserDirectory

TEST_PRICING_POLICY = PricingPolicy(max_discount=Decimal("0.30"), vat_rate=Decimal("0.10"))
TEST_APPROVAL_POLICY = ApprovalPolicy(
    auto_approve_threshold=Decimal("0.10"),
    rule_id="test-auto-approve",
)
TEST_RULE_ID = "test-discount-rule"
FIXED_TIME = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)

TEST_USERS = UserDirectory(
    [
        User("agent-1", "Test Agent", Role.AGENT),
        User("sales-1", "Test Sales", Role.SALES),
        User("manager-1", "Test Manager", Role.MANAGER),
        User("viewer-1", "Test Viewer", Role.VIEWER),
    ]
)


def make_price_lists() -> PriceListCatalog:
    return PriceListCatalog(
        [
            PriceList("test-v1", {"widget": Decimal("10.00"), "cable": Decimal("2.00")}),
            PriceList("test-v2", {"widget": Decimal("12.00"), "cable": Decimal("2.50")}),
        ]
    )


@pytest.fixture
def audit_log() -> AuditLog:
    return AuditLog(clock=lambda: FIXED_TIME)


@pytest.fixture
def desk(audit_log: AuditLog) -> QuoteDesk:
    return QuoteDesk(
        users=TEST_USERS,
        price_lists=make_price_lists(),
        pricing_policy=TEST_PRICING_POLICY,
        approval_policy=TEST_APPROVAL_POLICY,
        audit_log=audit_log,
        cost_sheet=CostSheet("test-costs", {"widget": Decimal("6.00")}),
    )
