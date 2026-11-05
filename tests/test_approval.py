from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

import pytest

from quote_sim.access import PermissionDenied, Role
from quote_sim.approval import ApprovalPolicy, ApprovalWorkflow, InvalidTransition
from quote_sim.audit import AuditLog
from quote_sim.evidence import (
    MissingEvidence,
    PriceList,
    PriceListCatalog,
    attach_evidence,
)
from quote_sim.models import LineItem, PricingPolicy, Quote, QuoteState
from quote_sim.pricing import ValidationError

TEST_APPROVAL_POLICY = ApprovalPolicy(
    auto_approve_threshold=Decimal("0.10"),
    rule_id="test-auto-approve",
)
TEST_PRICING_POLICY = PricingPolicy(
    max_discount=Decimal("0.30"),
    vat_rate=Decimal("0.10"),
)


def make_line_item(discount: str) -> LineItem:
    line_item = LineItem(
        product_id="widget",
        quantity=1,
        unit_price=Decimal("10.00"),
        discount=Decimal(discount),
    )
    return attach_evidence(
        line_item,
        PriceList("test-v1", {"widget": Decimal("10.00")}),
        "test-discount-rule",
    )


def make_workflow(
    clock: Callable[[], datetime] | None = None,
) -> tuple[ApprovalWorkflow, AuditLog]:
    audit_log = AuditLog(clock=clock)
    price_lists = PriceListCatalog(
        [PriceList("test-v1", {"widget": Decimal("10.00")})]
    )
    return (
        ApprovalWorkflow(
            TEST_APPROVAL_POLICY,
            audit_log,
            price_lists,
            TEST_PRICING_POLICY,
        ),
        audit_log,
    )


def make_pending_quote(
    *,
    creator_id: str = "sales-1",
    submitted_by: str = "sales-1",
    discount: str = "0.20",
) -> Quote:
    return Quote(
        quote_id="quote-1",
        creator_id=creator_id,
        line_items=(make_line_item(discount),),
        state=QuoteState.PENDING_APPROVAL,
        submitted_by=submitted_by,
    )


def test_submission_above_threshold_moves_quote_to_pending_approval() -> None:
    workflow, audit_log = make_workflow()
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        line_items=(make_line_item("0.11"),),
    )

    submitted = workflow.submit(quote, "sales-2", Role.SALES)

    assert submitted.state is QuoteState.PENDING_APPROVAL
    assert audit_log.entries[0].to_state is QuoteState.PENDING_APPROVAL


def test_submission_without_evidence_fails_and_is_logged() -> None:
    workflow, audit_log = make_workflow()
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        line_items=(
            LineItem(
                product_id="widget",
                quantity=1,
                unit_price=Decimal("10.00"),
                discount=Decimal("0.20"),
            ),
        ),
    )

    with pytest.raises(MissingEvidence, match="no evidence"):
        workflow.submit(quote, "sales-2", Role.SALES)

    assert quote.state is QuoteState.DRAFT
    assert audit_log.entries[-1].details["result"] == "failed"


def test_submission_discount_above_maximum_fails_and_is_logged() -> None:
    workflow, audit_log = make_workflow()
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        line_items=(make_line_item("0.31"),),
    )

    with pytest.raises(ValidationError, match="discount must be between"):
        workflow.submit(quote, "sales-2", Role.SALES)

    assert quote.state is QuoteState.DRAFT
    assert audit_log.entries[-1].details["result"] == "failed"


def test_discount_at_threshold_auto_approves_and_records_policy_rule() -> None:
    workflow, audit_log = make_workflow()
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        line_items=(make_line_item("0.10"),),
    )

    submitted = workflow.submit(quote, "sales-2", Role.SALES)

    assert submitted.state is QuoteState.APPROVED
    assert submitted.approved_by == "policy"
    policy_entry = audit_log.entries[1]
    assert policy_entry.actor_id == "policy"
    assert policy_entry.role == "policy"
    assert policy_entry.details["rule_id"] == TEST_APPROVAL_POLICY.rule_id


def test_discount_just_above_threshold_remains_pending() -> None:
    workflow, _ = make_workflow()
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        line_items=(make_line_item("0.101"),),
    )

    submitted = workflow.submit(quote, "sales-2", Role.SALES)

    assert submitted.state is QuoteState.PENDING_APPROVAL


def test_eligible_manager_can_approve_pending_quote() -> None:
    workflow, _ = make_workflow()

    approved = workflow.approve(
        make_pending_quote(),
        "manager-1",
        Role.MANAGER,
    )

    assert approved.state is QuoteState.APPROVED
    assert approved.approved_by == "manager-1"


def test_eligible_manager_can_reject_pending_quote() -> None:
    workflow, _ = make_workflow()

    rejected = workflow.reject(
        make_pending_quote(),
        "manager-1",
        Role.MANAGER,
    )

    assert rejected.state is QuoteState.REJECTED


def test_creator_cannot_approve_quote_and_denial_is_logged() -> None:
    workflow, audit_log = make_workflow()
    quote = make_pending_quote(creator_id="manager-1")

    with pytest.raises(PermissionDenied):
        workflow.approve(quote, "manager-1", Role.MANAGER)

    assert quote.state is QuoteState.PENDING_APPROVAL
    assert audit_log.entries[-1].details["result"] == "denied"


def test_submitter_cannot_approve_quote_and_denial_is_logged() -> None:
    workflow, audit_log = make_workflow()
    quote = make_pending_quote(creator_id="sales-1", submitted_by="manager-1")

    with pytest.raises(PermissionDenied):
        workflow.approve(quote, "manager-1", Role.MANAGER)

    assert audit_log.entries[-1].details["result"] == "denied"


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_non_manager_cannot_make_decision_and_attempt_is_logged(decision: str) -> None:
    workflow, audit_log = make_workflow()
    quote = make_pending_quote()

    with pytest.raises(PermissionDenied):
        getattr(workflow, decision)(quote, "sales-2", Role.SALES)

    assert audit_log.entries[-1].details["result"] == "denied"


def test_rejected_quote_cannot_be_revised_while_authority_is_tbd() -> None:
    workflow, audit_log = make_workflow()
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        state=QuoteState.REJECTED,
    )

    with pytest.raises(PermissionDenied):
        workflow.revise(quote, "sales-1", Role.SALES)

    assert quote.state is QuoteState.REJECTED
    assert audit_log.entries[-1].details["result"] == "denied"


def test_approved_quote_cannot_be_edited_while_authority_is_tbd() -> None:
    workflow, audit_log = make_workflow()
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        line_items=(make_line_item("0.10"),),
        state=QuoteState.APPROVED,
        submitted_by="sales-2",
        approved_by="policy",
    )

    with pytest.raises(PermissionDenied):
        workflow.edit_approved(
            quote,
            "sales-1",
            Role.SALES,
            (make_line_item("0.05"),),
        )

    assert quote.state is QuoteState.APPROVED
    assert quote.approved_by == "policy"
    assert audit_log.entries[-1].details["result"] == "denied"


def test_sales_can_send_approved_quote_and_sent_is_final() -> None:
    workflow, audit_log = make_workflow()
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        state=QuoteState.APPROVED,
        approved_by="manager-1",
    )

    sent = workflow.send(quote, "sales-2", Role.SALES)

    assert sent.state is QuoteState.SENT
    with pytest.raises(InvalidTransition):
        workflow.send(sent, "sales-2", Role.SALES)
    assert audit_log.entries[-1].details["result"] == "failed"


def test_invalid_transition_is_rejected_and_logged_without_state_change() -> None:
    workflow, audit_log = make_workflow()
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        line_items=(make_line_item("0.20"),),
    )

    with pytest.raises(InvalidTransition):
        workflow.approve(quote, "manager-1", Role.MANAGER)

    assert quote.state is QuoteState.DRAFT
    assert audit_log.entries[-1].from_state is QuoteState.DRAFT
    assert audit_log.entries[-1].to_state is None
    assert audit_log.entries[-1].details["result"] == "failed"


def test_audit_timestamp_uses_injected_clock() -> None:
    expected_timestamp = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    workflow, audit_log = make_workflow(clock=lambda: expected_timestamp)
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        line_items=(make_line_item("0.20"),),
    )

    workflow.submit(quote, "sales-2", Role.SALES)

    assert audit_log.entries[0].timestamp == expected_timestamp


def test_audit_entries_and_details_are_immutable() -> None:
    workflow, audit_log = make_workflow()
    quote = Quote(
        quote_id="quote-1",
        creator_id="sales-1",
        line_items=(make_line_item("0.20"),),
    )
    workflow.submit(quote, "sales-2", Role.SALES)
    entries = audit_log.entries

    with pytest.raises(TypeError):
        entries[0].details["line_count"] = 0
    with pytest.raises(AttributeError):
        entries.clear()

    assert audit_log.entries[0].details["line_count"] == 1
