"""Turn domain objects into JSON-ready dicts.

Money and percentages leave the server as strings ("17.60"), never as JSON numbers, because a
browser would parse numbers as binary floats; the browser only displays them.
"""

from decimal import Decimal
from typing import Any

from quote_sim.access import PERMISSIONS
from quote_sim.audit import AuditEntry
from quote_sim.users import User
from quote_sim.views import LineView, QuoteView

from quote_sim.demo_data import AGENT_POLICY, APPROVAL_POLICY, PRICING_POLICY, FakeData

from server.scenario import PERCENT, ReplayResult


def percent_text(fraction: Decimal) -> str:
    """0.15 -> "15", 0.125 -> "12.5": readable, and exact because it stays a Decimal."""
    return format((fraction * PERCENT).normalize(), "f")


def money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def user_json(user: User) -> dict[str, Any]:
    return {"user_id": user.user_id, "display_name": user.display_name, "role": user.role.value}


def catalog_json(data: FakeData) -> dict[str, Any]:
    """Everything the page needs to build its menus. Costs are deliberately NOT included."""
    agent_ids = [user.user_id for user in data.users.users if user.role.value == "agent"]
    return {
        "users": [user_json(user) for user in data.users.users],
        "agent_user_id": agent_ids[0] if agent_ids else None,
        "price_lists": [
            {
                "version": price_list.version,
                "products": [
                    {"product_id": product_id, "unit_price": money(price)}
                    for product_id, price in price_list.products.items()
                ],
            }
            for price_list in data.price_lists
        ],
        "latest_price_list": data.price_lists[-1].version if data.price_lists else None,
        "policy": {
            "max_discount_percent": percent_text(PRICING_POLICY.max_discount),
            "vat_percent": percent_text(PRICING_POLICY.vat_rate),
            "auto_approve_percent": percent_text(APPROVAL_POLICY.auto_approve_threshold),
            "auto_approve_rule_id": APPROVAL_POLICY.rule_id,
        },
        "agent_rules": [
            {
                "rule_id": AGENT_POLICY.list_price_rule_id,
                "min_quantity": 1,
                "discount_percent": "0",
            }
        ]
        + [
            {
                "rule_id": rule.rule_id,
                "min_quantity": rule.min_quantity,
                "discount_percent": percent_text(rule.discount),
            }
            for rule in sorted(AGENT_POLICY.volume_rules, key=lambda rule: rule.min_quantity)
        ]
        + [
            {
                "rule_id": AGENT_POLICY.requested_discount_rule_id,
                "min_quantity": "any",
                "discount_percent": "as the customer asks",
            }
        ],
        "permissions": {
            role.value: sorted(action.value for action in actions)
            for role, actions in PERMISSIONS.items()
        },
    }


def line_json(line: LineView) -> dict[str, Any]:
    return {
        "product_id": line.product_id,
        "quantity": line.quantity,
        "unit_price": money(line.unit_price),
        "discount_percent": percent_text(line.discount),
        "line_total": money(line.line_total),
        "price_list_version": line.price_list_version,
        "discount_rule_id": line.discount_rule_id,
        "unit_cost": money(line.unit_cost),
        "margin": money(line.margin),
    }


def quote_json(view: QuoteView) -> dict[str, Any]:
    return {
        "quote_id": view.quote_id,
        "state": view.state.value,
        "creator_id": view.creator_id,
        "submitted_by": view.submitted_by,
        "approved_by": view.approved_by,
        "lines": [line_json(line) for line in view.lines],
        "subtotal": money(view.subtotal),
        "vat": money(view.vat),
        "total": money(view.total),
        "cost_visible": view.cost_visible,
        "total_margin": money(view.total_margin),
    }


def audit_json(entry: AuditEntry) -> dict[str, Any]:
    return {
        "timestamp": entry.timestamp.isoformat(),
        "actor_id": entry.actor_id,
        "role": entry.role,
        "action": entry.action,
        "quote_id": entry.quote_id,
        "from_state": entry.from_state.value if entry.from_state else None,
        "to_state": entry.to_state.value if entry.to_state else None,
        "details": {key: _detail(value) for key, value in entry.details.items()},
    }


def replay_json(result: ReplayResult, viewer: User) -> dict[str, Any]:
    """Views are built through the desk, so the viewer's reads appear in the audit log too."""
    desk = result.desk
    quotes = [quote_json(desk.view(viewer.user_id, quote_id)) for quote_id in desk.quote_ids]
    return {
        "viewer": user_json(viewer),
        "steps": [
            {"ok": step.ok, "message": step.message, "notes": list(step.notes)}
            for step in result.steps
        ],
        "quotes": quotes,
        "audit": [audit_json(entry) for entry in desk.audit_entries],
    }


def _detail(value: object) -> object:
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)
