from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType

from quote_sim.access import Action, PermissionDenied, Role, check_permission
from quote_sim.audit import AuditLog
from quote_sim.evidence import (
    MissingEvidence,
    PriceListCatalog,
    product_catalog,
    validate_quote_evidence,
)
from quote_sim.models import LineItem, PricingPolicy, Quote, QuoteState
from quote_sim.pricing import ValidationError, validate_line_item


class InvalidTransition(ValueError):
    """Identify a state change that is not part of the quote workflow."""


@dataclass(frozen=True)
class ApprovalPolicy:
    """Require the threshold and rule identity instead of inventing business defaults."""

    auto_approve_threshold: Decimal
    rule_id: str


TRANSITIONS: Mapping[tuple[QuoteState, Action], QuoteState] = MappingProxyType(
    {
        (QuoteState.DRAFT, Action.SUBMIT_QUOTE): QuoteState.PENDING_APPROVAL,
        (QuoteState.PENDING_APPROVAL, Action.APPROVE_QUOTE): QuoteState.APPROVED,
        (QuoteState.PENDING_APPROVAL, Action.REJECT_QUOTE): QuoteState.REJECTED,
        (QuoteState.REJECTED, Action.REVISE_QUOTE): QuoteState.DRAFT,
        (QuoteState.APPROVED, Action.EDIT_APPROVED): QuoteState.DRAFT,
        (QuoteState.APPROVED, Action.SEND_QUOTE): QuoteState.SENT,
    }
)


class ApprovalWorkflow:
    """Apply state changes, enforce role/context rules, and audit successes and failures."""

    def __init__(
        self,
        policy: ApprovalPolicy,
        audit_log: AuditLog,
        price_lists: PriceListCatalog,
        pricing_policy: PricingPolicy,
    ) -> None:
        self._validate_policy(policy)
        if not isinstance(pricing_policy, PricingPolicy):
            raise TypeError("pricing_policy must be a PricingPolicy")
        self._policy = policy
        self._audit_log = audit_log
        self._price_lists = price_lists
        self._pricing_policy = pricing_policy

    def submit(self, quote: Quote, actor_id: str, role: Role) -> Quote:
        try:
            self._check_permission(role, Action.SUBMIT_QUOTE)
            self._require_transition(quote, Action.SUBMIT_QUOTE)
            validate_quote_evidence(quote, self._price_lists)
            for line_item in quote.line_items:
                evidence = line_item.evidence
                if evidence is None:
                    raise MissingEvidence(
                        f"line for {line_item.product_id} has no evidence"
                    )
                price_list = self._price_lists.get(evidence.price_list_version)
                validate_line_item(
                    line_item,
                    product_catalog(price_list),
                    self._pricing_policy,
                )

            pending_quote = replace(
                quote,
                state=QuoteState.PENDING_APPROVAL,
                submitted_by=actor_id,
                approved_by=None,
            )
            self._record(
                quote,
                actor_id,
                role.value,
                Action.SUBMIT_QUOTE.value,
                pending_quote.state,
                {"line_count": len(quote.line_items)},
            )

            if all(
                item.discount <= self._policy.auto_approve_threshold
                for item in quote.line_items
            ):
                approved_quote = replace(
                    pending_quote,
                    state=QuoteState.APPROVED,
                    approved_by="policy",
                )
                self._record(
                    pending_quote,
                    "policy",
                    "policy",
                    "auto_approve",
                    approved_quote.state,
                    {"rule_id": self._policy.rule_id},
                )
                return approved_quote
            return pending_quote
        except (
            InvalidTransition,
            MissingEvidence,
            PermissionDenied,
            ValidationError,
        ) as error:
            self._record_failure(quote, actor_id, role, Action.SUBMIT_QUOTE, error)
            raise

    def approve(self, quote: Quote, actor_id: str, role: Role) -> Quote:
        return self._manager_decision(quote, actor_id, role, Action.APPROVE_QUOTE)

    def reject(self, quote: Quote, actor_id: str, role: Role) -> Quote:
        return self._manager_decision(quote, actor_id, role, Action.REJECT_QUOTE)

    def revise(self, quote: Quote, actor_id: str, role: Role) -> Quote:
        return self._apply_transition(
            quote,
            actor_id,
            role,
            Action.REVISE_QUOTE,
        )

    def edit_approved(
        self,
        quote: Quote,
        actor_id: str,
        role: Role,
        line_items: Sequence[LineItem],
    ) -> Quote:
        try:
            self._check_permission(role, Action.EDIT_APPROVED)
            self._require_transition(quote, Action.EDIT_APPROVED)
            edited_quote = replace(
                quote,
                state=QuoteState.DRAFT,
                line_items=tuple(line_items),
                submitted_by=None,
                approved_by=None,
            )
            self._record(
                quote,
                actor_id,
                role.value,
                Action.EDIT_APPROVED.value,
                edited_quote.state,
                {"line_count": len(edited_quote.line_items)},
            )
            return edited_quote
        except (InvalidTransition, PermissionDenied) as error:
            self._record_failure(quote, actor_id, role, Action.EDIT_APPROVED, error)
            raise

    def send(self, quote: Quote, actor_id: str, role: Role) -> Quote:
        return self._apply_transition(quote, actor_id, role, Action.SEND_QUOTE)

    def _manager_decision(
        self,
        quote: Quote,
        actor_id: str,
        role: Role,
        action: Action,
    ) -> Quote:
        try:
            self._check_permission(role, action)
            self._require_transition(quote, action)
            if actor_id in {quote.creator_id, quote.submitted_by}:
                raise PermissionDenied(
                    "a quote creator or submitter cannot approve or reject it"
                )
            return self._make_transition(quote, actor_id, role, action)
        except (InvalidTransition, PermissionDenied) as error:
            self._record_failure(quote, actor_id, role, action, error)
            raise

    def _apply_transition(
        self,
        quote: Quote,
        actor_id: str,
        role: Role,
        action: Action,
    ) -> Quote:
        try:
            self._check_permission(role, action)
            self._require_transition(quote, action)
            return self._make_transition(quote, actor_id, role, action)
        except (InvalidTransition, PermissionDenied) as error:
            self._record_failure(quote, actor_id, role, action, error)
            raise

    def _make_transition(
        self,
        quote: Quote,
        actor_id: str,
        role: Role,
        action: Action,
    ) -> Quote:
        target_state = TRANSITIONS[(quote.state, action)]
        if action == Action.APPROVE_QUOTE:
            approver = actor_id
        elif target_state in {QuoteState.REJECTED, QuoteState.DRAFT}:
            approver = None
        else:
            approver = quote.approved_by
        updated_quote = replace(
            quote,
            state=target_state,
            approved_by=approver,
        )
        self._record(
            quote,
            actor_id,
            role.value,
            action.value,
            updated_quote.state,
            {},
        )
        return updated_quote

    def _require_transition(self, quote: Quote, action: Action) -> None:
        if (quote.state, action) not in TRANSITIONS:
            raise InvalidTransition(
                f"cannot {action.value} a quote in {quote.state.value}"
            )

    @staticmethod
    def _check_permission(role: Role, action: Action) -> None:
        if action in {Action.REVISE_QUOTE, Action.EDIT_APPROVED}:
            raise PermissionDenied(f"no role is authorized to {action.value} yet")
        check_permission(role, action)

    def _record(
        self,
        quote: Quote,
        actor_id: str,
        role: str,
        action: str,
        to_state: QuoteState,
        details: Mapping[str, object],
    ) -> None:
        self._audit_log.record(
            actor_id=actor_id,
            role=role,
            action=action,
            quote_id=quote.quote_id,
            from_state=quote.state,
            to_state=to_state,
            details=details,
        )

    def _record_failure(
        self,
        quote: Quote,
        actor_id: str,
        role: Role,
        action: Action,
        error: Exception,
    ) -> None:
        self._audit_log.record(
            actor_id=actor_id,
            role=role.value,
            action=action.value,
            quote_id=quote.quote_id,
            from_state=quote.state,
            to_state=None,
            details={
                "result": "denied" if isinstance(error, PermissionDenied) else "failed",
                "reason": str(error),
            },
        )

    @staticmethod
    def _validate_policy(policy: ApprovalPolicy) -> None:
        if not isinstance(policy, ApprovalPolicy):
            raise TypeError("policy must be an ApprovalPolicy")
        if (
            not isinstance(policy.auto_approve_threshold, Decimal)
            or not policy.auto_approve_threshold.is_finite()
            or not Decimal(0) <= policy.auto_approve_threshold <= Decimal(1)
        ):
            raise ValueError("auto_approve_threshold must be a Decimal between 0 and 1")
        if not isinstance(policy.rule_id, str) or not policy.rule_id.strip():
            raise ValueError("rule_id must be a non-empty string")
