from decimal import Decimal

import pytest

from quote_sim.access import PermissionDenied
from quote_sim.approval import InvalidTransition
from quote_sim.audit import AuditLog
from quote_sim.evidence import PriceList
from quote_sim.models import QuoteState
from quote_sim.pricing import ValidationError
from quote_sim.service import QuoteDesk

from conftest import TEST_RULE_ID

ABOVE_AUTO_APPROVE = Decimal("0.20")


def draft_with_widget(
    desk: QuoteDesk,
    *,
    discount: Decimal = ABOVE_AUTO_APPROVE,
    price_list_version: str | None = "test-v1",
) -> str:
    quote = desk.create_quote("agent-1")
    desk.add_line(
        "agent-1",
        quote.quote_id,
        product_id="widget",
        quantity=2,
        discount=discount,
        discount_rule_id=TEST_RULE_ID,
        price_list_version=price_list_version,
    )
    return quote.quote_id


def test_agent_creates_draft_with_sequential_quote_id(desk: QuoteDesk) -> None:
    first = desk.create_quote("agent-1")
    second = desk.create_quote("agent-1")

    assert (first.quote_id, second.quote_id) == ("Q-0001", "Q-0002")
    assert first.state is QuoteState.DRAFT
    assert first.creator_id == "agent-1"


def test_viewer_cannot_create_quote_and_attempt_is_logged(
    desk: QuoteDesk, audit_log: AuditLog
) -> None:
    with pytest.raises(PermissionDenied):
        desk.create_quote("viewer-1")

    entry = audit_log.entries[-1]
    assert (entry.actor_id, entry.role, entry.action) == ("viewer-1", "viewer", "create_quote")
    assert entry.details["result"] == "denied"
    assert desk.quote_ids == ()


def test_unknown_actor_is_denied_and_logged_with_unknown_role(
    desk: QuoteDesk, audit_log: AuditLog
) -> None:
    quote_id = draft_with_widget(desk)

    with pytest.raises(PermissionDenied, match="unknown user"):
        desk.submit("intruder-1", quote_id)

    entry = audit_log.entries[-1]
    assert (entry.actor_id, entry.role, entry.action) == ("intruder-1", "unknown", "submit_quote")
    assert entry.details["result"] == "denied"


def test_added_line_records_version_snapshot_and_rule(desk: QuoteDesk) -> None:
    quote_id = draft_with_widget(desk, price_list_version="test-v1")

    line = desk.add_line(
        "sales-1",
        quote_id,
        product_id="cable",
        quantity=3,
        discount=Decimal("0"),
        discount_rule_id=TEST_RULE_ID,
        price_list_version="test-v1",
    ).line_items[-1]

    assert line.evidence is not None
    assert line.evidence.price_list_version == "test-v1"
    assert line.evidence.unit_price_snapshot == Decimal("2.00")
    assert line.evidence.discount_rule_id == TEST_RULE_ID


def test_add_line_without_version_uses_latest_published_price_list(desk: QuoteDesk) -> None:
    quote_id = draft_with_widget(desk, price_list_version=None)

    line = desk.view("sales-1", quote_id).lines[0]

    assert line.price_list_version == "test-v2"
    assert line.unit_price == Decimal("12.00")


def test_invalid_quantity_is_rejected_and_logged(desk: QuoteDesk, audit_log: AuditLog) -> None:
    quote = desk.create_quote("agent-1")

    with pytest.raises(ValidationError, match="positive integer"):
        desk.add_line(
            "agent-1",
            quote.quote_id,
            product_id="widget",
            quantity=0,
            discount=Decimal("0"),
            discount_rule_id=TEST_RULE_ID,
        )

    entry = audit_log.entries[-1]
    assert entry.action == "edit_draft"
    assert entry.details["result"] == "failed"
    assert entry.to_state is None


def test_update_line_keeps_original_price_list_version(desk: QuoteDesk) -> None:
    quote_id = draft_with_widget(desk, price_list_version="test-v1")
    desk.price_lists.publish(PriceList("test-v3", {"widget": Decimal("50.00")}))

    updated = desk.update_line(
        "sales-1",
        quote_id,
        0,
        quantity=5,
        discount=Decimal("0.05"),
        discount_rule_id=TEST_RULE_ID,
    )

    line = updated.line_items[0]
    assert line.quantity == 5
    assert line.unit_price == Decimal("10.00")
    assert line.evidence is not None
    assert line.evidence.price_list_version == "test-v1"


def test_removing_line_at_missing_index_is_rejected(desk: QuoteDesk) -> None:
    quote_id = draft_with_widget(desk)

    with pytest.raises(ValidationError, match="no line at index 1"):
        desk.remove_line("agent-1", quote_id, 1)


def test_manager_cannot_edit_draft(desk: QuoteDesk) -> None:
    quote_id = draft_with_widget(desk)

    with pytest.raises(PermissionDenied):
        desk.remove_line("manager-1", quote_id, 0)


def test_editing_pending_quote_raises_invalid_transition_and_is_logged(
    desk: QuoteDesk, audit_log: AuditLog
) -> None:
    quote_id = draft_with_widget(desk)
    desk.submit("sales-1", quote_id)

    with pytest.raises(InvalidTransition, match="pending_approval"):
        desk.remove_line("sales-1", quote_id, 0)

    entry = audit_log.entries[-1]
    assert entry.from_state is QuoteState.PENDING_APPROVAL
    assert entry.details["result"] == "failed"


def test_editing_sent_quote_is_rejected(desk: QuoteDesk) -> None:
    quote_id = draft_with_widget(desk)
    desk.submit("sales-1", quote_id)
    desk.approve("manager-1", quote_id)
    desk.send("sales-1", quote_id)

    with pytest.raises(InvalidTransition, match="sent"):
        desk.remove_line("sales-1", quote_id, 0)


def test_editing_approved_quote_is_denied_until_authority_is_decided(
    desk: QuoteDesk, audit_log: AuditLog
) -> None:
    quote_id = draft_with_widget(desk)
    desk.submit("sales-1", quote_id)
    desk.approve("manager-1", quote_id)

    with pytest.raises(PermissionDenied, match="no role is authorized"):
        desk.remove_line("sales-1", quote_id, 0)

    assert desk.view("sales-1", quote_id).state is QuoteState.APPROVED
    assert audit_log.entries[-2].action == "edit_approved"
    assert audit_log.entries[-2].details["result"] == "denied"


def test_failed_approval_writes_exactly_one_audit_entry(
    desk: QuoteDesk, audit_log: AuditLog
) -> None:
    quote_id = draft_with_widget(desk)
    desk.submit("sales-1", quote_id)
    entries_before = len(audit_log.entries)

    with pytest.raises(PermissionDenied):
        desk.approve("sales-1", quote_id)

    assert len(audit_log.entries) == entries_before + 1


def test_unknown_quote_id_is_rejected_and_logged(desk: QuoteDesk, audit_log: AuditLog) -> None:
    with pytest.raises(ValidationError, match="unknown quote"):
        desk.submit("sales-1", "Q-9999")

    entry = audit_log.entries[-1]
    assert (entry.quote_id, entry.action) == ("Q-9999", "submit_quote")
    assert entry.details["result"] == "failed"


def test_viewing_quote_is_audited_with_cost_visibility(
    desk: QuoteDesk, audit_log: AuditLog
) -> None:
    quote_id = draft_with_widget(desk)

    desk.view("manager-1", quote_id)
    desk.view("viewer-1", quote_id)

    manager_entry, viewer_entry = audit_log.entries[-2:]
    assert manager_entry.action == viewer_entry.action == "view_quote"
    assert manager_entry.details["cost_margin_visible"] is True
    assert viewer_entry.details["cost_margin_visible"] is False


def test_agent_draft_to_sent_flow_records_every_step(
    desk: QuoteDesk, audit_log: AuditLog
) -> None:
    quote_id = draft_with_widget(desk)
    desk.submit("sales-1", quote_id)
    desk.approve("manager-1", quote_id)
    sent = desk.send("sales-1", quote_id)

    assert sent.state is QuoteState.SENT
    assert [(entry.actor_id, entry.action) for entry in audit_log.entries] == [
        ("agent-1", "create_quote"),
        ("agent-1", "edit_draft"),
        ("sales-1", "submit_quote"),
        ("manager-1", "approve_quote"),
        ("sales-1", "send_quote"),
    ]
