from enum import Enum
from types import MappingProxyType
from typing import Mapping


class Role(str, Enum):
    AGENT = "agent"
    SALES = "sales"
    MANAGER = "manager"
    VIEWER = "viewer"


class Action(str, Enum):
    CREATE_QUOTE = "create_quote"
    EDIT_DRAFT = "edit_draft"
    SUBMIT_QUOTE = "submit_quote"
    APPROVE_QUOTE = "approve_quote"
    REJECT_QUOTE = "reject_quote"
    SEND_QUOTE = "send_quote"
    REVISE_QUOTE = "revise_quote"
    EDIT_APPROVED = "edit_approved"
    VIEW_QUOTE = "view_quote"
    VIEW_COST_MARGIN = "view_cost_margin"


AGENT_ACTIONS = frozenset(
    {
        Action.CREATE_QUOTE,
        Action.EDIT_DRAFT,
        Action.VIEW_QUOTE,
    }
)
SALES_ACTIONS = AGENT_ACTIONS | frozenset(
    {
        Action.SUBMIT_QUOTE,
        Action.SEND_QUOTE,
    }
)
MANAGER_ACTIONS = frozenset(
    {
        Action.APPROVE_QUOTE,
        Action.REJECT_QUOTE,
        Action.VIEW_QUOTE,
        Action.VIEW_COST_MARGIN,
    }
)
VIEWER_ACTIONS = frozenset({Action.VIEW_QUOTE})

PERMISSIONS: Mapping[Role, frozenset[Action]] = MappingProxyType(
    {
        Role.AGENT: AGENT_ACTIONS,
        Role.SALES: SALES_ACTIONS,
        Role.MANAGER: MANAGER_ACTIONS,
        Role.VIEWER: VIEWER_ACTIONS,
    }
)


class PermissionDenied(PermissionError):
    """Make forbidden operations explicit so callers cannot treat them as successful."""


def check_permission(role: Role, action: Action) -> None:
    """Raise when a role lacks an action; quote-specific rules belong to workflow checks."""
    if not isinstance(role, Role):
        raise TypeError("role must be a Role")
    if not isinstance(action, Action):
        raise TypeError("action must be an Action")
    if action not in PERMISSIONS[role]:
        raise PermissionDenied(f"{role.value} cannot perform {action.value}")
