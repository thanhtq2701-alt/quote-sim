import pytest

from quote_sim.access import Action, PermissionDenied, Role, check_permission, is_allowed


def test_agent_can_create_quote() -> None:
    check_permission(Role.AGENT, Action.CREATE_QUOTE)


def test_agent_can_edit_draft() -> None:
    check_permission(Role.AGENT, Action.EDIT_DRAFT)


def test_agent_cannot_submit_quote() -> None:
    with pytest.raises(PermissionDenied):
        check_permission(Role.AGENT, Action.SUBMIT_QUOTE)


def test_agent_cannot_approve_quote() -> None:
    with pytest.raises(PermissionDenied):
        check_permission(Role.AGENT, Action.APPROVE_QUOTE)


def test_agent_cannot_reject_quote() -> None:
    with pytest.raises(PermissionDenied):
        check_permission(Role.AGENT, Action.REJECT_QUOTE)


def test_agent_cannot_send_quote() -> None:
    with pytest.raises(PermissionDenied):
        check_permission(Role.AGENT, Action.SEND_QUOTE)


def test_sales_can_submit_quote() -> None:
    check_permission(Role.SALES, Action.SUBMIT_QUOTE)


def test_sales_can_send_quote() -> None:
    check_permission(Role.SALES, Action.SEND_QUOTE)


def test_sales_cannot_approve_quote() -> None:
    with pytest.raises(PermissionDenied):
        check_permission(Role.SALES, Action.APPROVE_QUOTE)


def test_sales_cannot_reject_quote() -> None:
    with pytest.raises(PermissionDenied):
        check_permission(Role.SALES, Action.REJECT_QUOTE)


def test_manager_can_approve_quote() -> None:
    check_permission(Role.MANAGER, Action.APPROVE_QUOTE)


def test_manager_can_reject_quote() -> None:
    check_permission(Role.MANAGER, Action.REJECT_QUOTE)


def test_manager_can_view_cost_and_margin() -> None:
    check_permission(Role.MANAGER, Action.VIEW_COST_MARGIN)


@pytest.mark.parametrize(
    "role",
    [Role.AGENT, Role.SALES, Role.VIEWER],
)
def test_non_manager_cannot_view_cost_and_margin(role: Role) -> None:
    with pytest.raises(PermissionDenied):
        check_permission(role, Action.VIEW_COST_MARGIN)


def test_viewer_can_read_quote() -> None:
    check_permission(Role.VIEWER, Action.VIEW_QUOTE)


def test_viewer_cannot_create_quote() -> None:
    with pytest.raises(PermissionDenied):
        check_permission(Role.VIEWER, Action.CREATE_QUOTE)


def test_viewer_cannot_edit_draft() -> None:
    with pytest.raises(PermissionDenied):
        check_permission(Role.VIEWER, Action.EDIT_DRAFT)


def test_is_allowed_returns_false_instead_of_raising() -> None:
    assert is_allowed(Role.MANAGER, Action.VIEW_COST_MARGIN) is True
    assert is_allowed(Role.SALES, Action.VIEW_COST_MARGIN) is False
