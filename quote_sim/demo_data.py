"""Build the fake-data demo world once, for both the terminal demo and the browser server.

Policies here are made from the ILLUSTRATIVE values in config.py. Keeping the wiring in one place
means the terminal demo and the web demo can never quietly disagree about the rules.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from quote_sim import config
from quote_sim.agent import AgentPolicy, QuoteAgent, VolumeRule
from quote_sim.approval import ApprovalPolicy
from quote_sim.audit import AuditLog
from quote_sim.costs import CostSheet, load_cost_sheet
from quote_sim.evidence import PriceList, PriceListCatalog, load_price_list
from quote_sim.models import PricingPolicy
from quote_sim.service import QuoteDesk
from quote_sim.users import UserDirectory, load_users

SIMULATION_START = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
SIMULATION_TICK = timedelta(minutes=1)

PRICING_POLICY = PricingPolicy(
    max_discount=config.DEMO_MAX_DISCOUNT,
    vat_rate=config.DEMO_VAT_RATE,
)
APPROVAL_POLICY = ApprovalPolicy(
    auto_approve_threshold=config.DEMO_AUTO_APPROVE_THRESHOLD,
    rule_id=config.DEMO_AUTO_APPROVE_RULE_ID,
)
AGENT_POLICY = AgentPolicy(
    list_price_rule_id=config.DEMO_LIST_PRICE_RULE_ID,
    requested_discount_rule_id=config.DEMO_REQUESTED_DISCOUNT_RULE_ID,
    volume_rules=tuple(VolumeRule(*rule) for rule in config.DEMO_VOLUME_RULES),
)


class SimulatedClock:
    """Advance one minute per audit entry so demo timestamps are stable and readable."""

    def __init__(self, start: datetime = SIMULATION_START) -> None:
        self._next = start

    def __call__(self) -> datetime:
        current = self._next
        self._next += SIMULATION_TICK
        return current


@dataclass(frozen=True)
class FakeData:
    """Immutable inputs loaded once; every desk builds its own mutable catalog from them."""

    users: UserDirectory
    price_lists: tuple[PriceList, ...]
    cost_sheet: CostSheet


@lru_cache(maxsize=1)
def load_fake_data() -> FakeData:
    return FakeData(
        users=load_users(config.USERS_FILE),
        price_lists=tuple(load_price_list(path) for path in config.PRICE_LIST_FILES),
        cost_sheet=load_cost_sheet(config.COST_SHEET_FILE),
    )


def new_desk(data: FakeData | None = None) -> QuoteDesk:
    """A fresh, empty desk with a simulated clock; nothing is shared between desks."""
    data = data or load_fake_data()
    return QuoteDesk(
        users=data.users,
        price_lists=PriceListCatalog(data.price_lists),
        pricing_policy=PRICING_POLICY,
        approval_policy=APPROVAL_POLICY,
        audit_log=AuditLog(clock=SimulatedClock()),
        cost_sheet=data.cost_sheet,
    )


def new_agent(desk: QuoteDesk, agent_id: str) -> QuoteAgent:
    return QuoteAgent(desk, agent_id, AGENT_POLICY)
